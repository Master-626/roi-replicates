"""Pytest coverage for replicate summaries and demonstrated edge cases."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from roi_replicates import ValidationError, analyze_manifest, equivalent_diameter

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "synthetic" / "manifest.json"


def _image(name: str, *, group: str = "g", replicate: str = "A", **extra: object) -> dict:
    entry = {
        "group": group,
        "replicate": replicate,
        "image": Path(name).stem,
        "table": name,
        "delimiter": ",",
        "area_unit": "um2",
        "calibration_confirmed": True,
    }
    entry.update(extra)
    return entry


def _manifest(root: Path, tables: dict[str, str], images: list[dict], **extra: object) -> Path:
    for name, text in tables.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    document = {
        "schema_version": 1,
        "synthetic": True,
        "replicate_definition": "Independent synthetic cultures",
        "within_replicate": "objects",
        "images": images,
    }
    document.update(extra)
    path = root / "manifest.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_equivalent_diameter_matches_a_known_circle() -> None:
    assert equivalent_diameter(math.pi * 25) == pytest.approx(10)
    assert equivalent_diameter(100) == pytest.approx((2 / math.sqrt(math.pi)) * 10)


@pytest.mark.parametrize("value", [0, -1, True, None, "10", float("nan"), float("inf")])
def test_equivalent_diameter_rejects_values_that_are_not_positive_areas(value: object) -> None:
    with pytest.raises(ValidationError):
        equivalent_diameter(value)  # type: ignore[arg-type]


def test_synthetic_example_weights_analyzable_replicates_equally() -> None:
    group = analyze_manifest(EXAMPLE)["groups"][0]
    assert group["n_replicates_declared"] == 3
    assert group["n_replicates_with_objects"] == 2
    assert group["n_included"] == 4
    assert group["n_excluded"] == 1
    assert group["mean_diameter_um"] == pytest.approx(15)
    assert group["sd_diameter_um"] == pytest.approx(math.sqrt(50))
    assert group["median_diameter_um"] == pytest.approx(15)


def test_within_replicate_image_weighting_is_not_object_pooling(tmp_path: Path) -> None:
    tables = {
        "a.csv": "Area\n" + "".join(f"{math.pi * 25}\n" for _ in range(3)),
        "b.csv": "Area\n" + f"{math.pi * 225}\n",
    }
    images = [_image("a.csv", replicate="A"), _image("b.csv", replicate="A", image="b")]
    objects = analyze_manifest(_manifest(tmp_path, tables, images))
    assert objects["replicates"][0]["mean_diameter_um"] == pytest.approx(15)
    images_mode = analyze_manifest(_manifest(tmp_path, tables, images, within_replicate="images"))
    assert images_mode["replicates"][0]["mean_diameter_um"] == pytest.approx(20)


def test_pixel_calibration_is_applied_once_per_object(tmp_path: Path) -> None:
    path = _manifest(
        tmp_path,
        {"px.csv": "Area\n100\n"},
        [_image("px.csv", area_unit="px2", pixel_size_um=[0.5, 2.0])],
    )
    obj = analyze_manifest(path)["objects"][0]
    assert obj["area_um2"] == pytest.approx(100)
    assert obj["diameter_um"] == pytest.approx(equivalent_diameter(100))


def test_exclusions_and_empty_replicates_stay_out_of_the_mean(tmp_path: Path) -> None:
    tables = {
        "used.csv": "Area,Reason\n100,\n400,border object\n",
        "empty.csv": "Area\n",
    }
    images = [
        _image("used.csv", replicate="A", exclude_column="Reason"),
        _image("empty.csv", replicate="B", image="empty"),
    ]
    report = analyze_manifest(_manifest(tmp_path, tables, images))
    assert [row["included"] for row in report["objects"]] == [True, False]
    assert report["objects"][1]["exclude_reason"] == "border object"
    assert report["replicates"][1]["mean_diameter_um"] is None
    group = report["groups"][0]
    assert group["n_replicates_declared"] == 2
    assert group["n_replicates_with_objects"] == 1
    assert group["mean_diameter_um"] == pytest.approx(equivalent_diameter(100))
    assert group["sd_diameter_um"] is None
    assert group["n_included"] == 1
    codes = [warning["code"] for warning in report["warnings"]]
    assert "no_included_objects" in codes
    assert "empty_replicate_not_in_mean" in codes


def test_imagej_space_header_is_accepted_and_can_preserve_row_numbers(tmp_path: Path) -> None:
    text = " ,Label,Area,Mean\n001,cell,1.000E2,5\n2,cell,400,9\n"
    path = _manifest(
        tmp_path,
        {"results.csv": text},
        [_image("results.csv", object_column="")],
    )
    rows = analyze_manifest(path)["objects"]
    assert [row["source_object_id"] for row in rows] == ["001", "2"]
    assert rows[0]["area_um2"] == pytest.approx(100)
    assert rows[1]["diameter_um"] == pytest.approx(equivalent_diameter(400))
    assert rows[0]["source_line_end"] == 2


def test_imagej_tab_export_with_only_the_space_header(tmp_path: Path) -> None:
    path = _manifest(
        tmp_path,
        {"results.tsv": " \tArea\n1\t100\n"},
        [_image("results.tsv", delimiter="\t")],
    )
    report = analyze_manifest(path)
    assert report["objects"][0]["source_object_id"] is None
    assert report["objects"][0]["area_um2"] == pytest.approx(100)


@pytest.mark.parametrize(
    "text",
    [" Area\n100\n", "Area \n100\n", "  ,Area\n1,100\n", "Area, \n100,1\n"],
)
def test_other_padded_headers_are_still_rejected(tmp_path: Path, text: str) -> None:
    path = _manifest(tmp_path, {"bad.csv": text}, [_image("bad.csv")])
    with pytest.raises(ValidationError, match="surrounding whitespace"):
        analyze_manifest(path)


def test_blank_object_column_still_preserves_text_ids(tmp_path: Path) -> None:
    path = _manifest(
        tmp_path,
        {"ids.csv": ",Area\n001,100\n"},
        [_image("ids.csv", object_column="")],
    )
    assert analyze_manifest(path)["objects"][0]["source_object_id"] == "001"


def test_ambiguous_row_number_header_is_rejected(tmp_path: Path) -> None:
    path = _manifest(
        tmp_path,
        {"odd.csv": " ,,Area\n1,,100\n"},
        [_image("odd.csv", object_column="")],
    )
    with pytest.raises(ValidationError, match="ambiguous ImageJ row-number header"):
        analyze_manifest(path)


def test_identical_bytes_warn_against_the_first_image(tmp_path: Path) -> None:
    text = "Area\n100\n"
    images = [_image(f"{name}.csv", replicate=name, image=name) for name in ("a", "b", "c")]
    path = _manifest(tmp_path, {f"{name}.csv": text for name in ("a", "b", "c")}, images)
    warnings = [item for item in analyze_manifest(path)["warnings"] if item["code"] == "identical_table_bytes"]
    assert [item["image"] for item in warnings] == ["b", "c"]
    assert [item["other_image"] for item in warnings] == ["a", "a"]

