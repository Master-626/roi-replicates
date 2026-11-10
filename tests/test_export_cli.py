from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from roi_replicates import analyze_manifest, export_report
from roi_replicates.cli import main

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "synthetic" / "manifest.json"


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.report = analyze_manifest(EXAMPLE)

    def test_complete_export_has_checksums_no_marker(self):
        output = export_report(self.report, self.root / "out")
        self.assertFalse((output / "_INCOMPLETE").exists())
        for name, digest in json.loads((output / "checksums.json").read_text(encoding="utf-8")).items():
            self.assertEqual(digest, hashlib.sha256((output / name).read_bytes()).hexdigest())
        self.assertEqual(json.loads((output / "report.json").read_text(encoding="utf-8")), self.report)
        self.assertIn("SYNTHETIC DATA", (output / "README.txt").read_text(encoding="utf-8"))
        self.assertIn("C,1,0,0,0,", (output / "replicates.csv").read_text(encoding="utf-8"))

    def test_existing_directory_never_overwritten(self):
        destination = self.root / "exists"
        destination.mkdir()
        sentinel = destination / "report.json"
        sentinel.write_text("preserve", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            export_report(self.report, destination)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_existing_file_never_overwritten(self):
        destination = self.root / "exists"
        destination.write_text("preserve", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            export_report(self.report, destination)
        self.assertEqual(destination.read_text(encoding="utf-8"), "preserve")

    def test_symlink_destination_never_followed(self):
        destination = self.root / "symlink"
        target = self.root / "target"
        target.mkdir()
        try:
            destination.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks unavailable")
        with self.assertRaises(FileExistsError):
            export_report(self.report, destination)
        self.assertEqual(list(target.iterdir()), [])

    def test_serialization_failure_does_not_create_directory(self):
        self.report["objects"][0]["diameter_um"] = float("nan")
        destination = self.root / "out"
        with self.assertRaises(ValueError):
            export_report(self.report, destination)
        self.assertFalse(destination.exists())

    def test_write_failure_leaves_incomplete_marker(self):
        real_open = Path.open
        def fail(path, *args, **kwargs):
            if path.name == "images.csv":
                raise OSError("injected write failure")
            return real_open(path, *args, **kwargs)
        destination = self.root / "out"
        with patch.object(Path, "open", fail):
            with self.assertRaises(OSError):
                export_report(self.report, destination)
        self.assertTrue((destination / "_INCOMPLETE").exists())
        self.assertFalse((destination / "checksums.json").exists())

    def test_formula_like_text_safe_csv_lossless_json(self):
        for table in ["objects", "images", "replicates", "groups"]:
            for row in self.report[table]:
                row["group"] = '=HYPERLINK("https://example.test")'
        output = export_report(self.report, self.root / "out")
        csv_text = (output / "groups.csv").read_text(encoding="utf-8")
        self.assertIn("'=HYPERLINK", csv_text)
        loaded = json.loads((output / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(loaded["groups"][0]["group"], self.report["groups"][0]["group"])

    def test_deterministic_files(self):
        first = export_report(self.report, self.root / "a")
        second = export_report(self.report, self.root / "b")
        self.assertEqual({p.name: p.read_bytes() for p in first.iterdir()},
                         {p.name: p.read_bytes() for p in second.iterdir()})

    def test_cli_validate_writes_nothing(self):
        before = list(self.root.iterdir())
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            status = main(["validate", str(EXAMPLE)])
        self.assertEqual(status, 0)
        self.assertTrue(json.loads(captured.getvalue())["valid"])
        self.assertEqual(list(self.root.iterdir()), before)

    def test_cli_summarize(self):
        output = self.root / "output"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["summarize", str(EXAMPLE), "-o", str(output)]), 0)
        self.assertTrue((output / "checksums.json").exists())

    def test_cli_bad_input_and_existing_output_return_two(self):
        with contextlib.redirect_stderr(io.StringIO()) as captured:
            self.assertEqual(main(["validate", str(self.root / "missing.json")]), 2)
            self.assertEqual(main(["summarize", str(EXAMPLE), "-o", str(self.root)]), 2)
        self.assertNotIn("Traceback", captured.getvalue())

    def test_module_entrypoint_and_version(self):
        result = subprocess.run([sys.executable, "-m", "roi_replicates", "--version"],
                                capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertIn("0.1.0", result.stdout)

    def test_bad_input_cli_subprocess(self):
        result = subprocess.run([sys.executable, "-m", "roi_replicates", "validate", str(self.root / "missing")],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
