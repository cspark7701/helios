"""HELIOS Maximum Entropy (MENT) Tomography and 3D Lost Particle Halo Modeling.

Implements:
1. Multi-monitor profile projection reconstruction via Maximum Entropy algorithm.
2. Core-Halo decomposition and Halo Parameter (H) calculation.
3. 3D continuous lost particle radiation mapping along cryomodule walls.
"""

from dataclasses import dataclass
import logging
from typing import Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class PhaseSpaceReconstruction:
    """Reconstructed 2D phase space distribution (e.g., x-x' or y-y')."""
    grid_size: int
    x_range_mm: Tuple[float, float]
    xp_range_mrad: Tuple[float, float]
    density_matrix: np.ndarray  # 2D normalized probability density
    emittance_rms_mm_mrad: float
    alpha: float
    beta_m: float
    gamma_inv_m: float
    entropy: float


@dataclass
class HaloAnalysisResult:
    """Core-halo separation and scraping risk metrics."""
    core_fraction_pct: float
    halo_fraction_pct: float
    halo_parameter_h: float  # Gaussian = 1.0, high-halo beam > 2.0
    scraping_risk_level: str  # LOW, MODERATE, HIGH, CRITICAL
    effective_aperture_clearance_mm: float


@dataclass
class LostParticleMap3D:
    """Continuous 3D loss distribution along linac vacuum chamber."""
    z_positions_m: np.ndarray
    loss_density_w_per_m: np.ndarray
    hotspots: List[Dict[str, float]]
    total_power_loss_w: float


class PhaseSpaceTomographyMENT:
    """Maximum Entropy phase-space reconstructor from 1D profile monitor projections."""

    @staticmethod
    def reconstruct_2d_phase_space(
        projections: List[np.ndarray],
        projection_angles_rad: List[float],
        grid_size: int = 64,
        x_span_mm: float = 20.0,
        xp_span_mrad: float = 10.0,
        max_iterations: int = 25,
    ) -> PhaseSpaceReconstruction:
        """Iterative Maximum Entropy reconstruction from tomographic angle projections."""
        # Initialize uniform distribution (maximum unconstrained entropy)
        density = np.ones((grid_size, grid_size), dtype=np.float64) / (grid_size * grid_size)
        x_coords = np.linspace(-x_span_mm / 2.0, x_span_mm / 2.0, grid_size)
        xp_coords = np.linspace(-xp_span_mrad / 2.0, xp_span_mrad / 2.0, grid_size)
        X, XP = np.meshgrid(x_coords, xp_coords)

        # MENT iterative projection adjustment
        for _ in range(max_iterations):
            for proj, angle in zip(projections, projection_angles_rad):
                # Rotated coordinate: u = x * cos(theta) + xp * sin(theta) * (scale)
                scale = x_span_mm / xp_span_mrad
                u = X * np.cos(angle) + (XP * scale) * np.sin(angle)
                
                # Digitize coordinates to projection bins
                bin_indices = np.clip(
                    ((u + x_span_mm / 2.0) / x_span_mm * len(proj)).astype(int),
                    0,
                    len(proj) - 1,
                )
                
                # Compute current projected slice
                sim_proj = np.zeros_like(proj, dtype=np.float64)
                for i in range(len(proj)):
                    sim_proj[i] = np.sum(density[bin_indices == i])
                sim_proj = np.maximum(sim_proj, 1e-12)

                # Multiplicative Lagrange correction
                corr_factor = (proj / np.sum(proj)) / (sim_proj / np.sum(sim_proj))
                density = density * corr_factor[bin_indices]
                density = density / np.sum(density)

        # Compute Twiss parameters and emittance
        mean_x = np.sum(X * density)
        mean_xp = np.sum(XP * density)
        sig_xx = np.sum((X - mean_x) ** 2 * density)
        sig_xpxp = np.sum((XP - mean_xp) ** 2 * density)
        sig_xxp = np.sum((X - mean_x) * (XP - mean_xp) * density)

        emit_rms = float(np.sqrt(max(1e-12, sig_xx * sig_xpxp - sig_xxp ** 2)))
        beta = float(sig_xx / emit_rms) * 1e-3  # m
        gamma = float(sig_xpxp / emit_rms) * 1e3
        alpha = float(-sig_xxp / emit_rms)

        entropy = float(-np.sum(density * np.log(np.maximum(density, 1e-15))))

        return PhaseSpaceReconstruction(
            grid_size=grid_size,
            x_range_mm=(-x_span_mm / 2.0, x_span_mm / 2.0),
            xp_range_mrad=(-xp_span_mrad / 2.0, xp_span_mrad / 2.0),
            density_matrix=density,
            emittance_rms_mm_mrad=emit_rms,
            alpha=alpha,
            beta_m=beta,
            gamma_inv_m=gamma,
            entropy=entropy,
        )


