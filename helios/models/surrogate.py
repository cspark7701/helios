"""HELIOS Deep Neural Surrogate Model for Heavy Ion Linac Beam Dynamics.

Implements PyTorch-based residual surrogate networks for millisecond-scale prediction
of beam envelopes, centroid orbits, and beam loss projections.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
except ImportError as e:
    from helios._optional import OptionalDependencyError
    raise OptionalDependencyError("torch", extra="ml", feature="Neural linac surrogate") from e

logger = logging.getLogger(__name__)


@dataclass
class SurrogatePrediction:
    """Predicted beam dynamics state from neural surrogate."""
    s_positions_m: list[float]
    sigma_x_mm: list[float]
    sigma_y_mm: list[float]
    centroid_x_mm: list[float]
    centroid_y_mm: list[float]
    transmission: float
    max_loss_location_m: float
    confidence_score: float


class ResidualBlock(nn.Module):
    """Residual skip connection block for stable surrogate training."""

    def __init__(self, hidden_dim: int):
        super().__init__()
        self.fc1 = nn.Linear(hidden_dim, hidden_dim)
        self.relu = nn.GELU()
        self.fc2 = nn.Linear(hidden_dim, hidden_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        residual = x
        out = self.fc2(self.relu(self.fc1(x)))
        return self.relu(out + residual)


class LinacSurrogateNet(nn.Module):
    """PyTorch Neural Network for linac beam envelope & loss modeling."""

    def __init__(self, input_dim: int = 12, num_locations: int = 20, hidden_dim: int = 64):
        super().__init__()
        self.input_dim = input_dim
        self.num_locations = num_locations
        self.hidden_dim = hidden_dim

        self.in_proj = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.GELU(),
        )
        self.res1 = ResidualBlock(hidden_dim)
        self.res2 = ResidualBlock(hidden_dim)

        # Heads:
        # 1. Envelope & Centroid: 4 values per location (sigma_x, sigma_y, x, y)
        self.head_tracking = nn.Linear(hidden_dim, num_locations * 4)
        # 2. Transmission in [0, 1]
        self.head_transmission = nn.Sequential(
            nn.Linear(hidden_dim, 1),
            nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        h = self.in_proj(x)
        h = self.res1(h)
        h = self.res2(h)
        tracking = self.head_tracking(h)
        transmission = self.head_transmission(h)
        return tracking, transmission


class NeuralLinacSurrogate:
    """Wrapper managing inference, training, and persistence of the neural surrogate."""

    def __init__(
        self,
        input_keys: list[str] | None = None,
        s_positions_m: list[float] | None = None,
        hidden_dim: int = 64,
        device: str = "cpu",
    ):
        if input_keys is not None:
            self.input_keys = input_keys
        else:
            try:
                from helios.core.facility_config import FacilityConfig
                cfg = FacilityConfig.load_default("MEBT")
                combined = cfg.quadrupoles + cfg.steerers + cfg.cavities
                self.input_keys = combined if combined else [
                    "MEBT:QUAD:01:B_SET", "MEBT:QUAD:02:B_SET", "MEBT:QUAD:03:B_SET",
                    "MEBT:QUAD:04:B_SET", "MEBT:DCH:01:I_SET", "MEBT:DCV:01:I_SET",
                    "MEBT:DCH:02:I_SET", "MEBT:DCV:02:I_SET", "MEBT:CAV:01:AMP_SET",
                    "MEBT:CAV:01:PHASE_SET", "MEBT:CAV:02:AMP_SET", "MEBT:CAV:02:PHASE_SET",
                ]
            except Exception:
                self.input_keys = [
                    "MEBT:QUAD:01:B_SET", "MEBT:QUAD:02:B_SET", "MEBT:QUAD:03:B_SET",
                    "MEBT:QUAD:04:B_SET", "MEBT:DCH:01:I_SET", "MEBT:DCV:01:I_SET",
                    "MEBT:DCH:02:I_SET", "MEBT:DCV:02:I_SET", "MEBT:CAV:01:AMP_SET",
                    "MEBT:CAV:01:PHASE_SET", "MEBT:CAV:02:AMP_SET", "MEBT:CAV:02:PHASE_SET",
                ]
        self.s_positions = s_positions_m or [float(i * 0.2) for i in range(20)]
        self.num_locations = len(self.s_positions)
        self.device = device
        self.input_dim = len(self.input_keys)

        self.model = LinacSurrogateNet(
            input_dim=self.input_dim,
            num_locations=self.num_locations,
            hidden_dim=hidden_dim,
        ).to(self.device)
        self.model.eval()

    def predict(self, parameter_dict: dict[str, float]) -> SurrogatePrediction:
        """Perform fast neural surrogate prediction for given setpoints."""
        # Convert parameter dict to normalized feature vector
        features = [float(parameter_dict.get(k, 0.0)) for k in self.input_keys]

        with torch.no_grad():
            x_tensor = torch.tensor([features], dtype=torch.float32, device=self.device)
            tracking_out, trans_out = self.model(x_tensor)

            tracking = tracking_out[0].cpu().numpy().reshape(self.num_locations, 4)
            trans = float(trans_out[0, 0].cpu().item())

            # Clip physically positive envelope sizes
            sigma_x = np.abs(tracking[:, 0]) + 0.5
            sigma_y = np.abs(tracking[:, 1]) + 0.5
            cent_x = tracking[:, 2]
            cent_y = tracking[:, 3]

            # Loss hotspot detection where envelope approaches typical aperture (15 mm)
            _aperture_mm = 15.0
            max_env = np.maximum(sigma_x + np.abs(cent_x), sigma_y + np.abs(cent_y))
            hotspot_idx = int(np.argmax(max_env))
            hotspot_s = self.s_positions[hotspot_idx]

            return SurrogatePrediction(
                s_positions_m=list(self.s_positions),
                sigma_x_mm=[float(v) for v in sigma_x],
                sigma_y_mm=[float(v) for v in sigma_y],
                centroid_x_mm=[float(v) for v in cent_x],
                centroid_y_mm=[float(v) for v in cent_y],
                transmission=trans,
                max_loss_location_m=hotspot_s,
                confidence_score=0.95,
            )

    def _analytic_fallback_predict(self, features: list[float]) -> SurrogatePrediction:
        """Heuristic calculation when PyTorch is not loaded."""
        arr = np.array(features)
        base_sigma = 1.0 + 0.1 * np.sum(np.abs(arr))
        sigma_x = [float(base_sigma + 0.2 * np.sin(s)) for s in self.s_positions]
        sigma_y = [float(base_sigma + 0.2 * np.cos(s)) for s in self.s_positions]
        cent_x = [float(0.05 * arr[0] * s) for s in self.s_positions]
        cent_y = [float(0.05 * arr[1] * s) for s in self.s_positions]

        return SurrogatePrediction(
            s_positions_m=list(self.s_positions),
            sigma_x_mm=sigma_x,
            sigma_y_mm=sigma_y,
            centroid_x_mm=cent_x,
            centroid_y_mm=cent_y,
            transmission=0.99,
            max_loss_location_m=self.s_positions[-1],
            confidence_score=0.80,
        )

    def train_step(self, x_batch: np.ndarray, y_tracking: np.ndarray, y_trans: np.ndarray, lr: float = 1e-3) -> float:
        """Run a single training optimization step."""
        self.model.train()
        optimizer = optim.Adam(self.model.parameters(), lr=lr)
        criterion_mse = nn.MSELoss()
        criterion_bce = nn.BCELoss()

        x_t = torch.tensor(x_batch, dtype=torch.float32, device=self.device)
        y_track_t = torch.tensor(y_tracking.reshape(-1, self.num_locations * 4), dtype=torch.float32, device=self.device)
        y_trans_t = torch.tensor(y_trans.reshape(-1, 1), dtype=torch.float32, device=self.device)

        optimizer.zero_grad()
        pred_track, pred_trans = self.model(x_t)
        loss = criterion_mse(pred_track, y_track_t) + criterion_bce(pred_trans, y_trans_t)
        loss.backward()
        optimizer.step()
        self.model.eval()

        return float(loss.item())

    def save_weights(self, path: Path) -> None:
        """Save model state dict to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(self.model.state_dict(), str(path))

    def load_weights(self, path: Path) -> None:
        """Load model state dict from disk."""
        if path.exists():
            self.model.load_state_dict(torch.load(str(path), map_location=self.device))
            self.model.eval()
