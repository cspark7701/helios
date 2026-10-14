"""Fast analytic orbit correction and station response data for interactive tuning."""

import time
from typing import Any

import numpy as np

from helios.optimization.algorithms import SVDOrbitCorrection
from helios.physics.elements import Steerer

# Standard baseline diagnostics and response data for fast analytic GUI tuning
LEBT_STATION_DATA = [
    {"name": "WS_1", "z_m": 1.9812, "x_init": 0.0424, "y_init": 0.0001},
    {"name": "Allison", "z_m": 4.0082, "x_init": -0.0264, "y_init": -0.0002},
    {"name": "WS_2", "z_m": 7.6402, "x_init": 0.0967, "y_init": 0.0003},
    {"name": "WS_3", "z_m": 9.9872, "x_init": -0.1155, "y_init": -0.0001},
    {"name": "WS_4", "z_m": 10.7672, "x_init": -0.2281, "y_init": 0.0002},
    {"name": "BPM_EXIT", "z_m": 12.2832, "x_init": -0.0111, "y_init": -0.0003},
]

LEBT_STEERER_NAMES = ["STM_1", "STM_2", "STM_3", "STM_4", "STM_5"]

LEBT_RX = np.array([
    [-0.039,  0.000,  0.000,  0.000,  0.000],
    [-0.045,  0.155,  0.000,  0.000,  0.000],
    [-0.038,  0.182,  0.095,  0.000,  0.000],
    [-0.035,  0.210,  0.110, -0.095,  0.000],
    [-0.038,  0.235,  0.125, -0.108,  0.071],
    [-0.039,  0.254,  0.137, -0.120,  0.086],
])

LEBT_RY = np.array([
    [-0.075,  0.000,  0.000,  0.000,  0.000],
    [-0.078,  0.215,  0.000,  0.000,  0.000],
    [-0.072,  0.245,  0.130,  0.000,  0.000],
    [-0.068,  0.280,  0.150, -0.130,  0.000],
    [-0.070,  0.310,  0.170, -0.150, -0.240],
    [-0.075,  0.340,  0.190, -0.170, -0.241],
])


def execute_analytic_orbit_correction(
    section: str = "LEBT",
    conversion_factor_a_per_mrad: float = 0.168,
    current_increment_a: float = 0.05,
) -> dict[str, Any]:
    """Perform rapid analytic orbit correction for interactive operator console."""
    start_time = time.perf_counter()

    if section.upper() == "LEBT":
        stations = LEBT_STATION_DATA
        steerers = LEBT_STEERER_NAMES
        Rx = LEBT_RX
        Ry = LEBT_RY
        x_init = np.array([s["x_init"] for s in stations])
        y_init = np.array([s["y_init"] for s in stations])
    else:
        stations = [
            {"name": f"MEBT_BPM_{i+1:02d}", "z_m": round(0.5 + i * 0.45, 3), "x_init": round(0.15 * np.sin(i * 0.9), 4), "y_init": round(-0.10 * np.cos(i * 0.8), 4)}
            for i in range(8)
        ]
        steerers = ["MEBT_ST_01", "MEBT_ST_02", "MEBT_ST_03", "MEBT_ST_04"]
        m, n = len(stations), len(steerers)
        Rx = np.zeros((m, n))
        Ry = np.zeros((m, n))
        for i in range(m):
            for j in range(n):
                if i >= j * 2:
                    Rx[i, j] = 0.25 * (i - j * 2 + 1)
                    Ry[i, j] = 0.22 * (i - j * 2 + 1)
        x_init = np.array([s["x_init"] for s in stations])
        y_init = np.array([s["y_init"] for s in stations])

    rms_x_init = float(np.sqrt(np.mean(x_init**2)))
    rms_y_init = float(np.sqrt(np.mean(y_init**2)))

    kicks_x, _ = SVDOrbitCorrection.calculate_correction(
        response_matrix=Rx,
        measured_offsets_mm=x_init,
        singular_value_cutoff=1e-3,
        tikhonov_regularization=1e-4,
    )
    kicks_y, _ = SVDOrbitCorrection.calculate_correction(
        response_matrix=Ry,
        measured_offsets_mm=y_init,
        singular_value_cutoff=1e-3,
        tikhonov_regularization=1e-4,
    )

    steerers_result = []
    eff_kicks_x = []
    eff_kicks_y = []

    for idx, stm in enumerate(steerers):
        curr_x = Steerer.kick_to_current(float(kicks_x[idx]), conversion_factor_a_per_mrad, current_increment_a)
        curr_y = Steerer.kick_to_current(float(kicks_y[idx]), conversion_factor_a_per_mrad, current_increment_a)
        eff_kx = Steerer.current_to_kick(curr_x, conversion_factor_a_per_mrad)
        eff_ky = Steerer.current_to_kick(curr_y, conversion_factor_a_per_mrad)

        eff_kicks_x.append(eff_kx)
        eff_kicks_y.append(eff_ky)

        steerers_result.append({
            "name": stm,
            "kick_x_mrad": round(eff_kx, 4),
            "current_x_a": round(curr_x, 4),
            "kick_y_mrad": round(eff_ky, 4),
            "current_y_a": round(curr_y, 4),
        })

    x_corr = x_init + Rx @ np.array(eff_kicks_x)
    y_corr = y_init + Ry @ np.array(eff_kicks_y)

    rms_x_corr = float(np.sqrt(np.mean(x_corr**2)))
    rms_y_corr = float(np.sqrt(np.mean(y_corr**2)))
    improvement_x_pct = ((rms_x_init - rms_x_corr) / max(1e-6, rms_x_init)) * 100.0

    monitors_result = []
    for i, s in enumerate(stations):
        monitors_result.append({
            "name": s["name"],
            "z_m": s["z_m"],
            "x_init_mm": round(float(x_init[i]), 4),
            "x_corr_mm": round(float(x_corr[i]), 4),
            "y_init_mm": round(float(y_init[i]), 4),
            "y_corr_mm": round(float(y_corr[i]), 4),
        })

    elapsed_time_s = time.perf_counter() - start_time

    return {
        "section": section,
        "engine": "analytic",
        "initial_rms_x_mm": round(rms_x_init, 4),
        "corrected_rms_x_mm": round(rms_x_corr, 4),
        "initial_rms_y_mm": round(rms_y_init, 4),
        "corrected_rms_y_mm": round(rms_y_corr, 4),
        "improvement_pct": round(improvement_x_pct, 1),
        "elapsed_time_s": round(elapsed_time_s, 3),
        "conversion_factor_a_per_mrad": conversion_factor_a_per_mrad,
        "current_increment_a": current_increment_a,
        "steerers": steerers_result,
        "monitors": monitors_result,
    }
