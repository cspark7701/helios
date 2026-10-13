"""HELIOS Phase 47: Space-Charge Equipartitioning & Hofmann Stability Charts.

Evaluates transverse-longitudinal kinetic energy anisotropy (T_perp / T_parallel)
in high-intensity heavy-ion linacs, maps phase advances onto Hofmann stability charts,
and autonomously rematches lattice parameters away from emittance-exchange stopbands.
"""

from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
import math
import numpy as np
from pydantic import BaseModel, Field


class HofmannResonanceType(str, Enum):
    NONE = "none"
    SECOND_ORDER_DIFFERENCE = "2sigma_t_minus_sigma_l"  # 2*sigma_t - sigma_l = 0
    FOURTH_ORDER_STRUCTURE = "sigma_t_minus_sigma_l"   # sigma_t = sigma_l
    HIGH_ORDER_MULTIPOLE = "3sigma_t_minus_sigma_l"


class LinacPhaseAdvance(BaseModel):
    """Zero-current and space-charge depressed phase advances per lattice period."""
    section_id: str
    sigma_0t_deg: float = Field(..., ge=10.0, le=120.0, description="Zero-current transverse phase advance in deg")
    sigma_0l_deg: float = Field(..., ge=10.0, le=120.0, description="Zero-current longitudinal phase advance in deg")
    sigma_t_deg: float = Field(..., ge=5.0, description="Space-charge depressed transverse phase advance in deg")
    sigma_l_deg: float = Field(..., ge=5.0, description="Space-charge depressed longitudinal phase advance in deg")
    emit_norm_t_mm_mrad: float
    emit_norm_l_deg_MeV: float


class HofmannStabilityResult(BaseModel):
    """Hofmann chart stability evaluation and emittance exchange risk."""
    section_id: str
    tune_depression_t: float  # sigma_t / sigma_0t
    tune_depression_l: float  # sigma_l / sigma_0l
    anisotropy_ratio: float   # T_perp / T_parallel
    is_equipartitioned: bool
    active_resonance: HofmannResonanceType
    distance_to_nearest_stopband_deg: float
    stability_status: str  # STABLE, MARGINAL, UNSTABLE_EMITTANCE_EXCHANGE
    recommended_sigma_t_deg: float
    recommended_sigma_l_deg: float


class HofmannEquipartitionEngine:
    """Analyzes space-charge anisotropy and calculates resonance-free lattice rematching."""

    def evaluate_stability(self, params: LinacPhaseAdvance) -> HofmannStabilityResult:
        """Map phase advances onto Hofmann stability chart."""
        eta_t = params.sigma_t_deg / params.sigma_0t_deg
        eta_l = params.sigma_l_deg / params.sigma_0l_deg

        # Kinetic temperature ratio T_perp / T_parallel:
        # T_perp / T_parallel ~ (emit_t * sigma_t) / (emit_l * sigma_l)
        # Normalized approximation
        emit_ratio = max(0.01, params.emit_norm_t_mm_mrad / max(1e-4, params.emit_norm_l_deg_MeV * 0.1))
        t_ratio = emit_ratio * (params.sigma_t_deg / params.sigma_l_deg)

        is_eq = abs(t_ratio - 1.0) < 0.15

        # Hofmann resonance conditions:
        # 1. 2*sigma_t - sigma_l ~ 0 (with resonance stopband width ~ 8 deg if tune depressed < 0.7)
        diff_2t_l = abs(2.0 * params.sigma_t_deg - params.sigma_l_deg)
        # 2. sigma_t - sigma_l ~ 0
        diff_t_l = abs(params.sigma_t_deg - params.sigma_l_deg)
        # 3. 3*sigma_t - params.sigma_l
        diff_3t_l = abs(3.0 * params.sigma_t_deg - params.sigma_l_deg)

        res_type = HofmannResonanceType.NONE
        dist_min = min(diff_2t_l, diff_t_l, diff_3t_l)

        # Stopband width grows with space-charge depression (1 - eta_t)
        stopband_width = 8.0 * (1.0 - min(eta_t, eta_l)) + 3.0

        if diff_2t_l < stopband_width:
            res_type = HofmannResonanceType.SECOND_ORDER_DIFFERENCE
        elif diff_t_l < stopband_width * 0.8:
            res_type = HofmannResonanceType.FOURTH_ORDER_STRUCTURE
        elif diff_3t_l < stopband_width * 0.5:
            res_type = HofmannResonanceType.HIGH_ORDER_MULTIPOLE

        if res_type != HofmannResonanceType.NONE:
            status = "UNSTABLE_EMITTANCE_EXCHANGE"
        elif dist_min < stopband_width * 1.5:
            status = "MARGINAL"
        else:
            status = "STABLE"

        # Rematching recommendation: shift sigma_t away from stopband
        if res_type == HofmannResonanceType.SECOND_ORDER_DIFFERENCE:
            # Shift sigma_t higher to satisfy 2*sigma_t > sigma_l + 12 deg
            target_st = (params.sigma_l_deg + 15.0) / 2.0
            target_sl = params.sigma_l_deg
        elif res_type == HofmannResonanceType.FOURTH_ORDER_STRUCTURE:
            target_st = params.sigma_t_deg + 12.0
            target_sl = params.sigma_l_deg
        else:
            target_st = params.sigma_t_deg
            target_sl = params.sigma_l_deg

        return HofmannStabilityResult(
            section_id=params.section_id,
            tune_depression_t=round(float(eta_t), 3),
            tune_depression_l=round(float(eta_l), 3),
            anisotropy_ratio=round(float(t_ratio), 3),
            is_equipartitioned=is_eq,
            active_resonance=res_type,
            distance_to_nearest_stopband_deg=round(float(dist_min), 2),
            stability_status=status,
            recommended_sigma_t_deg=round(float(target_st), 2),
            recommended_sigma_l_deg=round(float(target_sl), 2)
        )
