"""Checksum verification for directories written by export_report."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from roi_replicates import ValidationError, analyze_manifest, export_report, verify_export
from roi_replicates.cli import main

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "synthetic" / "manifest.json"
EXPECTED_FILES = [
    "report.json",
    "objects.csv",
    "images.csv",
    "replicates.csv",
    "groups.csv",
    "README.txt",
]


def _export(tmp_path: Path) -> Path:
    return export_report(analyze_manifest(EXAMPLE), tmp_path / "out")


def test_verify_accepts_a_complete_export_without_changing_it(tmp_path: Path) -> None:
    output = _export(tmp_path)
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    result = verify_export(output)
    after = {path.name: path.read_bytes() for path in output.iterdir()}
    assert result == {"file_count": 6, "files": EXPECTED_FILES}
    assert after == before
    assert "_INCOMPLETE" not in after


def test_verify_reports_a_modified_file(tmp_path: Path) -> None:
    output = _export(tmp_path)
    objects = output / "objects.csv"
    objects.write_bytes(objects.read_bytes() + b"\n")
    with pytest.raises(ValidationError, match="objects.csv: checksum mismatch"):
        verify_export(output)


def test_verify_rejects_an_incomplete_marker(tmp_path: Path) -> None:
    output = _export(tmp_path)
    (output / "_INCOMPLETE").write_text("partial\n", encoding="utf-8")
    with pytest.raises(ValidationError, match="_INCOMPLETE"):
        verify_export(output)


def test_verify_rejects_missing_checksums_and_required_entries(tmp_path: Path) -> None:
    output = _export(tmp_path)
    checksum_path = output / "checksums.json"
    checksums = json.loads(checksum_path.read_text(encoding="utf-8"))
    del checksums["README.txt"]
    checksum_path.write_text(json.dumps(checksums), encoding="utf-8")
    with pytest.raises(ValidationError, match="missing"):
        verify_export(output)
    checksum_path.unlink()
    with pytest.raises(ValidationError, match="checksums.json is missing"):
        verify_export(output)


def test_verify_rejects_names_that_leave_the_directory(tmp_path: Path) -> None:
    output = _export(tmp_path)
    checksum_path = output / "checksums.json"
    checksums = json.loads(checksum_path.read_text(encoding="utf-8"))
    checksums["../secret.json"] = "a" * 64
    checksum_path.write_text(json.dumps(checksums), encoding="utf-8")
    with pytest.raises(ValidationError, match="plain file name"):
        verify_export(output)


def test_verify_rejects_symlink_directory_and_symlink_file(tmp_path: Path) -> None:
    output = _export(tmp_path)
    link = tmp_path / "linked-out"
    try:
        link.symlink_to(output, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValidationError, match="real directory"):
        verify_export(link)
    target = tmp_path / "copy.csv"
    target.write_bytes((output / "objects.csv").read_bytes())
    (output / "objects.csv").unlink()
    (output / "objects.csv").symlink_to(target)
    with pytest.raises(ValidationError, match="regular file"):
        verify_export(output)


def test_cli_verify_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = _export(tmp_path)
    assert main(["verify", str(output)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["valid"] is True
    assert payload["file_count"] == 6
    assert main(["verify", str(tmp_path / "missing")]) == 2
    captured = capsys.readouterr()
    assert "roi-replicates:" in captured.err
    assert "Traceback" not in captured.err
