# Execution Plan / Change Record: 00019

- **Sub-tasks**: Phase 11 Deep Neural Surrogates & Virtual Diagnostics (11.1, 11.2, 11.3)
- **Status**: Completed
- **Date**: 2026-10-13
- **Author**: Chong Shik Park / HELIOS Team
- **Reference**: LBNL Osprey Framework, PyTorch Deep Surrogates, Virtual Diagnostics

---

## 1. Objectives

- Implement deep neural surrogate architecture using PyTorch with residual skip connections for sub-5ms predictions of 6D linac envelopes, centroid trajectories, and beam transmission.
- Build non-interceptive virtual diagnostics: `VirtualWireScanner` (transverse profile and emittance reconstruction) and `VirtualBeamLossMonitor` (halo scraping and radiation loss hotspot forecasting).
- Implement `OnlineModelCalibrator` to calibrate digital twin and surrogate parameters against live BPM orbit and beam telemetry.
- Register Phase 11 tools in the `CapabilityRegistry`.

---

## 2. Implementation Summary

1. **PyTorch Neural Surrogate (`helios/models/surrogate.py`)**:
   - `LinacSurrogateNet`: Deep neural network featuring GELU activations, multi-layer residual blocks (`ResidualBlock`), and dual output heads for spatial envelopes ($\sigma_x, \sigma_y, x, y$) and transmission $\eta \in [0, 1]$.
   - `NeuralLinacSurrogate`: Orchestrates inference, training (`train_step`), and model serialization (`save_weights`, `load_weights`), with fallback for non-PyTorch environments.
2. **Virtual Diagnostics Suite (`helios/models/virtual_diagnostics.py`)**:
   - `VirtualWireScanner`: Evaluates beam size, emittance, and Gaussian intensity profiles at arbitrary longitudinal positions $s$ non-interceptively.
   - `VirtualBeamLossMonitor`: Evaluates $3\sigma$ beam envelope against vacuum chamber aperture radii, detects halo scraping, computes beam power loss density ($W/\text{m}$), and flags interlock trips before beam delivery.
3. **Online Model Calibration (`helios/models/calibration.py`)**:
   - `OnlineModelCalibrator`: Performs bounded L-BFGS-B optimization to fit quadrupole calibration scaling factors against measured BPM orbit telemetry, minimizing RMS tracking error.
4. **Registry & Testing**:
   - Registered `predict_virtual_profile`, `predict_virtual_loss_map`, and `calibrate_model_parameters` in `CapabilityRegistry`.
   - Built comprehensive test suite in `tests/test_surrogates_and_virtual_diag.py`.
   - Verified that all 58 tests pass in the `helios` conda environment.

---

## 3. Files Modified / Created

- `M  docs/exec-plans/active/00014_next_development_phases_tasklist.md`
- `A  docs/exec-plans/completed/00019_phase11_surrogates_and_virtual_diagnostics.md`
- `M  helios/core/capabilities.py`
- `A  helios/models/__init__.py`
- `A  helios/models/calibration.py`
- `A  helios/models/surrogate.py`
- `A  helios/models/virtual_diagnostics.py`
- `A  tests/test_surrogates_and_virtual_diag.py`
