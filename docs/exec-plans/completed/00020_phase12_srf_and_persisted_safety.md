# Execution Plan / Change Record: 00020

- **Sub-tasks**: Phase 12 Superconducting RF (SRF) & Advanced Linac Safety Guardrails (12.1, 12.2, 12.3)
- **Status**: Completed
- **Date**: 2026-10-13
- **Author**: Chong Shik Park / HELIOS Team
- **Reference**: LBNL Osprey Framework, SRF Cryomodule Protection, Fast MPS Modeling

---

## 1. Objectives

- Implement superconducting RF (SRF) quench and cryogenic thermal protection checks (quench gradient limits, multipacting zone barriers, sub-atmospheric 2K helium bath limits, liquid inventory, and reflected power ratio trips).
- Implement a persistent SQLite-backed rollback journal (`PersistentRollbackJournal`) ensuring baseline checkpoints survive power outages and process restarts.
- Add an emergency panic shutdown protocol (`panic_shutdown`) to instantly de-energize beamline RF and steerers.
- Model fast Machine Protection System (MPS) latency budgets ($\le 25 \mu\text{s}$) to prevent heavy-ion beam puncture of niobium/copper cavity walls.

---

## 2. Implementation Summary

1. **SRF Cavity Quench & Thermal Protection (`helios/safety/srf_protection.py`)**:
   - `SRFCavityLimits`: Holds cavity quench limit ($E_{acc,max}$), cryogenic temperature threshold ($T_{max} \le 2.1\text{ K}$), minimum liquid helium level, and forbidden multipacting resonance intervals.
   - `SRFProtectionMonitor`: Validates candidate cavity setpoints against physical quench, arcing, and thermal margins, emitting structured `ValidationResult`.
2. **Persistent Rollback Journal & Panic Shutdown (`helios/safety/rollback.py`)**:
   - `PersistentRollbackJournal`: SQLite-backed journal persisting checkpoints (`checkpoint_id`, `label`, `timestamp`, `setpoints_json`).
   - `RollbackController`: Hydrates in-memory stack from SQLite on initialization, persists every new checkpoint to disk.
   - `panic_shutdown`: Emergency one-click setpoint zeroing for all critical RF amplitudes and steerers.
3. **MPS Latency Modeling & Fast Interlocks (`helios/safety/mps.py`)**:
   - `LatencyBudget`: Verifies $\tau_{detect} + \tau_{propagate} + \tau_{actuate} \le \tau_{damage}$.
   - `MPSManager`: Fast interlock node supervision (differential BPM loss, ion chamber BLMs, fast valves, arc detectors).
4. **Registry & Testing**:
   - Registered `verify_srf_quench_margins` and `panic_shutdown_machine` in `CapabilityRegistry`.
   - Built test suite `tests/test_srf_and_persisted_safety.py`.
   - Verified that all 61 tests pass in the `helios` conda environment.

---

## 3. Files Modified / Created

- `M  docs/exec-plans/active/00014_next_development_phases_tasklist.md`
- `A  docs/exec-plans/completed/00020_phase12_srf_and_persisted_safety.md`
- `M  helios/core/capabilities.py`
- `M  helios/safety/__init__.py`
- `A  helios/safety/mps.py`
- `M  helios/safety/rollback.py`
- `A  helios/safety/srf_protection.py`
- `A  tests/test_srf_and_persisted_safety.py`
