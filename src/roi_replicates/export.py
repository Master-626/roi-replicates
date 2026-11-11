"""Export complete analysis to a newly created directory, never over inputs."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any

from .core import ValidationError, _unique_pairs

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REQUIRED_EXPORTS = (
    "report.json",
    "objects.csv",
    "images.csv",
    "replicates.csv",
    "groups.csv",
    "README.txt",
)
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


def _plain_export_name(name: str) -> None:
    if (
        not isinstance(name, str)
        or name in {"", ".", ".."}
        or any(sep in name for sep in ("/", "\\", ":"))
        or name != Path(name).name
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
    ):
        raise ValidationError(f"checksum entry is not a plain file name: {name!r}")


def _load_checksums(data: bytes) -> dict[str, Any]:
    if len(data) > 1_048_576:
        raise ValidationError("checksums.json exceeds the 1 MiB limit")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValidationError("checksums.json: expected UTF-8") from exc
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_unique_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ValidationError(f"non-finite JSON constant: {token}")
            ),
        )
    except ValidationError:
        raise
    except (ValueError, RecursionError) as exc:
        raise ValidationError(f"invalid checksums.json: {exc}") from exc
    if not isinstance(parsed, dict) or not parsed:
        raise ValidationError("checksums.json must be a nonempty object")
    return parsed


def verify_export(destination: str | Path) -> dict[str, Any]:
    """Recompute SHA-256 checksums for a directory written by export_report.

    Succeeds only when `_INCOMPLETE` is absent, every required report file is
    listed in checksums.json, and each listed file's bytes match. Names cannot
    escape the directory, and symlinks are rejected. This catches accidental
    edits and truncated copies. It does not detect someone rewriting a file and
    checksums.json together, and it is not a signature or a scientific review.
    """
    output = Path(destination)
    if output.is_symlink() or not output.is_dir():
        raise ValidationError("export path must be a real directory")
    marker = output / "_INCOMPLETE"
    if marker.is_symlink() or marker.exists():
        raise ValidationError("incomplete export: _INCOMPLETE marker is present")
    checksum_path = output / "checksums.json"
    if checksum_path.is_symlink() or not checksum_path.is_file():
        raise ValidationError("checksums.json is missing")
    try:
        checksums = _load_checksums(checksum_path.read_bytes())
    except OSError as exc:
        raise ValidationError(f"cannot read checksums.json: {exc.strerror}") from exc
    missing = [name for name in _REQUIRED_EXPORTS if name not in checksums]
    if missing:
        raise ValidationError(f"checksums.json is missing {missing}")
    verified: list[str] = []
    for name, digest in checksums.items():
        _plain_export_name(name)
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValidationError(f"{name}: checksum must be a lowercase sha256 hex digest")
        path = output / name
        if path.is_symlink() or not path.is_file():
            raise ValidationError(f"{name}: expected a regular file in the export directory")
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ValidationError(f"cannot read {name}: {exc.strerror}") from exc
        if actual != digest:
            raise ValidationError(f"{name}: checksum mismatch")
        verified.append(name)
    return {"file_count": len(verified), "files": verified}
