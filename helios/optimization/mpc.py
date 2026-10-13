"""HELIOS Neural Model-Predictive Control (MPC) Engine.

Optimizes receding-horizon actuator trajectories using fast neural surrogate models
to compensate for slow thermal drift, cryogenic pressure variations, and 60 Hz mains jitter.
"""

from dataclasses import dataclass
import logging
from typing import Dict, List, Optional, Tuple
import numpy as np
from scipy.optimize import minimize

from helios.models.surrogate import NeuralLinacSurrogate

logger = logging.getLogger(__name__)


@dataclass
class MPCStepResult:
    """Outcome of receding-horizon MPC optimization step."""
    optimal_action: Dict[str, float]
    predicted_horizon_cost: float
    predicted_rms_error_mm: float
    iterations: int
    horizon_steps: int


class NeuralMPCController:
    """Model-Predictive Controller utilizing neural surrogates for multi-step receding horizon planning."""

    def __init__(
        self,
        surrogate: Optional[NeuralLinacSurrogate] = None,
        actuator_keys: Optional[List[str]] = None,
        horizon_steps: int = 4,
        weight_tracking: float = 1.0,
        weight_actuation: float = 0.05,
        weight_slew: float = 0.10,
    ):
        self.surrogate = surrogate or NeuralLinacSurrogate()
        self.actuator_keys = actuator_keys or [
            "MEBT:DCH:01:I_SET",
            "MEBT:DCV:01:I_SET",
            "MEBT:DCH:02:I_SET",
            "MEBT:DCV:02:I_SET",
        ]
        self.horizon_steps = horizon_steps
        self.w_track = weight_tracking
        self.w_act = weight_actuation
        self.w_slew = weight_slew
        self.num_actuators = len(self.actuator_keys)

    def optimize_action(
        self,
        current_setpoints: Dict[str, float],
        target_orbit_mm: Optional[Dict[str, float]] = None,
        estimated_drift_rate_mm_per_step: float = 0.0,
    ) -> MPCStepResult:
        """Calculate optimal next actuator setpoint adjustment using receding horizon."""
        base_u = np.array([current_setpoints.get(k, 0.0) for k in self.actuator_keys])
        u_dim = self.num_actuators
        H = self.horizon_steps

        # Flattened decision variable: H * u_dim
        # Initial guess: repeat current setpoint
        x0 = np.tile(base_u, H)

        # Bounds: setpoints constrained within [-5.0, 5.0] Amperes
        bounds = [(-5.0, 5.0) for _ in range(H * u_dim)]

        def cost_fn(u_flat: np.ndarray) -> float:
            u_matrix = u_flat.reshape(H, u_dim)
            total_cost = 0.0
            prev_u = base_u

            for t in range(H):
                u_t = u_matrix[t]
                # Apply setpoints to test dict
                step_setpoints = dict(current_setpoints)
                for k, val in zip(self.actuator_keys, u_t):
                    step_setpoints[k] = float(val)

                # Predict orbit with surrogate
                pred = self.surrogate.predict(step_setpoints)
                # Model drift along horizon
                drift_offset = estimated_drift_rate_mm_per_step * (t + 1)
                predicted_orbit = np.array(pred.centroid_x_mm[:4]) + drift_offset

                # Cost terms:
                # 1. Orbit tracking error
                tracking_cost = self.w_track * np.sum(predicted_orbit ** 2)
                # 2. Control effort penalty
                effort_cost = self.w_act * np.sum(u_t ** 2)
                # 3. Slew / rate-of-change penalty
                slew_cost = self.w_slew * np.sum((u_t - prev_u) ** 2)

                total_cost += tracking_cost + effort_cost + slew_cost
                prev_u = u_t

            return float(total_cost)

        res = minimize(cost_fn, x0, method="SLSQP", bounds=bounds, options={"maxiter": 30, "ftol": 1e-4})

        optimal_plan = res.x.reshape(H, u_dim)
        first_step_u = optimal_plan[0]

        best_action = {k: float(val) for k, val in zip(self.actuator_keys, first_step_u)}

        # Evaluate predicted first-step RMS
        eval_setpoints = dict(current_setpoints, **best_action)
        first_pred = self.surrogate.predict(eval_setpoints)
        pred_rms = float(np.sqrt(np.mean(np.array(first_pred.centroid_x_mm[:4]) ** 2)))

        return MPCStepResult(
            optimal_action=best_action,
            predicted_horizon_cost=float(res.fun),
            predicted_rms_error_mm=pred_rms,
            iterations=int(res.nit),
            horizon_steps=H,
        )
