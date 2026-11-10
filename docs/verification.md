# Verification record

Checked locally on Linux x86_64 on 2026-11-10. This is a software verification record, not scientific validation or public-release evidence.

## Passed

- Full 50-test `unittest` suite on CPython 3.10.22 and 3.12.14.
- Built a wheel with setuptools 84.2.1 and wheel 0.48.0, then installed that wheel without dependencies or network in two fresh virtual environments.
- Ran the full 50-test suite again from outside the source checkout, using each environment's installed package. Verified imports resolved to `site-packages`, not the source tree.
- Installed CLI version, validation, synthetic export and Python API example in both environments. The expected synthetic group mean was 15 µm, SD 7.0710678118654755 µm, with 3 declared / 2 analyzable replicates.
- `pip check` in each environment: no broken requirements.
- `compileall` on package, examples and tests.
- Built a source distribution and rebuilt a wheel from its extracted source. Reinstalled the rebuilt wheel and reran all 50 tests against the extracted source distribution.
- Additional independent adversarial checks covered invalid number syntax, conversion overflow/underflow, extreme finite values, malformed CSV, source duplication, empty/excluded counts, weighting, exact JSON round-trip, formula-like CSV strings, hashes and no-overwrite behavior.
- Review identified a lone-Unicode-surrogate validation gap. Input validation now rejects it before serialization, with a regression case. Original ROI-ID handling and raw-area preservation were reviewed after addition.

The 50 tests include subcases for malformed inputs, so this number is test methods, not a count of every input case. Sources and packages in this delivery have SHA-256 checksums in the bundle.

## Not run / not claimed

- Windows or macOS execution. The supplied GitHub Actions matrix is proposed, not a completed CI run.
- All Python versions allowed by `requires-python`; only 3.10.22 and 3.12.14 were run.
- Ruff lint or static type checks. Ruff was not installed or in the offline tool cache; no successful lint result is claimed. Syntax compilation and runtime tests passed.
- Real instrument/ImageJ exports, acquisition calibration, segmentation review, biological replicate validation, experimental comparison or scientific accuracy validation.
- Very large-dataset performance or hostile concurrent filesystem mutation testing. Resource caps are not throughput guarantees.
- PyPI upload, new GitHub repository creation, public push, or external CI. The artifact remains a private review bundle.
