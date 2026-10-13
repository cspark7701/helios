# Execution Plan / Change Record: 00022

- **Sub-tasks**: Phase 14 Multi-Species & Multi-Charge-State (MCS) Heavy Ion Commissioning (14.1, 14.2, 14.3, 14.4)
- **Status**: Completed
- **Date**: 2026-10-13
- **Author**: Chong Shik Park / HELIOS Team
- **Reference**: LBNL Osprey Framework, Baron Stripping Formulation, Charge State Selection

---

## 1. Objectives

- Implement multi-species beam parameter modeling ($^{238}\text{U}$, $^{124}\text{Xe}$, $^{40}\text{Ar}$, protons) with relativistic kinematics and magnetic rigidity ($B\rho$).
- Model multi-charge state (MCS) composite beams with fractional currents and charge-dependent rigidity dispersion broadening.
- Implement carbon/lithium stripper foil physics: Baron equilibrium charge redistribution, heavy-ion Bethe-Bloch energy loss ($\Delta E$), multiple scattering, and foil degradation tracking.
- Build Charge State Separator (CSS) chicane model with autonomous slit aperture tuning for purity and transmission optimization.
- Register Phase 14 capabilities into `CapabilityRegistry`.

---

## 2. Implementation Summary

1. **Ion Species & Multi-Charge Beam Dynamics (`helios/physics/species.py`)**:
   - `IonSpecies`: Calculates total energy, rest energy, relativistic $\beta$, $\gamma$, momentum, and magnetic rigidity $B\rho = p / (q e)$ in $\text{T}\cdot\text{m}$.
   - `MultiChargeBeam`: Models composite multi-charge distributions (e.g. $^{238}\text{U}^{33+/34+}$); calculates dispersion-broadened effective transverse beam envelopes:
     $$\sigma_{eff}^2 = \sigma_0^2 + \sum w_i (x_i - \bar{x})^2$$
   - Heavy ion beam factory functions for Uranium, Xenon, Argon, and Protons.
2. **Stripper Foil Physics Engine (`helios/physics/stripper.py`)**:
   - `StripperFoil`: Tracks areal thickness ($\mu\text{g}/\text{cm}^2$), volumetric density, and integrated ion fluence with replacement thresholds ($> 80\%$).
   - `StripperPhysicsEngine`: Employs Baron's empirical formula for equilibrium mean charge $Q_{eq}$, Bethe-Bloch stopping power $\Delta E$, Highland Coulomb scattering angles $\theta_{rms}$, and vacuum thermal heating.
3. **Charge State Separator (`helios/physics/css.py`)**:
   - `ChargeStateSeparator`: Models horizontal dispersion $\eta_x$ at chicane slit planes, computes spatial charge separation $\Delta x = \eta_x \frac{\Delta(B\rho)}{B\rho_0}$.
   - `tune_slits_for_optimal_purity`: Automatically optimizes slit gap and center to maximize charge state purity while maintaining target transmission $\ge 90\%$.
4. **Registry & Testing**:
   - Registered `evaluate_multi_charge_beam`, `model_stripper_foil`, and `tune_charge_separator` in `CapabilityRegistry`.
   - Built comprehensive test suite in `tests/test_multi_charge_physics.py`.
   - Verified that all 70 tests pass cleanly in the `helios` conda environment.

---

## 3. Files Modified / Created

- `M  docs/exec-plans/active/00022_next_development_phases_tasklist.md`
- `A  docs/exec-plans/completed/00022_phase14_multi_charge_state_commissioning.md`
- `M  helios/core/capabilities.py`
- `M  helios/physics/__init__.py`
- `A  helios/physics/css.py`
- `A  helios/physics/species.py`
- `A  helios/physics/stripper.py`
- `A  tests/test_multi_charge_physics.py`
