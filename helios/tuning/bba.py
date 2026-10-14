"""HELIOS Online Beam-Based Alignment (BBA) and Dispersion-Free Steering (DFS).

Implements:
1. Quadrupole strength modulation (Delta K1) to resolve beam offset relative to magnetic center.
2. Dispersion-Free Steering (DFS) simultaneously minimizing orbit distortion and spurious dispersion.
3. Automated alignment solver with error covariance minimization.
"""

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class BBAQuadResult:
    """Outcome of Beam-Based Alignment measurement on a single quadrupole."""
    quad_name: str
    magnetic_center_offset_x_mm: float
    magnetic_center_offset_y_mm: float
    fit_residual_rms_mm: float
    confidence_interval_mm: float
    recommended_steerer_dx_mm: float
    recommended_steerer_dy_mm: float


@dataclass
class DFSResult:
    """Outcome of Dispersion-Free Steering optimization."""
    success: bool
    steerer_corrections: dict[str, float]
    initial_orbit_rms_mm: float
    final_orbit_rms_mm: float
    initial_dispersion_rms_m: float
    final_dispersion_rms_m: float
    emittance_growth_projected_pct: float


class BeamBasedAlignmentSolver:
    """Estimates beam position relative to quadrupole magnetic centers."""

    @staticmethod
    def solve_quad_offset(
        delta_k1: float,
        bpm_reading_nominal_mm: float,
        bpm_reading_modulated_mm: float,
        transfer_r12: float,
    ) -> float:
        """Calculate beam offset relative to quad magnetic center using Delta K1 modulation.

        From first-order perturbation theory:
            Delta x_bpm = R_12 * (Delta K1 * L) * (x_beam - x_quad)
        Therefore:
            x_offset = (x_beam - x_quad) = Delta x_bpm / (R_12 * Delta K1)
        """
        if abs(transfer_r12 * delta_k1) < 1e-9:
            raise ValueError("Transfer matrix R12 or Delta K1 too close to zero for stable inversion")

        delta_bpm = bpm_reading_modulated_mm - bpm_reading_nominal_mm
        offset = delta_bpm / (transfer_r12 * delta_k1)
        return float(offset)

    @classmethod
    def fit_bba_modulation_curve(
        cls,
        quad_name: str,
        k1_modulations: np.ndarray,
        bpm_x_measurements: np.ndarray,
        bpm_y_measurements: np.ndarray,
        r12_x: float,
        r12_y: float,
    ) -> BBAQuadResult:
        """Fit linear regression across multiple modulation steps to find quad offset."""
        # Slope d(BPM_x) / d(K1) = r12_x * offset_x
        slope_x, _ = np.polyfit(k1_modulations, bpm_x_measurements, 1)
        slope_y, _ = np.polyfit(k1_modulations, bpm_y_measurements, 1)

        offset_x = slope_x / max(1e-6, abs(r12_x)) * np.sign(r12_x)
        offset_y = slope_y / max(1e-6, abs(r12_y)) * np.sign(r12_y)

        # Residuals
        pred_x = np.polyval(np.polyfit(k1_modulations, bpm_x_measurements, 1), k1_modulations)
        residual = float(np.sqrt(np.mean((bpm_x_measurements - pred_x) ** 2)))

        return BBAQuadResult(
            quad_name=quad_name,
            magnetic_center_offset_x_mm=float(offset_x),
            magnetic_center_offset_y_mm=float(offset_y),
            fit_residual_rms_mm=residual,
            confidence_interval_mm=max(0.01, residual * 1.96),
            recommended_steerer_dx_mm=float(-offset_x),
            recommended_steerer_dy_mm=float(-offset_y),
        )


class DispersionFreeSteeringSolver:
    """Simultaneously minimizes trajectory offsets and spurious dispersion.

    Objective:
        min || R_orbit * Delta_theta + x_0 ||^2 + w^2 * || R_disp * Delta_theta + eta_0 ||^2
    where:
        R_disp = (R(E + Delta E) - R(E)) / (Delta E / E)
    """

    @classmethod
    def solve_dfs(
        cls,
        response_orbit: np.ndarray,
        response_dispersion: np.ndarray,
        current_orbit_mm: np.ndarray,
        current_dispersion_m: np.ndarray,
        steerer_names: list[str],
        dispersion_weight: float = 1.0,
        svd_cutoff: float = 1e-4,
    ) -> DFSResult:
        """Compute steerer kicks via weighted stacked SVD."""
        # Stack stacked linear system:
        # [ R_orbit                  ] * Delta_theta = - [ current_orbit_mm ]
        # [ w * R_disp (scaled to mm)]                   - [ w * current_disp_mm ]
        # Dispersion scaled: 1 m dispersion with 1% dp/p = 10 mm offset
        disp_scale = 1000.0  # m to mm

        r_stacked = np.vstack([
            response_orbit,
            dispersion_weight * response_dispersion * disp_scale,
        ])
        target_stacked = -np.concatenate([
            current_orbit_mm,
            dispersion_weight * current_dispersion_m * disp_scale,
        ])

        # SVD Inversion
        u, s, vt = np.linalg.svd(r_stacked, full_matrices=False)
        inv_s = np.zeros_like(s)
        max_s = np.max(s)
        for i, val in enumerate(s):
            if val / max_s > svd_cutoff:
                inv_s[i] = 1.0 / val

        delta_theta = vt.T @ (inv_s * (u.T @ target_stacked))

        # Project post-correction state
        pred_orbit = current_orbit_mm + response_orbit @ delta_theta
        pred_disp = current_dispersion_m + response_dispersion @ delta_theta

        init_orb_rms = float(np.sqrt(np.mean(current_orbit_mm ** 2)))
        final_orb_rms = float(np.sqrt(np.mean(pred_orbit ** 2)))
        init_disp_rms = float(np.sqrt(np.mean(current_dispersion_m ** 2)))
        final_disp_rms = float(np.sqrt(np.mean(pred_disp ** 2)))

        # Emittance growth approx: Delta eps / eps ~ (Delta eta / beta_x)^2
        emit_growth = max(0.0, float((final_disp_rms / 0.5) ** 2 * 10.0))

        corrections = {name: float(delta_theta[i]) for i, name in enumerate(steerer_names)}

        return DFSResult(
            success=True,
            steerer_corrections=corrections,
            initial_orbit_rms_mm=init_orb_rms,
            final_orbit_rms_mm=final_orb_rms,
            initial_dispersion_rms_m=init_disp_rms,
            final_dispersion_rms_m=final_disp_rms,
            emittance_growth_projected_pct=emit_growth,
        )
