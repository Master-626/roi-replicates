# roi-replicates

**From ImageJ/Fiji area tables to traceable, replicate-aware 2D size summaries.**

MIT-licensed source · Python 3.10+ · no runtime dependencies · experimental 0.1.0

This package fills a small gap between measurement exports and plotting: it requires explicit area units and experiment grouping, converts each ROI's area to an area-equivalent diameter, then produces descriptive summaries without silently treating every ROI as an independent biological experiment.

It **does not segment images, choose exclusions, infer calibration or independence, estimate 3D volume, or perform significance tests**. No patient or experimental data are bundled. The examples and tests use synthetic values only. This experimental source is published on GitHub under the MIT license. It is not published on PyPI.

## 中文快速说明

这个库接收 ImageJ/Fiji 导出的面积 CSV/TSV，计算二维面积等效圆直径，并按你明确声明的生物学重复汇总。对象数量与生物学重复数分别保留，避免把同一重复中的大量细胞/细胞团直接当作大量独立实验。

- 每张图明确指定面积单位。像素面积 `px2` 必须给出 x/y 像素尺寸；已经校准的 `um2` 禁止再传像素尺寸，防止重复换算。
- 每个 ROI 都保留原始面积、来源记录、纳入/排除状态和原因。没有自动删异常值。
- 每组对各个可分析重复的均值等权汇总。重复内按对象还是按图像平均，需要你明确选择。
- 空图像、无有效对象的重复不会消失，也不会被当成“直径为零”。输出单独记录数量并发出提示。
- 原始文件只读。输出必须是全新目录，包含 JSON、四级 CSV 和校验值。

**这是早期软件，不是经实验验证的分析流程。** 二维等效圆直径不等于三维细胞球直径，软件也不能证明分割、视野选择、标定或实验独立性正确。不要直接把示例标定值用于真实数据。

## Install locally

From the source root, preferably inside a fresh virtual environment:

```sh
python -m pip install .
roi-replicates --version
```

There is no network access during analysis. Building from source may require downloading the build tools listed in `pyproject.toml`. For an offline install, build a wheel on a compatible connected machine, then install that wheel with `python -m pip install --no-index --no-deps <wheel-file>`.

## Try the synthetic example

Run these commands from the extracted source root. `synthetic-report` must not already exist:

```sh
roi-replicates validate examples/synthetic/manifest.json
roi-replicates summarize examples/synthetic/manifest.json -o synthetic-report
python examples/use_api.py
```

The demo has three declared replicates:

- A: three included objects, each 10 µm, across two fields; one extra object is explicitly excluded.
- B: one 20 µm object, using fictional 0.5 × 0.5 µm pixel calibration.
- C: an empty field, retained as a declared replicate with an undefined mean.

The group mean across the **two analyzable replicate means** is **15 µm**, with sample SD approximately **7.071 µm**. Pooling the four objects would produce 12.5 µm instead. Neither estimator is universally correct: this library deliberately estimates the average analyzable replicate, using the declared within-replicate weighting. The missing third replicate is highlighted, not repaired. Empty samples may themselves be biologically meaningful; diameter alone cannot describe them.

## Manifest

Save each image's measurement table separately under the same directory as its manifest, or a subdirectory. The manifest is JSON; do not paste literal tab characters into JSON strings. Use `"\t"` for TSV.

```json
{
  "schema_version": 1,
  "synthetic": false,
  "replicate_definition": "Describe the independently prepared experimental unit here",
  "within_replicate": "objects",
  "images": [
    {
      "group": "condition-A",
      "replicate": "preparation-1",
      "image": "preparation-1-field-1",
      "table": "measurements/field-1.csv",
      "delimiter": ",",
      "area_column": "Area",
      "area_unit": "um2",
      "calibration_confirmed": true,
      "source_image": "original-field-1.tif"
    }
  ]
}
```

Set `calibration_confirmed` to true **only after checking the actual acquisition/export calibration**. `source_image` is an optional label, not a loaded or hash-verified image. The package hashes the measurement tables, not image pixels. For pixel area, use `"area_unit": "px2"` plus `"pixel_size_um": [x_size, y_size]` in µm/pixel. There is no unit guessing, implicit mm² conversion, or automatic scale-bar measurement.

To preserve original ROI IDs, set `"object_column": "ROI"` (or `"object_column": ""` for an unlabeled ImageJ row-number header). IDs remain strings, including leading zeros; duplicate IDs within an image are rejected. Without this option, parsed record numbers still trace objects to their source tables.

Use a different globally unique `image` identifier for every image. Replicate identifiers are scoped within each group. Reusing a replicate label across groups does not establish paired data. The grouping must correspond to your design, not just different filenames, wells, fields, days, or objects. See [the full input/output contract](docs/schema.md).

