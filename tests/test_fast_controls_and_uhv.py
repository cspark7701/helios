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

