"""Unit tests for HELIOS Advanced Physics, Switchyard Routing, and Resilience (Phases 30 - 34).

Validates:
1. Phase 30: FieldMap3DInterpolator and SymplecticParticlePusher (Boris algorithm).
2. Phase 31: IntraBeamScatteringEngine (Piwinski IBS diffusion rates).
3. Phase 32: SwitchyardBeamRouter (HEBT target vault transitions).
4. Phase 33: GameTheoreticCoTuner (Nash equilibrium multi-agent arbitration).
5. Phase 34: HILStressTestbed (Synthetic disturbance injection & MTTR resilience).
"""

import numpy as np
import pytest

from helios.physics.fieldmaps import FieldMap3DInterpolator
from helios.physics.pusher import SymplecticParticlePusher
from helios.physics.ibs import IntraBeamScatteringEngine
from helios.tuning.switchyard import SwitchyardBeamRouter, TargetVaultID
from helios.agents.cotuner import GameTheoreticCoTuner, ProposedSubsystemActuation
from helios.ops.stress import HILStressTestbed


def test_3d_fieldmap_and_symplectic_boris_tracking():
    # 1. 3D Synthetic Cavity Map
    interp = FieldMap3DInterpolator.create_synthetic_rf_cavity_map(
        length_m=0.3,
        radius_m=0.03,
        peak_ez_mv_m=5.0,
        frequency_mhz=162.5,
        grid_points=15,
    )

    # Evaluate at center
    E, B = interp.evaluate_field(0.0, 0.0, 0.15, time_s=0.0)
    assert E[2] > 1e5  # Strong axial accelerating field Ez
    assert abs(E[0]) < 1e3  # On-axis Ex is near zero

    # 2. Relativistic Boris symplectic integration
    pusher = SymplecticParticlePusher(mass_amu=238.0, charge_q=33)
    pos0 = np.array([0.001, 0.001, 0.0])  # 1mm offset
    v_z0 = 0.05 * 299792458.0  # beta ~ 0.05 (approx 1 MeV/u)
    vel0 = np.array([0.0, 0.0, v_z0])

    traj = pusher.track_boris(
        interpolator=interp,
        initial_position_m=pos0,
        initial_velocity_m_s=vel0,
        time_step_s=1e-10,
        num_steps=100,
        aperture_radius_m=0.03,
    )
    assert traj.survived is True
    assert len(traj.z_m) > 50
    assert traj.z_m[-1] > pos0[2]
    assert traj.kinetic_energy_mev_u[-1] > 0.0


def test_intra_beam_scattering_engine():
    rates = IntraBeamScatteringEngine.calculate_ibs_rates(
        mass_amu=238.0,
        charge_q=33,
        kinetic_energy_mev_u=15.0,
        num_ions_per_bunch=1e9,
        bunch_length_rms_mm=2.5,
        norm_emittance_x_um=0.35,
        norm_emittance_y_um=0.35,
        momentum_spread_dpp=0.001,
        beta_x_m=4.5,
        beta_y_m=4.5,
    )
    assert rates.tau_x_s > 0.0
    assert rates.tau_z_s > 0.0
    assert rates.rate_x_inv_s > 0.0
    assert rates.emittance_x_after_10m_pct >= 0.0


def test_switchyard_target_routing():
    router = SwitchyardBeamRouter()
    assert router.active_vault == TargetVaultID.BEAM_DUMP

    # Transition to Nuclear Physics Vault
    outcome = router.plan_route_transition(
        new_target_vault=TargetVaultID.NUCLEAR_PHYSICS_VAULT,
        max_slew_rate_a_s=25.0,
    )
    assert outcome.success is True
    assert outcome.target_vault == TargetVaultID.NUCLEAR_PHYSICS_VAULT
    assert outcome.transition_time_s > 0.0
    assert "HEBT:PS_DIPOLE_SW:I_Set" in outcome.actuated_pvs
    assert router.active_vault == TargetVaultID.NUCLEAR_PHYSICS_VAULT


def test_game_theoretic_cotuner_arbitration():
    # Scenario: Agent 1 (MEBT Tuner) and Agent 2 (SCL Tuner) propose overlapping setpoints for interface quad
    p1 = ProposedSubsystemActuation(
        agent_id="HELIOS-Tuner-MEBT",
        subsystem="MEBT",
        proposed_setpoints={"MEBT:PS_Q06:I_Set": 14.2, "MEBT:PS_CH03:I_Set": 0.5},
        priority=5,
        expected_gain_pct=2.0,
        rationale="Match horizontal envelope at exit",
    )
    p2 = ProposedSubsystemActuation(
        agent_id="HELIOS-Tuner-SCL1",
        subsystem="SCL1",
        proposed_setpoints={"MEBT:PS_Q06:I_Set": 14.8, "SCL1:PS_Q01:I_Set": 15.0},
        priority=6,
        expected_gain_pct=2.5,
        rationale="Accept matched envelope into cryomodule 1",
    )

    resolution = GameTheoreticCoTuner.arbitrate_conflicts([p1, p2])
    assert resolution.conflicts_detected == 1
    assert len(resolution.compromises_made) == 1
    # Consensus should be between 14.2 and 14.8 A
    consensus_q06 = resolution.approved_setpoints["MEBT:PS_Q06:I_Set"]
    assert 14.2 < consensus_q06 < 14.8
    assert "MEBT:PS_CH03:I_Set" in resolution.approved_setpoints
    assert "SCL1:PS_Q01:I_Set" in resolution.approved_setpoints


def test_hil_stress_testbed_resilience():
    testbed = HILStressTestbed()
    res = testbed.simulate_stress_cycles(num_cycles=30)
    assert res.total_cycles_tested == 30
    assert res.faults_injected_count > 0
    assert res.faults_recovered_count == res.faults_injected_count
    assert res.trips_prevented_pct == 100.0
    assert res.mean_recovery_time_s < 1.0
    assert res.robustness_grade in ["A+", "A"]
