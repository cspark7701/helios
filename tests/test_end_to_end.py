"""End-to-End Multi-Agent Integration Tests for HELIOS.

Tests the complete closed-loop orchestration cycle:
Diagnostics -> Tuner -> Physics Validation -> Safety Validation -> Authorization -> Actuation -> Archival.
"""

from pathlib import Path
import pytest

from helios.agents.orchestrator import HeliosOrchestrator
from helios.core.schemas import AutonomyLevel, PlanState, StepStatus
from helios.interfaces.epics import MockControlInterface


def test_end_to_end_orbit_correction_success(tmp_path: Path):
    """Verify complete closed-loop execution of orbit correction workflow."""
    ctrl = MockControlInterface()
    # Initial distorted orbit
    ctrl.set_initial_pv("MEBT:DIAG:BPM01:X_POS", 0.85)
    ctrl.set_initial_pv("MEBT:DIAG:BPM01:Y_POS", -0.40)
    ctrl.set_initial_pv("MEBT:DIAG:BPM02:X_POS", 1.25)
    ctrl.set_initial_pv("MEBT:DIAG:BPM02:Y_POS", -0.70)
    # Steerer baseline
    ctrl.set_initial_pv("MEBT:PSC:CH01:CurrentSet", 0.0)
    ctrl.set_initial_pv("MEBT:PSC:CH01:CurrentAct", 0.0)

    orch = HeliosOrchestrator(control_interface=ctrl, base_dir=tmp_path)

    plan = orch.run_orbit_correction_loop(
        plan_id="00050",
        section="MEBT",
        steerers=["MEBT_CH01"],
        bpms=["MEBT_BPM01", "MEBT_BPM02"],
        autonomy_level=AutonomyLevel.BOUNDED_AUTONOMOUS,
        operator_confirmed=True,
    )

    # 1. Plan State is COMPLETED
    assert plan.state == PlanState.COMPLETED
    assert len(plan.steps) >= 1
    assert plan.steps[0].status == StepStatus.SUCCESS

    # 2. Physics & Safety Validations Attached and Passed
    assert len(plan.validation_records) == 2
    assert all(v.is_valid for v in plan.validation_records)

    # 3. Hardware Setpoint Updated
    assert ctrl.get("MEBT:PSC:CH01:CurrentSet") != 0.0

    # 4. Plan Artifact archived in completed/
    completed_file = tmp_path / "docs" / "exec-plans" / "completed" / "00050_mebt_orbit_trajectory_correction.md"
    assert completed_file.exists()


def test_end_to_end_permission_withheld(tmp_path: Path):
    """Verify plan stops and waits when operator confirmation is withheld."""
    ctrl = MockControlInterface()
    orch = HeliosOrchestrator(control_interface=ctrl, base_dir=tmp_path)

    plan = orch.run_orbit_correction_loop(
        plan_id="00051",
        section="MEBT",
        autonomy_level=AutonomyLevel.SUPERVISED,
        operator_confirmed=False,  # Denied!
    )

    # Should remain in SAFETY_APPROVED and NOT execute
    assert plan.state == PlanState.SAFETY_APPROVED
    assert all(s.status == StepStatus.PENDING for s in plan.steps)
