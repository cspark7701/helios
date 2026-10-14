"""HELIOS Capability Catalog per-domain registry aggregator."""

from helios.core.capabilities import Capability
from helios.core.catalog.controls import CONTROLS_CAPABILITIES
from helios.core.catalog.diagnostics import DIAGNOSTICS_CAPABILITIES
from helios.core.catalog.ops import OPS_CAPABILITIES
from helios.core.catalog.optimization import OPTIMIZATION_CAPABILITIES
from helios.core.catalog.orbit import ORBIT_CAPABILITIES
from helios.core.catalog.rf import RF_CAPABILITIES
from helios.core.catalog.safety import SAFETY_CAPABILITIES
from helios.core.catalog.simulation import SIMULATION_CAPABILITIES

ALL_DEFAULT_CAPABILITIES: list[Capability] = [
    *DIAGNOSTICS_CAPABILITIES,
    *ORBIT_CAPABILITIES,
    *RF_CAPABILITIES,
    *OPTIMIZATION_CAPABILITIES,
    *SIMULATION_CAPABILITIES,
    *SAFETY_CAPABILITIES,
    *CONTROLS_CAPABILITIES,
    *OPS_CAPABILITIES,
]

__all__ = [
    "ALL_DEFAULT_CAPABILITIES",
    "CONTROLS_CAPABILITIES",
    "DIAGNOSTICS_CAPABILITIES",
    "OPS_CAPABILITIES",
    "OPTIMIZATION_CAPABILITIES",
    "ORBIT_CAPABILITIES",
    "RF_CAPABILITIES",
    "SAFETY_CAPABILITIES",
    "SIMULATION_CAPABILITIES",
]
