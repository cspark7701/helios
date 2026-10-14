"""HELIOS Gymnasium Linac Environment for Reinforcement Learning and Optimization.

Provides a standard Gymnasium API (reset, step) wrapped around accelerator
digital twin physics, domain randomization, and multi-objective rewards.
"""

from typing import Any

import numpy as np

try:
    import gymnasium as gym
    from gymnasium import spaces
    HAVE_GYMNASIUM = True
except ImportError:
    HAVE_GYMNASIUM = False
    gym = object  # type: ignore
    spaces = None  # type: ignore

from helios.physics.engine import AnalyticDigitalTwinEngine
from helios.physics.lattice import Lattice, create_baseline_mebt_lattice


class LinacGymEnv(gym.Env if HAVE_GYMNASIUM else object):
    """Gymnasium reinforcement learning environment for heavy ion linac orbit & envelope control."""

    metadata = {"render_modes": ["human", "rgb_array"]}

    def __init__(
        self,
        lattice: Lattice | None = None,
        steerer_pvs: list[str] | None = None,
        bpm_pvs: list[str] | None = None,
        max_steps: int = 50,
        domain_randomization: bool = False,
        target_rms_mm: float = 0.10,
    ):
        if not HAVE_GYMNASIUM:
            raise RuntimeError("Gymnasium is required. Install via 'pip install gymnasium'.")

        super().__init__()
        self.lattice = lattice or create_baseline_mebt_lattice()
        self.engine = AnalyticDigitalTwinEngine()
        self.max_steps = max_steps
        self.domain_randomization = domain_randomization
        self.target_rms_mm = target_rms_mm

        if steerer_pvs is not None:
            self.steerer_pvs = steerer_pvs
        else:
            try:
                from helios.core.facility_config import FacilityConfig
                cfg = FacilityConfig.load_default("MEBT")
                self.steerer_pvs = cfg.steerers if cfg.steerers else [
                    "MEBT:DCH:01:I_SET", "MEBT:DCV:01:I_SET",
                    "MEBT:DCH:02:I_SET", "MEBT:DCV:02:I_SET",
                ]
            except Exception:
                self.steerer_pvs = [
                    "MEBT:DCH:01:I_SET", "MEBT:DCV:01:I_SET",
                    "MEBT:DCH:02:I_SET", "MEBT:DCV:02:I_SET",
                ]

        if bpm_pvs is not None:
            self.bpm_pvs = bpm_pvs
        else:
            try:
                from helios.core.facility_config import FacilityConfig
                cfg = FacilityConfig.load_default("MEBT")
                self.bpm_pvs = cfg.bpms if cfg.bpms else [
                    "MEBT:BPM:01", "MEBT:BPM:02", "MEBT:BPM:03", "MEBT:BPM:04",
                ]
            except Exception:
                self.bpm_pvs = [
                    "MEBT:BPM:01", "MEBT:BPM:02", "MEBT:BPM:03", "MEBT:BPM:04",
                ]

        self.num_actuators = len(self.steerer_pvs)
        self.num_bpms = len(self.bpm_pvs)
        self.current_step = 0

        # Action: delta adjustment per steerer in [-1.0, 1.0] Amperes
        self.action_space = spaces.Box(
            low=-1.0, high=1.0, shape=(self.num_actuators,), dtype=np.float32
        )

        # Observation: [BPM_x (mm)..., BPM_y (mm)..., transmission_pct]
        obs_dim = (self.num_bpms * 2) + 1
        self.observation_space = spaces.Box(
            low=-20.0, high=20.0, shape=(obs_dim,), dtype=np.float32
        )

        self.state_setpoints: dict[str, float] = {}
        self.quad_misalignments: dict[str, float] = {}

    def _get_obs(self) -> np.ndarray:
        """Run beam dynamics tracking and format observation vector."""
        traj = self.engine.run_simulation(self.lattice, self.state_setpoints)

        # Extract BPM positions
        bpm_points = [pt for pt in traj if "BPM" in pt.element_name]
        if len(bpm_points) < self.num_bpms:
            # Pad or take evenly spaced points
            step_stride = max(1, len(traj) // self.num_bpms)
            bpm_points = traj[::step_stride][:self.num_bpms]

        obs_x = [pt.x_mm for pt in bpm_points]
        obs_y = [pt.y_mm for pt in bpm_points]

        # Domain randomization noise injection
        if self.domain_randomization:
            obs_x = [x + np.random.normal(0.0, 0.02) for x in obs_x]
            obs_y = [y + np.random.normal(0.0, 0.02) for y in obs_y]

        # Transmission proxy: decreases if beam centroid or envelope exceeds vacuum chamber (15 mm)
        max_r = max([max(abs(x), abs(y)) for x, y in zip(obs_x, obs_y)] or [0.0])
        transmission = 100.0 if max_r < 12.0 else max(50.0, 100.0 - (max_r - 12.0) * 15.0)

        obs = np.array(obs_x + obs_y + [transmission], dtype=np.float32)
        return obs

    def reset(
        self,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Reset environment to distorted initial orbit state."""
        super().reset(seed=seed)
        self.current_step = 0

        # Initial steerer setpoints with random misalignment offsets
        self.state_setpoints = {}
        for pv in self.steerer_pvs:
            # Distort initial orbit with random steerer kicks
            self.state_setpoints[pv] = float(np.random.uniform(-1.5, 1.5))

        if self.domain_randomization:
            # Random quadrupole misalignment offsets
            self.quad_misalignments = {
                "MEBT:QUAD:01": float(np.random.normal(0.0, 0.05)),
                "MEBT:QUAD:02": float(np.random.normal(0.0, 0.05)),
            }

        obs = self._get_obs()
        info = {"initial_rms_mm": float(np.sqrt(np.mean(obs[:-1] ** 2)))}
        return obs, info

    def step(self, action: np.ndarray) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Execute action delta and return step transition."""
        self.current_step += 1
        action = np.clip(action, self.action_space.low, self.action_space.high)

        # Apply action delta to steerers
        for pv, delta in zip(self.steerer_pvs, action):
            self.state_setpoints[pv] = float(np.clip(
                self.state_setpoints.get(pv, 0.0) + delta, -5.0, 5.0
            ))

        obs = self._get_obs()
        orbit_coords = obs[:-1]
        transmission = obs[-1]

        rms_orbit = float(np.sqrt(np.mean(orbit_coords ** 2)))
        action_penalty = float(np.sum(action ** 2)) * 0.05
        loss_penalty = (100.0 - transmission) * 0.1

        # Reward formulation
        reward = -(rms_orbit + action_penalty + loss_penalty)
        if rms_orbit < self.target_rms_mm:
            reward += 10.0  # Success bonus

        terminated = rms_orbit < self.target_rms_mm or transmission < 60.0
        truncated = self.current_step >= self.max_steps

        info = {
            "rms_orbit_mm": rms_orbit,
            "transmission_pct": transmission,
            "step": self.current_step,
        }

        return obs, float(reward), terminated, truncated, info
