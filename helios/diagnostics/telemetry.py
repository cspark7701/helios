"""HELIOS Diagnostics & Telemetry Processing Pipeline.

Processes raw BPM, BLM, and current monitor readouts to calculate beam metrics:
RMS orbit distortion, transmission, and time-of-flight (ToF) beam energy.
"""

import math
from typing import Dict, List, Optional, Tuple
import numpy as np

from helios.core.schemas import TelemetrySnapshot


class TelemetryProcessor:
    """Processes real-time accelerator diagnostic readouts."""

    @staticmethod
    def compute_rms_orbit(bpm_positions: Dict[str, float]) -> float:
        """Calculate RMS orbit distortion in millimeters."""
        if not bpm_positions:
            return 0.0
        values = list(bpm_positions.values())
        return float(np.sqrt(np.mean(np.square(values))))

    @staticmethod
    def compute_transmission(upstream_current_ma: float, downstream_current_ma: float) -> float:
        """Calculate beam transmission percentage (0 - 100%)."""
        if upstream_current_ma <= 1e-6:
            return 0.0
        ratio = (downstream_current_ma / upstream_current_ma) * 100.0
        return float(np.clip(ratio, 0.0, 100.0))

    @staticmethod
    def calculate_energy_from_tof(
        phase_deg_1: float,
        phase_deg_2: float,
        distance_m: float,
        rf_freq_mhz: float = 81.25,
        mass_amu: float = 1.0,
    ) -> float:
        """Calculate beam kinetic energy (MeV/u) from two-BPM Time-of-Flight (ToF) phase difference.

        Delta_phi = 2 * pi * f * (d / v) [mod 360]
        v = 2 * pi * f * d / Delta_phi_rad
        """
        c = 299792458.0
        f_hz = rf_freq_mhz * 1e6

        # Phase difference unwrapped
        delta_phi_deg = (phase_deg_2 - phase_deg_1) % 360.0
        if delta_phi_deg < 0:
            delta_phi_deg += 360.0

        # Account for minimum transit time if delta_phi near zero
        delta_phi_rad = math.radians(delta_phi_deg)
        if delta_phi_rad < 1e-4:
            delta_phi_rad = 2 * math.pi

        # Velocity v = 2 * pi * f * distance / delta_phi_rad
        v = (2 * math.pi * f_hz * distance_m) / delta_phi_rad
        beta = min(0.999, v / c)

        gamma = 1.0 / math.sqrt(max(1e-9, 1.0 - beta**2))
        m_mev = 931.494  # MeV/u
        kinetic_energy_mev_u = (gamma - 1.0) * m_mev
        return float(kinetic_energy_mev_u)

    @staticmethod
    def process_snapshot(
        bpm_x: Dict[str, float],
        bpm_y: Dict[str, float],
        blm_losses: Dict[str, float],
        upstream_current_ma: float,
        downstream_current_ma: float,
        section: str = "MEBT",
    ) -> Tuple[TelemetrySnapshot, Dict[str, float]]:
        """Construct a validated TelemetrySnapshot and return computed summary metrics."""
        trans_pct = TelemetryProcessor.compute_transmission(upstream_current_ma, downstream_current_ma)
        rms_x = TelemetryProcessor.compute_rms_orbit(bpm_x)
        rms_y = TelemetryProcessor.compute_rms_orbit(bpm_y)

        snapshot = TelemetrySnapshot(
            section=section,
            bpm_x=bpm_x,
            bpm_y=bpm_y,
            blm_loss=blm_losses,
            transmission_pct=trans_pct,
            beam_current_ma=downstream_current_ma,
        )

        metrics = {
            "rms_x_mm": rms_x,
            "rms_y_mm": rms_y,
            "max_x_mm": max((abs(v) for v in bpm_x.values()), default=0.0),
            "max_y_mm": max((abs(v) for v in bpm_y.values()), default=0.0),
            "transmission_pct": trans_pct,
            "total_loss_dose": sum(blm_losses.values()),
        }

        return snapshot, metrics
