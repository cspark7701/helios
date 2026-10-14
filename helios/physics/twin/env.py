"""Gymnasium reinforcement learning environment wrapping FacilityTwin."""

from typing import Any

import numpy as np

from helios.physics.twin.protocol import FacilityTwin

try:
    import gymnasium as gym
    from gymnasium import spaces
    _HAS_GYM = True
except ImportError:
    gym = None  # type: ignore[assignment]
    spaces = None  # type: ignore[assignment]
    _HAS_GYM = False

_EnvBase = gym.Env if _HAS_GYM and gym is not None else object


class LinacSurrogateGymEnv(_EnvBase):  # type: ignore[misc, valid-type]
    """Fast Gymnasium training environment backed by a FacilityTwin surrogate model."""

    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        twin: FacilityTwin,
        max_steps: int = 50,
        target_rms_mm: float = 0.05,
        current_increment_a: float = 0.05,
        jitter_std: float = 0.01,
    ):
        if not _HAS_GYM:
            from helios._optional import OptionalDependencyError
            raise OptionalDependencyError("gymnasium", extra="rl", feature="LinacSurrogateGymEnv")
        super().__init__()
        self.twin = twin
        self.max_steps = max_steps
        self.target_rms_mm = target_rms_mm
        self.current_increment_a = current_increment_a
        self.jitter_std = jitter_std

        self.num_controls = len(twin.control_names)
        self.num_diagnostics = len(twin.diagnostic_names)

        # Action: normalized control step adjustments in [-1.0, 1.0]
        self.action_space = spaces.Box(
            low=-1.0,
            high=1.0,
            shape=(self.num_controls,),
            dtype=np.float32,
        )

        # Observation: normalized diagnostics (errors) + normalized control setpoints
        obs_dim = self.num_diagnostics + self.num_controls
        self.observation_space = spaces.Box(
            low=-10.0,
            high=10.0,
            shape=(obs_dim,),
            dtype=np.float32,
        )

        self.current_step = 0
        self.current_controls: dict[str, float] = {}

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        self.current_step = 0

        # Initialize randomized starting setpoints within domain
        self.current_controls = {}
        for name in self.twin.control_names:
            lo = self.twin.domain.lower.get(name, -5.0)
            hi = self.twin.domain.upper.get(name, 5.0)
            # Start near zero or mid-range with jitter
            self.current_controls[name] = float(np.random.uniform(lo * 0.3, hi * 0.3))

        obs = self._get_observation()
        return obs, {"controls": dict(self.current_controls)}

    def step(self, action: np.ndarray) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        self.current_step += 1

        # Apply normalized action delta scaled to current resolution
        action_clipped = np.clip(action, -1.0, 1.0)
        for i, name in enumerate(self.twin.control_names):
            delta = float(action_clipped[i]) * self.current_increment_a * 5.0
            # Jitter
            if self.jitter_std > 0:
                delta += float(np.random.normal(0.0, self.jitter_std))
            # Quantize
            quant_delta = round(delta / self.current_increment_a) * self.current_increment_a
            new_val = self.current_controls[name] + quant_delta
            # Clamp to domain
            lo = self.twin.domain.lower.get(name, -np.inf)
            hi = self.twin.domain.upper.get(name, np.inf)
            self.current_controls[name] = float(np.clip(new_val, lo, hi))

        # Forward prediction
        pred = self.twin.predict(self.current_controls)
        diag_vals = np.array([pred.get(d, 0.0) for d in self.twin.diagnostic_names], dtype=np.float32)
        rms = float(np.sqrt(np.mean(diag_vals**2))) if len(diag_vals) > 0 else 0.0

        # Reward: penalize orbit RMS and action magnitude
        reward = -rms - 0.05 * float(np.sum(action_clipped**2))
        if rms < self.target_rms_mm:
            reward += 10.0

        terminated = bool(rms < self.target_rms_mm * 0.5)
        truncated = bool(self.current_step >= self.max_steps)

        obs = self._get_observation(pred)
        info = {
            "rms_mm": rms,
            "controls": dict(self.current_controls),
            "step": self.current_step,
        }
        return obs, reward, terminated, truncated, info

    def _get_observation(self, prediction: dict[str, float] | None = None) -> np.ndarray:
        if prediction is None:
            prediction = self.twin.predict(self.current_controls)

        diag_vals = [prediction.get(d, 0.0) for d in self.twin.diagnostic_names]
        ctrl_norm = self.twin.domain.normalize(self.current_controls)
        obs = np.concatenate([np.array(diag_vals, dtype=np.float32), ctrl_norm])
        return obs.astype(np.float32)
