"""Run from the source root after installing the package."""
from pathlib import Path

from roi_replicates import analyze_manifest, equivalent_diameter

manifest = Path(__file__).parent / "synthetic" / "manifest.json"
report = analyze_manifest(manifest)
print("A 100 µm² ROI has area-equivalent diameter:", equivalent_diameter(100), "µm")
print("Synthetic group summary:", report["groups"][0])
print("Warnings:", report["warnings"])
assert abs(report["groups"][0]["mean_diameter_um"] - 15.0) < 1e-12
