#!/usr/bin/env bash
# ==============================================================================
# Environment loader for HELIOS Heavy Ion Linac Intelligent Orchestration
# ==============================================================================
# Usage:
#   source setup.sh
#
# Automatically activates the 'helios' Conda/Miniforge environment (or local venv),
# and exports paths for HELIOS and associated accelerator simulation codes (TRACK).
# ==============================================================================

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "Source this script so its environment changes persist: source setup.sh" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export HELIOS_ROOT="${SCRIPT_DIR}"
export PROJECT_ROOT="${SCRIPT_DIR}"
export TRACK_ROOT="${TRACK_ROOT:-}"
if [[ -n "${TRACK_ROOT}" ]]; then
    export TRACK_EXE_PATH="${TRACK_EXE_PATH:-${TRACK_ROOT}/TRACKv39C.exe}"
    export PATH="${TRACK_ROOT}:${PATH}"
fi

# Prepend project directories and simulation tools to PATH & PYTHONPATH
export PATH="${HELIOS_ROOT}/bin:${PATH}"
export PYTHONPATH="${HELIOS_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

# ------------------------------------------------------------------------------
# Activate Python Environment for HELIOS
# 1. Prefer conda/mamba environment 'helios' (e.g. Miniforge3)
# 2. Fall back to local checkout virtual environment (.venv)
# ------------------------------------------------------------------------------
HELIOS_ENV_ACTIVATED=0

# Check common Miniforge/Conda root locations
CONDA_ROOT_CANDIDATES=(
    "${CONDA_PREFIX}"
    "${CONDA_PREFIX_1}"
    "${CONDA_ROOT}"
    "${HOME}/miniforge3"
    "${HOME}/miniconda3"
    "${HOME}/anaconda3"
)

# If conda command is available or can be sourced via profile.d/conda.sh
activate_conda_helios() {
    local conda_sh=""
    for root in "${CONDA_ROOT_CANDIDATES[@]}"; do
        if [[ -n "${root}" && -f "${root}/etc/profile.d/conda.sh" ]]; then
            conda_sh="${root}/etc/profile.d/conda.sh"
            break
        fi
    done

    if [[ -z "${conda_sh}" && -n "$(command -v conda 2>/dev/null)" ]]; then
        local conda_bin
        conda_bin="$(command -v conda)"
        local base_dir
        base_dir="$(cd "$(dirname "${conda_bin}")/.." && pwd)"
        if [[ -f "${base_dir}/etc/profile.d/conda.sh" ]]; then
            conda_sh="${base_dir}/etc/profile.d/conda.sh"
        fi
    fi

    if [[ -n "${conda_sh}" ]]; then
        source "${conda_sh}"
        if conda info --envs | grep -E '^helios\s+' >/dev/null 2>&1; then
            conda activate helios
            return 0
        fi
    fi

    # Fallback: check direct prefix path for helios env
    for root in "${CONDA_ROOT_CANDIDATES[@]}"; do
        if [[ -n "${root}" && -d "${root}/envs/helios" && -f "${root}/etc/profile.d/conda.sh" ]]; then
            source "${root}/etc/profile.d/conda.sh"
            conda activate "${root}/envs/helios"
            return 0
        fi
    done

    return 1
}

activate_local_venv() {
    if [[ -f "${HELIOS_ROOT}/.venv/bin/activate" ]]; then
        source "${HELIOS_ROOT}/.venv/bin/activate"
        return 0
    fi
    return 1
}

if activate_conda_helios; then
    HELIOS_ENV_ACTIVATED=1
    ENV_DESC="conda: helios (${CONDA_PREFIX})"
elif activate_local_venv; then
    HELIOS_ENV_ACTIVATED=1
    ENV_DESC="venv: ${HELIOS_ROOT}/.venv"
else
    echo "[helios] Warning: Could not find 'helios' conda environment or .venv" >&2
    ENV_DESC="system default ($(which python 2>/dev/null || echo 'none'))"
fi

echo "[helios] Environment configured:"
echo "  PROJECT_ROOT:   ${HELIOS_ROOT}"
echo "  PYTHON:         $(which python 2>/dev/null)"
echo "  ACTIVE ENV:     ${ENV_DESC}"
if [[ -x "${TRACK_EXE_PATH}" ]]; then
    echo "  TRACK_EXE_PATH: ${TRACK_EXE_PATH} (available)"
else
    echo "  TRACK_EXE_PATH: ${TRACK_EXE_PATH} (not found or not executable)"
fi
