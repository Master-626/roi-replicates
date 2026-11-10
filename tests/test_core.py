from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import random
import statistics
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from roi_replicates import ValidationError, analyze_manifest, equivalent_diameter


class AnalysisCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = {"schema_version": 1, "synthetic": True,
                         "replicate_definition": "Independent synthetic cultures",
                         "within_replicate": "objects", "images": []}

    def add_table(self, diameters=(10,), *, group="g", rep="A", text=None, **kwargs):
        index = len(self.manifest["images"])
        name = f"table-{index}.csv"
        path = self.root / name
        if text is None:
            text = "Area\n" + "".join(f"{math.pi * (d / 2) ** 2}\n" for d in diameters)
        # Preserve deliberately supplied line endings on Windows as well as Unix.
        path.write_bytes(text.encode("utf-8"))
        entry = {"group": group, "replicate": rep, "image": f"image-{index}", "table": name,
                 "delimiter": ",", "area_unit": "um2", "calibration_confirmed": True}
        entry.update(kwargs)
        self.manifest["images"].append(entry)
        return entry, path

    def run_analysis(self):
        path = self.root / "manifest.json"
        path.write_text(json.dumps(self.manifest), encoding="utf-8")
        return analyze_manifest(path)

    def test_group_weights_replicates_not_objects(self):
        self.add_table([10] * 100, rep="A")
        self.add_table([20], rep="B")
        report = self.run_analysis()
        self.assertAlmostEqual(report["groups"][0]["mean_diameter_um"], 15)
        self.assertAlmostEqual(report["groups"][0]["sd_diameter_um"], math.sqrt(50))
        self.assertEqual(report["groups"][0]["n_included"], 101)
        self.assertEqual(report["groups"][0]["n_replicates_declared"], 2)

    def test_explicit_within_replicate_weighting(self):
        self.add_table([10] * 3)
        self.add_table([30])
        self.assertAlmostEqual(self.run_analysis()["replicates"][0]["mean_diameter_um"], 15)
        self.manifest["within_replicate"] = "images"
        self.assertAlmostEqual(self.run_analysis()["replicates"][0]["mean_diameter_um"], 20)

    def test_convert_each_object_before_averaging(self):
        self.add_table([10, 30])
        self.assertAlmostEqual(self.run_analysis()["groups"][0]["mean_diameter_um"], 20)

    def test_anisotropic_pixel_calibration(self):
        self.add_table(text="Area\n100\n", area_unit="px2", pixel_size_um=[0.5, 2.0])
        obj = self.run_analysis()["objects"][0]
        self.assertEqual(obj["area_um2"], 100)
        self.assertAlmostEqual(obj["diameter_um"], equivalent_diameter(100))

    def test_pixels_and_calibrated_area_match(self):
        self.add_table(text="Area\n400\n", area_unit="px2", pixel_size_um=[0.5, 0.5])
        self.add_table(text="Area\n100\n", rep="B")
        objects = self.run_analysis()["objects"]
        self.assertEqual(objects[0]["diameter_um"], objects[1]["diameter_um"])

    def test_optional_source_roi_ids_preserved_without_numeric_coercion(self):
        self.add_table(text=",Area\n001, 100 \n002,200\n", object_column="")
        rows = self.run_analysis()["objects"]
        self.assertEqual(rows[0]["source_object_id"], "001")
        self.assertEqual(rows[0]["raw_area"], " 100 ")
        self.assertEqual(rows[0]["area_um2"], 100)

    def test_bad_source_roi_ids_rejected(self):
        entry, path = self.add_table(object_column="ID")
        for content in ["Area\n100\n", "Area,ID\n100,\n", "Area,ID\n100,1\n200,1\n", "Area,ID\n100, a \n"]:
            with self.subTest(content=content):
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(ValidationError):
                    self.run_analysis()
        entry["object_column"] = "Area"
        with self.assertRaises(ValidationError):
            self.run_analysis()

    def test_exclusions_preserve_original_measurements(self):
        self.add_table(text="Area,Reason\n100,\n400,border object\n", exclude_column="Reason")
        report = self.run_analysis()
        self.assertEqual(len(report["objects"]), 2)
        self.assertFalse(report["objects"][1]["included"])
        self.assertEqual(report["objects"][1]["exclude_reason"], "border object")
        self.assertEqual(report["images"][0]["n_excluded"], 1)
        self.assertEqual(report["groups"][0]["n_included"], 1)
        self.assertAlmostEqual(report["groups"][0]["mean_diameter_um"], equivalent_diameter(100))

    def test_empty_image_and_replicate_are_retained(self):
        self.add_table([])
        self.add_table([20], rep="B")
        report = self.run_analysis()
        self.assertIsNone(report["images"][0]["mean_diameter_um"])
        self.assertIsNone(report["replicates"][0]["mean_diameter_um"])
        group = report["groups"][0]
        self.assertEqual(group["n_replicates_declared"], 2)
        self.assertEqual(group["n_replicates_with_objects"], 1)
        self.assertAlmostEqual(group["mean_diameter_um"], 20)
        self.assertIsNone(group["sd_diameter_um"])
        self.assertIn("empty_replicate_not_in_mean", [w["code"] for w in report["warnings"]])

    def test_all_excluded_and_all_empty(self):
        self.add_table(text="Area,R\n10,border\n", exclude_column="R")
        self.add_table([], rep="B")
        report = self.run_analysis()
        self.assertEqual(report["groups"][0]["n_included"], 0)
        self.assertIsNone(report["groups"][0]["mean_diameter_um"])
        self.assertEqual(report["groups"][0]["n_excluded"], 1)

    def test_groups_and_replicates_are_scoped_and_sorted(self):
        self.add_table([20], group="z", rep="A")
        self.add_table([10], group="a", rep="A")
        report = self.run_analysis()
        self.assertEqual([r["group"] for r in report["groups"]], ["a", "z"])
        self.assertEqual(len(report["replicates"]), 2)

    def test_hashes_match_exact_parsed_bytes_and_preserve_inputs(self):
        _, path = self.add_table(text="\ufeffArea\r\n100\r\n")
        before = path.read_bytes()
        self.assertEqual(before, b"\xef\xbb\xbfArea\r\n100\r\n")
        report = self.run_analysis()
        self.assertEqual(report["sources"][0]["sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(report["manifest_sha256"], hashlib.sha256((self.root / "manifest.json").read_bytes()).hexdigest())

    def test_identical_content_warns_but_does_not_assume_duplication(self):
        self.add_table([10])
        self.add_table([10], rep="B")
        self.assertIn("identical_table_bytes", [w["code"] for w in self.run_analysis()["warnings"]])

    def test_tsv_with_imagej_unlabeled_index_and_utf8_labels(self):
        self.add_table(group="细胞组", text="\tArea\tLabel\n1\t1e2\t细胞一\n", delimiter="\t")
        report = self.run_analysis()
        self.assertEqual(report["objects"][0]["group"], "细胞组")
        self.assertEqual(report["objects"][0]["source_line_end"], 2)

    def test_quoted_extra_fields_and_multiline_labels(self):
        self.add_table(text='Area,Label\n100,"a,b\ncontinued"\n')
        obj = self.run_analysis()["objects"][0]
        self.assertEqual(obj["record"], 1)
        self.assertEqual(obj["source_line_end"], 3)

    def test_float_extremes_and_scientific_notation(self):
        self.add_table(text="Area\n1e308\n5e-324\n")
        report = self.run_analysis()
        self.assertTrue(all(math.isfinite(o["diameter_um"]) for o in report["objects"]))
        json.dumps(report, allow_nan=False)

    def test_bad_area_values_rejected_even_when_excluded(self):
        entry, path = self.add_table(exclude_column="R")
        for bad in ["", "0", "-1", "nan", "inf", "1e999", "1e-999", "1_000", "١٠", "1 000", "0x10"]:
            with self.subTest(bad=bad):
                path.write_text(f"Area,R\n{bad},exclude\n", encoding="utf-8")
                with self.assertRaises(ValidationError):
                    self.run_analysis()

    def test_bad_tables(self):
        entry, path = self.add_table()
        for text in ["", "Area,Area\n1,2\n", "Other\n1\n", "Area\n1,2\n", "Area,X\n1\n",
                     " Area\n1\n", 'Area\n"100\n', "Area\n\n", "Area\n1\x00\n"]:
            with self.subTest(text=text):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValidationError):
                    self.run_analysis()

    def test_bad_encoding(self):
        _, path = self.add_table()
        path.write_bytes("Area\n100\n".encode("utf-16"))
        with self.assertRaisesRegex(ValidationError, "UTF-8"):
            self.run_analysis()

    def test_missing_file(self):
        _, path = self.add_table()
        path.unlink()
        with self.assertRaises(ValidationError):
            self.run_analysis()

    def test_duplicate_image_and_table(self):
        entry, path = self.add_table()
        second, _ = self.add_table(rep="B")
        second["image"] = entry["image"]
        with self.assertRaisesRegex(ValidationError, "duplicate image"):
            self.run_analysis()
        second["image"] = "other"
        second["table"] = entry["table"]
        with self.assertRaisesRegex(ValidationError, "more than once"):
            self.run_analysis()

    def test_hardlink_duplicate(self):
        _, path = self.add_table()
        _, second = self.add_table(rep="B")
        second.unlink()
        try:
            os.link(path, second)
        except OSError:
            self.skipTest("hardlinks unavailable")
        with self.assertRaisesRegex(ValidationError, "more than once"):
            self.run_analysis()

    def test_symlink_table_rejected(self):
        entry, path = self.add_table()
        link = self.root / "alias.csv"
        try:
            link.symlink_to(path)
        except OSError:
            self.skipTest("symlinks unavailable")
        entry["table"] = "alias.csv"
        with self.assertRaisesRegex(ValidationError, "symlinks"):
            self.run_analysis()

    def test_path_traversal_and_nonportable_paths_rejected(self):
        entry, _ = self.add_table()
        for bad in ["/tmp/foo", "../foo", "folder/../foo", "./foo", "C:/foo", "folder\\foo", "a//b"]:
            with self.subTest(bad=bad):
                entry["table"] = bad
                with self.assertRaises(ValidationError):
                    self.run_analysis()

    def test_contained_subdirectory_allowed(self):
        entry, path = self.add_table()
        directory = self.root / "data"
        directory.mkdir()
        path.rename(directory / path.name)
        entry["table"] = "data/" + path.name
        self.assertEqual(len(self.run_analysis()["objects"]), 1)

    def test_bad_manifest_fields(self):
        self.add_table()
        original = copy.deepcopy(self.manifest)
        for key, bad in [("schema_version", True), ("schema_version", 2), ("synthetic", 1),
                         ("within_replicate", "auto"), ("replicate_definition", ""),
                         ("replicate_definition", " padded "), ("images", []), ("images", {})]:
            with self.subTest(key=key, bad=bad):
                self.manifest = copy.deepcopy(original)
                self.manifest[key] = bad
                with self.assertRaises(ValidationError):
                    self.run_analysis()
        self.manifest = original
        self.manifest["unknown"] = 1
        with self.assertRaisesRegex(ValidationError, "unknown"):
            self.run_analysis()

    def test_bad_image_fields(self):
        entry, _ = self.add_table()
        original = copy.deepcopy(entry)
        for key, bad in [("group", ""), ("group", " a "), ("replicate", "a\tb"),
                         ("calibration_confirmed", False), ("calibration_confirmed", 1),
                         ("area_unit", "mm2"), ("area_column", "missing"),
                         ("delimiter", ";"), ("exclude_column", "Area"),
                         ("exclude_column", "missing"), ("exclude_column", None), ("source_image", ""), ("group", "\ud800")]:
            with self.subTest(key=key, bad=bad):
                entry.clear()
                entry.update(original)
                entry[key] = bad
                with self.assertRaises(ValidationError):
                    self.run_analysis()

    def test_calibration_ambiguity_and_invalid_scales(self):
        entry, _ = self.add_table()
        entry["pixel_size_um"] = [1, 1]
        with self.assertRaisesRegex(ValidationError, "double calibration"):
            self.run_analysis()
        entry["area_unit"] = "px2"
        for bad in [None, [1], [1, 2, 3], [0, 1], [-1, 1], [True, 1], ["1", 1],
                    [float("inf"), 1], [1e-300, 1e-300], [1e300, 1e300]]:
            with self.subTest(bad=bad):
                entry["pixel_size_um"] = bad
                with self.assertRaises(ValidationError):
                    self.run_analysis()

    def test_calibrated_area_underflow_and_overflow(self):
        entry, path = self.add_table(area_unit="px2", pixel_size_um=[1e-100, 1e-100], text="Area\n1e-200\n")
        with self.assertRaises(ValidationError):
            self.run_analysis()
        entry["pixel_size_um"] = [1e100, 1e100]
        path.write_text("Area\n1e200\n", encoding="utf-8")
        with self.assertRaises(ValidationError):
            self.run_analysis()

    def test_json_duplicates_nonfinite_and_syntax(self):
        path = self.root / "manifest.json"
        for text in ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{', '[]', 'null']:
            with self.subTest(text=text):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValidationError):
                    analyze_manifest(path)

    def test_limits_fail_closed(self):
        self.add_table([10, 20])
        for name, limit in [("MAX_IMAGES", 0), ("MAX_ROWS", 1), ("MAX_TABLE_BYTES", 4),
                            ("MAX_TOTAL_TABLE_BYTES", 4), ("MAX_MANIFEST_BYTES", 4)]:
            with self.subTest(name=name):
                with patch(f"roi_replicates.core.{name}", limit):
                    with self.assertRaises(ValidationError):
                        self.run_analysis()

    def test_no_exclusion_control_characters(self):
        self.add_table(text='Area,R\n100,"a\nb"\n', exclude_column="R")
        with self.assertRaises(ValidationError):
            self.run_analysis()

    def test_determinism_and_permutation_invariance(self):
        rng = random.Random(626)
        expected = []
        for rep in range(5):
            values = [rng.uniform(1, 500) for _ in range(rep + 2)]
            expected.append(statistics.mean(values))
            self.add_table(values, rep=str(rep))
        report = self.run_analysis()
        self.assertEqual(report, self.run_analysis())
        self.assertAlmostEqual(report["groups"][0]["mean_diameter_um"], statistics.mean(expected))
        self.manifest["images"].reverse()
        self.assertEqual(report["groups"], self.run_analysis()["groups"])


class DiameterTests(unittest.TestCase):
    def test_known_circle(self):
        self.assertAlmostEqual(equivalent_diameter(math.pi * 25), 10)

    def test_invalid(self):
        for value in [0, -1, True, None, "10", float("nan"), float("inf"), 10 ** 1000]:
            with self.subTest(value=str(value)[:30]):
                with self.assertRaises(ValidationError):
                    equivalent_diameter(value)

    def test_large_finite_area_does_not_overflow(self):
        self.assertTrue(math.isfinite(equivalent_diameter(1.7e308)))

    def test_scaling_property(self):
        for area in [1e-200, 1, 123.45, 1e200]:
            self.assertAlmostEqual(equivalent_diameter(area * 9) / equivalent_diameter(area), 3)


if __name__ == "__main__":
    unittest.main()
