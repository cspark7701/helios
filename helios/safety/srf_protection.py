"""HELIOS Superconducting RF (SRF) Quench and Thermal Protection Guardrails.

Enforces cryogenic bath temperature constraints, liquid helium inventory levels,
cavity accelerating gradient quench limits, reflected RF power ratio trips,
and multipacting resonance barrier avoidance.
"""

import logging
from dataclasses import dataclass, field

from helios.core.schemas import ValidationCheck, ValidationResult

logger = logging.getLogger(__name__)


@dataclass
class SRFCavityLimits:
    """Operating boundaries for a superconducting radiofrequency (SRF) cavity."""
    cavity_id: str
    max_gradient_mv_m: float = 16.5        # Quench gradient limit
    warn_gradient_mv_m: float = 15.0       # Administrative warning threshold
    max_cryo_temp_k: float = 2.10          # Sub-atmospheric 2K helium bath limit
    min_helium_level_pct: float = 75.0     # Minimum liquid helium inventory
    max_reflected_power_ratio: float = 0.20 # Max Pref / Pfwd before trip
    multipacting_zones: list[tuple[float, float]] = field(
        default_factory=lambda: [(1.5, 2.2), (3.8, 4.4)]
    )  # Forbidden gradient bands where resonant electron emission causes arcing


class SRFProtectionMonitor:
    """Validates cavity setpoints and evaluates live cryogenic health telemetry."""

    def __init__(self, cavity_limits: dict[str, SRFCavityLimits] | None = None):
        if cavity_limits is not None:
            self.limits = cavity_limits
        else:
            try:
                from helios.core.facility_config import FacilityConfig
                cfg = FacilityConfig.load_default("MEBT")
                default_limits = {
                    f"{cfg.section}:CAV:01": SRFCavityLimits(cavity_id=f"{cfg.section}:CAV:01", max_gradient_mv_m=12.0),
                    f"{cfg.section}:CAV:02": SRFCavityLimits(cavity_id=f"{cfg.section}:CAV:02", max_gradient_mv_m=12.0),
                    "SCL:CAV:01": SRFCavityLimits(cavity_id="SCL:CAV:01", max_gradient_mv_m=18.0),
                }
                self.limits = default_limits
            except Exception:
                self.limits = {
                    "MEBT:CAV:01": SRFCavityLimits(cavity_id="MEBT:CAV:01", max_gradient_mv_m=12.0),
                    "MEBT:CAV:02": SRFCavityLimits(cavity_id="MEBT:CAV:02", max_gradient_mv_m=12.0),
                    "SCL:CAV:01": SRFCavityLimits(cavity_id="SCL:CAV:01", max_gradient_mv_m=18.0),
                }

    def register_cavity_limits(self, limits: SRFCavityLimits) -> None:
        """Register or update limits for a specific SRF cavity."""
        self.limits[limits.cavity_id] = limits

    def validate_srf_state(
        self,
        cavity_id: str,
        gradient_mv_m: float,
        cryo_temp_k: float = 2.05,
        helium_level_pct: float = 90.0,
        p_fwd_kw: float = 5.0,
        p_refl_kw: float = 0.2,
    ) -> ValidationResult:
        """Evaluate candidate cavity setpoint and live cryo telemetry against quench thresholds."""
        lim = self.limits.get(cavity_id, SRFCavityLimits(cavity_id=cavity_id))
        checks: list[ValidationCheck] = []
        errors: list[str] = []
        warnings: list[str] = []

        # 1. Accelerating Gradient Quench Check
        gradient_safe = gradient_mv_m <= lim.max_gradient_mv_m
        checks.append(ValidationCheck(
            check_name=f"{cavity_id} Gradient Quench Limit",
            passed=gradient_safe,
            measured_value=gradient_mv_m,
            limit_value=lim.max_gradient_mv_m,
            message=f"{gradient_mv_m:.2f} MV/m <= {lim.max_gradient_mv_m:.2f} MV/m",
        ))
        if not gradient_safe:
            errors.append(
                f"{cavity_id}: Gradient {gradient_mv_m:.2f} MV/m exceeds quench threshold {lim.max_gradient_mv_m:.2f} MV/m"
            )
        elif gradient_mv_m > lim.warn_gradient_mv_m:
            warnings.append(
                f"{cavity_id}: Gradient {gradient_mv_m:.2f} MV/m approaches quench limit ({lim.max_gradient_mv_m:.2f} MV/m)"
            )

        # 2. Multipacting Barrier Avoidance
        in_mp_band = any(low <= gradient_mv_m <= high for low, high in lim.multipacting_zones)
        checks.append(ValidationCheck(
            check_name=f"{cavity_id} Multipacting Avoidance",
            passed=not in_mp_band,
            measured_value=gradient_mv_m,
            limit_value=0.0,
            message="Outside multipacting zones" if not in_mp_band else "INSIDE MULTIPACTING ZONE",
        ))
        if in_mp_band:
            errors.append(
                f"{cavity_id}: Gradient {gradient_mv_m:.2f} MV/m resides within resonant multipacting zone {lim.multipacting_zones}"
            )

        # 3. Cryogenic Helium Bath Temperature
        temp_safe = cryo_temp_k <= lim.max_cryo_temp_k
        checks.append(ValidationCheck(
            check_name=f"{cavity_id} Cryogenic Temp (He-II Bath)",
            passed=temp_safe,
            measured_value=cryo_temp_k,
            limit_value=lim.max_cryo_temp_k,
            message=f"{cryo_temp_k:.3f} K <= {lim.max_cryo_temp_k:.3f} K",
        ))
        if not temp_safe:
            errors.append(
                f"{cavity_id}: Cryogenic bath temperature {cryo_temp_k:.3f} K exceeds superfluid limit {lim.max_cryo_temp_k:.3f} K"
            )

        # 4. Liquid Helium Inventory Level
        he_level_safe = helium_level_pct >= lim.min_helium_level_pct
        checks.append(ValidationCheck(
            check_name=f"{cavity_id} Liquid Helium Level",
            passed=he_level_safe,
            measured_value=helium_level_pct,
            limit_value=lim.min_helium_level_pct,
            message=f"{helium_level_pct:.1f}% >= {lim.min_helium_level_pct:.1f}%",
        ))
        if not he_level_safe:
            errors.append(
                f"{cavity_id}: Liquid helium level {helium_level_pct:.1f}% is below minimum safe level {lim.min_helium_level_pct:.1f}%"
            )

        # 5. RF Reflected Power Ratio Check
        refl_ratio = (p_refl_kw / p_fwd_kw) if p_fwd_kw > 0.05 else 0.0
        refl_safe = refl_ratio <= lim.max_reflected_power_ratio
        checks.append(ValidationCheck(
            check_name=f"{cavity_id} Reflected Power Ratio",
            passed=refl_safe,
            measured_value=refl_ratio,
            limit_value=lim.max_reflected_power_ratio,
            message=f"Pref/Pfwd = {refl_ratio:.3f} <= {lim.max_reflected_power_ratio:.3f}",
        ))
        if not refl_safe:
            errors.append(
                f"{cavity_id}: Reflected power ratio {refl_ratio:.3f} exceeds threshold {lim.max_reflected_power_ratio:.3f} (arcing/detuning risk)"
            )

        overall_valid = len(errors) == 0

        return ValidationResult(
            is_valid=overall_valid,
            validator_agent="HELIOS-Safety",
            checks=checks,
            errors=errors,
            warnings=warnings,
        )
