# Active Execution Plan: Development of `helios.physics.twin`

- **Status**: Active (proposed execution plan)
- **Plan ID**: `00051`
- **Domain**: Accelerator Physics, Digital Twin, Machine Learning & Control
- **Reference Architecture**: HELIOS Standard Architecture (`AGENTS.md`), Osprey Pattern, and `docs/integration_synaptictrack_raon.md`
- **Created**: 2026-10-14

---

## 🎯 Executive Summary & Objectives

This plan defines the end-to-end implementation roadmap for the **`helios.physics.twin`** package. 
As established in the architectural evaluation (`docs/integration_synaptictrack_raon.md`), the Digital Twin is split by concern:
1. **Twin Framework Host (`helios.physics.twin`)**: Open, facility-agnostic host in HELIOS providing the plugin registry, pre-flight safety verifier, Gymnasium RL adapter, Neural MPC optimizer, and state synchronization loop.
2. **Machine-Neutral ML Engine (`synapticTrack`)**: Public PyTorch library providing `FrozenSurrogateInterface`, `TorchFrozenSurrogate`, unit normalizers, MAP beam-state estimation, and deterministic mock surrogates.
3. **Private Facility Content (`raon`)**: Proprietary lattice decks, trained checkpoints (`legacy_50000/best_model.pt`), and hardware calibration sets loaded in-process via an entry-point plugin.

The package must guarantee sub-millisecond pre-flight evaluation (measured at 0.16 ms on CPU for the RAON LEBT surrogate), strict out-of-domain boundary rejection, and zero import-time dependence on private repositories, ensuring HELIOS remains fully publishable with 100% passing public CI.

---

## 🏗️ Target Package Architecture (`helios/physics/twin/`)

```
helios/physics/twin/
├── __init__.py           # Public exports: FacilityTwin, TwinDomain, FacilityPlugin, etc.
├── protocol.py           # Protocol & data schemas: TwinDomain, FacilityTwin, FacilityPlugin
├── registry.py           # Entry-point discovery ('helios.facilities') & fallback manager
├── verifier.py           # TwinPreFlightVerifier with Out-of-Domain (OOD) guards & aperture checks
├── env.py                # LinacSurrogateGymEnv: Gymnasium adapter wrapping FacilityTwin
├── mpc.py                # TwinNeuralMPC: Autograd gradient descent through FrozenSurrogateInterface
└── sync.py               # TwinStateSynchronizer: Telemetry assimilation & MAP beam estimation
```

---

## 📋 Detailed Task Breakdown

### Phase 1: Core Protocols and Domain Contracts (`protocol.py`)
- [x] **T-01: Define `TwinDomain` with Out-of-Domain (OOD) Detection**
  - Implement `TwinDomain(names, lower, upper)` with physical parameter limits.
  - Provide `out_of_domain(u, margin=0.0) -> list[str]` returning violated control names.
- [x] **T-02: Define `FacilityTwin` Container**
  - Encapsulate `facility: str`, `section: str`, `surrogate: FrozenSurrogateInterface`, `control_names`, `control_units`, `diagnostic_names`, `domain: TwinDomain`, and `provenance: Mapping[str, str]` (checkpoint SHA-256, schema version, factory ID).
- [ ] **T-03: Define `FacilityPlugin` Formal Protocol**
  - Specify `available_sections() -> Sequence[str]`, `load_twin(section) -> FacilityTwin`, `to_actuator_commands(section, controls) -> Mapping[str, dict]`, and `make_env(section, **kwargs) -> gym.Env`.
  - Ensure protocol imports only standard library and machine-neutral `synapticTrack` interfaces.

### Phase 2: Plugin Registry & Mock Fallback (`registry.py`)
- [ ] **T-04: Implement Dynamic Entry-Point Discovery**
  - Discover plugins registered under the `helios.facilities` entry-point group using `importlib.metadata.entry_points`.
  - Isolate third-party exceptions: if a private plugin fails to load, log a warning without raising, preserving HELIOS availability.
- [ ] **T-05: Implement Built-in `MockFacilityPlugin` for Public CI**
  - Provide a zero-dependency synthetic mock plugin using `synapticTrack.inference.MockNonlinearSurrogate` or analytic fallback.
  - Ensure all HELIOS unit tests and CI workflows run cleanly without requiring local access to `raon`.
- [ ] **T-06: Implement `AnalyticTwinFallback`**
  - Wrap `AnalyticDigitalTwinEngine` as a default fallback when no neural surrogate plugin is registered for a given linac section.

### Phase 3: Pre-Flight Safety Verifier & Aperture Loss Model (`verifier.py`)
- [ ] **T-07: Implement `TwinPreFlightVerifier`**
  - Ingest candidate control setpoints from `HELIOS-Tuner` or operational plans.
  - Execute pre-flight verification step in under 2 ms:
    1. Check candidate values against `TwinDomain.out_of_domain()`. Reject or escalate out-of-domain requests.
    2. Execute differentiable surrogate prediction: `surrogate.predict(beam_state, machine_setting)`.
    3. Evaluate predicted centroid orbit $\vec{x}_{\text{BPM}}$ against operational stay-clear boundaries.
    4. Compute stay-clear margin using beam envelope $\sigma(s)$ against physical aperture limits.
