# HELIOS Next Phase Development Task List (Phases 24 - 28)

- **Status**: Active
- **Reference Architecture**: LBNL Osprey Framework & Autonomous Control Rooms
- **Domain**: Heavy Ion Linear Accelerators (LEBT, RFQ, MEBT, SCL, HEBT)
- **Created**: 2026-10-13

---

## 🎯 Strategic Roadmap Overview (Phases 24 - 28)

Having completed core orchestration, physics simulation codes, neural surrogates, reinforcement learning, multi-species/charge states, fault recovery, multi-facility models, BBA/DFS, MENT tomography, RF conditioning, and E2E commissioning harnesses (Phases 1–23, 88/88 passing tests), the framework now advances toward **facility-grade production deployment, security, optimization, and digital twin high-performance execution**:

```mermaid
flowchart TD
    P24["Phase 24: High-Performance Parallel Batch Simulation Engine"] --> P25["Phase 25: Digital Twin Synchronization & Real-Time Parameter Tracking"]
    P24 --> P26["Phase 26: Multi-Objective Pareto Linac Optics Optimizer"]
    P25 --> P27["Phase 27: Control Room Security, RBAC & Hardened Interlocks"]
    P26 --> P28["Phase 28: Production Deployment, Containerization & Automated Docs"]
    P27 --> P28
```

---

## Phase 24: High-Performance Parallel Batch Simulation Engine (Ray / Multiprocessing)

- [ ] **24.1 Asynchronous Worker Pool for Simulation Ensembles**
  - [ ] Implement multi-worker task execution pool for parallel ANL TRACK and LBNL IMPACT-Z runs across multi-core CPUs and cluster nodes.
  - [ ] Support dynamic job queuing, progress tracking, and batch result reduction.
- [ ] **24.2 Parallel Parameter Sweeps & Uncertainty Quantification (UQ)**
  - [ ] Systematic lattice parameter scans ($\pm 5\%$ quad gradients, RF cavity phase jitter, beam current fluctuations).
  - [ ] Compute confidence bands and statistical transmission probability distributions.
- [ ] **24.3 GPU-Accelerated Particle Tracking Backend**
  - [ ] PyTorch/CUDA-based batch transfer matrix and space-charge particle pusher for sub-millisecond envelope and particle ensemble tracking.

---

## Phase 25: Online Digital Twin Synchronization & Real-Time Parameter Tracking

- [ ] **25.1 Continuous Kalman Filter / State Observer**
  - [ ] Unscented Kalman Filter (UKF) / Ensemble Kalman Filter (EnKF) assimilating live BPM, BLM, and FC telemetry into the active digital twin lattice state.
  - [ ] Real-time estimation of unmeasured states (beam energy spread, unmonitored emittance, longitudinal centroid).
- [ ] **25.2 Drift Detection & Autonomous Recalibration Trigger**
  - [ ] Continuous tracking of discrepancy between digital twin predictions and real machine readbacks.
  - [ ] Autonomous trigger initiating background recalibration when residual error exceeds statistical confidence thresholds.
- [ ] **25.3 Golden Baseline Snapshot Archive & Semantic Diff Engine**
  - [ ] Facility-wide golden setpoint storage with semantic diff highlighting deviations by subsystem (optics, RF, diagnostics).

---

## Phase 26: Multi-Objective Pareto Linac Optics Optimizer

- [ ] **26.1 Non-Dominated Sorting Genetic Algorithm (NSGA-II / NSGA-III)**
  - [ ] Multi-objective evolutionary optimization engine tailored for heavy-ion linacs.
  - [ ] Simultaneous optimization of competing goals: maximize transmission ($>98\%$), minimize longitudinal emittance blowup, and minimize transverse envelope scalloping.
- [ ] **26.2 Constrained Bayesian Optimization with Gaussian Processes**
  - [ ] Safe BO algorithm incorporating strict upper-bound BLM radiation loss constraints using acquisition functions (Expected Improvement with Probability of Feasibility).
- [ ] **26.3 Interactive Pareto Front Explorer**
  - [ ] Capability and visualization export allowing operators to inspect and select preferred Pareto-optimal operating points.

---

## Phase 27: Enterprise Control Room Security, RBAC & Hardened Interlocks

- [ ] **27.1 Role-Based Access Control (RBAC) & Epics CAS Security Integration**
  - [ ] Multi-tiered user authentication (Viewer, Commissioning Physicist, Safety Officer, Admin).
  - [ ] Cryptographic token-based authorization gating dangerous setpoint writes and panic shutdown triggers.
- [ ] **27.2 Hardware Machine Protection System (MPS) Heartbeat Watchdog**
  - [ ] Standalone safety daemon maintaining a continuous sub-second cryptographic heartbeat with live EPICS IOCs.
  - [ ] Automatic fallback to safe default machine state upon agent communication timeout or network disruption.
- [ ] **27.3 Secure Operator Audit Log Export & Archiving**
  - [ ] Signed audit log export conforming to nuclear regulatory and laboratory quality assurance standards.

---

## Phase 28: Production Deployment, Containerization & Automated API Documentation

- [ ] **28.1 Production Docker Container & Orchestration Decks**
  - [ ] Multi-stage production `Dockerfile` bundling HELIOS, PyTorch, Wine, ANL TRACK, lume-impact, and EPICS base.
  - [ ] `docker-compose.yml` deploying HELIOS Orchestrator, FastAPI dashboard, Redis event broker, and mock IOC.
- [ ] **28.2 Automated Interactive OpenAPI & Sphinx Physics Documentation**
  - [ ] Auto-generated Sphinx / MkDocs documentation suite covering all 28 phases, agent protocols, and physics formulas.
- [ ] **28.3 Release Packaging & PyPI Distribution Readiness**
  - [ ] Validated `pyproject.toml` configuration ready for production distribution.
