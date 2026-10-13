# Execution Plan / Change Record: 00017

- **Sub-tasks**: Phase 9 Production Simulators (ANL TRACK & LBNL IMPACT-Z Integration)
- **Status**: Completed
- **Date**: 2026-10-13
- **Author**: Chong Shik Park / HELIOS Team
- **Reference**: LBNL Osprey Framework, ANL TRACK, LBNL IMPACT-Z (lume-impact)

---

## 1. Objectives

- Integrate ANL TRACK (64-bit binary running under Wine) as the primary heavy-ion linac tracking engine, replacing proprietary/closed TraceWin.
- Integrate LBNL IMPACT-Z (via `lume-impact` and `ImpactZ`) for 3D particle-in-cell space-charge simulation.
- Register TRACK and IMPACT-Z simulators as first-class tools in the `CapabilityRegistry` for dynamic injection into agent LLM prompts.
- Implement robust graceful degradation: if simulation binaries or Wine environments are unavailable or fail, fall back seamlessly to the analytic digital twin engine.
- Update documentation and architectural diagrams in `README.md` and `AGENTS.md`.

---

## 2. Implementation Summary

1. **ANL TRACK Simulation Engine (`helios/physics/engine.py:TrackSimulator`)**:
   - Generates input control file `track.dat` and lattice definition file `sclinac.dat`.
   - Executes 64-bit Windows binary `/home/cspark/Work/simulation_codes-working/track/TRACKv39C.exe` headlessly via `/usr/bin/wine`.
   - Ingests `envelop.out` for beam RMS beam sizes ($\sigma_x, \sigma_y$) and centroids.
   - Provides seamless fallback to `AnalyticDigitalTwinEngine` if execution encounters wine/binary faults.
2. **LBNL IMPACT-Z Simulation Engine (`helios/physics/engine.py:ImpactZSimulator`)**:
   - Interfaces with `lume-impact` (`Impact`, `ImpactZ`) for 3D space-charge PIC calculations.
   - Returns beam dynamics metrics including projected beam loss and final beam envelopes.
   - Includes graceful fallback for environments lacking local impact binaries.
3. **Capability Registration (`helios/core/capabilities.py`)**:
   - Registered `run_track_simulation` and `run_impactz_simulation` as physics capabilities in `CapabilityRegistry`.
   - Tagged with domain `physics`, risk `low`, and read-only flags.
4. **Verification & Tests (`tests/test_physics.py`, `tests/test_capabilities.py`)**:
   - Added unit tests for `TrackSimulator` and `ImpactZSimulator` verifying lattice generation, execution, output parsing, and fallback mechanics.
   - Verified capability discovery and execution via registry.
   - All 50 tests passing in the `helios` conda environment.

---

## 3. Files Modified / Created

- `M  AGENTS.md`
- `M  README.md`
- `M  docs/exec-plans/active/00014_next_development_phases_tasklist.md`
- `A  docs/exec-plans/completed/00017_phase9_track_and_impactz_simulators.md`
- `M  helios/core/capabilities.py`
- `M  helios/physics/__init__.py`
- `M  helios/physics/engine.py`
- `M  tests/test_capabilities.py`
- `M  tests/test_physics.py`