- [ ] **T-08: Provenance & Audit Trail Integration**
  - Generate structured validation metadata: model identity, checkpoint checksum, inference execution latency, and OOD check status.
  - Wire directly into `HELIOS-Safety` (`SafetyGatekeeper`) and `docs/exec-plans/` audit logging.

### Phase 4: Gymnasium Reinforcement Learning Adapter (`env.py`)
- [ ] **T-09: Implement `LinacSurrogateGymEnv`**
  - Wrap `FacilityTwin` in the standard Gymnasium API (`reset`, `step`, `action_space`, `observation_space`).
  - Adapt `raon_adapters.legacy.rl_env.SurrogateLEBTEnv` conventions:
    - Observation: normalized diagnostic errors concatenated with normalized control setpoints.
    - Action: normalized control step adjustments $\Delta u$.
    - Reward: weighted RMS trajectory error penalty + actuator change regularization.
- [ ] **T-10: Domain Randomization and Quantization**
  - Support physical parameter jitter (initial Twiss parameters, incoming beam angle/position offsets).
  - Apply discrete power supply current quantization (e.g. 0.05 A DAC resolution) and slew rate clamping during simulation steps.
  - Verify throughput achieves $\le 0.5\text{ ms}$ per step ($\ge 2{,}000\text{ steps/s}$ on CPU).

### Phase 5: Differentiable Neural MPC Engine (`mpc.py`)
- [ ] **T-11: Implement `TwinNeuralMPC` Controller**
  - Replace dict-based `NeuralLinacSurrogate` dependence in `helios/optimization/mpc.py` with `FrozenSurrogateInterface`.
  - Implement PyTorch autograd loss minimization across a receding horizon $H$:
    $$\vec{u}^* = \arg\min_{\vec{u} \in \mathcal{D}} \sum_{k=1}^H \left\| W \big(\vec{y}_\theta(\vec{u}_k) - \vec{y}_{\text{target}}\big)\right\|^2 + \lambda_a \|\vec{u}_k - \vec{u}_0\|^2 + \lambda_s \|\vec{u}_k - \vec{u}_{k-1}\|^2$$
  - Constrain optimization trajectory within `TwinDomain` bounds.

### Phase 6: Telemetry Assimilation & State Synchronization (`sync.py`)
- [ ] **T-12: Implement `TwinStateSynchronizer`**
  - Connect live diagnostic readouts (BPM coordinates, Allison scanner, wire scanner profiles) to twin state.
  - Bridge to `synapticTrack.inference.map_refinement.refine_beam_state_map` to infer incoming Twiss parameters $(\alpha, \beta, \epsilon)$ in real time.
  - Feed estimated beam state into `FacilityTwin` inputs for downstream linac trajectory prediction.

### Phase 7: Verification Suite & Documentation
- [ ] **T-13: Comprehensive Unit & Integration Tests (`tests/test_twin.py`)**
  - Test protocol compliance, OOD rejection, mock plugin discovery, pre-flight verification latency, and Gym step speed.
- [ ] **T-14: Package Exports and Documentation**
  - Export `helios.physics.twin` in `helios/physics/__init__.py`.
  - Update user manuals and architecture documentation.

---

## 🔒 Safety Guardrails & Invariants

1. **Deterministic OOD Rejection**: If an operator plan specifies setpoints outside the surrogate's verified training envelope, the verifier must immediately reject the plan or flag mandatory operator manual review (`AutonomyLevel.ASSISTED`).
2. **Aperture Safety**: Surrogate predictions alone must never override physical aperture interlocks; if envelope information is absent, the verifier must combine predicted centroids with conservative beam sizes from the analytic engine.
3. **No Network Latency in Safety Path**: `FacilityTwin` must evaluate entirely in-process ($< 1\text{ ms}$). No remote RPC hops are permitted in the pre-flight gatekeeper loop.

---

## 📈 Verification & Acceptance Criteria

| Component | Target Metric | Verification Method |
| :--- | :--- | :--- |
| `protocol.py` | 100% type annotations, Pydantic/dataclass schema parity | `mypy` / `pytest tests/test_twin.py` |
| `registry.py` | Zero import errors when `raon` is missing | Public CI environment dry-run |
| `verifier.py` | Latency $< 2\text{ ms}$, deterministic OOD rejection | Benchmarked on 1,000 synthetic test points |
| `env.py` | Step throughput $\ge 2{,}000\text{ steps/s}$ ($< 0.5\text{ ms/step}$) | Benchmark test with Gymnasium runner |
| `mpc.py` | Non-zero finite autograd gradients $\nabla_u \mathcal{L}$ | Backward pass verification |
