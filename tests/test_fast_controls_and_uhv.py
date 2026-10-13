"""Tests for HELIOS Phases 50-54: Real-Time Fast Controls, Chicane Compression & Vacuum Dynamics."""

import pytest
from helios.rf.microphonics import (
    MicrophonicsSpectrum,
    AdaptiveFxLMSPiezoController,
)


def test_srf_lorentz_detuning_and_piezo_microphonics():
    """Verify LFD detuning calculation and adaptive FxLMS microphonics cancellation."""
    spectrum = MicrophonicsSpectrum(
        cavity_id="CAV_SCL1_03",
        lfd_coefficient_Hz_per_MV2=2.5,
        mechanical_eigenmodes_Hz=[35.0, 75.0, 125.0],
        ambient_noise_std_Hz=6.0
    )

    controller = AdaptiveFxLMSPiezoController(
        filter_order=16,
        learning_rate_mu=0.25,
        piezo_coupling_Hz_per_V=3.2,
        max_piezo_voltage_V=120.0
    )

    result = controller.simulate_compensation(
        spectrum=spectrum,
        E_acc_MV_m=10.0,
        duration_s=0.3,
        sampling_rate_Hz=4000.0
    )

    assert result.cavity_id == "CAV_SCL1_03"
    # LFD = -2.5 * 10^2 = -250 Hz
    assert result.static_lfd_detuning_Hz == -250.0
    assert result.raw_microphonics_rms_Hz > 5.0
    # Compensated jitter should be significantly reduced
    assert result.compensated_microphonics_rms_Hz < result.raw_microphonics_rms_Hz
    assert result.jitter_rejection_ratio_dB > 5.0
    assert result.peak_piezo_voltage_V <= 120.0
    assert result.status in ["OPTIMAL_CONTROL", "MARGINAL"]


def test_fast_mps_differential_current_and_diamond_abort():
    """Verify sub-5 microsecond beam abort upon differential loss or diamond BLM trip."""
    from helios.safety.fast_mps import FastMPSConfiguration, FastMPSEngine

    config = FastMPSConfiguration(
        diff_current_threshold_uA=30.0,
        diamond_blm_threshold_V=0.80,
        max_safe_abort_latency_us=5.0
    )
    engine = FastMPSEngine(config)

    # 1. Nominal beam transmission (upstream 500 uA, downstream 495 uA -> 5 uA loss)
    ev_nom = engine.evaluate_signals(
        upstream_current_uA=500.0,
        downstream_current_uA=495.0,
        diamond_blm_voltage_V=0.15
    )
    assert not ev_nom.aborted
    assert ev_nom.trigger_cause == "NONE"
    assert ev_nom.cryomodule_puncture_prevented

    # 2. Sudden beam loss in cryomodule (upstream 500 uA, downstream 420 uA -> 80 uA loss!)
    ev_trip = engine.evaluate_signals(
        upstream_current_uA=500.0,
        downstream_current_uA=420.0,
        diamond_blm_voltage_V=1.25  # concurrent diamond shower
    )
    assert ev_trip.aborted
    assert ev_trip.trigger_cause == "DUAL_COINCIDENCE"
    assert ev_trip.differential_current_uA == 80.0
    # Abort latency must be under 5 us!
    assert ev_trip.total_abort_latency_us < 5.0
    assert "LEBT_ELECTROSTATIC_CHOPPER" in ev_trip.actuators_fired
    assert "RFQ_FAST_RF_CUTOFF" in ev_trip.actuators_fired
    assert ev_trip.cryomodule_puncture_prevented


def test_bunch_compressor_chicane_optics_and_optimization():
    """Verify 4-dipole chicane R56, bunch length compression, and chirp voltage optimization."""
    from helios.tuning.bunch_compressor import (
        ChicaneParameters,
        BunchCompressorChicaneOptimizer,
    )

    optimizer = BunchCompressorChicaneOptimizer()
    params = ChicaneParameters(
        dipole_bend_angle_deg=16.0,
        dipole_length_m=0.45,
        drift_12_m=1.2,
        drift_23_m=0.8,
        rf_chirp_voltage_MV=5.0,
        rf_chirp_phase_deg=-90.0,
        rf_frequency_MHz=162.5
    )

    res = optimizer.evaluate_chicane(
        params=params,
        beam_energy_MeV_u=17.5,
        initial_bunch_length_ps=80.0,
        initial_energy_spread_percent=0.20
    )

    # R56 must be negative for a standard 4-dipole C-chicane
    assert res.R56_mm < 0.0
    assert abs(res.R56_mm) > 10.0  # Typically -30 to -80 mm
    assert res.T566_mm > 0.0       # T566 is positive (-1.5 * R56)
    assert res.compression_factor > 1.2
    assert res.compressed_bunch_length_ps < res.initial_bunch_length_ps
    assert res.peak_current_enhancement > 1.2

    # Test optimization for target compression factor 3.0
    best_v = optimizer.optimize_chirp_voltage(params, target_compression_factor=3.0, beam_energy_MeV_u=17.5)
    assert 0.5 < best_v < 8.0


def test_linac_uhv_pressure_and_gas_stripping_losses():
    """Verify UHV pressure profiles, cold-bore condensation, and heavy-ion gas stripping losses."""
    from helios.physics.vacuum import VacuumSegment, LinacVacuumPhysicsEngine

    engine = LinacVacuumPhysicsEngine()

    # 1. Warm MEBT section (293 K, 120 l/s ion pump)
    mebt_sec = VacuumSegment(
        section_name="MEBT_VAC_01",
        length_m=3.5,
        tube_diameter_mm=40.0,
        is_cryogenic=False,
        ion_pump_speed_l_per_s=120.0,
        outgassing_rate_mbar_l_s_cm2=2.0e-11,
        temperature_K=293.15
    )
    res_mebt = engine.evaluate_segment_vacuum(mebt_sec, ion_species="U238", ion_charge=33, beam_energy_MeV_u=2.5)
    assert res_mebt.section_name == "MEBT_VAC_01"
    assert res_mebt.mean_pressure_mbar > 0.0
    assert res_mebt.fractional_beam_loss_percent > 0.0
    assert res_mebt.vacuum_runaway_safety_margin > 2.0
    assert res_mebt.vacuum_status in ["EXCELLENT_UHV", "ACCEPTABLE"]

    # 2. Superconducting Cryomodule SCL cold-bore (2 K condensation pumping)
    scl_sec = VacuumSegment(
        section_name="SCL1_CRYOMODULE_01",
        length_m=5.0,
        tube_diameter_mm=35.0,
        is_cryogenic=True,
        ion_pump_speed_l_per_s=60.0,
        outgassing_rate_mbar_l_s_cm2=1.0e-12,
        temperature_K=2.05
    )
    res_scl = engine.evaluate_segment_vacuum(scl_sec, ion_species="U238", ion_charge=33, beam_energy_MeV_u=17.5)
    # Cold bore cryopumping should produce ultra-high vacuum < 1e-8 mbar
    assert res_scl.mean_pressure_mbar < 1.0e-8
    assert res_scl.vacuum_status == "EXCELLENT_UHV"
    # Loss in clean cryogenic vacuum must be negligible
    assert res_scl.fractional_beam_loss_percent < 0.01



