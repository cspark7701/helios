"""Tests for Diagnostics, Telemetry processing, Anomaly detection, and Archiver."""

from pathlib import Path
import pytest

from helios.core.schemas import AnomalySeverity
from helios.diagnostics.anomaly import LinacAnomalyDetector
from helios.diagnostics.archiver import TelemetryArchiver
from helios.diagnostics.telemetry import TelemetryProcessor


def test_telemetry_processor_metrics():
    """Verify RMS orbit, transmission, and ToF calculation."""
    bpm_x = {"BPM1": 0.3, "BPM2": -0.4}
    bpm_y = {"BPM1": -0.2, "BPM2": 0.2}
    blm_loss = {"BLM1": 0.5, "BLM2": 1.2}

    snap, metrics = TelemetryProcessor.process_snapshot(
        bpm_x=bpm_x,
        bpm_y=bpm_y,
        blm_losses=blm_loss,
        upstream_current_ma=10.0,
        downstream_current_ma=9.8,
        section="MEBT",
    )

    assert metrics["transmission_pct"] == pytest.approx(98.0)
    # sqrt((0.3^2 + 0.4^2)/2) = sqrt(0.25/2) = sqrt(0.125) = ~0.3535 mm
    assert abs(metrics["rms_x_mm"] - 0.3535) < 0.01

    # ToF Energy calculation
    energy = TelemetryProcessor.calculate_energy_from_tof(
        phase_deg_1=0.0,
        phase_deg_2=90.0,
        distance_m=0.5,
        rf_freq_mhz=81.25,
    )
    assert energy > 0.0


def test_anomaly_detector():
    """Verify anomaly detection for transmission drops, loss spikes, and RF trips."""
    detector = LinacAnomalyDetector(max_rms_orbit_mm=1.0, min_transmission_pct=90.0, max_blm_dose=10.0)

    # 1. Normal Snapshot
    norm_snap, _ = TelemetryProcessor.process_snapshot(
        bpm_x={"BPM1": 0.2}, bpm_y={"BPM1": 0.1}, blm_losses={"BLM1": 1.0},
        upstream_current_ma=10.0, downstream_current_ma=9.8,
    )
    assert len(detector.inspect_telemetry(norm_snap)) == 0

    # 2. Transmission drop
    bad_trans, _ = TelemetryProcessor.process_snapshot(
        bpm_x={"BPM1": 0.2}, bpm_y={"BPM1": 0.1}, blm_losses={"BLM1": 1.0},
        upstream_current_ma=10.0, downstream_current_ma=7.0,
    )
    reports = detector.inspect_telemetry(bad_trans)
    assert len(reports) == 1
    assert reports[0].anomaly_type == "TRANSMISSION_DROP"

    # 3. BLM loss spike
    loss_spike, _ = TelemetryProcessor.process_snapshot(
        bpm_x={"BPM1": 0.2}, bpm_y={"BPM1": 0.1}, blm_losses={"BLM1": 25.0},
        upstream_current_ma=10.0, downstream_current_ma=9.8,
    )
    spike_reports = detector.inspect_telemetry(loss_spike)
    assert any(r.anomaly_type == "BEAM_LOSS_SPIKE" for r in spike_reports)

    # 4. RF Station Trip
    rf_report = detector.inspect_rf_station("MEBT_CAV01", amp_set=120.0, amp_act=0.0, interlock_tripped=True)
    assert rf_report is not None
    assert rf_report.severity == AnomalySeverity.CRITICAL
    assert rf_report.anomaly_type == "RF_TRIP"


def test_telemetry_archiver(tmp_path: Path):
    """Verify archiver history storage, trend statistics, and JSON export."""
    archiver = TelemetryArchiver(max_buffer_size=50)

    for i in range(5):
        snap, _ = TelemetryProcessor.process_snapshot(
            bpm_x={"BPM1": 0.1 * i}, bpm_y={"BPM1": -0.05 * i}, blm_losses={"BLM1": 0.5},
            upstream_current_ma=10.0, downstream_current_ma=9.9,
        )
        archiver.record_snapshot(snap)

    assert len(archiver.get_recent(10)) == 5
    assert archiver.get_latest().bpm_x["BPM1"] == 0.4

    stats = archiver.compute_trend_stats("BPM1", plane="x")
    assert stats["count"] == 5
    assert stats["min"] == 0.0
    assert stats["max"] == 0.4

    export_file = tmp_path / "telemetry_dump.json"
    archiver.export_json(export_file)
    assert export_file.exists()
