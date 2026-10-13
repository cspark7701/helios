"""HELIOS Reinforcement Learning Policy and Continuous Control Agent.

Implements Actor-Critic policy architectures in PyTorch for autonomous closed-loop
accelerator trajectory tuning, space charge compensation, and multi-objective control.
"""

from dataclasses import dataclass
import logging
from typing import Dict, List, Optional, Tuple
import numpy as np

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    HAVE_TORCH = True
except ImportError:
    torch = None
    nn = None
    optim = None
    HAVE_TORCH = False

logger = logging.getLogger(__name__)


if HAVE_TORCH:
    class ActorCriticNetwork(nn.Module):
        """Continuous Actor-Critic network with Gaussian action distributions."""

        def __init__(self, obs_dim: int, action_dim: int, hidden_dim: int = 64):
            super().__init__()
            # Shared feature extractor
            self.shared = nn.Sequential(
                nn.Linear(obs_dim, hidden_dim),
                nn.Tanh(),
                nn.Linear(hidden_dim, hidden_dim),
                nn.Tanh(),
            )
            # Actor head (mean action)
            self.actor_mean = nn.Sequential(
                nn.Linear(hidden_dim, action_dim),
                nn.Tanh(),  # Bounded actions in [-1, 1]
            )
            # Log std (learnable parameter)
            self.actor_log_std = nn.Parameter(torch.zeros(action_dim))

            # Critic head (state value V(s))
            self.critic = nn.Linear(hidden_dim, 1)

        def forward(self, obs: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
            features = self.shared(obs)
            mean = self.actor_mean(features)
            value = self.critic(features)
            std = torch.exp(self.actor_log_std)
            return mean, std, value
else:
    class ActorCriticNetwork:  # type: ignore
        pass


class LinacRLAgent:
    """Continuous Reinforcement Learning Agent for linac trajectory & envelope control."""

    def __init__(
        self,
        obs_dim: int = 9,
        action_dim: int = 4,
        hidden_dim: int = 64,
        learning_rate: float = 3e-4,
        device: str = "cpu",
    ):
        self.obs_dim = obs_dim
        self.action_dim = action_dim
        self.device = device

        if HAVE_TORCH:
            self.net = ActorCriticNetwork(obs_dim, action_dim, hidden_dim).to(device)
            self.optimizer = optim.Adam(self.net.parameters(), lr=learning_rate)
        else:
            self.net = None
            self.optimizer = None

    def act(self, obs: np.ndarray, deterministic: bool = True) -> np.ndarray:
        """Select action vector given current accelerator observation."""
        if not HAVE_TORCH or self.net is None:
            # Deterministic linear proportional feedback fallback
            return -0.2 * obs[:self.action_dim]

        with torch.no_grad():
            obs_tensor = torch.tensor(obs, dtype=torch.float32, device=self.device).unsqueeze(0)
            mean, std, _ = self.net(obs_tensor)

            if deterministic:
                action = mean.squeeze(0).cpu().numpy()
            else:
                dist = torch.distributions.Normal(mean, std)
                action = dist.sample().squeeze(0).cpu().numpy()

        return np.clip(action, -1.0, 1.0)

    def train_step(
        self,
        obs: np.ndarray,
        actions: np.ndarray,
        rewards: np.ndarray,
        next_obs: np.ndarray,
        dones: np.ndarray,
        gamma: float = 0.99,
    ) -> float:
        """Run policy gradient / value loss update step."""
        if not HAVE_TORCH or self.net is None:
            return 0.0

        self.net.train()
        obs_t = torch.tensor(obs, dtype=torch.float32, device=self.device)
        act_t = torch.tensor(actions, dtype=torch.float32, device=self.device)
        rew_t = torch.tensor(rewards, dtype=torch.float32, device=self.device).unsqueeze(-1)
        next_obs_t = torch.tensor(next_obs, dtype=torch.float32, device=self.device)
        done_t = torch.tensor(dones, dtype=torch.float32, device=self.device).unsqueeze(-1)

        mean, std, values = self.net(obs_t)
        with torch.no_grad():
            _, _, next_values = self.net(next_obs_t)
            targets = rew_t + gamma * next_values * (1.0 - done_t)

        advantages = (targets - values).detach()

        dist = torch.distributions.Normal(mean, std)
        log_prob = dist.log_prob(act_t).sum(dim=-1, keepdim=True)

        policy_loss = -(log_prob * advantages).mean()
        value_loss = nn.functional.mse_loss(values, targets)
        loss = policy_loss + 0.5 * value_loss

        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        self.net.eval()

        return float(loss.item())
