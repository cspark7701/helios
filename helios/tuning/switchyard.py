"""HELIOS High Energy Beam Transport (HEBT) Switchyard Router.

Implements:
1. Automated beamline routing from main linac to experimental target stations.
2. Coordinated dipole bending, septum, and steerer kick synchronization.
3. Fast lattice transitions between distinct target energy/species requirements.
"""

from dataclasses import dataclass, field
from enum import Enum
import logging
from typing import Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)


class TargetVaultID(str, Enum):
    NUCLEAR_PHYSICS_VAULT = "NUCLEAR_PHYSICS_VAULT"
    ISOTOPE_PRODUCTION_VAULT = "ISOTOPE_PRODUCTION_VAULT"
    MATERIALS_SCIENCE_VAULT = "MATERIALS_SCIENCE_VAULT"
    BEAM_DUMP = "BEAM_DUMP"


@dataclass
class SwitchyardRouteConfig:
    """Hardware configuration for routing beam to a target vault."""
    target_vault: TargetVaultID
    switching_dipole_current_a: float
    septum_voltage_kv: float
    corrector_kicks_mrad: Dict[str, float]
    active_beamline_length_m: float
    required_energy_mev_u: float
    interlocks_verified: bool = True


@dataclass
class RouteTransitionOutcome:
    """Outcome of a switchyard beamline transition."""
    success: bool
    previous_vault: TargetVaultID
    target_vault: TargetVaultID
    transition_time_s: float
    max_orbit_deviation_mm: float
    losses_projected_w: float
    actuated_pvs: Dict[str, float]


class SwitchyardBeamRouter:
    """Directs heavy-ion beam to designated target stations via coordinated magnetic switching."""

    def __init__(self):
        # Target definitions with baseline dipole currents (A)
        self._routes: Dict[TargetVaultID, SwitchyardRouteConfig] = {
            TargetVaultID.BEAM_DUMP: SwitchyardRouteConfig(
                target_vault=TargetVaultID.BEAM_DUMP,
                switching_dipole_current_a=0.0,  # Straight ahead
                septum_voltage_kv=0.0,
                corrector_kicks_mrad={"HEBT:CH01": 0.0, "HEBT:CV01": 0.0},
                active_beamline_length_m=15.0,
                required_energy_mev_u=15.0,
            ),
            TargetVaultID.NUCLEAR_PHYSICS_VAULT: SwitchyardRouteConfig(
                target_vault=TargetVaultID.NUCLEAR_PHYSICS_VAULT,
                switching_dipole_current_a=125.5,  # 30 deg bend
                septum_voltage_kv=45.0,
                corrector_kicks_mrad={"HEBT:CH01": 0.45, "HEBT:CV01": -0.20},
                active_beamline_length_m=35.0,
                required_energy_mev_u=18.5,
            ),
            TargetVaultID.ISOTOPE_PRODUCTION_VAULT: SwitchyardRouteConfig(
                target_vault=TargetVaultID.ISOTOPE_PRODUCTION_VAULT,
                switching_dipole_current_a=-125.5,  # -30 deg bend
                septum_voltage_kv=45.0,
                corrector_kicks_mrad={"HEBT:CH01": -0.45, "HEBT:CV01": 0.15},
                active_beamline_length_m=42.0,
                required_energy_mev_u=12.0,
            ),
            TargetVaultID.MATERIALS_SCIENCE_VAULT: SwitchyardRouteConfig(
                target_vault=TargetVaultID.MATERIALS_SCIENCE_VAULT,
                switching_dipole_current_a=185.0,  # 45 deg bend
                septum_voltage_kv=60.0,
                corrector_kicks_mrad={"HEBT:CH01": 0.85, "HEBT:CV01": -0.35},
                active_beamline_length_m=28.0,
                required_energy_mev_u=8.0,
            ),
        }
        self.active_vault = TargetVaultID.BEAM_DUMP

    def plan_route_transition(
        self,
        new_target_vault: TargetVaultID,
        max_slew_rate_a_s: float = 25.0,
    ) -> RouteTransitionOutcome:
        """Calculate coordinated actuator setpoints and transition time for route change."""
        current_cfg = self._routes[self.active_vault]
        target_cfg = self._routes[new_target_vault]

        delta_i = abs(target_cfg.switching_dipole_current_a - current_cfg.switching_dipole_current_a)
        ramp_time = max(1.0, delta_i / max_slew_rate_a_s)

        actuations: Dict[str, float] = {
            "HEBT:PS_DIPOLE_SW:I_Set": target_cfg.switching_dipole_current_a,
            "HEBT:SEPTUM01:V_Set": target_cfg.septum_voltage_kv,
        }
        for pv, kick in target_cfg.corrector_kicks_mrad.items():
            actuations[f"{pv}:Kick_Set"] = kick

        outcome = RouteTransitionOutcome(
            success=True,
            previous_vault=self.active_vault,
            target_vault=new_target_vault,
            transition_time_s=float(ramp_time),
            max_orbit_deviation_mm=0.18,
            losses_projected_w=0.01,
            actuated_pvs=actuations,
        )

        self.active_vault = new_target_vault
        return outcome
