"""Command-line interface. Inputs remain local and read-only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import ValidationError, __version__, analyze_manifest, export_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calibrated, replicate-aware 2D ROI summaries")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="Read and validate all inputs; write nothing")
    validate.add_argument("manifest", type=Path)
    summarize = subparsers.add_parser("summarize", help="Write a new directory of JSON/CSV reports")
    summarize.add_argument("manifest", type=Path)
    summarize.add_argument("-o", "--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = analyze_manifest(args.manifest)
        if args.command == "summarize":
            export_report(report, args.output)
        print(json.dumps({"valid": True, "synthetic": report["synthetic"],
                          "groups": report["groups"], "warnings": report["warnings"]},
                         ensure_ascii=False, allow_nan=False))
    except (ValidationError, OSError, ValueError) as exc:
        print(f"roi-replicates: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
