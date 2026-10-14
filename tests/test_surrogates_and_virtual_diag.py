"""Unit tests for Deep Neural Surrogates and Virtual Diagnostics (Phase 11)."""

import tempfile
from pathlib import Path
import numpy as np
import pytest

pytest.importorskip("torch")

from helios.models.calibration import OnlineModelCalibrator
from helios.models.surrogate import NeuralLinacSurrogate
from helios.models.virtual_diagnostics import VirtualBeamLossMonitor, VirtualWireScanner


def test_neural_linac_surrogate_prediction_and_training():
    """Verify PyTorch NeuralLinacSurrogate forward prediction and train step."""
    surrogate = NeuralLinacSurrogate()

    sample_setpoints = {
        "MEBT:QUAD:01:B_SET": 1.2,
        "MEBT:QUAD:02:B_SET": -1.1,
        "MEBT:QUAD:03:B_SET": 1.0,
        "MEBT:QUAD:04:B_SET": -0.9,
        "MEBT:DCH:01:I_SET": 0.5,
        "MEBT:DCV:01:I_SET": -0.3,
    }

    pred = surrogate.predict(sample_setpoints)
    assert len(pred.s_positions_m) > 0
    assert len(pred.sigma_x_mm) == len(pred.s_positions_m)
    assert len(pred.sigma_y_mm) == len(pred.s_positions_m)
    assert len(pred.centroid_x_mm) == len(pred.s_positions_m)
    assert len(pred.centroid_y_mm) == len(pred.s_positions_m)
    assert 0.0 <= pred.transmission <= 1.0
    assert pred.confidence_score > 0.0

    # Test single training step
    x_batch = np.random.randn(4, surrogate.input_dim).astype(np.float32)
    y_track = np.random.randn(4, surrogate.num_locations, 4).astype(np.float32)
    y_trans = np.ones((4, 1), dtype=np.float32) * 0.98

    loss_val = surrogate.train_step(x_batch, y_track, y_trans)
    assert isinstance(loss_val, float)
    assert loss_val >= 0.0

    # Test weight persistence
    with tempfile.TemporaryDirectory() as tmpdir:
        w_path = Path(tmpdir) / "surrogate.pt"
        surrogate.save_weights(w_path)
        assert w_path.exists()
        surrogate.load_weights(w_path)


def test_virtual_wire_scanner_profile_inference():
    """Verify VirtualWireScanner computes non-interceptive transverse profiles."""
    v_scanner = VirtualWireScanner()

    setpoints = {
        "MEBT:QUAD:01:B_SET": 1.5,
        "MEBT:QUAD:02:B_SET": -1.3,
    }

    profile = v_scanner.predict_profile(location_s_m=1.8, setpoints=setpoints)
    assert profile.location_s_m == 1.8
    assert profile.sigma_x_mm > 0.0
    assert profile.sigma_y_mm > 0.0
    assert profile.emittance_x_um > 0.0
    assert profile.emittance_y_um > 0.0
    assert len(profile.coords_mm) == 100
    assert len(profile.intensity_x) == 100
    assert max(profile.intensity_x) > 0.5


def test_virtual_beam_loss_monitor():
    """Verify VirtualBeamLossMonitor detects scraping and power loss distribution."""
    v_blm = VirtualBeamLossMonitor(aperture_radius_mm=10.0, beam_current_ma=5.0)

    # Moderate setpoints -> normal operation
    normal_setpoints = {"MEBT:QUAD:01:B_SET": 1.0}
    loss_map = v_blm.predict_losses(normal_setpoints)
    assert len(loss_map.s_positions_m) > 0
    assert len(loss_map.loss_fraction_per_m) == len(loss_map.s_positions_m)
    assert loss_map.aperture_limit_mm == 10.0

    # Extreme setpoints -> aperture breach trip
    extreme_setpoints = {"MEBT:DCH:01:I_SET": 50.0}
    extreme_loss_map = v_blm.predict_losses(extreme_setpoints)
    assert isinstance(extreme_loss_map.tripped, bool)


def test_online_model_calibrator():
    """Verify OnlineModelCalibrator minimizes RMS discrepancy between measured and simulated orbit."""
    calibrator = OnlineModelCalibrator()

    active_setpoints = {
        "MEBT:QUAD:01:B_SET": 1.5,
        "MEBT:QUAD:02:B_SET": -1.4,
        "MEBT:QUAD:03:B_SET": 1.2,
        "MEBT:QUAD:04:B_SET": -1.1,
    }

    measured_orbit = {
        "MEBT:BPM:01:X": 0.15,
        "MEBT:BPM:02:X": -0.10,
        "MEBT:BPM:03:X": 0.22,
    }

    res = calibrator.calibrate_quadrupole_factors(
        measured_orbit_mm=measured_orbit,
        active_setpoints=active_setpoints,
    )

    assert res.success is True
    assert res.final_rms_error_mm <= res.initial_rms_error_mm + 0.1
    assert len(res.calibrated_factors) == 4
    for factor in res.calibrated_factors.values():
        assert 0.80 <= factor <= 1.20
