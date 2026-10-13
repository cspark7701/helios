# HELIOS Next Phase Development Task List: Differentiable Physics, Ion Source Automation & Enterprise Agent Mesh (Phases 35 - 39)

- **Status**: Active
- **Plan ID**: `00039`
- **Domain**: Heavy Ion Linear Accelerators (ECR Ion Source, LEBT, RFQ, MEBT, SCL, HEBT)
- **Reference Architecture**: LBNL Osprey Framework & Autonomous Digital Twin Operation
- **Created**: 2026-10-13

---

## 🎯 Strategic Roadmap Overview (Phases 35 - 39)

With high-order 3D field map symplectic tracking, Intra-Beam Scattering (IBS), automated switchyard beam routing, game-theoretic co-tuning, and hardware-in-the-loop stress testing established (Phases 1–34, 103/103 tests passing), this roadmap advances HELIOS toward **differentiable beam dynamics, automated ion source plasma tuning, predictive quench protection, distributed agent mesh architecture, and multi-modal operator interfaces**:

```mermaid
flowchart TD
    P35["Phase 35: Differentiable Beam Dynamics & Gradient-Based Inverse Solver"] --> P37["Phase 37: Beam Halo Dynamics, Collimation & Predictive Quench Protection"]
    P36["Phase 36: ECR Ion Source Plasma Optimization & Fast Species Switching"] --> P37
    P37 --> P38["Phase 38: Distributed Multi-Node Agent Mesh & Edge-Cloud Sync"]
    P38 --> P39["Phase 39: Multi-Modal Control Room Interface & Phase-Space Visualizer"]
```

---

## Phase 35: Differentiable Beam Dynamics & Gradient-Based Inverse Lattice Solver

- [ ] **35.1 End-to-End Differentiable Lattice Modeling (`helios/physics/differentiable.py`)**
  - [ ] Implement differentiable beam transport operators (transfer matrices, thin-lens non-linear kicks, RF buncher gaps) in PyTorch/autodiff.
  - [ ] Compute analytical exact gradients ($\nabla_{\mathbf{k}} \mathcal{L}$, $\nabla_{\mathbf{\phi}} \mathcal{L}$) through multi-element lattices without finite-difference perturbational noise.
- [ ] **35.2 One-Shot Inverse Problem Solver for Lattice Calibration**
  - [ ] Solve inverse reconstruction of unknown cavity phase drifts and quadrupole calibration errors directly from downstream BPM and profile monitor data using gradient backpropagation.
  - [ ] Benchmark convergence speed against standard derivative-free optimization (Nelder-Mead, Powell, BO).

---

## Phase 36: ECR Ion Source Plasma Optimization & Fast Multi-Species Switching

- [ ] **36.1 Electron Cyclotron Resonance (ECR) Source Tuner (`helios/tuning/ionsource.py`)**
  - [ ] Model ECR plasma heating dynamics: microwave forward power, frequency tuning, gas injection valves ($O_2, He$ gas mixing), and extraction bias voltages.
  - [ ] Formulate Charge State Distribution (CSD) optimization to peak target charge states (e.g., $^{238}\text{U}^{33+}$, $^{124}\text{Xe}^{26+}$) while minimizing unwanted contamination.
- [ ] **36.2 Rapid Interleaved Multi-Species Beam Switching**
  - [ ] Automated switching between distinct ion species within minutes for multi-user experimental facility schedules.
  - [ ] Coordinated LEBT steerer and solenoidal focus scaling based on species magnetic rigidity $B\rho = \frac{p}{q}$.

---

## Phase 37: Beam Halo Dynamics, Dynamic Collimation & Predictive Quench Interlocks

- [ ] **37.1 Beam Halo Characterization & Core-Halo Decomposition (`helios/physics/halo.py`)**
  - [ ] Compute beam halo metric parameters (Kurtosis, $H$-parameter, Gaussian core vs super-Gaussian halo tail separation).
  - [ ] Dynamic collimator blade positioning algorithm maximizing halo interception while guaranteeing core beam transmission $> 99.5\%$.
- [ ] **37.2 Machine Protection System (MPS) Predictive Quench Prevention (`helios/safety/predictive.py`)**
  - [ ] Time-series trend analysis on cryomodule liquid helium bath temperature, pressure fluctuations, and RF forward/reflected power signals.
  - [ ] Predictive early-warning trigger: Detect impending cavity thermal quenches $100\text{--}500\text{ ms}$ prior to physical interlock trip, executing proactive gentle beam cut-off.

---

## Phase 38: Distributed Multi-Node Agent Mesh & Resilient Edge-Cloud Architecture

- [ ] **38.1 High-Performance Event-Driven Agent Mesh (`helios/core/mesh.py`)**
  - [ ] Lightweight asynchronous pub/sub transport layer (ZeroMQ / Redis Streams / gRPC) connecting IOC edge nodes, physics compute clusters, and control consoles.
  - [ ] Dynamic node discovery, heartbeat liveness monitoring, and automatic failover election for Master Orchestrator.
- [ ] **38.2 Edge Autonomy with Resilient Reconnection Sync**
  - [ ] Subsystem edge agents execute localized feedback loops during central network partitions and cleanly synchronize historical telemetry upon reconnection.

---

## Phase 39: Multi-Modal Control Room Interface & Real-Time Phase Space Visualizer

- [ ] **39.1 Multi-Modal Operator Voice & Intent Parsing (`helios/ui/voice.py`)**
  - [ ] Domain-specific natural language parser for control room commands (e.g. *"Flatten vertical orbit in SCL2 and verify transmission"*).
  - [ ] Confirmation prompt synthesis mapped to Plan-First execution workflow.
- [ ] **39.2 High-Fidelity 6D Phase Space Projection & Visual Diagnostics (`helios/ui/visualizer.py`)**
  - [ ] Real-time 2D/3D slice visualizer for beam phase-space distribution: $(x, x')$, $(y, y')$, and $(z, \Delta p/p)$.
  - [ ] Interactive what-if slider overlays comparing live telemetry with digital twin projections.
- [ ] **39.3 Comprehensive Verification Test Suite (`tests/test_advanced_enterprise_and_mesh.py`)**
  - [ ] Unit and integration tests covering differentiable tracking, ECR source tuning, halo computation, predictive quench interlocks, and agent mesh messaging.
