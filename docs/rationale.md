# Scope, rationale and existing tools

## Bounded research, 2026-11-10

`image-batch-processor` is a related tool for traceable display exports. Its current scope distinguishes display PNGs from quantitative measurements. It does not replace measurement analysis. The new library stays on the tabular side and does not duplicate image display, introduce another segmenter or implement a generic CSV editor.

ImageJ documents that area may be in square pixels or calibrated square units after Set Scale. A table headed `Area` therefore does not establish its units. Explicit per-image units and calibration are the first design requirement. ImageJ also supports tab-delimited measurement exports, so both explicitly declared CSV and TSV are accepted.

The SuperPlots paper distinguishes experimental reproducibility from cell-to-cell variability. SuperPlotsOfData already provides replicate-aware plots and summary choices. Equal weighting of replicate means is not a new method and is not universally optimal. The small differentiator here is an installable, dependency-free local pre-plotting bridge: strict unit handling, declared within-replicate weighting, retained empty/excluded counts, and input/output integrity records together in a Python API and CLI.

### Primary sources consulted

- ImageJ Analyze menu, area calibration and measurement exports: https://imagej.net/ij/docs/menus/analyze.html
- ImageJ User Guide, measurement definitions: https://imagej.net/ij/docs/guide/146-30.html
- Lord et al., *SuperPlots: Communicating reproducibility and variability in cell biology*, JCB (2020), DOI 10.1083/jcb.202001064: https://rupress.org/jcb/article/219/6/e202001064/151717/SuperPlots-Communicating-reproducibility-and
- SuperPlotsOfData official app: https://huygens.science.uva.nl/SuperPlotsOfData/
- SuperPlotsOfData source: https://github.com/JoachimGoedhart/SuperPlotsOfData
- Existing image display tool: https://github.com/Master-626/image-batch-processor

This was a bounded comparison, not an exhaustive novelty search. No claim is made that equivalent functionality is unavailable elsewhere. This comparison does not establish trademark clearance, exhaustive compatibility or suitability for a particular experiment.

## Scientific limits

- Area-equivalent circular diameter is a **2D shape descriptor**. Projection, segmentation, shape and imaging plane affect it. It is not Feret diameter, a direct 3D spheroid measurement or proof of volume.
- No actual images or research data were inspected. Calibration assertions, image labels and biological grouping are not independently verified.
- Fields/images within a replicate may be correlated. This library's descriptive aggregation does not model that correlation or imply that inferential statistics are appropriate.
- The object-weighted and image-weighted choices answer different questions. Group means represent analyzable replicate means equally, not all cells equally and not all declared replicates if some are empty.
- Empty fields/replicates may be scientifically informative. Retaining counts and warning does not solve missingness or selection bias. Plan the analysis before inspecting outcomes.
- Exclusion reasons are user-entered and not evaluated. A traceable exclusion is not necessarily justified.
- Fields omitted from the manifest cannot be detected. Repeated image content under different table exports is not detectable reliably.
- No plot, p-value, power calculation, hierarchical model, correction for unequal sampling, or experimental recommendation is generated.
- Numerical tests and passing CI do not constitute validation on actual instrument exports or experimental data.

## Practical next step

Before using it for a manuscript, privately test a small independently checked set of actual ImageJ exports: confirm area units against acquisition records, match every image and ROI, verify experiment/field grouping, predefine exclusions and aggregation, and hand-check at least a few diameters and replicate means. This release does not claim that step was completed.
