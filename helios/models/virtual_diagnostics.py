"""HELIOS Virtual Diagnostics Suite.

Provides non-interceptive virtual instrumentation:
1. VirtualWireScanner: predicts transverse beam sizes (sigma_x, sigma_y) and profiles.
2. VirtualBeamLossMonitor: predicts beam halo scraping and loss radiation hotspots along the linac.
"""

from dataclasses import dataclass
import logging
import math
from typing import Dict, List, Optional, Tuple
import numpy as np

from helios.models.surrogate import NeuralLinacSurrogate, SurrogatePrediction

logger = logging.getLogger(__name__)


@dataclass
class VirtualProfile:
    """Reconstructed beam profile from virtual wire scanner."""
    location_s_m: float
    sigma_x_mm: float
    sigma_y_mm: float
    centroid_x_mm: float
    centroid_y_mm: float
    emittance_x_um: float
    emittance_y_um: float
    coords_mm: List[float]
    intensity_x: List[float]
    intensity_y: List[float]


@dataclass
class VirtualLossMap:
    """Predicted radiation and scraping loss map along the accelerator."""
    s_positions_m: List[float]
    loss_fraction_per_m: List[float]
    beam_power_w_per_m: List[float]
    aperture_limit_mm: float
    tripped: bool
    hotspot_location_m: float
    max_loss_w_per_m: float


class VirtualWireScanner:
    """Non-interceptive virtual wire scanner reconstructing transverse profiles."""

    def __init__(self, surrogate: Optional[NeuralLinacSurrogate] = None):
        self.surrogate = surrogate or NeuralLinacSurrogate()

    def predict_profile(
        self,
        location_s_m: float,
        setpoints: Dict[str, float],
        grid_range_mm: float = 10.0,
        grid_points: int = 100,
    ) -> VirtualProfile:
        """Evaluate beam profile and transverse distributions at position s."""
        pred = self.surrogate.predict(setpoints)

        # Interpolate envelope at target location_s_m
        s_arr = np.array(pred.s_positions_m)
        sig_x_arr = np.array(pred.sigma_x_mm)
        sig_y_arr = np.array(pred.sigma_y_mm)
        cent_x_arr = np.array(pred.centroid_x_mm)
        cent_y_arr = np.array(pred.centroid_y_mm)

        sigma_x = float(np.interp(location_s_m, s_arr, sig_x_arr))
        sigma_y = float(np.interp(location_s_m, s_arr, sig_y_arr))
        cent_x = float(np.interp(location_s_m, s_arr, cent_x_arr))
        cent_y = float(np.interp(location_s_m, s_arr, cent_y_arr))

        # Synthetic 1D wire scanner scan profiles
        coords = np.linspace(-grid_range_mm, grid_range_mm, grid_points)
        ix = np.exp(-((coords - cent_x) ** 2) / (2.0 * max(0.01, sigma_x ** 2)))
        iy = np.exp(-((coords - cent_y) ** 2) / (2.0 * max(0.01, sigma_y ** 2)))

        # Normalized geometric emittance approximation (um)
        emit_x = max(0.1, (sigma_x ** 2) / 2.5)
        emit_y = max(0.1, (sigma_y ** 2) / 2.5)

        return VirtualProfile(
            location_s_m=location_s_m,
            sigma_x_mm=sigma_x,
            sigma_y_mm=sigma_y,
            centroid_x_mm=cent_x,
            centroid_y_mm=cent_y,
            emittance_x_um=float(emit_x),
            emittance_y_um=float(emit_y),
            coords_mm=[float(c) for c in coords],
            intensity_x=[float(v) for v in ix],
            intensity_y=[float(v) for v in iy],
        )


class VirtualBeamLossMonitor:
    """Predicts halo scraping and beam loss radiation before live beam exposure."""

    def __init__(
        self,
        surrogate: Optional[NeuralLinacSurrogate] = None,
        aperture_radius_mm: float = 15.0,
        beam_current_ma: float = 5.0,
        energy_mev_u: float = 0.5,
        loss_trip_threshold_w_per_m: float = 1.0,
    ):
        self.surrogate = surrogate or NeuralLinacSurrogate()
        self.aperture_radius_mm = aperture_radius_mm
        self.beam_current_ma = beam_current_ma
        self.energy_mev_u = energy_mev_u
        self.loss_trip_threshold_w_per_m = loss_trip_threshold_w_per_m

    def predict_losses(self, setpoints: Dict[str, float]) -> VirtualLossMap:
        """Compute projected scraping along the vacuum chamber."""
        pred = self.surrogate.predict(setpoints)
        s_arr = pred.s_positions_m

        loss_fractions = []
        power_losses = []

        total_beam_power_w = self.beam_current_ma * 1e-3 * self.energy_mev_u * 1e6  # Watts

        for sig_x, sig_y, cx, cy in zip(pred.sigma_x_mm, pred.sigma_y_mm, pred.centroid_x_mm, pred.centroid_y_mm):
            # Effective beam envelope radius at 3-sigma
            r_beam = max(abs(cx) + 3.0 * sig_x, abs(cy) + 3.0 * sig_y)

            if r_beam > self.aperture_radius_mm:
                # Scraping occurs
                excess = r_beam - self.aperture_radius_mm
                fraction = min(0.1, (excess / self.aperture_radius_mm) ** 2)
            else:
                fraction = 0.0

            loss_fractions.append(fraction)
            p_loss = fraction * total_beam_power_w
            power_losses.append(p_loss)

        max_loss = max(power_losses) if power_losses else 0.0
        max_idx = int(np.argmax(power_losses)) if power_losses else 0
        hotspot_s = s_arr[max_idx] if s_arr else 0.0
        tripped = max_loss > self.loss_trip_threshold_w_per_m

        return VirtualLossMap(
            s_positions_m=s_arr,
            loss_fraction_per_m=[float(f) for f in loss_fractions],
            beam_power_w_per_m=[float(p) for p in power_losses],
            aperture_limit_mm=self.aperture_radius_mm,
            tripped=tripped,
            hotspot_location_m=float(hotspot_s),
            max_loss_w_per_m=float(max_loss),
        )
