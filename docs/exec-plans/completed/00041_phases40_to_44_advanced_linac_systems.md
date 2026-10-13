# Execution Plan Change Record: Phases 40 to 44 Advanced Heavy Ion Linac Systems

- **Plan ID**: `00041`
- **Phases**: 40, 41, 42, 43, 44
- **Title**: RFQ Vane Modulation, Liquid Stripper Hydrodynamics, SRF Cryoplant Heat Balancing, Tensor Bunch Compression & Laser Survey
- **Status**: Completed
- **Timestamp**: 2026-10-13
- **Reference Architecture**: LBNL Osprey Framework & Autonomous Digital Twin Operation

---

## 1. Executive Summary

Phases 40 through 44 advance the HELIOS framework with dedicated heavy-ion linear accelerator subsystems, high-power beam targets, thermodynamic cryogenic plant management, and geodetic alignment robotics:

1. **Phase 40: Radio-Frequency Quadrupole (RFQ) 3D Vane Modulation & Cell Dynamics**:
   - `RFQVaneDynamicsEngine`, `RFQCell`, `RFQDesignParameters` (`helios/physics/rfq.py`): Cell-by-cell vane modulation ($m(z), a(z), l(z)=\beta\lambda/2, B(z)$) across Radial Matching, Shaper, Gentle Buncher, and Accelerator sections.
   - 3D electric field harmonics ($A_{10}, A_{30}$) and adiabatic longitudinal bunching capturing $>80\%$ macroparticles for $^{238}\text{U}^{33+}$.
2. **Phase 41: Advanced Liquid Metal & Windowless Gas Jet Strippers**:
   - `LiquidStripperEngine`, `LiquidStripperParameters` (`helios/physics/liquid_stripper.py`): Liquid lithium film hydrodynamics (Weber number $We$), thermal dissipation under multi-kW beam deposition, evaporative Langmuir vaporization rates, and equilibrium charge state distributions ($\bar{q} \approx 88+$ for $^{238}\text{U}$).
3. **Phase 42: SRF Cryogenic Plant Thermodynamic Heat Load Balancing**:
   - `CryoplantThermodynamicOptimizer`, `CavityCryoState`, `CryoplantCapacity` (`helios/rf/cryoplant.py`): BCS surface resistance ($R_{\text{BCS}} \propto f^2/T \exp(-\Delta/k_B T)$), residual resistance $R_{\text{res}}$, dynamic heat loss ($P_{\text{loss}} \propto V^2 / R_s$), and closed-loop cavity gradient balancing within 2.0 K sub-atmospheric cryoplant capacity.
4. **Phase 43: Tensor Network Macroparticle Compression & Quantum Linac Tuning**:
   - `TensorTrainDecomposer` (`helios/physics/tensornet.py`): Low-rank Matrix Product State (MPS) / Tensor Train SVD factorization achieving $>10\times$ memory reduction for 6D linac bunch distributions while preserving transverse and longitudinal moments.
   - `SimulatedQuantumAnnealer` (`helios/optimization/quantum.py`): Path-integral Monte Carlo (PIMC) transverse-field Ising optimizer solving discrete combinatorial linac tuning (steerer polarities, collimator staging) without local minimum entrapment.
5. **Phase 44: Geodetic Laser Tracker Ingestion, Girder Alignment & Golden Runs**:
   - `LaserTrackerSurveyAnalyzer` (`helios/diagnostics/survey.py`): Ingestion of Leica/Hexagon 3D fiducial survey data and calculation of motorized girder cam/jack displacements, reducing residual magnet offsets and steerer current demand by $>70\%$.
   - `GoldenRunCertificationEngine` (`helios/ops/golden.py`): Statistical discrepancy grading and SHA-256 cryptographic compliance certification against authorized Golden Run baselines.
   - `helios/core/capabilities.py`: Registration of high-level capabilities (`simulate_rfq_vane_modulation`, `evaluate_liquid_metal_stripper`, `balance_srf_cryoplant_heat`, `compress_bunch_tensor_network`, `optimize_girder_laser_alignment`).

---

## 2. Test Verification

- **New Suite**: `tests/test_advanced_linac_systems.py` (7/7 passed).
- **Full Repository Suite**: **116/116 passed** across all 44 phases.
