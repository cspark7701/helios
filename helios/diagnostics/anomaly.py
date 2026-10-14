"""HELIOS Anomaly & Fault Detection Engine.

Detects RF trips, beam loss spikes, transmission degradation, and orbit drift
from real-time accelerator telemetry, producing structured AnomalyReport objects.
"""

from datetime import datetime, timezone

from helios.core.schemas import AnomalyReport, AnomalySeverity, TelemetrySnapshot


class LinacAnomalyDetector:
    """Analyzes telemetry snapshots to flag operational faults and anomalies."""

    def __init__(
        self,
        max_rms_orbit_mm: float = 1.0,
        min_transmission_pct: float = 90.0,
        max_blm_dose: float = 10.0,
    ):
        self.max_rms_orbit_mm = max_rms_orbit_mm
        self.min_transmission_pct = min_transmission_pct
        self.max_blm_dose = max_blm_dose

    def inspect_telemetry(self, telemetry: TelemetrySnapshot) -> list[AnomalyReport]:
        """Perform anomaly checks across BPM, BLM, and transmission channels."""
        reports: list[AnomalyReport] = []

        # 1. Transmission Check
        if telemetry.transmission_pct < self.min_transmission_pct:
            reports.append(AnomalyReport(
                timestamp=datetime.now(timezone.utc),
                severity=AnomalySeverity.CRITICAL if telemetry.transmission_pct < 50.0 else AnomalySeverity.WARNING,
                anomaly_type="TRANSMISSION_DROP",
                description=f"Beam transmission ({telemetry.transmission_pct:.1f}%) is below minimum threshold ({self.min_transmission_pct:.1f}%)",
                affected_channels=[f"{telemetry.section}:TRANSMISSION"],
                recommended_action="Inspect upstream steerers and RF buncher phase/amplitude.",
            ))

        # 2. Beam Loss Spike Check
        hotspots = [ch for ch, dose in telemetry.blm_loss.items() if dose > self.max_blm_dose]
        if hotspots:
            reports.append(AnomalyReport(
                timestamp=datetime.now(timezone.utc),
                severity=AnomalySeverity.CRITICAL,
                anomaly_type="BEAM_LOSS_SPIKE",
                description=f"Beam loss monitor alert: {len(hotspots)} sensor(s) exceed safe dose threshold ({self.max_blm_dose})",
                affected_channels=hotspots,
                recommended_action="Immediately check trajectory alignment or trigger rollback.",
            ))

        # 3. Orbit Drift Check
        orbit_excursions = []
        for ch, val in telemetry.bpm_x.items():
            if abs(val) > self.max_rms_orbit_mm:
                orbit_excursions.append(ch)
        for ch, val in telemetry.bpm_y.items():
            if abs(val) > self.max_rms_orbit_mm and ch not in orbit_excursions:
                orbit_excursions.append(ch)

        if orbit_excursions:
            reports.append(AnomalyReport(
                timestamp=datetime.now(timezone.utc),
                severity=AnomalySeverity.WARNING,
                anomaly_type="ORBIT_EXCURSION",
                description=f"Orbit distortion exceeded {self.max_rms_orbit_mm} mm at {len(orbit_excursions)} BPM(s)",
                affected_channels=orbit_excursions,
                recommended_action="Run automated SVD orbit correction.",
            ))

        return reports

    def inspect_rf_station(
        self,
        cavity_name: str,
        amp_set: float,
        amp_act: float,
        interlock_tripped: bool,
    ) -> AnomalyReport | None:
        """Inspect cavity RF station status for trip or power loss."""
        if interlock_tripped:
            return AnomalyReport(
                timestamp=datetime.now(timezone.utc),
                severity=AnomalySeverity.CRITICAL,
                anomaly_type="RF_TRIP",
                description=f"Cavity {cavity_name} RF station interlock tripped!",
                affected_channels=[f"{cavity_name}:Interlock"],
                recommended_action="Inhibit beam pulse, reset interlock, and initiate auto-recovery sequence.",
            )

        if amp_set > 5.0 and amp_act < 1.0:
            return AnomalyReport(
                timestamp=datetime.now(timezone.utc),
                severity=AnomalySeverity.CRITICAL,
                anomaly_type="RF_AMPLITUDE_COLLAPSE",
                description=f"Cavity {cavity_name} setpoint is {amp_set:.1f} kV but readback collapsed to {amp_act:.1f} kV",
                affected_channels=[f"{cavity_name}:AmpAct"],
                recommended_action="Verify klystron/solid-state amplifier and low-level RF (LLRF) lock.",
            )

        return None
