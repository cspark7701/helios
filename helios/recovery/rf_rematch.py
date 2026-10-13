"""HELIOS Autonomous RF Cavity Failure Rematching.

Autonomously recalculates downstream RF cavity amplitudes and synchronous phases
when an SRF cavity trips, preserving beam energy and arrival time without beam interruption.
"""

from dataclasses import dataclass
import logging
import math
from typing import Dict, List, Optional, Tuple
import numpy as np
from scipy.optimize import minimize

logger = logging.getLogger(__name__)


@dataclass
class RFCavityRematchResult:
    """Outcome of local downstream RF cavity rematching."""
    tripped_cavity_id: str
    compensated_cavities: List[str]
    new_setpoints: Dict[str, float]
    energy_recovery_pct: float
    residual_energy_error_mev: float
    synchronous_phase_margin_deg: float
    success: bool
    iterations: int


class RFCavityRematcher:
    """Calculates local rematching setpoints for downstream SRF cavities upon cavity trip."""

    def __init__(
        self,
        max_voltage_boost_factor: float = 1.30,  # Max allowable voltage overdrive on operational cavities
        max_phase_shift_deg: float = 45.0,
        synchronous_phase_limit_deg: float = -15.0, # Minimum negative phase for longitudinal focusing
    ):
        self.max_boost = max_voltage_boost_factor
        self.max_phase_shift = max_phase_shift_deg
        self.synch_phase_limit = synchronous_phase_limit_deg

    def rematch_downstream_cavities(
        self,
        tripped_cavity_id: str,
        downstream_cavities: List[str],
        active_voltages_kv: Dict[str, float],
        active_phases_deg: Dict[str, float],
        nominal_voltage_tripped_kv: float = 800.0,
        nominal_phase_tripped_deg: float = -25.0,
        charge_q: float = 33.0,
    ) -> RFCavityRematchResult:
        """Autonomously recalculate downstream amplitudes and phases to recover lost energy."""
        if not downstream_cavities:
            raise ValueError("No downstream cavities provided for energy rematching.")

        # Target missing energy gain: dW [MeV] = q * V [MV] * cos(phi)
        v_trip_mv = nominal_voltage_tripped_kv * 1e-3
        phi_trip_rad = math.radians(nominal_phase_tripped_deg)
        target_energy_loss_mev = (charge_q * v_trip_mv * math.cos(phi_trip_rad)) / 238.0  # per nucleon approx

        n_down = len(downstream_cavities)
        v0 = np.array([active_voltages_kv.get(cid, 800.0) for cid in downstream_cavities])
        phi0 = np.array([active_phases_deg.get(cid, -20.0) for cid in downstream_cavities])

        # Nominal energy gain of downstream cavities before rematch
        base_gain_mev = sum(
            (charge_q * (v * 1e-3) * math.cos(math.radians(p))) / 238.0
            for v, p in zip(v0, phi0)
        )
        required_total_gain_mev = base_gain_mev + target_energy_loss_mev

        # Normalized decision variables: scale_v = V / V0 in [0.5, max_boost], delta_phi in [-shift, +shift]
        x0 = np.concatenate([np.ones(n_down) * 1.15, np.zeros(n_down)])
        bounds = []
        for _ in range(n_down):
            bounds.append((0.5, self.max_boost))
        for p in phi0:
            max_pos = min(self.synch_phase_limit - p, self.max_phase_shift)
            bounds.append((-self.max_phase_shift, max(0.0, max_pos)))

        def loss_fn(x: np.ndarray) -> float:
            scale_v = x[:n_down]
            d_phi = x[n_down:]
            v_cand = v0 * scale_v
            phi_cand = phi0 + d_phi

            cand_gain = sum(
                (charge_q * (v * 1e-3) * math.cos(math.radians(p))) / 238.0
                for v, p in zip(v_cand, phi_cand)
            )

            energy_diff = 100.0 * ((cand_gain - required_total_gain_mev) ** 2)
            phase_reg = 0.005 * np.sum(d_phi ** 2)
            v_reg = 0.05 * np.sum((scale_v - 1.0) ** 2)
            return float(energy_diff + phase_reg + v_reg)

        res = minimize(loss_fn, x0, method="L-BFGS-B", bounds=bounds, options={"maxiter": 100})

        best_v = v0 * res.x[:n_down]
        best_phi = phi0 + res.x[n_down:]

        achieved_gain = sum(
            (charge_q * (v * 1e-3) * math.cos(math.radians(p))) / 238.0
            for v, p in zip(best_v, best_phi)
        )
        recovered_energy = achieved_gain - base_gain_mev
        recovery_pct = min(100.0, max(0.0, (recovered_energy / max(1e-6, target_energy_loss_mev)) * 100.0))
        residual_err = abs(achieved_gain - required_total_gain_mev)

        new_setpoints: Dict[str, float] = {}
        for cid, v, p in zip(downstream_cavities, best_v, best_phi):
            new_setpoints[f"{cid}:VOLT_SET"] = float(v)
            new_setpoints[f"{cid}:PHASE_SET"] = float(p)

        min_phase_margin = float(min(abs(p - self.synch_phase_limit) for p in best_phi))

        return RFCavityRematchResult(
            tripped_cavity_id=tripped_cavity_id,
            compensated_cavities=downstream_cavities,
            new_setpoints=new_setpoints,
            energy_recovery_pct=recovery_pct,
            residual_energy_error_mev=float(residual_err),
            synchronous_phase_margin_deg=min_phase_margin,
            success=bool(recovery_pct >= 90.0),
            iterations=int(res.nit),
        )
