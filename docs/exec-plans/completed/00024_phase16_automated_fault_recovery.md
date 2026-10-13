# Execution Plan / Change Record: 00024

- **Sub-tasks**: Phase 16 Automated Fault Recovery & Self-Healing Linac Architecture (16.1, 16.2, 16.3)
- **Status**: Completed
- **Date**: 2026-10-13
- **Author**: Chong Shik Park / HELIOS Team
- **Reference**: LBNL Osprey Framework, Automated Linac Fault Rematching, Self-Healing Operations

---

## 1. Objectives

- Implement autonomous local RF cavity rematching to recover energy gain and synchronous arrival time when an SRF cavity trips or unlatches in superconducting linacs.
- Implement magnet power supply trip isolation with SVD-based orbit re-steering using surviving healthy magnets.
- Build radiation loss hotspot localization and autonomous steerer mitigation to guide beam off vacuum chamber walls.
- Register Phase 16 recovery capabilities in `CapabilityRegistry`.

---

## 2. Implementation Summary

1. **Autonomous RF Cavity Failure Rematching (`helios/recovery/rf_rematch.py`)**:
   - `RFCavityRematcher`: Solves bounded L-BFGS-B optimization over downstream operational cavity voltages and phases to restore target energy gain ($\ge 90\%$) while respecting maximum voltage limits and bucket phase stability ($\le -15^\circ$).
2. **Magnet Power Supply Trip Recovery (`helios/recovery/magnet_recovery.py`)**:
   - `MagnetPowerSupplyRecoverer`: Sets the tripped power supply setpoint to 0.0, slices the response matrix for active healthy steerers, and solves pseudo-inverse correction to flatten residual BPM distortion.
3. **Beam Loss Hotspot Mitigation (`helios/recovery/loss_mitigation.py`)**:
   - `BeamLossMitigator`: Pinpoints peak loss locations from BLM detector telemetry and identifies nearest upstream steerers to apply corrective kicks away from chamber scraping surfaces.
4. **Registry & Testing**:
   - Registered `autonomous_rf_cavity_rematch`, `recover_tripped_magnet`, and `mitigate_beam_loss_hotspot` in `CapabilityRegistry`.
   - Built comprehensive test suite in `tests/test_fault_recovery.py`.
   - Verified that all 76 tests pass in the `helios` conda environment.

---

## 3. Files Modified / Created

- `M  docs/exec-plans/active/00022_next_development_phases_tasklist.md`
- `A  docs/exec-plans/completed/00024_phase16_automated_fault_recovery.md`
- `M  helios/core/capabilities.py`
- `A  helios/recovery/__init__.py`
- `A  helios/recovery/loss_mitigation.py`
- `A  helios/recovery/magnet_recovery.py`
- `A  helios/recovery/rf_rematch.py`
- `A  tests/test_fault_recovery.py`
