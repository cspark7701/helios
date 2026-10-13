# Execution Plan / Change Record: 00018

- **Sub-tasks**: Phase 10 Advanced EPICS pvAccess & Archiver Appliance Bridge (10.1, 10.2, 10.3)
- **Status**: Completed
- **Date**: 2026-10-13
- **Author**: Chong Shik Park / HELIOS Team
- **Reference**: LBNL Osprey Framework, EPICS pvAccess (p4p), EPICS Archiver Appliance

---

## 1. Objectives

- Implement high-performance EPICS pvAccess (PVA) communication using `p4p` supporting normative types (`NTTable`, `NTNDArray`, `NTScalar`).
- Integrate an EPICS Archiver Appliance REST client for querying PB/JSON time-series data, historical baseline extraction, and drift rate statistics.
- Enforce Channel Access Security (CAS) policies and role-based clearance checks (`READ_ONLY`, `OPERATOR`, `PHYSICIST`, `ADMIN`) before issuing writes.
- Register PVA and Archiver tools into the `CapabilityRegistry`.

---

## 2. Implementation Summary

1. **EPICS pvAccess Client (`helios/interfaces/pva.py`)**:
   - `PVAccessInterface` implements `BaseControlInterface`.
   - Supports native `p4p` thread context with fallback mock operations.
   - Normative Type support:
     - `get_nt_table` / `put_nt_table` for multi-BPM orbit vectors.
     - `get_nt_ndarray` / `put_nt_ndarray` for profile monitor camera image matrices.
     - Synchronous `get`, `put`, `get_many`, `put_many`, and subscription monitors.
2. **Archiver Appliance Client (`helios/interfaces/archiver.py`)**:
   - `ArchiverApplianceClient` queries `/retrieval/data/getData.json`.
   - `get_golden_baseline`: extracts median snapshot values for specified PVs around reference timestamps.
   - `compute_pv_statistics`: computes mean, std, min, max, and drift slope per minute.
3. **Control Security Manager (`helios/interfaces/security.py`)**:
   - `ControlSecurityManager` & `ControlSecurityPolicy`.
   - Enforces RBAC permissions and pattern-based protection (interlocks and MPS statuses require ADMIN; cavities/quads require PHYSICIST; steerers require OPERATOR).
   - Integrated into `PVAccessInterface` to block unauthorized actuations with `SecurityViolationError`.
4. **Registry & Testing**:
   - Registered `query_archiver_data` and `pva_get_table` in `CapabilityRegistry`.
   - Added unit test suite `tests/test_pva_and_archiver.py` covering roles, NT normative types, monitors, and archiver queries.
   - All 54 tests passing in `helios` conda environment.

---

## 3. Files Modified / Created

- `M  docs/exec-plans/active/00014_next_development_phases_tasklist.md`
- `A  docs/exec-plans/completed/00018_phase10_pvaccess_and_archiver.md`
- `M  helios/core/capabilities.py`
- `M  helios/interfaces/__init__.py`
- `A  helios/interfaces/archiver.py`
- `A  helios/interfaces/pva.py`
- `A  helios/interfaces/security.py`
- `A  tests/test_pva_and_archiver.py`
