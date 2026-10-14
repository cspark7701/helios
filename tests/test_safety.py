"""Tests for SafetyGatekeeper, RollbackController, and AutonomyPolicyEngine."""

import pytest

from helios.core.schemas import AutonomyLevel, ExecutionPlan, PlanState
from helios.interfaces.channel_map import create_baseline_mebt_channel_manager
from helios.interfaces.epics import MockControlInterface
from helios.safety.gatekeeper import SafetyGatekeeper
from helios.safety.policy import AutonomyPolicyEngine
from helios.safety.rollback import RollbackController


def test_safety_gatekeeper_within_limits():
    """Verify setpoints within limits pass validation."""
    channels = create_baseline_mebt_channel_manager()
    ctrl = MockControlInterface()
    ctrl.set_initial_pv("MPS:GLOBAL:INTERLOCK_OK", 1)

    gatekeeper = SafetyGatekeeper(channel_manager=channels, control_interface=ctrl)

    # Valid setpoints: QD01 within [-50, 50] A, CH01 within [-10, 10] A
    valid_setpoints = {
        "MEBT:PSC:QD01:CurrentSet": 15.0,
        "MEBT:PSC:CH01:CurrentSet": 2.5,
    }
    result = gatekeeper.validate_setpoints(valid_setpoints)
    assert result.is_valid
    assert len(result.errors) == 0


def test_safety_gatekeeper_exceeds_limits():
    """Verify setpoints exceeding limits fail validation."""
    channels = create_baseline_mebt_channel_manager()
    gatekeeper = SafetyGatekeeper(channel_manager=channels)

    # Exceeds max current: CH01 limit is 10.0 A
    bad_setpoints = {
        "MEBT:PSC:CH01:CurrentSet": 18.0,
    }
    result = gatekeeper.validate_setpoints(bad_setpoints)
    assert not result.is_valid
    assert len(result.errors) >= 1
    assert "exceeds hard limits" in result.errors[0]


def test_safety_gatekeeper_mps_interlock_blocked():
    """Verify live actuation is blocked when MPS interlock is active."""
    channels = create_baseline_mebt_channel_manager()
    ctrl = MockControlInterface()
    ctrl.set_initial_pv("MPS:GLOBAL:INTERLOCK_OK", 0)  # Interlock tripped!

    gatekeeper = SafetyGatekeeper(channel_manager=channels, control_interface=ctrl)
    result = gatekeeper.validate_setpoints({"MEBT:PSC:QD01:CurrentSet": 5.0})

    assert not result.is_valid
    assert any("MPS Interlock" in err for err in result.errors)


def test_rollback_controller_checkpoint_and_restore():
    """Verify checkpoint registration and rollback restoration."""
    ctrl = MockControlInterface()
    ctrl.set_initial_pv("MEBT:PSC:QD01:CurrentSet", 10.0)
    ctrl.set_initial_pv("MEBT:PSC:QD01:CurrentAct", 10.0)
    ctrl.set_initial_pv("MEBT:PSC:CH01:CurrentSet", 1.0)
    ctrl.set_initial_pv("MEBT:PSC:CH01:CurrentAct", 1.0)

    rollback = RollbackController(control_interface=ctrl)

    # Capture baseline
    cp_id = rollback.capture_baseline_from_hardware(
        label="Pre-tuning baseline",
        pvs=["MEBT:PSC:QD01:CurrentSet", "MEBT:PSC:CH01:CurrentSet"],
    )
    assert cp_id is not None
    assert len(rollback.list_checkpoints()) == 1

    # Mutate values
    ctrl.put("MEBT:PSC:QD01:CurrentSet", 25.0)
    ctrl.put("MEBT:PSC:CH01:CurrentSet", 5.0)
    assert ctrl.get("MEBT:PSC:QD01:CurrentSet") == 25.0

    # Trigger Rollback
    success = rollback.trigger_rollback()
    assert success is True
    assert ctrl.get("MEBT:PSC:QD01:CurrentSet") == 10.0
    assert ctrl.get("MEBT:PSC:CH01:CurrentSet") == 1.0


def test_autonomy_policy_engine_rules():
    """Verify graduated autonomy permission checks."""
    # Level 0 (Advisory): Cannot write hardware
    assert not AutonomyPolicyEngine.allows_hardware_write(AutonomyLevel.ADVISORY)
    assert AutonomyPolicyEngine.requires_human_signoff_before_execution(AutonomyLevel.ADVISORY)

    # Level 1 (Assisted): Can write, mandates sign-off
    assert AutonomyPolicyEngine.allows_hardware_write(AutonomyLevel.ASSISTED)
    assert AutonomyPolicyEngine.requires_human_signoff_before_execution(AutonomyLevel.ASSISTED)

    # Level 3 (Bounded Auto): Can write, does NOT mandate interactive sign-off
    assert AutonomyPolicyEngine.allows_hardware_write(AutonomyLevel.BOUNDED_AUTONOMOUS)
    assert not AutonomyPolicyEngine.requires_human_signoff_before_execution(AutonomyLevel.BOUNDED_AUTONOMOUS)

    # Plan authorization check
    plan = ExecutionPlan(
        plan_id="00030",
        title="Supervised Steering",
        objective="Flatten orbit",
        autonomy_level=AutonomyLevel.SUPERVISED,
        state=PlanState.SAFETY_APPROVED,
    )

    # Without operator confirmation: rejected
    auth, reason = AutonomyPolicyEngine.evaluate_plan_authorization(plan, operator_confirmed=False)
    assert not auth
    assert "Operator confirmation required" in reason

    # With operator confirmation: authorized
    auth_ok, _ = AutonomyPolicyEngine.evaluate_plan_authorization(plan, operator_confirmed=True)
    assert auth_ok


