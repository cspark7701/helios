"""Tests for HELIOS Advanced Beam, RF, and Production Harness (Phases 19 - 23).

Validates:
1. Phase 19: BeamBasedAlignmentSolver and DispersionFreeSteeringSolver.
2. Phase 20: PhaseSpaceTomographyMENT, BeamHaloQuantifier, and LostParticleTomography3D.
3. Phase 21: AutonomousRFConditioner and CavityResonanceTracker.
4. Phase 22: DistributedEventBus RPC services and backend configuration.
5. Phase 23: VirtualLinacEPICSMock and EndToEndCommissioningHarness.
"""

import numpy as np
import pytest

from helios.tuning.bba import BeamBasedAlignmentSolver, DispersionFreeSteeringSolver
from helios.physics.halo import (
    PhaseSpaceTomographyMENT,
    BeamHaloQuantifier,
    LostParticleTomography3D,
)
from helios.rf.conditioning import AutonomousRFConditioner, CavityResonanceTracker, ConditioningState
from helios.ops.broker import DistributedEventBus, BrokerBackendType
from helios.ops.harness import VirtualLinacEPICSMock, EndToEndCommissioningHarness


def test_beam_based_alignment_and_dfs():
    # 1. BBA Single Quad offset calculation
    # Delta x_bpm = R12 * Delta K1 * offset
    # 0.05 mm = 0.5 * 0.2 * offset => offset = 0.5 mm
    offset = BeamBasedAlignmentSolver.solve_quad_offset(
        delta_k1=0.2,
        bpm_reading_nominal_mm=1.0,
        bpm_reading_modulated_mm=1.05,
        transfer_r12=0.5,
    )
    assert pytest.approx(offset, rel=1e-3) == 0.5

    # 2. BBA Modulation Curve Fit
    k1_steps = np.linspace(-0.2, 0.2, 5)
    bpm_x = 1.0 + 0.5 * 0.4 * k1_steps  # offset_x = 0.4 mm
    bpm_y = -0.5 + 0.5 * (-0.2) * k1_steps  # offset_y = -0.2 mm
    res = BeamBasedAlignmentSolver.fit_bba_modulation_curve(
        quad_name="MEBT_Q01",
        k1_modulations=k1_steps,
        bpm_x_measurements=bpm_x,
        bpm_y_measurements=bpm_y,
        r12_x=0.5,
        r12_y=0.5,
    )
    assert res.quad_name == "MEBT_Q01"
    assert pytest.approx(res.magnetic_center_offset_x_mm, abs=1e-3) == 0.4
    assert pytest.approx(res.magnetic_center_offset_y_mm, abs=1e-3) == -0.2
    assert res.recommended_steerer_dx_mm == -res.magnetic_center_offset_x_mm

    # 3. Dispersion-Free Steering (DFS)
    r_orbit = np.array([[0.8, 0.2], [0.3, 0.7]])
    r_disp = np.array([[0.05, 0.01], [0.02, 0.04]])
    curr_orbit = np.array([1.5, -1.2])
    curr_disp = np.array([0.15, -0.10])
    dfs_res = DispersionFreeSteeringSolver.solve_dfs(
        response_orbit=r_orbit,
        response_dispersion=r_disp,
        current_orbit_mm=curr_orbit,
        current_dispersion_m=curr_disp,
        steerer_names=["CH01", "CH02"],
        dispersion_weight=0.5,
    )
    assert dfs_res.success is True
    assert dfs_res.final_orbit_rms_mm < dfs_res.initial_orbit_rms_mm
    assert dfs_res.final_dispersion_rms_m < dfs_res.initial_dispersion_rms_m


