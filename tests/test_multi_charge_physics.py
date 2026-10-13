"""Unit tests for Multi-Species, Multi-Charge-State (MCS), Stripper Foil, and CSS (Phase 14)."""

import math
import pytest

from helios.physics.css import ChargeStateSeparator
from helios.physics.species import (
    IonSpecies,
    MultiChargeBeam,
    MultiChargeComponent,
    create_argon_beam,
    create_proton_beam,
    create_uranium_multicharge_beam,
    create_xenon_multicharge_beam,
)
from helios.physics.stripper import StripperFoil, StripperPhysicsEngine


def test_ion_species_relativistic_kinematics():
    """Verify relativistic calculations and magnetic rigidity for various heavy ions."""
    # Uranium 238 at 0.5 MeV/u with Q=33
    u_ion = IonSpecies("U238_33+", mass_amu=238.05, atomic_number_z=92, charge_state_q=33, kinetic_energy_mev_u=0.5)
    assert u_ion.gamma > 1.0
    assert 0.02 < u_ion.beta < 0.05
    assert u_ion.momentum_mev_c > 0.0
    assert u_ion.magnetic_rigidity_t_m > 0.5

    # Proton at 3.0 MeV
    p_ion = IonSpecies("Proton", mass_amu=1.007, atomic_number_z=1, charge_state_q=1, kinetic_energy_mev_u=3.0)
    assert p_ion.beta > u_ion.beta
    assert p_ion.magnetic_rigidity_t_m < u_ion.magnetic_rigidity_t_m


def test_multi_charge_beam_composite_envelope():
    """Verify composite beam envelopes accounting for rigidity dispersion."""
    beam = create_uranium_multicharge_beam(energy_mev_u=0.5, total_current_ma=2.0)
    assert len(beam.components) == 2
    assert math.isclose(beam.mean_charge_state, 33.5, abs_tol=0.1)

    # In zero dispersion region, composite envelope equals baseline
    cx, cy, sig_x, sig_y = beam.compute_composite_envelope(dispersion_x_m=0.0, baseline_sigma_x_mm=1.5, baseline_sigma_y_mm=1.5)
    assert math.isclose(cx, 0.0, abs_tol=1e-5)
    assert math.isclose(sig_x, 1.5, abs_tol=1e-5)

    # In dispersive region (D_x = 1.0 m), charge separation broadens effective horizontal envelope
    cx_disp, cy_disp, sig_x_disp, sig_y_disp = beam.compute_composite_envelope(
        dispersion_x_m=1.0, baseline_sigma_x_mm=1.5, baseline_sigma_y_mm=1.5
    )
    assert sig_x_disp > sig_x  # Rigidity mismatch spreads beam horizontally
    assert math.isclose(sig_y_disp, 1.5, abs_tol=1e-5)  # Vertical unaffected


def test_stripper_physics_and_foil_degradation():
    """Verify charge redistribution, energy loss, and foil degradation."""
    foil = StripperFoil(foil_id="STRIP_01", thickness_ug_cm2=300.0, max_fluence_ions_cm2=1.0e15)
    engine = StripperPhysicsEngine(foil=foil)

    u33 = IonSpecies("U238_33+", mass_amu=238.05, atomic_number_z=92, charge_state_q=33, kinetic_energy_mev_u=1.4)
    outcome = engine.strip_beam(incoming=u33, beam_current_ma=1.0, exposure_hours=0.5)

    assert outcome.mean_charge_state > 33.0  # Stripping increases charge
    assert outcome.energy_loss_mev_u > 0.0
    assert outcome.final_energy_mev_u < 1.4
    assert outcome.rms_scattering_angle_mrad > 0.0
    assert outcome.temperature_rise_k > 0.0
    assert len(outcome.outgoing_beam.components) == 3

    # Check degradation accumulation and replacement warning
    assert outcome.foil_degradation_pct > 0.0
    # Add heavy exposure to trigger replacement threshold
    engine.strip_beam(incoming=u33, beam_current_ma=1.0, exposure_hours=100.0)
    assert foil.needs_replacement is True


def test_charge_state_separator_autonomous_tuning():
    """Verify achromatic CSS slit tuning and charge state selection."""
    css = ChargeStateSeparator(dispersion_x_m=1.5, default_slit_gap_mm=10.0)
    beam = create_uranium_multicharge_beam(energy_mev_u=0.5, total_current_ma=2.0)

    # 1. Charge positions at slit plane
    positions = css.calculate_charge_positions_mm(beam)
    assert len(positions) == 2
    assert positions[33] != positions[34]

    # 2. Transmission evaluation for target Q=34
    report_initial = css.evaluate_transmission(beam, target_charge_q=34)
    assert report_initial.selected_charge_state == 34
    assert report_initial.total_transmitted_current_ma > 0.0

    # 3. Autonomous slit tuning for maximum purity
    report_tuned = css.tune_slits_for_optimal_purity(beam, target_charge_q=34, min_transmission_pct=90.0)
    assert report_tuned.target_transmission_pct >= 90.0
    assert report_tuned.charge_purity_pct >= report_initial.charge_purity_pct
    assert report_tuned.slit_gap_mm > 0.0
