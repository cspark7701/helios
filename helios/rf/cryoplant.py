"""HELIOS Phase 42: SRF Cryogenic Plant Thermodynamic Heat Load Balancing.

Models superconducting RF cavity surface resistance (BCS and residual resistance),
dynamic thermal dissipation at 2.0 K sub-atmospheric bath and 4.5 K / 50 K shields,
and coordinates cavity gradient setpoints against central cryoplant refrigeration capacity.
"""

from typing import Dict, List, Any, Optional
import math
from pydantic import BaseModel, Field


class CavityCryoState(BaseModel):
    """Thermal and electromagnetic state for an individual SRF cavity."""
    cavity_id: str
    cavity_type: str  # QWR, HWR, SPOKE, ELLIPTICAL
    frequency_MHz: float
    temperature_K: float
    voltage_MV: float
    R_over_Q_ohm: float
    geometry_factor_G: float
    residual_resistance_nOhm: float = 8.0
    static_heat_load_W: float = 2.5
    dynamic_heat_load_W: float = 0.0
    total_heat_load_W: float = 0.0
    q0_quality_factor: float = 0.0


class CryoplantCapacity(BaseModel):
    """Central cryogenic plant cooling capacity and operational limits."""
    stage_2K_max_power_W: float = Field(default=850.0, description="Available 2.0 K sub-atmospheric cooling capacity in W")
    stage_4K_max_power_W: float = Field(default=3500.0, description="Available 4.5 K thermal interception capacity in W")
    stage_50K_max_power_W: float = Field(default=15000.0, description="Available 50 K thermal shield capacity in W")
    surge_margin_percent: float = Field(default=15.0, description="Minimum reserve cooling margin to prevent compressor trips")


class CryoBalancingResult(BaseModel):
    """Outcome of cryoplant heat load optimization."""
    total_2K_heat_load_W: float
    available_2K_capacity_W: float
    cooling_margin_percent: float
    status: str  # NOMINAL, CONSTRAINED, SURGE_RISK
    adjusted_voltages_MV: Dict[str, float]
    total_linac_voltage_MV: float


class CryoplantThermodynamicOptimizer:
    """Calculates SRF thermal dissipation and balances cavity gradients."""

    # Superconducting Niobium constants
    DELTA_OVER_KB = 17.67  # 1.76 * Tc for Nb (Tc = 9.25 K)

    @classmethod
    def calculate_surface_resistance(
        cls,
        frequency_MHz: float,
        temperature_K: float,
        residual_nOhm: float = 8.0
    ) -> float:
        """Calculate total surface resistance Rs = R_BCS + R_res in Ohms."""
        # Semi-empirical BCS resistance formula for Niobium:
        # R_BCS (Ohm) ~ 2e-4 * (f / 1.5 GHz)^2 * (1 / T) * exp(-17.67 / T)
        f_GHz = frequency_MHz / 1000.0
        r_bcs = 2.0e-4 * (f_GHz ** 2) * (1.0 / temperature_K) * math.exp(-cls.DELTA_OVER_KB / temperature_K)
        r_res = residual_nOhm * 1e-9
        return r_bcs + r_res

    def evaluate_cavity_thermal(
        self,
        cavity: CavityCryoState,
        voltage_MV: Optional[float] = None
    ) -> CavityCryoState:
        """Evaluate Q0 and heat load for given cavity and voltage setpoint."""
        v_mv = voltage_MV if voltage_MV is not None else cavity.voltage_MV
        v_volts = v_mv * 1e6

        r_s = self.calculate_surface_resistance(
            frequency_MHz=cavity.frequency_MHz,
            temperature_K=cavity.temperature_K,
            residual_nOhm=cavity.residual_resistance_nOhm
        )

        q0 = cavity.geometry_factor_G / max(1e-12, r_s)

        # Dynamic heat dissipation P_loss = V^2 / ((R/Q) * Q0)
        p_dyn = (v_volts ** 2) / (cavity.R_over_Q_ohm * q0)
        p_tot = cavity.static_heat_load_W + p_dyn

        updated = cavity.model_copy()
        updated.voltage_MV = round(v_mv, 3)
        updated.dynamic_heat_load_W = round(p_dyn, 2)
        updated.total_heat_load_W = round(p_tot, 2)
        updated.q0_quality_factor = round(q0, 0)
        return updated

    def balance_linac_heat_load(
        self,
        cavities: List[CavityCryoState],
        target_total_voltage_MV: float,
        cryoplant: CryoplantCapacity
    ) -> CryoBalancingResult:
        """Balance cavity accelerating voltages to meet voltage target while respecting 2K cryo limits."""
        # Safe limit respecting margin
        safe_2k_limit = cryoplant.stage_2K_max_power_W * (1.0 - cryoplant.surge_margin_percent / 100.0)

        # Initial uniform distribution
        n_cavs = len(cavities)
        v_per_cav = target_total_voltage_MV / n_cavs

        evaluated_cavs = [self.evaluate_cavity_thermal(c, voltage_MV=v_per_cav) for c in cavities]
        tot_2k = sum(c.total_heat_load_W for c in evaluated_cavs)

        adjusted_voltages: Dict[str, float] = {}

        if tot_2k <= safe_2k_limit:
            adjusted_voltages = {c.cavity_id: c.voltage_MV for c in evaluated_cavs}
            status = "NOMINAL"
        else:
            # Over cryo budget: redistribute gradients weighted by cavity Q0
            # Higher Q0 cavities take slightly more gradient since P_dyn ~ 1/Q0
            q0_weights = [math.sqrt(c.q0_quality_factor) for c in evaluated_cavs]
            weight_sum = sum(q0_weights)

            # Scale down total voltage if needed or re-allocate
            scale_factor = math.sqrt(safe_2k_limit / max(1.0, tot_2k))
            adjusted_total_V = target_total_voltage_MV * min(1.0, scale_factor)

            for c, w in zip(cavities, q0_weights):
                v_opt = (w / weight_sum) * adjusted_total_V
                adjusted_voltages[c.cavity_id] = round(v_opt, 3)

            evaluated_cavs = [self.evaluate_cavity_thermal(c, voltage_MV=adjusted_voltages[c.cavity_id]) for c in cavities]
            tot_2k = sum(c.total_heat_load_W for c in evaluated_cavs)
            status = "CONSTRAINED" if tot_2k <= cryoplant.stage_2K_max_power_W else "SURGE_RISK"

        margin = ((cryoplant.stage_2K_max_power_W - tot_2k) / cryoplant.stage_2K_max_power_W) * 100.0
        tot_v = sum(adjusted_voltages.values())

        return CryoBalancingResult(
            total_2K_heat_load_W=round(tot_2k, 2),
            available_2K_capacity_W=round(cryoplant.stage_2K_max_power_W, 2),
            cooling_margin_percent=round(margin, 2),
            status=status,
            adjusted_voltages_MV=adjusted_voltages,
            total_linac_voltage_MV=round(tot_v, 2)
        )
