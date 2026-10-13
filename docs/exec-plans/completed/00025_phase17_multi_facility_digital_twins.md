# Execution Plan / Change Record: 00025

- **Sub-tasks**: Phase 17 Multi-Facility Digital Twin Adapters & Benchmark Lattice Decks (17.1, 17.2, 17.3)
- **Status**: Completed
- **Date**: 2026-10-13
- **Author**: Chong Shik Park / HELIOS Team
- **Reference**: LBNL Osprey Framework, RAON, FRIB, GSI/FAIR, MAD-X, Elegant

---

## 1. Objectives

- Provide verified out-of-the-box accelerator digital twin models for international heavy ion facilities:
  - RAON (SCL1 QWR/HWR superconducting linac)
  - FRIB (Linac Segment 1 QWR cryomodules and superconducting solenoids)
  - GSI / FAIR (UNILAC injector linac)
- Implement bi-directional lattice converters supporting CERN MAD-X and APS Elegant LTE file formats.
- Implement automated cross-code benchmark runner comparing ANL TRACK, LBNL IMPACT-Z, and the Analytic Digital Twin.
- Register Phase 17 capabilities in `CapabilityRegistry`.

---

## 2. Implementation Summary

1. **Facility Lattice Digital Twins (`helios/physics/facilities.py`)**:
   - `create_raon_scl1_lattice`: Generates multi-period QWR and HWR cryomodule structures with superconducting doublets, BPMs, and BLMs.
   - `create_frib_ls1_lattice`: Models FRIB LS1 $\beta=0.041, 0.085$ cavities and 9T focusing solenoids.
   - `create_gsi_fair_lattice`: Models GSI UNILAC High-Charge State injector structures.
2. **Cross-Format Lattice Converters (`helios/physics/converters.py`)**:
   - `LatticeConverter.export_to_madx`: Generates valid MAD-X beamline definitions (`DRIFT`, `QUADRUPOLE`, `RFCAVITY`, `HKICKER`, `MONITOR`, `LINE`).
   - `LatticeConverter.export_to_elegant`: Generates valid Elegant `.lte` decks (`EDRIFT`, `KQUAD`, `RFCW`, `HKICK`, `WATCH`).
   - `LatticeConverter.import_from_madx`: Ingests and parses MAD-X deck definitions into HELIOS `Lattice` objects.
3. **Cross-Code Benchmark Runner (`helios/physics/benchmarks.py`)**:
   - `CrossCodeBenchmarkRunner`: Executes benchmark runs across solvers, extracts execution latency (ms), RMS envelope extrema, and reports consistency metrics.
4. **Registry & Testing**:
   - Registered `load_facility_lattice`, `export_lattice_format`, and `run_cross_code_benchmarks` in `CapabilityRegistry`.
   - Built comprehensive test suite in `tests/test_facilities_and_converters.py`.
   - Verified that all 79 tests pass in the `helios` conda environment.

---

## 3. Files Modified / Created

- `M  docs/exec-plans/active/00022_next_development_phases_tasklist.md`
- `A  docs/exec-plans/completed/00025_phase17_multi_facility_digital_twins.md`
- `M  helios/core/capabilities.py`
- `M  helios/physics/__init__.py`
- `A  helios/physics/benchmarks.py`
- `A  helios/physics/converters.py`
- `A  helios/physics/facilities.py`
- `M  helios/physics/lattice.py`
- `A  tests/test_facilities_and_converters.py`
