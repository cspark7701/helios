# Execution Plan / Change Record: 00013

- **Sub-task**: Dedicated Conda Environment Setup (`helios`)
- **Status**: Completed
- **Date**: 2026-10-13
- **Author**: Chong Shik Park / HELIOS Team
- **Reference**: LBNL Osprey Framework

---

## 1. Objectives

- Define a reproducible conda environment specification file (`environment.yml`).
- Create and provision a dedicated conda environment named `helios` with Python 3.11.
- Install the `helios-linac` package in editable mode with all dev and EPICS dependencies into the `helios` environment.
- Verify that the full pytest test suite (44 tests) passes within the conda environment.
- Document conda activation and workflow in `README.md`.

---

## 2. Implementation Summary

1. **`environment.yml`**:
   - Specified conda-forge channels with `python=3.11`, `numpy>=1.24.0`, `scipy>=1.10.0`, `pyyaml>=6.0`, and pip dependencies installing `.[dev,epics]`.
2. **Conda Environment Creation**:
   - Executed `/home/cspark/Work/simulation_codes-working/miniforge3/condabin/conda env create -f environment.yml`.
   - Environment created at `/home/cspark/Work/simulation_codes-working/miniforge3/envs/helios`.
   - Verified installation of `pyepics-3.5.10`, `pydantic-2.14.1`, `rich-15.0.0`, `typer-0.27.3`, `pytest-9.1.1`, and `helios-linac==0.1.0`.
3. **Verification**:
   - Ran `/home/cspark/Work/simulation_codes-working/miniforge3/envs/helios/bin/pytest`: 44/44 tests passed in 1.11s.
   - Tested `/home/cspark/Work/simulation_codes-working/miniforge3/envs/helios/bin/helios info`: CLI functioning as expected.
4. **Documentation**:
   - Updated `README.md` to provide Option 1 (Conda Environment `helios`) and Option 2 (Python venv).

---

## 3. Files Modified / Created

- `M  README.md`
- `A  environment.yml`
- `A  docs/exec-plans/completed/00013_conda_environment_setup.md`
