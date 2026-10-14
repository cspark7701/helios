"""Tests for PlanLifecycleManager, state transitions, and PlanArtifactStore."""

from pathlib import Path
import pytest

from helios.core.plan_engine import (
    PlanArtifactStore,
    PlanLifecycleManager,
    PlanStore,
    PlanTransitionError,
)
from helios.core.schemas import (
    AutonomyLevel,
    ExecutionPlan,
    PlanState,
    PlanStep,
    StepStatus,
    ValidationCheck,
    ValidationResult,
)


def test_plan_lifecycle_successful_flow():
    """Verify happy path from DRAFT to COMPLETED with validation gating."""
    plan = ExecutionPlan(
        plan_id="00010",
        title="RFQ Transmission Tune",
        objective="Optimize RFQ transmission to > 95%",
        autonomy_level=AutonomyLevel.ASSISTED,
        state=PlanState.DRAFT,
        steps=[
            PlanStep(
                step_id="step_1",
                name="Solenoid Scan",
                target_agent="HELIOS-Tuner",
                action="scan_solenoids",
            )
        ],
    )
    manager = PlanLifecycleManager(plan)

    # 1. Physics Validation
    phys_val = ValidationResult(
        is_valid=True,
        validator_agent="HELIOS-Physics",
        checks=[ValidationCheck(check_name="Envelope Constraint", passed=True, message="Within chamber aperture")],
    )
    manager.attach_physics_validation(phys_val)
    assert plan.state == PlanState.SIMULATION_VERIFIED

    # 2. Safety Validation
    safety_val = ValidationResult(
        is_valid=True,
        validator_agent="HELIOS-Safety",
        checks=[ValidationCheck(check_name="Power Supply Limits", passed=True, message="Under 150 A max")],
    )
    manager.attach_safety_validation(safety_val)
    assert plan.state == PlanState.SAFETY_APPROVED

    # 3. Execution Authorization (requires operator approval for ASSISTED)
    with pytest.raises(PermissionError):
        manager.authorize_execution(operator_approval=False)

    manager.authorize_execution(operator_approval=True)
    assert plan.state == PlanState.EXECUTING

    # 4. Step execution & Plan completion
    plan.steps[0].status = StepStatus.SUCCESS
    manager.complete_plan()
    assert plan.state == PlanState.COMPLETED


def test_plan_lifecycle_physics_failure():
    """Verify plan marks FAILED when physics validation fails."""
    plan = ExecutionPlan(
        plan_id="00011",
        title="Unsafe Quad Scan",
        objective="Push gradients beyond envelope limits",
        state=PlanState.DRAFT,
    )
    manager = PlanLifecycleManager(plan)

    phys_val = ValidationResult(
        is_valid=False,
        validator_agent="HELIOS-Physics",
        errors=["Beam loss in drift section exceeds 5%"],
    )
    manager.attach_physics_validation(phys_val)
    assert plan.state == PlanState.FAILED


def test_artifact_store_save_and_archive(tmp_path: Path):
    """Test saving plan to active and moving to completed directory."""
    store = PlanArtifactStore(base_dir=tmp_path)
    plan = ExecutionPlan(
        plan_id="00012",
        title="MEBT Steerer Zeroing",
        objective="Zero out all horizontal and vertical steerers",
        state=PlanState.DRAFT,
        steps=[
            PlanStep(
                step_id="s1",
                name="Zero Steerers",
                target_agent="HELIOS-Control",
                action="set_steerers_zero",
            )
        ],
        rollback_targets={"MEBT:PSC:CH01:CurrentSet": 1.5},
    )

    # Save to active
    active_path = store.save_active(plan)
    assert active_path.exists()
    assert "00012_mebt_steerer_zeroing.md" in active_path.name
    content = active_path.read_text(encoding="utf-8")
    assert "MEBT Steerer Zeroing" in content
    assert "Baseline Setpoint" in content

    # Mark completed and archive
    plan.state = PlanState.COMPLETED
    plan.steps[0].status = StepStatus.SUCCESS
    completed_path = store.archive_completed(plan)

    assert not active_path.exists()
    assert completed_path.exists()
    assert "00012_mebt_steerer_zeroing.md" in completed_path.name


def test_plan_store_lifecycle_and_approval(tmp_path: Path):
    """Test PlanStore registration, querying, approval, and rejection."""
    store = PlanStore(base_dir=tmp_path, persist_artifacts=True)
    plan = ExecutionPlan(
        plan_id="00020",
        title="BPM Orbit Steering",
        objective="Steer orbit through BPMs",
        autonomy_level=AutonomyLevel.ASSISTED,
        state=PlanState.SAFETY_APPROVED,
        steps=[PlanStep(step_id="s1", name="Step 1", target_agent="HELIOS-Tuner", action="tune")],
    )
    store.register_plan(plan)

    # Retrieval
    assert store.get_plan("00020") is not None
    assert store.get_manager("00020") is not None
    assert len(store.list_plans()) >= 1

    # Approval transitions plan to EXECUTING
    approved_plan = store.approve_plan("00020", operator_approval=True)
    assert approved_plan.state == PlanState.EXECUTING

    # Rejection transitions plan to FAILED
    rejected_plan = store.reject_plan("00020", reason="Test rejection")
    assert rejected_plan.state == PlanState.FAILED

