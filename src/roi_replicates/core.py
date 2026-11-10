"""Validation and analysis. Files are read only; no image processing is done."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import __version__

MAX_MANIFEST_BYTES = 1_048_576
MAX_TABLE_BYTES = 33_554_432
MAX_TOTAL_TABLE_BYTES = 134_217_728
MAX_IMAGES = 1_000
MAX_ROWS = 1_000_000
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


class ValidationError(ValueError):
    """An input cannot be interpreted without guessing or losing information."""


def _positive(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{where}: expected a positive finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValidationError(f"{where}: number outside supported float range") from exc
    if not math.isfinite(result) or result <= 0:
        raise ValidationError(f"{where}: expected a positive finite number")
    return result


def equivalent_diameter(area_um2: float) -> float:
    """Return the diameter in µm of a circle with this positive 2D area in µm².

    This is not Feret diameter, a 3D spheroid diameter, or a volume estimate.
    """
    area = _positive(area_um2, "area_um2")
    return (2 / math.sqrt(math.pi)) * math.sqrt(area)


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{where}: expected a nonempty string")
    if value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValidationError(f"{where}: surrounding whitespace/control characters are not allowed")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValidationError(f"{where}: invalid Unicode surrogate") from exc
    return value


def _keys(obj: Any, required: set[str], optional: set[str], where: str) -> dict:
    if not isinstance(obj, dict):
        raise ValidationError(f"{where}: expected an object")
    missing, unknown = required - obj.keys(), obj.keys() - required - optional
    if missing or unknown:
        raise ValidationError(f"{where}: missing keys {sorted(missing)}; unknown keys {sorted(unknown)}")
    return obj


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValidationError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _read(path: Path, limit: int) -> bytes:
    try:
        if not path.is_file():
            raise ValidationError(f"not a regular file: {path.name}")
        with path.open("rb") as stream:
            data = stream.read(limit + 1)
    except OSError as exc:
        raise ValidationError(f"cannot read {path.name}: {exc.strerror}") from exc
    if len(data) > limit:
        raise ValidationError(f"{path.name}: exceeds the {limit}-byte input limit")
    return data


def _decode(data: bytes, label: str) -> str:
    try:
        result = data.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValidationError(f"{label}: expected UTF-8 (a UTF-8 BOM is allowed)") from exc
    if "\x00" in result:
        raise ValidationError(f"{label}: NUL characters are not supported")
    return result


def _table_path(base: Path, name: Any) -> Path:
    name = _text(name, "image.table")
    # Portable manifest syntax, independent of the machine reading it.
    parts = name.split("/")
    if "\\" in name or ":" in name or any(p in {"", ".", ".."} for p in parts):
        raise ValidationError("image.table: use a relative slash-separated path without '..'")
    path = base
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise ValidationError(f"image.table: symlinks are not supported ({name})")
    if not path.resolve().is_relative_to(base):
        raise ValidationError("image.table: path must remain inside the manifest directory")
    return path


def _summary(values: list[float]) -> dict[str, Any]:
    return {
        "mean_diameter_um": statistics.mean(values) if values else None,
        "sd_diameter_um": statistics.stdev(values) if len(values) >= 2 else None,
        "median_diameter_um": statistics.median(values) if values else None,
    }


def analyze_manifest(path: str | Path) -> dict[str, Any]:
    """Read a version-1 JSON manifest and its CSV/TSV tables, without writing.

    See docs/schema.md. Paths are resolved relative to the manifest. Table bytes
    used for hashing are exactly the bytes parsed. Replicate independence and
    measurement validity are declarations by the caller, not inferred facts.
    """
    manifest_path = Path(path)
    raw = _read(manifest_path, MAX_MANIFEST_BYTES)
    try:
        manifest = json.loads(_decode(raw, "manifest"), object_pairs_hook=_unique_pairs,
                              parse_constant=lambda s: (_ for _ in ()).throw(
                                  ValidationError(f"non-finite JSON constant: {s}")))
    except ValidationError:
        raise
    except (ValueError, RecursionError) as exc:
        raise ValidationError(f"invalid JSON manifest: {exc}") from exc
    _keys(manifest, {"schema_version", "synthetic", "replicate_definition",
                     "within_replicate", "images"}, set(), "manifest")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise ValidationError("schema_version must be the integer 1")
    if type(manifest["synthetic"]) is not bool:
        raise ValidationError("synthetic must be true or false")
    _text(manifest["replicate_definition"], "replicate_definition")
    weighting = manifest["within_replicate"]
    if weighting not in ("objects", "images"):
        raise ValidationError("within_replicate must be 'objects' or 'images'")
    entries = manifest["images"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_IMAGES:
        raise ValidationError(f"images must contain between 1 and {MAX_IMAGES} entries")
    base = manifest_path.resolve().parent
    objects: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    image_ids: set[str] = set()
    paths: set[Path] = set()
    inodes: set[tuple[int, int]] = set()
    hashes: dict[str, str] = {}
    values_by_rep: dict[tuple[str, str], list[float]] = defaultdict(list)
    images_by_rep: dict[tuple[str, str], list[dict]] = defaultdict(list)
    total_bytes = 0
    for index, entry in enumerate(entries):
        where = f"images[{index}]"
        _keys(entry, {"group", "replicate", "image", "table", "delimiter", "area_unit",
                      "calibration_confirmed"},
              {"area_column", "exclude_column", "object_column", "pixel_size_um", "source_image"}, where)
        group = _text(entry["group"], f"{where}.group")
        replicate = _text(entry["replicate"], f"{where}.replicate")
        image_id = _text(entry["image"], f"{where}.image")
        if image_id in image_ids:
            raise ValidationError(f"duplicate image ID: {image_id!r}")
        image_ids.add(image_id)
        if entry["calibration_confirmed"] is not True:
            raise ValidationError(f"{where}: calibration_confirmed must be true")
        unit = entry["area_unit"]
        if unit not in ("px2", "um2"):
            raise ValidationError(f"{where}: area_unit must be 'px2' or 'um2'")
        scale = 1.0
        if unit == "px2":
            pixel_size = entry.get("pixel_size_um")
            if not isinstance(pixel_size, list) or len(pixel_size) != 2:
                raise ValidationError(f"{where}: px2 requires pixel_size_um [x, y]")
            scale = _positive(pixel_size[0], f"{where}.pixel_size_um[0]") * _positive(
                pixel_size[1], f"{where}.pixel_size_um[1]")
            _positive(scale, f"{where}: pixel area")
        elif "pixel_size_um" in entry:
            raise ValidationError(f"{where}: um2 forbids pixel_size_um to prevent double calibration")
        delimiter = entry["delimiter"]
        if delimiter not in (",", "\t"):
            raise ValidationError(f"{where}: delimiter must be ',' or a tab")
        area_column = _text(entry.get("area_column", "Area"), f"{where}.area_column")
        exclude_column = entry.get("exclude_column")
        if "exclude_column" in entry:
            _text(exclude_column, f"{where}.exclude_column")
            if exclude_column == area_column:
                raise ValidationError(f"{where}: area and exclusion columns must differ")
        object_column = entry.get("object_column")
        if "object_column" in entry and object_column != "":
            _text(object_column, f"{where}.object_column")
        if object_column in (area_column, exclude_column) and object_column is not None:
            raise ValidationError(f"{where}: object column must differ from area/exclusion columns")
        if "source_image" in entry:
            _text(entry["source_image"], f"{where}.source_image")
        table_path = _table_path(base, entry["table"])
        data = _read(table_path, MAX_TABLE_BYTES)
        total_bytes += len(data)
        if total_bytes > MAX_TOTAL_TABLE_BYTES:
            raise ValidationError("total table bytes exceed the 128 MiB limit")
        resolved = table_path.resolve()
        stat = table_path.stat()
        identity = (stat.st_dev, stat.st_ino)
        if resolved in paths or (stat.st_ino != 0 and identity in inodes):
            raise ValidationError(f"table used more than once: {entry['table']}")
        paths.add(resolved)
        inodes.add(identity)
        sha256 = hashlib.sha256(data).hexdigest()
        if sha256 in hashes:
            warnings.append({"code": "identical_table_bytes", "image": image_id,
                             "other_image": hashes[sha256]})
        hashes[sha256] = image_id
        source = dict(entry)
        source.update({"sha256": sha256, "bytes": len(data)})
        sources.append(source)
        reader = csv.reader(io.StringIO(_decode(data, entry["table"]), newline=""),
                            delimiter=delimiter, strict=True)
        try:
            header = next(reader, None)
            if not header or len(set(header)) != len(header):
                raise ValidationError(f"{where}: missing or duplicate table header")
            # ImageJ may export one unlabeled row-number column; it is ignored.
            if any(h and h != h.strip() for h in header):
                raise ValidationError(f"{where}: header has surrounding whitespace")
            if area_column not in header or (exclude_column and exclude_column not in header):
                raise ValidationError(f"{where}: required measurement column is missing")
            if object_column is not None and object_column not in header:
                raise ValidationError(f"{where}: object ID column is missing")
            object_index = header.index(object_column) if object_column is not None else None
            object_ids: set[str] = set()
            area_index = header.index(area_column)
            exclude_index = header.index(exclude_column) if exclude_column else None
            values: list[float] = []
            excluded = 0
            row_count = 0
            for record, row in enumerate(reader, 1):
                if len(objects) >= MAX_ROWS:
                    raise ValidationError(f"total measurements exceed the {MAX_ROWS}-row limit")
                if len(row) != len(header):
                    raise ValidationError(f"{where}, record {record}: wrong number of fields")
                raw_area = row[area_index]
                area_text = raw_area.strip()
                if not _NUMBER.fullmatch(area_text):
                    raise ValidationError(f"{where}, record {record}: Area must be an ASCII decimal number")
                area = _positive(float(area_text), f"{where}, record {record}: Area")
                converted = _positive(area * scale, f"{where}, record {record}: calibrated area")
                diameter = equivalent_diameter(converted)
                reason = row[exclude_index].strip() if exclude_index is not None else ""
                if any(ord(c) < 32 or ord(c) == 127 for c in reason):
                    raise ValidationError(f"{where}, record {record}: exclusion reason has control characters")
                source_object_id = None
                if object_index is not None:
                    source_object_id = _text(row[object_index], f"{where}, record {record}: object ID")
                    if source_object_id in object_ids:
                        raise ValidationError(f"{where}: duplicate object ID {source_object_id!r}")
                    object_ids.add(source_object_id)
                included = not reason
                if included:
                    values.append(diameter)
                else:
                    excluded += 1
                row_count += 1
                objects.append({"group": group, "replicate": replicate, "image": image_id,
                                "record": record, "source_object_id": source_object_id, "source_line_end": reader.line_num,
                                "raw_area": raw_area, "area_unit": unit,
                                "area_um2": converted, "diameter_um": diameter,
                                "included": included, "exclude_reason": reason})
        except csv.Error as exc:
            raise ValidationError(f"{where}: invalid delimited table: {exc}") from exc
        image_summary = {"group": group, "replicate": replicate, "image": image_id,
                         "n_rows": row_count, "n_included": len(values), "n_excluded": excluded,
                         **_summary(values)}
        images.append(image_summary)
        key = (group, replicate)
        values_by_rep[key].extend(values)
        images_by_rep[key].append(image_summary)
        if not values:
            warnings.append({"code": "no_included_objects", "image": image_id})
    replicates: list[dict[str, Any]] = []
    by_group: dict[str, list[dict]] = defaultdict(list)
    for (group, replicate), rep_images in sorted(images_by_rep.items()):
        object_values = values_by_rep[(group, replicate)]
        image_values = [i["mean_diameter_um"] for i in rep_images if i["n_included"]]
        effective_values = object_values if weighting == "objects" else image_values
        value = statistics.mean(effective_values) if effective_values else None
        summary = {"group": group, "replicate": replicate,
                   "n_images": len(rep_images), "n_images_with_objects": len(image_values),
                   "n_included": len(object_values),
                   "n_excluded": sum(i["n_excluded"] for i in rep_images),
                   "mean_diameter_um": value}
        replicates.append(summary)
        by_group[group].append(summary)
    groups: list[dict[str, Any]] = []
    for group, reps in sorted(by_group.items()):
        means = [r["mean_diameter_um"] for r in reps if r["mean_diameter_um"] is not None]
        groups.append({"group": group, "n_replicates_declared": len(reps),
                       "n_replicates_with_objects": len(means),
                       "n_included": sum(r["n_included"] for r in reps),
                       "n_excluded": sum(r["n_excluded"] for r in reps), **_summary(means)})
        if len(means) < 2:
            warnings.append({"code": "fewer_than_two_analyzable_replicates", "group": group})
        if len(means) != len(reps):
            warnings.append({"code": "empty_replicate_not_in_mean", "group": group,
                             "count": len(reps) - len(means)})
    return {"report_schema_version": 1, "software": {"name": "roi-replicates", "version": __version__},
            "synthetic": manifest["synthetic"],
            "replicate_definition": manifest["replicate_definition"],
            "within_replicate": weighting,
            "manifest_sha256": hashlib.sha256(raw).hexdigest(), "sources": sources,
            "objects": objects, "images": images, "replicates": replicates,
            "groups": groups, "warnings": warnings}