def test_phase_space_tomography_and_halo():
    # 1. MENT 2D Reconstruction from 1D Projections
    n_bins = 32
    angles = [0.0, np.pi / 4.0, np.pi / 2.0]
    # Synthetic Gaussian projections
    x = np.linspace(-10, 10, n_bins)
    proj1 = np.exp(-(x**2) / (2 * 2.0**2))
    proj2 = np.exp(-(x**2) / (2 * 2.5**2))
    proj3 = np.exp(-(x**2) / (2 * 3.0**2))
    recon = PhaseSpaceTomographyMENT.reconstruct_2d_phase_space(
        projections=[proj1, proj2, proj3],
        projection_angles_rad=angles,
        grid_size=32,
        x_span_mm=20.0,
        xp_span_mrad=10.0,
        max_iterations=10,
    )
    assert recon.density_matrix.shape == (32, 32)
    assert recon.emittance_rms_mm_mrad > 0.0
    assert recon.entropy > 0.0

    # 2. Halo Quantification
    r = np.linspace(0, 15, 50)
    # Profile with prominent tail
    profile = np.exp(-r / 1.5) + 0.1 * np.exp(-r / 6.0)
    halo_res = BeamHaloQuantifier.evaluate_halo(profile, r, pipe_radius_mm=20.0)
    assert halo_res.halo_parameter_h > 0.5
    assert halo_res.core_fraction_pct > 50.0
    assert halo_res.effective_aperture_clearance_mm > 0.0

    # 3. 3D Loss Map Synthesis
    blm_z = np.array([2.0, 5.0, 8.0])
    blm_gy = np.array([0.01, 0.08, 0.02])
    loss_map = LostParticleTomography3D.reconstruct_3d_loss_map(
        linac_length_m=10.0,
        blm_positions_m=blm_z,
        blm_readings_gy_s=blm_gy,
        beam_energy_mev=15.0,
        beam_current_ua=100.0,
    )
    assert len(loss_map.z_positions_m) == 200
    assert loss_map.total_power_loss_w > 0.0
    assert len(loss_map.hotspots) >= 1


def test_autonomous_rf_conditioning_and_resonance_tracker():
    # 1. Conditioning normal ramp
    conditioner = AutonomousRFConditioner(cavity_id="CAV01", target_power_kw=5.0)
    step1 = conditioner.step(measured_vacuum_mbar=1e-8, electron_pickup_ua=0.01)
    assert step1.power_kw > 0.1
    assert step1.state == ConditioningState.RAMPING

    # 2. Multipacting barrier detection
    step2 = conditioner.step(measured_vacuum_mbar=1e-8, electron_pickup_ua=1.2)  # High electron current
    assert step2.state == ConditioningState.FAST_JUMPING
    assert "Multipacting" in step2.action_taken

    # 3. Vacuum interlock spike back-off
    step3 = conditioner.step(measured_vacuum_mbar=2e-7, electron_pickup_ua=0.05)  # Vacuum exceeds 1e-7
    assert step3.state == ConditioningState.VACUUM_RECOVERY
    assert "Vacuum spike" in step3.action_taken

    # 4. Resonance tracking (Piezo and stepper)
    tracker = CavityResonanceTracker(cavity_id="CAV01")
    # Small phase error: handled by fine piezo
    res1 = tracker.track(phase_error_deg=2.5)
    assert res1.frequency_detuning_hz == 5.0
    assert res1.stepper_position_steps == 0
    assert res1.piezo_voltage_v > 50.0

    # Large phase error: piezo saturates and offloads to stepper
    # 250 deg * 2 Hz/deg = 500 Hz detuning -> 500 / 12 V = +41.6V -> 50 + 41.6 = 91.6V (> 85V)
    res2 = tracker.track(phase_error_deg=250.0)
    assert res2.stepper_position_steps != 0


def test_distributed_event_bus_rpc():
    bus = DistributedEventBus(backend=BrokerBackendType.IN_PROCESS)

    def echo_service(params):
        return {"echo": params.get("val", "") * 2}

    bus.register_rpc_service("echo", echo_service)
    result = bus.call_rpc("echo", {"val": "helios_"})
    assert result["echo"] == "helios_helios_"

    with pytest.raises(KeyError):
        bus.call_rpc("non_existent", {})


def test_virtual_accelerator_mock_and_e2e_commissioning_harness():
    mock_ioc = VirtualLinacEPICSMock(section_name="SCL1")
    assert mock_ioc.caget("SCL1:PS_Q01:I_Set") == 15.0

    # Caput updates BPM readbacks through coupling
    init_x = mock_ioc.caget("SCL1:BPM01:X")
    mock_ioc.caput("SCL1:PS_CH01:I_Set", 1.0)
    new_x = mock_ioc.caget("SCL1:BPM01:X")
    assert new_x < init_x

    # Run complete end-to-end autonomous commissioning loop
    harness = EndToEndCommissioningHarness(mock_ioc=mock_ioc)
    result = harness.run_commissioning_cycle()
    assert result["success"] is True
    assert result["audit_entries_count"] >= 1
    assert result["audit_chain_valid"] is True
    assert "HELIOS Commissioning Shift Report" in result["shift_report"]
