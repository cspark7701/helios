"""HELIOS Digital Twin Package (`helios.physics.twin`).

Facility-agnostic digital twin framework hosting plugin registries,
pre-flight simulation verifiers, Gymnasium adapters, and Neural MPC engines.
"""

from helios.physics.twin.protocol import (
    FacilityPlugin,
    FacilityTwin,
    FrozenSurrogateInterface,
    TwinDomain,
)
from helios.physics.twin.registry import (
    AnalyticTwinFallbackPlugin,
    MockFacilityPlugin,
    discover_facility_plugins,
    get_facility_twin,
)
from helios.physics.twin.sync import TwinStateSynchronizer
from helios.physics.twin.verifier import TwinPreFlightVerifier

try:
    from helios.physics.twin.env import LinacSurrogateGymEnv
except Exception:
    LinacSurrogateGymEnv = None  # type: ignore[assignment, misc]

try:
    from helios.physics.twin.mpc import TwinNeuralMPC
except Exception:
    TwinNeuralMPC = None  # type: ignore[assignment, misc]


__all__ = [
    "AnalyticTwinFallbackPlugin",
    "FacilityPlugin",
    "FacilityTwin",
    "FrozenSurrogateInterface",
    "LinacSurrogateGymEnv",
    "MockFacilityPlugin",
    "TwinDomain",
    "TwinNeuralMPC",
    "TwinPreFlightVerifier",
    "TwinStateSynchronizer",
    "discover_facility_plugins",
    "get_facility_twin",
]
