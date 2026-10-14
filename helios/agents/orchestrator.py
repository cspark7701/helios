"""HELIOS Master Orchestrator Agent.

Executive coordinator implementing LBNL Osprey Plan-First closed-loop workflows,
delegating tasks across Physics, Diagnostics, Tuner, Safety, and Control agents.
"""

import logging
from pathlib import Path

from helios.core.capabilities import get_default_registry
from helios.core.plan_engine import PlanArtifactStore, PlanLifecycleManager
from helios.core.schemas import (
    AutonomyLevel,
    ExecutionPlan,
)
from helios.diagnostics.anomaly import LinacAnomalyDetector
from helios.diagnostics.telemetry import TelemetryProcessor
from helios.interfaces.base import (
    BaseControlInterface,
    ControlInterfaceError,
    MissingReadbackError,
)
from helios.interfaces.channel_map import (
    ChannelManager,
    create_baseline_mebt_channel_manager,
)
from helios.interfaces.epics import MockControlInterface
from helios.optimization.workflows import OrbitCorrectionWorkflow
from helios.physics.lattice import Lattice, create_baseline_mebt_lattice
from helios.physics.surrogate import FastPhysicsSurrogate
from helios.safety.gatekeeper import SafetyGatekeeper
from helios.safety.policy import AutonomyPolicyEngine
from helios.safety.rollback import RollbackController

logger = logging.getLogger(__name__)


