"""Differentiable Neural Model Predictive Control (MPC) engine using FacilityTwin."""

import logging
from collections.abc import Mapping
from typing import Any

try:
    import torch
except ImportError as e:
    from helios._optional import OptionalDependencyError
    raise OptionalDependencyError("torch", extra="ml", feature="TwinNeuralMPC") from e

from helios.physics.twin.protocol import FacilityTwin

logger = logging.getLogger(__name__)


class TwinNeuralMPC:
    """Differentiable MPC optimizer using PyTorch autograd through surrogate models."""

    def __init__(
        self,
        twin: FacilityTwin,
        horizon: int = 5,
        num_iterations: int = 40,
        learning_rate: float = 0.05,
        weight_tracking: float = 1.0,
        weight_actuator_reg: float = 0.01,
        weight_slew_rate: float = 0.05,
        device: str = "cpu",
    ):
        self.twin = twin
        self.horizon = horizon
        self.num_iterations = num_iterations
        self.lr = learning_rate
        self.w_track = weight_tracking
        self.w_act = weight_actuator_reg
        self.w_slew = weight_slew_rate
        self.device = torch.device(device)

        self.num_controls = len(twin.control_names)
        self.num_diagnostics = len(twin.diagnostic_names)

        # Build tensor bounds from twin domain
        lo = [twin.domain.lower.get(c, -10.0) for c in twin.control_names]
        hi = [twin.domain.upper.get(c, 10.0) for c in twin.control_names]
        self.lower_bound = torch.tensor(lo, dtype=torch.float32, device=self.device)
        self.upper_bound = torch.tensor(hi, dtype=torch.float32, device=self.device)

    def optimize(
        self,
        current_setpoints: Mapping[str, float],
        target_diagnostics: Mapping[str, float] | None = None,
    ) -> dict[str, Any]:
        """Run autograd gradient descent across receding horizon."""
        u0_vals = [float(current_setpoints.get(c, 0.0)) for c in self.twin.control_names]
        u0 = torch.tensor(u0_vals, dtype=torch.float32, device=self.device)

        # Target diagnostics (default to 0.0 mm centered orbit)
        if target_diagnostics:
            y_tgt = torch.tensor(
                [float(target_diagnostics.get(d, 0.0)) for d in self.twin.diagnostic_names],
                dtype=torch.float32,
                device=self.device,
            )
        else:
            y_tgt = torch.zeros(self.num_diagnostics, dtype=torch.float32, device=self.device)

        # Parameter to optimize: control deltas over horizon H x num_controls
        u_traj = torch.nn.Parameter(u0.unsqueeze(0).repeat(self.horizon, 1).clone())
        optimizer = torch.optim.Adam([u_traj], lr=self.lr)

        loss_history = []
        for _ in range(self.num_iterations):
            optimizer.zero_grad()

            # Clamp trajectory within domain bounds
            clamped_traj = torch.max(torch.min(u_traj, self.upper_bound), self.lower_bound)

            # Evaluate forward differentiable model
            loss = torch.tensor(0.0, device=self.device)
            for k in range(self.horizon):
                step_u = clamped_traj[k].unsqueeze(0)
                pred_y = self.twin.surrogate.predict_tensor(step_u).squeeze(0)

                # 1. Tracking loss
                loss = loss + self.w_track * torch.mean((pred_y - y_tgt) ** 2)

                # 2. Regularization from baseline
                loss = loss + self.w_act * torch.mean((clamped_traj[k] - u0) ** 2)

                # 3. Slew rate penalty
                if k > 0:
                    loss = loss + self.w_slew * torch.mean((clamped_traj[k] - clamped_traj[k - 1]) ** 2)

            loss.backward()
            optimizer.step()
            loss_history.append(float(loss.item()))

        with torch.no_grad():
            final_clamped = torch.max(torch.min(u_traj, self.upper_bound), self.lower_bound)
            best_first_step = final_clamped[0].cpu().numpy()

        optimized_controls = {
            self.twin.control_names[i]: float(best_first_step[i])
            for i in range(self.num_controls)
        }

        return {
            "optimized_setpoints": optimized_controls,
            "horizon_trajectory": final_clamped.cpu().numpy().tolist(),
            "initial_loss": loss_history[0] if loss_history else 0.0,
            "final_loss": loss_history[-1] if loss_history else 0.0,
            "iterations": len(loss_history),
        }
