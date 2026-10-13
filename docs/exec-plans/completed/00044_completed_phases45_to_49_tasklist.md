# HELIOS Development Task List: High-Power Targets, Multipactoring & Radiological Safety (Phases 45 - 49)

- **Status**: Completed
- **Plan ID**: `00044`
- **Domain**: Heavy Ion Linear Accelerators (LEBT, RFQ, MEBT, SCL, High-Power Targets, Beam Dumps, Radiation Protection)
- **Reference Architecture**: LBNL Osprey Framework & Autonomous Digital Twin Operation
- **Completed**: 2026-10-13

---

## 🎯 Strategic Roadmap Overview (Phases 45 - 49)

This roadmap deepens the heavy-ion linear accelerator physics and engineering envelope into **high-power target thermo-mechanics, cavity multipactoring breakdown modeling, space-charge equipartitioning stability, multi-physics digital twin co-simulation, and residual radiological activation forecasting**:

```mermaid
flowchart TD
    P45["Phase 45: High-Power Beam Dump & Production Target Thermo-Mechanics"] --> P47["Phase 47: Space-Charge Equipartitioning & Hofmann Stability Charts"]
    P46["Phase 46: RF Multipactoring Resonant Barriers & Field Emission Dark Current"] --> P47
    P47 --> P48["Phase 48: Multi-Physics Digital Twin Co-Simulation & Zero-Copy Streaming"]
    P48 --> P49["Phase 49: Radiological Activation, Decay Cooling & Personnel Safety Interlocks"]
```

---

## Phase 45: High-Power Target & Beam Dump Thermo-Mechanical Stress Simulation

- [x] **45.1 Bragg Peak Energy Deposition & Hydrodynamic Shockwave Modeling (`helios/physics/beam_dump.py`)**
  - [x] Model heavy-ion 3D energy deposition Bragg profiles ($dE/dx$) in high-power graphite, copper, and tungsten beam stops (up to 400 kW beam power).
  - [x] Evaluate instantaneous thermo-elastic pressure spikes ($\Delta P = \Gamma \rho \Delta E$) using Grüneisen equation of state.
  - [x] Calculate von Mises thermal fatigue stress and critical heat flux (CHF) boiling margins in cooling water channels.
- [x] **45.2 Proactive Beam Dump Protection Interlock**
  - [x] Automated beam abort trigger if peak surface power density exceeds thermal shock thresholds.

---

## Phase 46: RF Multipactoring Resonant Barriers & Field Emission Dark Current

- [x] **46.1 Secondary Electron Yield (SEY) Resonant Multipactoring Engine (`helios/rf/multipactor.py`)**
  - [x] Model 1-point and 2-point resonant electron multipactoring in coaxial power couplers and low-beta SRF cavities (QWR, HWR).
  - [x] Map SEY curve $\delta(E_{\text{impact}})$ and identify resonant RF voltage barrier bands susceptible to cavity vacuum trips.
- [x] **46.2 Fowler-Nordheim Field Emission & Dark Current Radiation Map**
  - [x] Simulate electron field emission current ($J_{\text{FN}} = A_1 E^2 \exp(-B_1 / E)$) from cavity iris surface defects.
  - [x] Map bremsstrahlung X-ray radiation dose accumulation along cryomodule silicon diode sensors.

---

## Phase 47: Space-Charge Equipartitioning & Hofmann Stability Charts

- [x] **47.1 Hofmann Chart Parametric Resonance Mapping (`helios/physics/equipartition.py`)**
  - [x] Compute transverse-longitudinal kinetic energy anisotropy ratio ($T_\perp / T_\parallel$) along high-current heavy-ion linacs.
  - [x] Map linac zero-current and depressed phase advances $(\sigma_{0t}, \sigma_{0l}, \sigma_t, \sigma_l)$ onto Hofmann anisotropic space-charge stability diagrams.
- [x] **47.2 Autonomous Emittance Exchange Avoidance Rematching**
  - [x] Detect proximity to dangerous parametric resonance stopbands ($2\sigma_t - \sigma_l = 0$, $\sigma_t - \sigma_l = 0$).
  - [x] Autonomously rematch quadrupole focus and RF cavity phase advances to maintain safe equipartitioning margins.

---

## Phase 48: Multi-Physics Digital Twin Co-Simulation Bridge & Zero-Copy Streaming

- [x] **48.1 High-Throughput In-Memory IPC Co-Simulation Bridge (`helios/sim/cosim.py`)**
  - [x] Implement zero-copy in-memory IPC buffer exchange linking particle trackers (TRACK/IMPACT-Z), thermal models, and EPICS.
  - [x] Synchronize linac macroparticle bunch arrays $(N, 6)$ and 3D loss distributions across heterogeneous simulation processes.
- [x] **48.2 Adaptive Repetition-Rate Simulation Synchronization**
  - [x] Dynamically throttle simulation time steps to lock onto live linac macro-pulse repetition rates (1 Hz to 100 Hz).

---

## Phase 49: Residual Radiological Activation, Decay Cooling & Personnel Safety

- [x] **49.1 Residual Isotope Inventory & Delayed Gamma Radiation Modeling (`helios/safety/activation.py`)**
  - [x] Calculate nuclear spallation and heavy-ion fragmentation activation along beam pipe walls and collimators.
  - [x] Implement Bateman decay equations for primary isotope decay chains ($^{56}\text{Mn}, ^{58}\text{Co}, ^{54}\text{Mn}, ^{60}\text{Co}$).
- [x] **49.2 Radiological Cooling Time Interlock & Access Authority**
  - [x] Calculate safe cool-down waiting times before personnel tunnel access is granted.
  - [x] Generate cryptographic clearance tokens for Radiation Protection Officers.
- [x] **49.3 Comprehensive Verification Suite (`tests/test_high_power_linac_physics.py`)**
  - [x] Unit and integration tests covering beam dump stress, multipactoring SEY, Hofmann charts, co-simulation bridge, and radiological decay.