class HeliosOrchestrator:
    """Master Orchestration Agent coordinating multi-agent linac workflows."""

    def __init__(
        self,
        lattice: Lattice | None = None,
        channel_manager: ChannelManager | None = None,
        control_interface: BaseControlInterface | None = None,
        base_dir: Path | None = None,
    ):
        self.lattice = lattice or create_baseline_mebt_lattice()
        self.channels = channel_manager or create_baseline_mebt_channel_manager()
        self.control = control_interface or MockControlInterface()
        self.registry = get_default_registry()
        self.store = PlanArtifactStore(base_dir or Path("."))

        # Specialized Sub-Agents / Engines
        self.physics_surrogate = FastPhysicsSurrogate()
        self.telemetry_processor = TelemetryProcessor()
        self.anomaly_detector = LinacAnomalyDetector()
        self.safety_gatekeeper = SafetyGatekeeper(self.channels, self.control)
        self.rollback_controller = RollbackController(self.control)
        self.orbit_workflow = OrbitCorrectionWorkflow(self.lattice, self.channels)

    def read_bpm_telemetry(self, section: str, bpms: list[str]) -> tuple[dict[str, float], dict[str, float]]:
        """Read horizontal and vertical telemetry from specified BPMs."""
        bpm_x: dict[str, float] = {}
        bpm_y: dict[str, float] = {}
        for b in bpms:
            b_name = b.replace(f"{section}_", "")
            dev = self.channels.get_device(section, b_name)
            pv_x = dev.readback_pv if dev else f"{section}:DIAG:{b_name}:X_POS"
            pv_y = dev.metadata.get("pv_y") if dev and dev.metadata.get("pv_y") else f"{section}:DIAG:{b_name}:Y_POS"
            val_x = self.control.get(pv_x)
            val_y = self.control.get(pv_y)
            if val_x is None or val_y is None:
                raise MissingReadbackError(
                    f"Diagnostics BPM telemetry unreadable on {b} ({pv_x}={val_x}, {pv_y}={val_y}). Aborting plan."
                )
            bpm_x[b] = float(val_x)
            bpm_y[b] = float(val_y)
        return bpm_x, bpm_y

    def formulate_orbit_plan(
        self,
        plan_id: str,
        section: str,
        steerers: list[str],
        bpms: list[str],
        bpm_x: dict[str, float],
        bpm_y: dict[str, float],
        autonomy_level: AutonomyLevel,
    ) -> tuple[ExecutionPlan, PlanLifecycleManager, dict[str, float]]:
        """Formulate candidate correction plan and compute proposed setpoints."""
        plan, proposed_setpoints = self.orbit_workflow.build_orbit_correction_plan(
            plan_id=plan_id,
            section=section,
            steerer_names=steerers,
            bpm_names=bpms,
            measured_bpm_x=bpm_x,
            measured_bpm_y=bpm_y,
        )
        plan.autonomy_level = autonomy_level
        plan_manager = PlanLifecycleManager(plan)
        return plan, plan_manager, proposed_setpoints

    def validate_plan_safety_and_physics(
        self,
        plan: ExecutionPlan,
        plan_manager: PlanLifecycleManager,
        proposed_setpoints: dict[str, float],
    ) -> bool:
        """Execute pre-flight physics simulation and safety verification checks."""
        phys_val = self.physics_surrogate.validate_plan_setpoints(proposed_setpoints)
        plan_manager.attach_physics_validation(phys_val)
        if not phys_val.is_valid:
            self.store.save_active(plan)
            logger.error("Orbit plan rejected by Physics Agent simulation verifier!")
            return False

        safety_val = self.safety_gatekeeper.validate_setpoints(proposed_setpoints)
        plan_manager.attach_safety_validation(safety_val)
        if not safety_val.is_valid:
            self.store.save_active(plan)
            logger.error("Orbit plan rejected by Safety Agent boundary check!")
            return False

        for pv in proposed_setpoints.keys():
            current_sp = self.control.get(pv)
            if current_sp is None:
                raise MissingReadbackError(
                    f"Cannot capture rollback target for unreadable setpoint PV '{pv}'. Aborting plan."
                )
            plan.rollback_targets[pv] = float(current_sp)

        self.store.save_active(plan)
        return True

    def authorize_and_actuate(
        self,
        plan: ExecutionPlan,
        plan_manager: PlanLifecycleManager,
        section: str,
        bpms: list[str],
        proposed_setpoints: dict[str, float],
        operator_confirmed: bool,
    ) -> bool:
        """Authorize execution and actuate hardware through safety gatekeeper with rollback protection."""
        authorized, auth_msg = AutonomyPolicyEngine.evaluate_plan_authorization(plan, operator_confirmed)
        if not authorized:
            logger.warning(f"Execution authorization withheld: {auth_msg}")
            return False

        plan_manager.authorize_execution(operator_approval=operator_confirmed)
        self.rollback_controller.capture_baseline_from_hardware(
            label=f"Pre-{plan.title}",
            pvs=list(proposed_setpoints.keys()),
        )

        try:
            self.safety_gatekeeper.execute(plan)
            self._verify_post_actuation_telemetry(plan, section, bpms)
            plan_manager.complete_plan()
            self.store.archive_completed(plan)
            logger.info(f"Plan {plan.plan_id} completed successfully and archived.")
            return True
        except (ControlInterfaceError, RuntimeError, TimeoutError) as e:
            logger.error(f"Execution failed, initiating automatic rollback: {e}")
            plan_manager.abort_or_fail(str(e))
            self.rollback_controller.trigger_rollback()
            plan_manager.mark_rolled_back()
            self.store.save_active(plan)
            return False

    def _verify_post_actuation_telemetry(self, plan: ExecutionPlan, section: str, bpms: list[str]) -> None:
        """Read post-actuation telemetry and record residual RMS orbit."""
        post_bpm_x: dict[str, float] = {}
        for b in bpms:
            b_name = b.replace(f"{section}_", "")
            dev = self.channels.get_device(section, b_name)
            post_pv = dev.readback_pv if dev else f"{section}:DIAG:{b_name}:X_POS"
            raw_post = self.control.get(post_pv)
            if raw_post is None:
                raise MissingReadbackError(
                    f"Post-actuation diagnostic telemetry unreadable on BPM {b} ({post_pv}). Verification failed."
                )
            post_bpm_x[b] = float(raw_post)
        post_rms = self.telemetry_processor.compute_rms_orbit(post_bpm_x)
        plan.provenance_metadata["post_rms_x_mm"] = post_rms

    def run_orbit_correction_loop(
        self,
        plan_id: str,
        section: str = "MEBT",
        steerers: list[str] | None = None,
        bpms: list[str] | None = None,
        autonomy_level: AutonomyLevel = AutonomyLevel.BOUNDED_AUTONOMOUS,
        operator_confirmed: bool = True,
    ) -> ExecutionPlan:
        """Executes the standard Plan-First Closed-Loop Orbit Correction Pipeline."""
        steerers = steerers or ["MEBT_CH01"]
        bpms = bpms or ["MEBT_BPM01", "MEBT_BPM02"]

        bpm_x, bpm_y = self.read_bpm_telemetry(section, bpms)
        plan, plan_manager, proposed_setpoints = self.formulate_orbit_plan(
            plan_id, section, steerers, bpms, bpm_x, bpm_y, autonomy_level
        )

        if not self.validate_plan_safety_and_physics(plan, plan_manager, proposed_setpoints):
            return plan

        self.authorize_and_actuate(
            plan, plan_manager, section, bpms, proposed_setpoints, operator_confirmed
        )
        return plan