## Exclusions and empty images

There are no automatic exclusions. To exclude a valid-area row, explicitly name an exclusion-reason column in the manifest, for example `"exclude_column": "reason"`. A nonblank reason marks that row excluded; blank means included. All values and reasons remain in `report.json` and `objects.csv`. An existing reason column is not used unless it is explicitly configured.

A zero, negative, missing, nonnumeric or non-finite area is an error **even on an excluded row**. This avoids using arbitrary text to bypass invalid data. Resolve malformed records upstream while retaining the original source and a correction record.

A header-only table declares an observed image with no measured objects. Record an entirely empty replicate with at least one such image. The library cannot discover omitted images, missing experiments, undetected objects or selected fields. It only reports the images declared in the manifest.

## Outputs

A successful export contains:

- `objects.csv`: every ROI, raw area, calibrated area, diameter, source record and exclusion status.
- `images.csv`: per-image included/excluded counts and object-level descriptive mean, sample SD and median.
- `replicates.csv`: one row per declared group/replicate; counts and the chosen within-replicate mean.
- `groups.csv`: counts of declared/analyzable replicates and mean, sample SD and median of analyzable replicate means.
- `report.json`: authoritative full-precision structured report, warnings, declared settings, input byte counts, SHA-256 hashes and package version.
- `README.txt` and `checksums.json`: interpretation and output integrity information.

JSON `null` and blank CSV numeric fields mean **undefined**, not zero. SD needs at least two values. Warnings are machine-readable and are not scientific judgments. The CLI prints a short JSON summary; exit code 0 means parsing/analysis succeeded, even if warnings exist. Exit code 2 means invalid input or export failure. Help/version exit normally.

CSV is a convenience export: formula-like text cells get a leading apostrophe for safer spreadsheet use. `report.json` preserves strings exactly. Numeric precision is not deliberately rounded. Spreadsheet programs may still change IDs, dates and numeric precision; import identifier columns as text and use JSON for exact downstream processing. Check hashes for accidental changes; hashes are not signatures or proof of scientific validity.

The output directory must be new and its parent must exist. Content is serialized before any writes. Export failures or interruption can leave a partial directory; `_INCOMPLETE` marks it. Use only outputs with `checksums.json` **and no `_INCOMPLETE`**. Never reuse a partial destination for a retry. The caller must control the destination and not modify it concurrently; this is not a hostile-filesystem security boundary or a crash-durable transaction.

## Python API

```python
from roi_replicates import analyze_manifest, equivalent_diameter, export_report

print(equivalent_diameter(100))  # 11.283791670955125 µm, from 100 µm²
report = analyze_manifest("measurements/manifest.json")
print(report["groups"])
export_report(report, "new-report-directory")
```

`analyze_manifest` returns a regular dictionary or raises `ValidationError` for invalid input. `export_report` accepts that dictionary unmodified; arbitrary hand-built report structures are not a supported input API. Filesystem and serialization failures are raised to library callers. `python -m roi_replicates` provides the same CLI.

## Mathematics and limits

For each ROI, calibrated area is `A_um2 = A_px2 × pixel_size_x × pixel_size_y`, or the declared µm² area. Diameter is `d = 2 × sqrt(A_um2 / pi)`, calculated separately for each ROI before averaging. The numerically equivalent implementation avoids overflowing `4 × area` for large finite inputs. Invalid or unrepresentable scale/area products are rejected.

`within_replicate: "objects"` gives each included object in that replicate equal weight. `"images"` first computes each nonempty image's object mean, then weights those image means equally. The latter changes the estimand and ignores empty-image means; both modes retain empty-image counts. Group summaries always weight analyzable replicate means equally. No SEM, confidence intervals, p-values, hierarchical model, paired test or correction for selection bias is supplied.

Read [method limits and existing tools](docs/rationale.md). For segmentation use established tools such as ImageJ/Fiji; for replicate-aware visualization, consider SuperPlotsOfData. This package is a small local bridge, not a replacement for those tools or a novel statistical method.

## Development and verification

```sh
python -m pip install .
python -m unittest discover -s tests -v
python -m compileall -q src tests examples
```

The test suite covers synthetic calibration, unequal object/image counts, per-object conversion, both weighting modes, empty/excluded data, malformed tables/manifests, finite-value checks, source hashes, duplicate input protection, deterministic exports, no overwrite and injected export failures. `docs/verification.md` records checks performed. No real experimental measurements were used, and tests do not establish scientific validation. The [GitHub Actions workflow](https://github.com/Master-626/roi-replicates/actions/workflows/tests.yml) tests Linux, Windows and macOS. Check the run for the commit you use; no untested Python version or platform is implied to be verified.
