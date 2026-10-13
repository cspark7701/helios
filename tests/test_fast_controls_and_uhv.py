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
