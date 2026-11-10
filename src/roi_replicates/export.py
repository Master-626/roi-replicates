"""Export complete analysis to a newly created directory, never over inputs."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

_FIELDS = {
    "objects": ["group", "replicate", "image", "record", "source_object_id", "source_line_end", "raw_area",
                "area_unit", "area_um2", "diameter_um", "included", "exclude_reason"],
    "images": ["group", "replicate", "image", "n_rows", "n_included", "n_excluded",
               "mean_diameter_um", "sd_diameter_um", "median_diameter_um"],
    "replicates": ["group", "replicate", "n_images", "n_images_with_objects", "n_included",
                   "n_excluded", "mean_diameter_um"],
    "groups": ["group", "n_replicates_declared", "n_replicates_with_objects", "n_included",
               "n_excluded", "mean_diameter_um", "sd_diameter_um", "median_diameter_um"],
}


def _safe_cell(value: Any) -> Any:
    # Quoting CSV alone does not stop spreadsheet formula execution. JSON is the
    # authoritative lossless copy; CSV text cells get a visible leading apostrophe.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _csv_bytes(rows: list[dict], fields: list[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fields, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: _safe_cell(v) for k, v in row.items()})
    return stream.getvalue().encode("utf-8")


def export_report(report: dict[str, Any], destination: str | Path) -> Path:
    """Write a report returned by analyze_manifest to a NEW directory.

    The parent directory must already exist. Prepare all serialized content
    before creating it. Writes are exclusive. A failed/interrupted export may
    leave a partial directory with _INCOMPLETE; choose a different destination
    to retry. This is a fail-closed marker, not an atomic directory transaction.
    The caller must not concurrently modify the destination or its parent.
    """
    payloads: dict[str, bytes] = {
        "report.json": (json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    }
    for table, fields in _FIELDS.items():
        payloads[f"{table}.csv"] = _csv_bytes(report[table], fields)
    readme = (
        "SYNTHETIC DATA\n" if report["synthetic"] else "USER-SUPPLIED MEASUREMENTS\n"
    ) + (
        "Descriptive 2D area-equivalent diameters, not 3D size or inferential statistics.\n"
        "Group mean/SD/median are across analyzable replicate means, equally weighted.\n"
        f"Within-replicate weighting: {report['within_replicate']}.\n"
        "Null JSON / blank CSV means undefined, not zero. Inspect all warnings in report.json.\n"
        "Replicate independence, calibration and segmentation were declared, not verified.\n"
        "report.json is authoritative; CSV text beginning with formula characters is prefixed\n"
        "with an apostrophe for safer spreadsheet opening. This is not a universal sanitizer.\n"
        "A complete export has checksums.json and no _INCOMPLETE marker.\n"
        "Checksums detect accidental changes, not malicious tampering or scientific validity.\n"
    )
    payloads["README.txt"] = readme.encode("utf-8")
    checksums = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
    payloads["checksums.json"] = (json.dumps(checksums, indent=2) + "\n").encode("utf-8")
    output = Path(destination)
    output.mkdir(exist_ok=False)
    marker = output / "_INCOMPLETE"
    with marker.open("xb") as stream:
        stream.write(b"Export not complete. Do not use these outputs.\n")
    for name, data in payloads.items():
        with (output / name).open("xb") as stream:
            stream.write(data)
    marker.unlink()
    return output
