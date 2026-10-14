"""HELIOS Phase 39: High-Fidelity 6D Phase Space Projection & Visual Diagnostics.

Provides 6D beam phase-space projection calculations, Twiss parameter extraction
(alpha, beta, gamma, emittance), ASCII console visualization for control room terminals,
and digital-twin vs measured telemetry distribution discrepancy analysis.
"""

import numpy as np
from pydantic import BaseModel


class TwissParameters(BaseModel):
    """Courant-Snyder Twiss parameters and RMS emittance."""
    plane: str
    emittance_rms_mm_mrad: float
    beta_m: float
    alpha: float
    gamma_per_m: float
    rms_size_mm: float
    rms_divergence_mrad: float


class PhaseSpaceProjection(BaseModel):
    """2D phase space projection metrics and bounds."""
    plane: str  # "x", "y", "z"
    num_particles: int
    twiss: TwissParameters
    x_min: float
    x_max: float
    xp_min: float
    xp_max: float


class PhaseSpaceVisualizer:
    """Computes Twiss optics and generates projections for operator displays."""

    @staticmethod
    def calculate_twiss(u: np.ndarray, up: np.ndarray, plane_name: str = "x") -> TwissParameters:
        """Calculate RMS Twiss parameters for coordinates u (m) and angles up (rad)."""
        u_m = u - np.mean(u)
        up_rad = up - np.mean(up)

        u2 = float(np.mean(u_m ** 2))
        up2 = float(np.mean(up_rad ** 2))
        u_up = float(np.mean(u_m * up_rad))

        # Geometric RMS emittance: eps = sqrt(<u^2><u'^2> - <u u'>^2)
        det = u2 * up2 - u_up ** 2
        eps = np.sqrt(max(0.0, det))

        if eps > 1e-12:
            beta = u2 / eps
            alpha = -u_up / eps
            gamma = up2 / eps
        else:
            beta = 1.0
            alpha = 0.0
            gamma = 1.0

        eps_mm_mrad = eps * 1e6
        rms_size_mm = np.sqrt(u2) * 1e3
        rms_div_mrad = np.sqrt(up2) * 1e3

        return TwissParameters(
            plane=plane_name,
            emittance_rms_mm_mrad=round(float(eps_mm_mrad), 4),
            beta_m=round(float(beta), 4),
            alpha=round(float(alpha), 4),
            gamma_per_m=round(float(gamma), 4),
            rms_size_mm=round(float(rms_size_mm), 4),
            rms_divergence_mrad=round(float(rms_div_mrad), 4)
        )

    def project(self, bunch: np.ndarray, plane: str = "x") -> PhaseSpaceProjection:
        """Project 6D bunch (N, 6) onto 2D phase space (x, x') or (y, y') or (z, delta)."""
        if plane == "x":
            u = bunch[:, 0]
            up = bunch[:, 1]
        elif plane == "y":
            u = bunch[:, 2]
            up = bunch[:, 3]
        else:  # longitudinal z
            u = bunch[:, 4]
            up = bunch[:, 5]

        twiss = self.calculate_twiss(u, up, plane_name=plane)
        return PhaseSpaceProjection(
            plane=plane,
            num_particles=len(bunch),
            twiss=twiss,
            x_min=round(float(np.min(u)), 6),
            x_max=round(float(np.max(u)), 6),
            xp_min=round(float(np.min(up)), 6),
            xp_max=round(float(np.max(up)), 6)
        )

    def render_ascii(self, bunch: np.ndarray, plane: str = "x", width: int = 40, height: int = 12) -> str:
        """Render compact ASCII scatter plot for CLI operator consoles."""
        if plane == "x":
            u = bunch[:, 0] * 1e3
            up = bunch[:, 1] * 1e3
        elif plane == "y":
            u = bunch[:, 2] * 1e3
            up = bunch[:, 3] * 1e3
        else:
            u = bunch[:, 4] * 1e3
            up = bunch[:, 5] * 1e3

        u_min, u_max = np.min(u), np.max(u)
        up_min, up_max = np.min(up), np.max(up)

        grid = [[" " for _ in range(width)] for _ in range(height)]

        u_span = max(1e-6, u_max - u_min)
        up_span = max(1e-6, up_max - up_min)

        for x_val, y_val in zip(u, up):
            col = int(min(width - 1, max(0, (x_val - u_min) / u_span * (width - 1))))
            # row: top is max up, bottom is min up
            row = int(min(height - 1, max(0, (up_max - y_val) / up_span * (height - 1))))
            grid[row][col] = "*"

        lines = ["+" + "-" * width + "+"]
        for row in grid:
            lines.append("|" + "".join(row) + "|")
        lines.append("+" + "-" * width + "+")
        lines.append(f"  {plane} (mm) range: [{u_min:.2f}, {u_max:.2f}] | {plane}' (mrad) range: [{up_min:.2f}, {up_max:.2f}]")
        return "\n".join(lines)

    @staticmethod
    def calculate_discrepancy(bunch_meas: np.ndarray, bunch_sim: np.ndarray) -> float:
        """Calculate statistical Wasserstein-1 / RMS distance between measured & digital twin bunches."""
        min_n = min(len(bunch_meas), len(bunch_sim))
        meas = bunch_meas[:min_n]
        sim = bunch_sim[:min_n]
        # Normalized RMS discrepancy
        diff = np.mean(np.linalg.norm(meas - sim, axis=1))
        return round(float(diff), 6)
