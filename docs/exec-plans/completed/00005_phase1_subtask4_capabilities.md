# Execution Plan / Change Record: 00005

- **Sub-task**: 1.4 Dynamic Capability Classifier
- **Status**: Completed
- **Date**: 2026-10-13
- **Author**: Chong Shik Park / HELIOS Team
- **Reference**: LBNL Osprey Framework

---

## 1. Objectives

- Implement the Dynamic Capability Classifier inspired directly by LBNL's Osprey framework.
- Protect LLM prompt efficiency and context boundaries by filtering hundreds of accelerator subsystem tools down to task-relevant subsets.
- Support metadata-based classification (domains, agent roles, keywords, risk levels) and default registry population.

---

## 2. Implementation Summary

1. **`Capability` Model (`helios/core/capabilities.py`)**:
   - Represents a tool or sub-skill with attributes: `name`, `description`, `domain` (ORBIT, OPTICS, RF, DIAGNOSTICS, SAFETY, SIMULATION, EPICS, OPTIMIZATION), `target_agent`, `risk_level` (READ_ONLY to CRITICAL), and intent keywords.
2. **`CapabilityRegistry` (`helios/core/capabilities.py`)**:
   - Provides methods for registering, querying by domain or agent, and dynamic semantic scoring (`classify_intent`) matching operator directives to tools.
   - Built-in rule guarantees high-priority safety inspection tools are included in any dispatched context.
3. **`get_default_registry()`**:
   - Pre-populates baseline heavy ion linac capabilities across diagnostics, orbit tuning, RF scanning, TraceWin simulation, and EPICS execution.
4. **Automated Testing**:
   - Implemented `tests/test_capabilities.py` verifying domain filtering, agent filtering, and dynamic intent classification for orbit, RF, and simulation workflows. All tests passed.

---

## 3. Files Modified / Created

- `M  docs/exec-plans/active/00001_development_tasklist.md`
- `A  docs/exec-plans/completed/00005_phase1_subtask4_capabilities.md`
- `M  helios/core/__init__.py`
- `A  helios/core/capabilities.py`
- `A  tests/test_capabilities.py`
