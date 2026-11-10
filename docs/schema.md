# Version 1 data contract

## Manifest

All keys are case-sensitive. Unknown keys and duplicate JSON keys are rejected rather than ignored. JSON must be UTF-8, optionally with a UTF-8 BOM. Non-finite JSON constants are rejected. Labels must be nonempty, free of surrounding whitespace, control characters and invalid Unicode surrogates.

Required top-level keys:

- `schema_version`: integer `1`, not a boolean.
- `synthetic`: explicit boolean.
- `replicate_definition`: free text describing the experimental unit. Recording a definition does not verify independence.
- `within_replicate`: `objects` or `images`; no default.
- `images`: 1–1,000 image records.

Required image keys:

- `group`, `replicate`, `image`: labels. Image IDs must be unique across the manifest. The pair `(group, replicate)` defines a replicate.
- `table`: relative slash-separated path below the manifest directory. Absolute paths, `..`, `.`, empty components, backslashes, colons and symlink components are rejected. No source table path or hardlink may be used twice. Identical bytes in distinct files produce a warning, since identical measurements are possible and are not proof of duplication.
- `delimiter`: comma or tab; JSON tab syntax is `"\t"`.
- `area_unit`: `px2` (square pixels) or `um2` (square micrometers).
- `calibration_confirmed`: boolean `true`, explicitly supplied by the caller.

Optional image keys:

- `area_column`: exact header name; default `Area`.
- `pixel_size_um`: exactly two positive finite numbers `[x, y]`; mandatory for `px2`, forbidden for `um2`. Anisotropic pixel area is supported. Inputs that underflow/overflow the positive finite conversion range fail.
- `exclude_column`: exact header name, different from `area_column`. A trimmed nonempty cell is an exclusion reason. It cannot contain control characters. A blank cell includes the row. This column must be explicitly configured.
- `object_column`: optional exact original ROI-ID header, or `""` for an unlabeled ImageJ row-number column. IDs are preserved as text without numerical coercion, must be nonempty and unique within each image, and reject surrounding whitespace/control characters instead of trimming them. It must differ from area/exclusion columns. If omitted, `source_object_id` is null and the record number still traces back to the table.
- `source_image`: nonempty provenance label only. The file is not accessed and calibration/segmentation/image identity are not verified.

## Measurement tables

UTF-8 CSV or TSV; UTF-8 BOM, LF and CRLF are supported. Every parsed data record must have exactly the header's column count. Quoting follows Python's strict CSV parser. Headers must be unique and cannot have surrounding whitespace. A single blank header is allowed for ImageJ's row-number column; it is ignored unless selected with `object_column: ""`. Blank records are errors. A header with zero data rows is a valid empty image.

The selected area column must contain a positive finite ASCII decimal number, optionally with sign, decimal point or exponent. Surrounding area-cell whitespace is ignored for parsing but preserved in `raw_area`. Decimal commas, grouping separators, NaN, infinity, underscores and empty cells are rejected. Even an excluded row requires a valid area.

Other columns are ignored for calculations. Their exact bytes remain covered by the source hash, but are not copied to objects. `record` is the 1-based parsed data-record ordinal, **not** the ImageJ row label or original ROI ID. `source_line_end` identifies the last physical input line of that record, including multiline quoted cells. The image ID plus record is the library's object identifier. Keep original measurement tables alongside reports.

Limits: manifest 1 MiB; each table 32 MiB; combined tables 128 MiB; all measurement rows 1,000,000. Analysis is in memory, not a streaming big-data pipeline. Python's CSV field-size limit also applies (usually 131,072 characters). Resource limits are safety bounds, not performance targets.

## Report

`report_schema_version` is 1. `sources` preserves declared image settings plus `sha256` and `bytes`; no absolute source path is recorded. Hashes cover the exact raw bytes used for parsing. The manifest itself is hashed. There is no embedded image content, acquisition metadata, timestamp claim or automatic evidence of original data authenticity.

Arrays `objects`, `images`, `replicates`, `groups` contain the corresponding rows. Object/image order follows manifest/table order; replicate/group rows are sorted lexicographically by their identifiers. Same inputs on the same package implementation generate deterministic report/export bytes; a software update may change numeric serialization or schema. The source manifest hash changes when only JSON formatting changes, intentionally.

Group `n_replicates_declared` counts declared group/replicate pairs, while `n_replicates_with_objects` counts pairs with at least one included object. `sd_diameter_um` in images is the sample SD of objects; in groups it is the sample SD of replicate means. These are different distributions. Replicate rows intentionally omit ambiguous object/field SD or SEM fields.

Warnings:

- `identical_table_bytes`: distinct image tables have exactly equal bytes. Review possible accidental duplicate exports; equality alone is not a reason to exclude.
- `no_included_objects`: empty or fully excluded image; count retained, diameter undefined.
- `fewer_than_two_analyzable_replicates`: fewer than two nonempty replicate means; group SD undefined.
- `empty_replicate_not_in_mean`: one or more declared replicates have no included objects. Counts are retained and means cannot include those replicates. Investigate what absence means in the experiment.

All output means/medians/SD are descriptive. No field is a validation grade or a p-value.