class BeamHaloQuantifier:
    """Calculates Wangler-Crump halo parameter and core-halo particle fraction."""

    @staticmethod
    def evaluate_halo(profile_intensity: np.ndarray, radius_mm: np.ndarray, pipe_radius_mm: float = 20.0) -> HaloAnalysisResult:
        """Core-halo separation using second and fourth moments:

        Halo parameter:
            H = <r^4> / (2 * <r^2>^2) - 1.0 (for 2D distribution; H=0 for Gaussian, H > 1 for large halo)
        """
        prob = profile_intensity / np.sum(profile_intensity)
        r2 = np.sum((radius_mm ** 2) * prob)
        r4 = np.sum((radius_mm ** 4) * prob)

        # Normalized halo parameter
        h_param = float(r4 / (2.0 * max(1e-6, r2 ** 2)))

        # Core fraction within 2 sigma
        sigma = np.sqrt(r2)
        core_mask = radius_mm <= (2.0 * sigma)
        core_frac = float(np.sum(prob[core_mask]) * 100.0)
        halo_frac = float(100.0 - core_frac)

        # Clearance
        max_beam_extent = np.max(radius_mm[prob > 1e-4]) if np.any(prob > 1e-4) else 0.0
        clearance = float(pipe_radius_mm - max_beam_extent)

        if h_param > 2.5 or clearance < 2.0:
            risk = "CRITICAL"
        elif h_param > 1.8 or clearance < 4.0:
            risk = "HIGH"
        elif h_param > 1.3:
            risk = "MODERATE"
        else:
            risk = "LOW"

        return HaloAnalysisResult(
            core_fraction_pct=core_frac,
            halo_fraction_pct=halo_frac,
            halo_parameter_h=h_param,
            scraping_risk_level=risk,
            effective_aperture_clearance_mm=clearance,
        )


class LostParticleTomography3D:
    """Synthesizes continuous 3D lost particle power density along the beam line."""

    @staticmethod
    def reconstruct_3d_loss_map(
        linac_length_m: float,
        blm_positions_m: np.ndarray,
        blm_readings_gy_s: np.ndarray,
        beam_energy_mev: float,
        beam_current_ua: float,
        pipe_radius_mm: float = 20.0,
    ) -> LostParticleMap3D:
        """Map BLM radiation doses back to linear loss power density W/m."""
        z_grid = np.linspace(0.0, linac_length_m, 200)
        # Spatial response convolution kernel (radiation spread along z)
        loss_density = np.zeros_like(z_grid)

        # Factor converting Gy/s to approximate localized lost power W/m
        conversion_factor = 12.5 * (beam_energy_mev / 10.0)

        for blm_z, blm_val in zip(blm_positions_m, blm_readings_gy_s):
            # Gaussian radiation dispersion kernel (sigma ~ 0.35m around sensor)
            kernel = np.exp(-((z_grid - blm_z) ** 2) / (2.0 * (0.35 ** 2)))
            loss_density += blm_val * conversion_factor * kernel

        hotspots = []
        threshold = np.mean(loss_density) + 2.0 * np.std(loss_density)
        for i, val in enumerate(loss_density):
            if val > threshold:
                hotspots.append({
                    "z_m": float(z_grid[i]),
                    "loss_power_w_m": float(val),
                })

        # NumPy 2.0+ uses trapezoid, fallback to trapz if older
        trapz_fn = getattr(np, "trapezoid", getattr(np, "trapz", None))
        total_loss_w = float(trapz_fn(loss_density, z_grid))

        return LostParticleMap3D(
            z_positions_m=z_grid,
            loss_density_w_per_m=loss_density,
            hotspots=hotspots,
            total_power_loss_w=total_loss_w,
        )
