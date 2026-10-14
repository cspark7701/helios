# Execution Plan 00052: Reach 100% Test Coverage across HELIOS

## 🎯 Goal & Overview
Elevate the total test coverage of the HELIOS codebase from ~90% to **100%** (`--cov-fail-under=100`), ensuring that all linac subsystems, safety gates, physics engines, digital twins, control interfaces, optimization routines, and user interfaces are comprehensively verified under all branches, edge cases, and exception conditions.

---

## 📋 Task Breakdown

### Phase 1: Physics Engine & Simulation Subsystems
- [x] **T-01: Physics Simulation Engines & Subprocess Verification (`tests/test_coverage_physics_engine.py`)**
  - Cover all execution branches in `helios/physics/engine.py`: `TrackSimulator` (`_parse_beam_file`, `_parse_envelope_file`, subprocess error handling, fallback provenance), `ImpactZSimulator`, `TraceWinSimulator`, and `AnalyticDigitalTwinEngine` (`apply_setpoints`, `estimate_losses`).
- [x] **T-02: Advanced Physics Elements, Strippers & Solvers (`tests/test_coverage_physics_elements.py`)**
  - Cover uncovered lines in `helios/physics/elements.py`, `species.py` (multi-charge components and isotopic lookups), `differentiable.py`, `parallel.py`, `halo.py`, `liquid_stripper.py`, `fieldmaps.py`, `vacuum.py`, `converters.py`, `pusher.py`, `beam_dump.py`, `css.py`, `stripper.py`, `surrogate.py`, `equipartition.py`.

### Phase 2: Core Orchestration, LLM & Plan Engine
- [x] **T-03: Core LLM Clients & Plan Engine Edge Cases (`tests/test_coverage_core.py`)**
  - Cover uncovered lines in `helios/core/llm.py` (OpenAI provider HTTP request, error handling, Ollama HTTP stream, fallback), `plan_engine.py` (execution errors, step timeouts, state transitions), `facility_config.py`, `capabilities.py`, `mesh.py`, `agents/orchestrator.py`, `agents/cotuner.py`, `agents/planner.py`.

### Phase 3: Control & Diagnostic Interfaces
- [x] **T-04: EPICS, PVA, Channel Map & Archiver Interfaces (`tests/test_coverage_interfaces.py`)**
  - Cover uncovered lines in `helios/interfaces/epics.py` (CA connect, put, get, monitor callbacks, reconnect), `pva.py` (P4P client interactions, disconnected channels), `channel_map.py` (YAML/JSON loaders, channel validation), `archiver.py` (Appliance HTTP queries, retry logic), `base.py`, `security.py`.
  - Cover diagnostics in `helios/diagnostics/anomaly.py`, `archiver.py`, `telemetry.py`, `survey.py`.

### Phase 4: Modular Digital Twin Framework
- [x] **T-05: Twin Registry, Protocol, Gym Env & MPC (`tests/test_coverage_twin.py`)**
  - Cover uncovered lines in `helios/physics/twin/registry.py` (entry point loading error handling, raon plugin import branch, missing facility lookups), `protocol.py`, `env.py` (target reached branch, rendering), `mpc.py` (step clamping), `sync.py`, and `helios/physics/twin/__init__.py` (import fallback branches).

### Phase 5: Safety, RF Systems & Recovery
- [x] **T-06: Safety Gatekeepers, Fast MPS & SRF Protection (`tests/test_coverage_safety_rf.py`)**
  - Cover uncovered lines in `helios/safety/gatekeeper.py`, `srf_protection.py`, `predictive.py`, `fast_mps.py`, `policy.py`, `activation.py`, `mps.py`.
  - Cover RF subsystems: `helios/rf/cryoplant.py` (closed-loop cryogenic balancing, heat load trip), `conditioning.py`, `multipactor.py`, `microphonics.py`.
  - Cover recovery modules: `helios/recovery/loss_mitigation.py`, `magnet_recovery.py`, `rf_rematch.py`.

### Phase 6: Optimization, Operations, Ontology & UI
- [x] **T-07: RL, Operations Harness, Ontology & Web UI (`tests/test_coverage_ops_ui.py`)**
  - Cover uncovered lines in `helios/optimization/rl_agent.py`, `mpc.py`, `workflows.py`, `algorithms.py`, `__init__.py`.
  - Cover `helios/envs/linac_env.py` and `__init__.py`.
  - Cover `helios/ops/broker.py`, `logbook.py`, `golden.py`, `audit.py`, `harness.py`.
  - Cover `helios/ontology/loader.py`, `rdf_exporter.py`, `graph.py`.
  - Cover `helios/ui/visualizer.py`, `voice.py`, `sim/cosim.py`, `security/rbac.py`, `tuning/bba.py`, `bunch_compressor.py`, `models/surrogate.py`, `calibration.py`.
  - Cover `helios/dashboard/app.py`, `deps.py`, `routers/llm.py`, `plans.py`, `status.py`, `ws.py`, `tuning.py`.

### Phase 7: Final Verification & 100% Coverage Gate
- [ ] **T-08: Pyproject Configuration & 100% Coverage Gate**
  - Update `pyproject.toml` to set `--cov-fail-under=100` and `fail_under = 100`.
  - Verify complete test suite achieves 100.0% coverage across all modules.
  - Run all CI contract checks (`python scripts/ci_contract.py checks`).
  - Archive plan to `docs/exec-plans/completed/00052_reach_100_percent_test_coverage.md` and update `INDEX.md`.

---

## 🔒 Safety & Testing Invariants
1. All existing functionality and test behaviors must be preserved.
2. No hardware writes without gatekeeper safety validation.
3. Every test must execute deterministically in CI without requiring external hardware, network APIs, or proprietary binaries.
