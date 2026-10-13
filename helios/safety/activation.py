"""HELIOS Phase 49: Residual Radiological Activation, Decay Cooling & Personnel Safety.

Models nuclear spallation and fragmentation residual isotope inventory along linac beam pipes
and collimators, calculates multi-isotope Bateman decay cooling curves, and enforces
mandatory cool-down waiting time interlocks with cryptographic clearance tokens for tunnel access.
"""

from typing import Dict, List, Any, Optional
import math
import time
import hashlib
import json
import numpy as np
from pydantic import BaseModel, Field


class IsotopeDecayInfo(BaseModel):
    """Radioisotope decay constant and initial dose rate contribution."""
    isotope: str
    half_life_days: float
    gamma_energy_MeV: float
    initial_dose_rate_uSv_hr: float
    decay_constant_per_hour: float = 0.0


class RadiologicalCoolingAssessment(BaseModel):
    """Radiological hazard assessment and tunnel access cool-down requirements."""
    location_id: str
    prompt_dose_rate_uSv_hr: float
    current_residual_dose_rate_uSv_hr: float
    cool_down_elapsed_hours: float
    tunnel_access_threshold_uSv_hr: float = 25.0
    access_granted: bool
    required_additional_cooling_hours: float
    dominant_isotopes: Dict[str, float]
    clearance_token_sha256: Optional[str] = None


class RadiologicalActivationEngine:
    """Calculates residual linac activation and enforces personnel radiation protection interlocks."""

    # Standard activation isotopes in stainless steel / copper heavy-ion structures
    CANONICAL_ISOTOPES = [
        {"name": "Mn-56", "half_life_days": 0.107, "gamma_MeV": 0.85, "initial_pct": 55.0}, # 2.58 hr
        {"name": "Co-58", "half_life_days": 70.86, "gamma_MeV": 0.81, "initial_pct": 20.0},
        {"name": "Mn-54", "half_life_days": 312.2, "gamma_MeV": 0.84, "initial_pct": 15.0},
        {"name": "Co-60", "half_life_days": 1925.0, "gamma_MeV": 1.25, "initial_pct": 10.0},
    ]

    def __init__(self, personnel_access_threshold_uSv_hr: float = 25.0):
        self.access_threshold = personnel_access_threshold_uSv_hr

    def evaluate_cooling(
        self,
        location_id: str,
        beam_loss_power_W: float,
        irradiation_hours: float = 120.0,
        cooling_elapsed_hours: float = 4.0
    ) -> RadiologicalCoolingAssessment:
        """Calculate Bateman decay cooling curve and access authorization."""
        # Initial prompt residual dose rate 1 minute after beam off:
        # Rule of thumb for heavy-ion linac: ~15-25 uSv/hr per Watt of beam loss at 1m
        initial_dose_rate_uSv_hr = beam_loss_power_W * 18.5 * min(1.0, irradiation_hours / 24.0)

        isotopes: List[IsotopeDecayInfo] = []
        for iso in self.CANONICAL_ISOTOPES:
            t_half_hr = iso["half_life_days"] * 24.0
            lam_hr = math.log(2.0) / t_half_hr
            init_dose = initial_dose_rate_uSv_hr * (iso["initial_pct"] / 100.0)
            isotopes.append(IsotopeDecayInfo(
                isotope=iso["name"],
                half_life_days=iso["half_life_days"],
                gamma_energy_MeV=iso["gamma_MeV"],
                initial_dose_rate_uSv_hr=round(init_dose, 3),
                decay_constant_per_hour=lam_hr
            ))

        # Current dose rate after cooling_elapsed_hours
        current_dose = 0.0
        active_fractions = {}
        for iso in isotopes:
            dose_iso = iso.initial_dose_rate_uSv_hr * math.exp(-iso.decay_constant_per_hour * cooling_elapsed_hours)
            current_dose += dose_iso
            active_fractions[iso.isotope] = round(dose_iso, 3)

        current_dose = round(current_dose, 2)
        access_granted = current_dose <= self.access_threshold

        # If not safe, solve required cooling time numerically
        req_additional_hr = 0.0
        if not access_granted:
            for t_extra in np.arange(0.5, 720.0, 0.5):
                t_tot = cooling_elapsed_hours + t_extra
                d_test = sum(
                    iso.initial_dose_rate_uSv_hr * math.exp(-iso.decay_constant_per_hour * t_tot)
                    for iso in isotopes
                )
                if d_test <= self.access_threshold:
                    req_additional_hr = round(float(t_extra), 1)
                    break
            else:
                req_additional_hr = 720.0

        # Cryptographic clearance token if access granted
        token = None
        if access_granted:
            raw_cert = f"RPO-CLEARANCE:{location_id}:{current_dose}:{time.time()}"
            token = hashlib.sha256(raw_cert.encode()).hexdigest()

        return RadiologicalCoolingAssessment(
            location_id=location_id,
            prompt_dose_rate_uSv_hr=round(initial_dose_rate_uSv_hr, 2),
            current_residual_dose_rate_uSv_hr=current_dose,
            cool_down_elapsed_hours=cooling_elapsed_hours,
            tunnel_access_threshold_uSv_hr=self.access_threshold,
            access_granted=access_granted,
            required_additional_cooling_hours=req_additional_hr,
            dominant_isotopes=active_fractions,
            clearance_token_sha256=token
        )