def test_guarded_control_interface_token_enforcement():
    """Verify GuardedControlInterface blocks unapproved writes and allows tokenized writes."""
    from helios.core.schemas import PlanStep
    from helios.safety.gatekeeper import GuardedControlInterface, SafetyInterlockError

    channels = create_baseline_mebt_channel_manager()
    ctrl = MockControlInterface()
    ctrl.set_initial_pv("MPS:GLOBAL:INTERLOCK_OK", 1)
    gatekeeper = SafetyGatekeeper(channel_manager=channels, control_interface=ctrl)

    guarded = gatekeeper.guarded_control
    assert isinstance(guarded, GuardedControlInterface)

    # 1. Direct write without token fails
    with pytest.raises(SafetyInterlockError) as exc_info:
        guarded.put("MEBT:PSC:CH01:CurrentSet", 2.0)
    assert "no valid SafetyGatekeeper authorization token" in str(exc_info.value)

    # 2. Direct write with invalid token fails
    with pytest.raises(SafetyInterlockError):
        guarded.put("MEBT:PSC:CH01:CurrentSet", 2.0, token="fake-token")

    # 3. Validate setpoints -> mint token -> write succeeds
    val_res = gatekeeper.validate_setpoints({"MEBT:PSC:CH01:CurrentSet": 2.0})
    assert val_res.is_valid
    token = val_res.authorization_token
    assert token is not None

    success = guarded.put("MEBT:PSC:CH01:CurrentSet", 2.0, token=token)
    assert success is True
    assert guarded.get("MEBT:PSC:CH01:CurrentSet") == 2.0

    # 4. Trying to write a different unapproved value with the same token fails
    with pytest.raises(SafetyInterlockError):
        guarded.put("MEBT:PSC:CH01:CurrentSet", 3.0, token=token)


def test_safety_gatekeeper_execute_plan_authorization():
    """Verify SafetyGatekeeper.execute validates plan tokens before actuation."""
    from helios.core.schemas import PlanStep
    from helios.safety.gatekeeper import SafetyInterlockError

    channels = create_baseline_mebt_channel_manager()
    ctrl = MockControlInterface()
    ctrl.set_initial_pv("MPS:GLOBAL:INTERLOCK_OK", 1)
    gatekeeper = SafetyGatekeeper(channel_manager=channels, control_interface=ctrl)

    step = PlanStep(
        step_id="step-1",
        name="Set CH01",
        target_agent="HELIOS-Control",
        action="caput",
        target="MEBT_CH01",
        parameters={"pv": "MEBT:PSC:CH01:CurrentSet", "value": 1.5},
    )
    plan = ExecutionPlan(
        plan_id="00031",
        title="Steering Test",
        objective="Test token execution",
        steps=[step],
    )

    # Executing unvalidated plan without safety token raises SafetyInterlockError
    with pytest.raises(SafetyInterlockError) as exc:
        gatekeeper.execute(plan)
    assert "No approved safety token found" in str(exc.value)

    # Validate setpoints through gatekeeper and attach result
    val_res = gatekeeper.validate_setpoints({"MEBT:PSC:CH01:CurrentSet": 1.5})
    plan.validation_records.append(val_res)

    assert gatekeeper.execute(plan) is True
    assert ctrl.get("MEBT:PSC:CH01:CurrentSet") == 1.5


def test_rollback_controller_failure_paths_and_deletion(tmp_path):
    """Verify rollback failure branches: empty stack, missing ID, and journal deletion."""
    ctrl = MockControlInterface()
    db_path = tmp_path / "rollback.db"
    rc = RollbackController(control_interface=ctrl, journal_path=db_path)

    # 1. Rollback on empty stack returns False
    assert rc.trigger_rollback() is False
    assert rc.trigger_rollback("nonexistent-id") is False

    # 2. Register a checkpoint
    cp_id = rc.create_checkpoint("test_cp", {"MEBT:TEST:PV": 10.0})
    assert len(rc._stack) == 1

    # 3. Requesting a non-matching checkpoint ID returns False
    assert rc.trigger_rollback("wrong_id") is False

    # 4. Deleting checkpoint from journal
    assert rc.journal is not None
    rc.journal.delete_checkpoint(cp_id)
    reloaded = rc.journal.load_all_checkpoints()
    assert len(reloaded) == 0


def test_panic_shutdown_variants(monkeypatch):
    """Verify panic shutdown with explicit PV list and config fallback exception."""
    ctrl = MockControlInterface()
    ctrl.set_initial_pv("CUSTOM:PANIC:01", 5.0)
    ctrl.set_initial_pv("CUSTOM:PANIC:02", 10.0)

    rc = RollbackController(control_interface=ctrl)

    # 1. Custom PV list
    success = rc.panic_shutdown(pvs_to_zero=["CUSTOM:PANIC:01", "CUSTOM:PANIC:02"])
    assert success is True
    assert ctrl.get("CUSTOM:PANIC:01") == 0.0
    assert ctrl.get("CUSTOM:PANIC:02") == 0.0

    # 2. FacilityConfig exception fallback
    from helios.core import facility_config
    monkeypatch.setattr(facility_config.FacilityConfig, "load_default", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Config error")))
    fallback_success = rc.panic_shutdown()
    assert fallback_success is True


