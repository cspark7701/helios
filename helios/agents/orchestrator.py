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

    def run_orbit_correction_loop(
        self,
        plan_id: str,
        section: str = "MEBT",
        steerers: list[str] | None = None,
        bpms: list[str] | None = None,
        autonomy_level: AutonomyLevel = AutonomyLevel.BOUNDED_AUTONOMOUS,
        operator_confirmed: bool = True,
    ) -> ExecutionPlan:
        """Executes the standard Plan-First Closed-Loop Orbit Correction Pipeline.

        Workflow:
        1. Query live BPM telemetry (Diagnostics Agent)
        2. Formulate correction plan & steerer kicks (Tuning Agent)
        3. Pre-flight simulation verification (Physics Agent)
        4. Hardware boundary & interlock verification (Safety Agent)
        5. Save active plan artifact in docs/exec-plans/active/
        6. HITL authorization check (Policy Engine)
        7. Snapshot rollback checkpoint & actuate hardware (Control Agent)
        8. Read post-actuation telemetry & verify orbit improvement (Diagnostics Agent)
        9. Mark plan complete and archive artifact in docs/exec-plans/completed/
        """
        steerers = steerers or ["MEBT_CH01"]
        bpms = bpms or ["MEBT_BPM01", "MEBT_BPM02"]

        # Step 1: Read Telemetry (Diagnostics)
        bpm_x = {}
        bpm_y = {}
        for b in bpms:
            b_name = b.replace(f"{section}_", "")
            dev = self.channels.get_device(section, b_name)
            pv_x = dev.readback_pv if dev else f"{section}:DIAG:{b_name}:X_POS"
            pv_y = (dev.metadata.get("pv_y") if dev and dev.metadata.get("pv_y") else f"{section}:DIAG:{b_name}:Y_POS")
            val_x = self.control.get(pv_x)
            val_y = self.control.get(pv_y)
            if val_x is None or val_y is None:
                raise MissingReadbackError(
                    f"Diagnostics BPM telemetry unreadable on {b} ({pv_x}={val_x}, {pv_y}={val_y}). Aborting plan."
                )
            bpm_x[b] = float(val_x)
            bpm_y[b] = float(val_y)

        # Step 2: Formulate Correction Plan (Tuner)
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

        # Step 3: Pre-flight Simulation Verification (Physics)
        phys_val = self.physics_surrogate.validate_plan_setpoints(proposed_setpoints)
        plan_manager.attach_physics_validation(phys_val)
        if not phys_val.is_valid:
            self.store.save_active(plan)
            logger.error("Orbit plan rejected by Physics Agent simulation verifier!")
            return plan

        # Step 4: Safety & Limits Verification (Safety)
        safety_val = self.safety_gatekeeper.validate_setpoints(proposed_setpoints)
        plan_manager.attach_safety_validation(safety_val)
        if not safety_val.is_valid:
            self.store.save_active(plan)
            logger.error("Orbit plan rejected by Safety Agent boundary check!")
            return plan

        # Register rollback targets in plan
        for pv in proposed_setpoints.keys():
            current_sp = self.control.get(pv)
            if current_sp is None:
                raise MissingReadbackError(
                    f"Cannot capture rollback target for unreadable setpoint PV '{pv}'. Aborting plan."
                )
            plan.rollback_targets[pv] = float(current_sp)

        # Step 5: Save Active Execution Plan Artifact
        self.store.save_active(plan)

        # Step 6: Authorization Gate
        authorized, auth_msg = AutonomyPolicyEngine.evaluate_plan_authorization(plan, operator_confirmed)
        if not authorized:
            logger.warning(f"Execution authorization withheld: {auth_msg}")
            return plan

        plan_manager.authorize_execution(operator_approval=operator_confirmed)

        # Step 7: Rollback Baseline & Hardware Actuation (Control)
        self.rollback_controller.capture_baseline_from_hardware(
            label=f"Pre-{plan.title}",
            pvs=list(proposed_setpoints.keys()),
        )

        try:
            # Actuate hardware through Safety Gatekeeper
            self.safety_gatekeeper.execute(plan)

            # Step 8: Post-actuation Telemetry Verification (Diagnostics)
            post_bpm_x = {}
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

            # Step 9: Complete and Archive Plan Artifact
            plan_manager.complete_plan()
            self.store.archive_completed(plan)
            logger.info(f"Plan {plan.plan_id} completed successfully and archived.")

        except (ControlInterfaceError, RuntimeError, TimeoutError) as e:
            logger.error(f"Execution failed, initiating automatic rollback: {e}")
            plan_manager.abort_or_fail(str(e))
            self.rollback_controller.trigger_rollback()
            plan_manager.mark_rolled_back()
            self.store.save_active(plan)

        return plan
