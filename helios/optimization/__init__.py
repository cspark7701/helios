"""HELIOS Optimization Module: Multi-objective algorithms, Bayesian optimization, and tuning loops."""

from helios.optimization.algorithms import (
    BayesianOptimizer,
    ExtremumSeekingController,
    SVDOrbitCorrection,
)
from helios.optimization.mpc import (
    MPCStepResult,
    NeuralMPCController,
)
from helios.optimization.workflows import (
    OrbitCorrectionWorkflow,
    RFPhaseScanWorkflow,
)

try:
    from helios.optimization.rl_agent import LinacRLAgent
except Exception:
    LinacRLAgent = None  # type: ignore[assignment, misc]


__all__ = [
    "BayesianOptimizer",
    "ExtremumSeekingController",
    "LinacRLAgent",
    "MPCStepResult",
    "NeuralMPCController",
    "OrbitCorrectionWorkflow",
    "RFPhaseScanWorkflow",
    "SVDOrbitCorrection",
]
