"""Unit tests for Gymnasium Linac Environment, RL Agent, and Neural MPC (Phase 15)."""

import numpy as np
import pytest

from helios.envs.linac_env import LinacGymEnv
from helios.optimization.mpc import NeuralMPCController
from helios.optimization.rl_agent import LinacRLAgent


def test_linac_gym_env_lifecycle_and_randomization():
    """Verify LinacGymEnv Gymnasium API (reset, step, observation/action spaces)."""
    env = LinacGymEnv(max_steps=10, domain_randomization=True)

    # 1. Reset
    obs, info = env.reset(seed=42)
    assert isinstance(obs, np.ndarray)
    assert obs.shape == env.observation_space.shape
    assert "initial_rms_mm" in info

    # 2. Step
    action = np.zeros(env.num_actuators, dtype=np.float32)
    next_obs, reward, terminated, truncated, step_info = env.step(action)

    assert isinstance(next_obs, np.ndarray)
    assert isinstance(reward, float)
    assert isinstance(terminated, bool)
    assert isinstance(truncated, bool)
    assert "rms_orbit_mm" in step_info
    assert "transmission_pct" in step_info


def test_linac_rl_agent_inference_and_learning():
    """Verify LinacRLAgent continuous policy evaluation and training."""
    obs_dim = 9
    act_dim = 4
    agent = LinacRLAgent(obs_dim=obs_dim, action_dim=act_dim, hidden_dim=32)

    # 1. Action inference
    sample_obs = np.random.randn(obs_dim).astype(np.float32)
    act_det = agent.act(sample_obs, deterministic=True)
    assert act_det.shape == (act_dim,)
    assert np.all(act_det >= -1.0) and np.all(act_det <= 1.0)

    act_stoch = agent.act(sample_obs, deterministic=False)
    assert act_stoch.shape == (act_dim,)

    # 2. Training step
    batch_size = 4
    b_obs = np.random.randn(batch_size, obs_dim).astype(np.float32)
    b_act = np.random.uniform(-1.0, 1.0, (batch_size, act_dim)).astype(np.float32)
    b_rew = np.random.randn(batch_size).astype(np.float32)
    b_nobs = np.random.randn(batch_size, obs_dim).astype(np.float32)
    b_dones = np.zeros(batch_size, dtype=np.float32)

    loss_val = agent.train_step(b_obs, b_act, b_rew, b_nobs, b_dones)
    assert isinstance(loss_val, float)


def test_neural_mpc_controller_receding_horizon():
    """Verify NeuralMPCController multi-step receding horizon trajectory planning."""
    mpc = NeuralMPCController(horizon_steps=3)

    current_setpoints = {
        "MEBT:DCH:01:I_SET": 1.2,
        "MEBT:DCV:01:I_SET": -0.8,
        "MEBT:DCH:02:I_SET": 0.5,
        "MEBT:DCV:02:I_SET": -0.4,
    }

    result = mpc.optimize_action(
        current_setpoints=current_setpoints,
        estimated_drift_rate_mm_per_step=0.01,
    )

    assert result.horizon_steps == 3
    assert len(result.optimal_action) == 4
    assert all(k in result.optimal_action for k in mpc.actuator_keys)
    assert result.predicted_horizon_cost >= 0.0
    assert result.predicted_rms_error_mm >= 0.0
    assert result.iterations >= 1
