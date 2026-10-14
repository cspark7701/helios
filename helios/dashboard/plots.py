"""HELIOS Dashboard Plot Generation and Telemetry Visualization.

Provides plot structures and SVG/JSON payloads for:
1. Live orbit distortion vs golden orbit and tolerance bands.
2. 3-sigma beam envelope profile vs vacuum aperture boundaries.
3. Beam loss monitor (BLM) radiation distribution heatmap.
"""

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class OrbitPlotData:
    """Telemetry structure for interactive orbit plots."""
    s_positions_m: list[float]
    bpm_names: list[float]  # or str
    x_mm: list[float]
    y_mm: list[float]
    golden_x_mm: list[float]
    golden_y_mm: list[float]
    tolerance_mm: float


@dataclass
class EnvelopePlotData:
    """Structure for 3-sigma beam envelope visualization."""
    s_positions_m: list[float]
    sigma_x_mm: list[float]
    sigma_y_mm: list[float]
    envelope_3sig_x_pos_mm: list[float]
    envelope_3sig_x_neg_mm: list[float]
    envelope_3sig_y_pos_mm: list[float]
    envelope_3sig_y_neg_mm: list[float]
    aperture_limit_mm: float


@dataclass
class BLMHeatmapData:
    """Structure for linac beam loss monitor radiation visualization."""
    s_positions_m: list[float]
    blm_names: list[str]
    loss_values_w: list[float]
    trip_threshold_w: float
    max_loss_w: float
    hotspot_location_m: float


def generate_orbit_plot_data(
    bpm_telemetry: dict[str, dict[str, float]],
    golden_orbit: dict[str, dict[str, float]] | None = None,
    tolerance_mm: float = 0.5,
) -> dict[str, Any]:
    """Format BPM telemetry into orbit plot dataset."""
    golden = golden_orbit or {}
    s_list = []
    names = []
    x_list = []
    y_list = []
    gx_list = []
    gy_list = []

    for bpm_name, data in sorted(bpm_telemetry.items(), key=lambda item: item[1].get("s_m", 0.0)):
        names.append(bpm_name)
        s_list.append(data.get("s_m", 0.0))
        x_list.append(data.get("x_mm", 0.0))
        y_list.append(data.get("y_mm", 0.0))

        g_data = golden.get(bpm_name, {})
        gx_list.append(g_data.get("x_mm", 0.0))
        gy_list.append(g_data.get("y_mm", 0.0))

    return {
        "bpm_names": names,
        "s_positions_m": s_list,
        "x_mm": x_list,
        "y_mm": y_list,
        "golden_x_mm": gx_list,
        "golden_y_mm": gy_list,
        "tolerance_mm": tolerance_mm,
    }


def generate_envelope_plot_data(
    s_positions: list[float],
    sigma_x_mm: list[float],
    sigma_y_mm: list[float],
    centroid_x_mm: list[float] | None = None,
    centroid_y_mm: list[float] | None = None,
    aperture_radius_mm: float = 15.0,
) -> dict[str, Any]:
    """Generate 3-sigma envelope bounds and aperture lines along linac axis."""
    cx = centroid_x_mm or [0.0] * len(s_positions)
    cy = centroid_y_mm or [0.0] * len(s_positions)

    env_3x_pos = [c + 3.0 * sig for c, sig in zip(cx, sigma_x_mm)]
    env_3x_neg = [c - 3.0 * sig for c, sig in zip(cx, sigma_x_mm)]
    env_3y_pos = [c + 3.0 * sig for c, sig in zip(cy, sigma_y_mm)]
    env_3y_neg = [c - 3.0 * sig for c, sig in zip(cy, sigma_y_mm)]

    return {
        "s_positions_m": s_positions,
        "sigma_x_mm": sigma_x_mm,
        "sigma_y_mm": sigma_y_mm,
        "envelope_3sig_x_pos_mm": env_3x_pos,
        "envelope_3sig_x_neg_mm": env_3x_neg,
        "envelope_3sig_y_pos_mm": env_3y_pos,
        "envelope_3sig_y_neg_mm": env_3y_neg,
        "aperture_limit_mm": aperture_radius_mm,
    }


def generate_blm_heatmap_data(
    blm_readings: dict[str, dict[str, float]],
    trip_threshold_w: float = 1.0,
) -> dict[str, Any]:
    """Format beam loss monitor data into radiation intensity plot dataset."""
    names = []
    s_list = []
    losses = []

    for name, data in sorted(blm_readings.items(), key=lambda item: item[1].get("s_m", 0.0)):
        names.append(name)
        s_list.append(data.get("s_m", 0.0))
        losses.append(data.get("loss_w", 0.0))

    max_loss = max(losses) if losses else 0.0
    max_idx = int(np.argmax(losses)) if losses else 0
    hotspot_s = s_list[max_idx] if s_list else 0.0

    return {
        "blm_names": names,
        "s_positions_m": s_list,
        "loss_values_w": losses,
        "trip_threshold_w": trip_threshold_w,
        "max_loss_w": max_loss,
        "hotspot_location_m": hotspot_s,
    }
