#!/usr/bin/env bash
# Before pushing: run full CI workflow checks locally (default).
# No remote push or network dispatch is performed.
# Use --dry-run to print planned commands without executing.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Find Python interpreter (prefer explicit, conda/venv, or repository environment)
if [ -n "${CI_CHECK_PYTHON:-}" ] && [ -x "${CI_CHECK_PYTHON}" ]; then
    PYTHON_BIN="${CI_CHECK_PYTHON}"
elif [ -n "${VIRTUAL_ENV:-}" ] && [ -x "${VIRTUAL_ENV}/bin/python" ]; then
    PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
elif [ -n "${CONDA_PREFIX:-}" ] && [ -x "${CONDA_PREFIX}/bin/python" ]; then
    PYTHON_BIN="${CONDA_PREFIX}/bin/python"
elif [ -x "${REPO_ROOT}/../miniforge3/envs/helios/bin/python" ]; then
    PYTHON_BIN="${REPO_ROOT}/../miniforge3/envs/helios/bin/python"
elif [ -x "${REPO_ROOT}/.venv/bin/python" ]; then
    PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
else
    PYTHON_BIN="python3"
fi

exec "${PYTHON_BIN}" "${REPO_ROOT}/scripts/ci_contract.py" local "$@"
