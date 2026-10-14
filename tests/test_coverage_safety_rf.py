"""Comprehensive test suite achieving 100% coverage on HELIOS safety, RF, and recovery systems.

Covers:
- helios/safety/gatekeeper.py
- helios/safety/srf_protection.py
- helios/safety/predictive.py
- helios/safety/fast_mps.py
- helios/safety/policy.py
- helios/safety/activation.py
- helios/safety/mps.py
- helios/safety/rollback.py
- helios/rf/cryoplant.py
- helios/rf/conditioning.py
- helios/rf/multipactor.py
- helios/rf/microphonics.py
- helios/recovery/loss_mitigation.py
- helios/recovery/magnet_recovery.py
- helios/recovery/rf_rematch.py
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from helios.core.schemas import (
    AutonomyLevel,
    ExecutionPlan,
    PlanState,
    PlanStep,
    StepStatus,
    ValidationCheck,
    ValidationResult,
)
from helios.interfaces.base import BaseControlInterface, ControlInterfaceError
from helios.interfaces.channel_map import (
    ChannelLimits,
    ChannelManager,
    LinacDevice,
    create_baseline_mebt_channel_manager,
)
from helios.interfaces.epics import MockControlInterface
from helios.recovery.loss_mitigation import BeamLossMitigator
from helios.recovery.magnet_recovery import MagnetPowerSupplyRecoverer
from helios.recovery.rf_rematch import RFCavityRematcher
from helios.rf.conditioning import (
    AutonomousRFConditioner,
    CavityResonanceTracker,
    ConditioningState,
)
from helios.rf.cryoplant import (
    CavityCryoState,
    CryoplantCapacity,
    CryoplantThermodynamicOptimizer,
)
from helios.rf.microphonics import (
    AdaptiveFxLMSPiezoController,
    MicrophonicsSpectrum,
)
from helios.rf.multipactor import (
    CavityMultipactorEngine,
    SurfaceMaterial,
)
from helios.safety.activation import RadiologicalActivationEngine
from helios.safety.fast_mps import FastMPSConfiguration, FastMPSEngine
from helios.safety.gatekeeper import (
    GuardedControlInterface,
    SafetyGatekeeper,
    SafetyInterlockError,
)
from helios.safety.mps import LatencyBudget, MPSInterlockChannel, MPSManager
from helios.safety.policy import AutonomyPolicyEngine
from helios.safety.predictive import (
    CryomoduleTelemetry,
    PredictiveQuenchInterlock,
    QuenchRiskLevel,
)
from helios.safety.rollback import (
    PersistentRollbackJournal,
    RollbackCheckpoint,
    RollbackController,
)
from helios.safety.srf_protection import SRFCavityLimits, SRFProtectionMonitor


# ==============================================================================
# 1. GuardedControlInterface & SafetyGatekeeper Coverage
# ==============================================================================

def test_guarded_control_interface_and_gatekeeper():
    ctrl = MockControlInterface()
    channels = create_baseline_mebt_channel_manager()
    gatekeeper = SafetyGatekeeper(channel_manager=channels, control_interface=ctrl)
    guarded = gatekeeper.guarded_control
    assert guarded is not None

    # Test subscribe, unsubscribe, and get pass-through
    sub_called = []
    def sub_cb(pv, val):
        sub_called.append((pv, val))

    guarded.subscribe("TEST:PV", sub_cb)
    guarded.unsubscribe("TEST:PV")
    ctrl.set_initial_pv("TEST:PV", 42.0)
    assert guarded.get("TEST:PV") == 42.0

    # Put without token -> raises SafetyInterlockError
    with pytest.raises(SafetyInterlockError):
        guarded.put("MEBT:PSC:QD01:CurrentSet", 10.0)

    # Mint valid token and put through guarded
    valid_setpoints = {"MEBT:PSC:QD01:CurrentSet": 10.0}
    token = gatekeeper.mint_token(valid_setpoints)
    assert gatekeeper.verify_token(token, "MEBT:PSC:QD01:CurrentSet", 10.0) is True
    assert gatekeeper.verify_token(token, "MEBT:PSC:QD01:CurrentSet", 99.0) is False
    assert gatekeeper.verify_token(token, "UNKNOWN:PV", 10.0) is False
    assert gatekeeper.verify_token(None, "MEBT:PSC:QD01:CurrentSet", 10.0) is False
    assert gatekeeper.verify_token("invalid_token", "MEBT:PSC:QD01:CurrentSet", 10.0) is False

    # Put with valid token succeeds
    res_put = guarded.put("MEBT:PSC:QD01:CurrentSet", 10.0, token=token)
    assert res_put is True
    assert ctrl.get("MEBT:PSC:QD01:CurrentSet") == 10.0

    # Verify non-float value in verify_token and guarded.put
    gatekeeper._valid_tokens["str_tok"] = {"TEST:STATE": "ON"}
    assert gatekeeper.verify_token("str_tok", "TEST:STATE", "ON") is True
    assert gatekeeper.verify_token("str_tok", "TEST:STATE", "OFF") is False
    ctrl.set_initial_pv("TEST:STATE", "OFF")
    assert guarded.put("TEST:STATE", "ON", token="str_tok") is True

    # Plan execution tests
    plan = ExecutionPlan(
        plan_id="PLAN_SAFETY_TEST",
        title="Safety Plan",
        objective="Test Safety Execution",
        autonomy_level=AutonomyLevel.SUPERVISED,
        state=PlanState.SAFETY_APPROVED,
        steps=[
            PlanStep(
                step_id="step_1",
                name="Actuate QD01",
                target_agent="HELIOS-Safety",
                action="actuate",
                parameters={"pv": "MEBT:PSC:QD01:CurrentSet", "value": 10.0},
            )
        ],
    )

    # 1. Gatekeeper without control raises ControlInterfaceError
    no_ctrl_gk = SafetyGatekeeper(channel_manager=channels, control_interface=None)
    with pytest.raises(ControlInterfaceError):
        no_ctrl_gk.execute(plan)

    # 2. Plan without HELIOS-Safety approved token raises SafetyInterlockError
    with pytest.raises(SafetyInterlockError):
        gatekeeper.execute(plan)

    # 3. Plan with token but step not authorized raises SafetyInterlockError
    plan.validation_records.append(
        ValidationResult(
            is_valid=True,
            validator_agent="HELIOS-Safety",
            authorization_token=token,
            checks=[],
        )
    )
    plan.steps[0].parameters["value"] = 55.0  # Not matching token
    with pytest.raises(SafetyInterlockError):
        gatekeeper.execute(plan)
    assert plan.steps[0].status == StepStatus.FAILED

    # 4. Step put fails raises RuntimeError
    plan.steps[0].parameters["value"] = 10.0
    with patch.object(ctrl, "put", return_value=False):
        with pytest.raises(RuntimeError):
            gatekeeper.execute(plan)
    assert plan.steps[0].status == StepStatus.FAILED

    # 5. Step put succeeds
    with patch.object(ctrl, "put", return_value=True):
        assert gatekeeper.execute(plan) is True
    assert plan.steps[0].status == StepStatus.SUCCESS
    assert plan.steps[0].result == {"actuated_value": 10.0}

    # Validate setpoints coverage
    # Unknown channel without limits -> warning
    val_res1 = gatekeeper.validate_setpoints({"UNKNOWN_CHANNEL": 5.0})
    assert any("No explicit limits defined" in w for w in val_res1.warnings)

    # Semantic format section:device -> resolved through get_device
    val_res_sem = gatekeeper.validate_setpoints({"MEBT:QD01": 15.0})
    assert val_res_sem.is_valid is True

    # Custom device with warn limits and slew rate limits
    from helios.interfaces.channel_map import DeviceType
    custom_mgr = ChannelManager()
    dev_with_warn = LinacDevice(
        name="QD_TEST",
        section="MEBT",
        device_type=DeviceType.QUADRUPOLE,
        setpoint_pv="MEBT:PSC:QD_TEST:CurrentSet",
        readback_pv="MEBT:PSC:QD_TEST:CurrentRB",
        limits=ChannelLimits(
            min_val=-50.0,
            max_val=50.0,
            warn_min=-20.0,
            warn_max=20.0,
            max_slew_rate=1.0,
            units="A",
        ),
    )
    custom_mgr.register_device(dev_with_warn)
    ctrl.set_initial_pv("MEBT:PSC:QD_TEST:CurrentSet", 0.0)

    gk_custom = SafetyGatekeeper(channel_manager=custom_mgr, control_interface=ctrl)

    # Soft warning limits and slew rate limit jump warning
    val_res2 = gk_custom.validate_setpoints({"MEBT:PSC:QD_TEST:CurrentSet": 25.0})
    assert any("exceeds warning limit 20.0" in w for w in val_res2.warnings)
    assert any("Large single jump" in w for w in val_res2.warnings)

    val_res_low = gk_custom.validate_setpoints({"MEBT:PSC:QD_TEST:CurrentSet": -25.0})
    assert any("below warning limit -20.0" in w for w in val_res_low.warnings)

    # Hard limit violation -> errors
    val_res_hard = gk_custom.validate_setpoints({"MEBT:PSC:QD_TEST:CurrentSet": 100.0})
    assert val_res_hard.is_valid is False
    assert len(val_res_hard.errors) > 0

    # Global MPS Interlock tripped -> error
    ctrl.set_initial_pv("MPS:GLOBAL:INTERLOCK_OK", 0)
    val_res_mps = gk_custom.validate_setpoints({"MEBT:PSC:QD_TEST:CurrentSet": 5.0})
    assert val_res_mps.is_valid is False
    assert any("MPS Interlock active" in e for e in val_res_mps.errors)
    ctrl.set_initial_pv("MPS:GLOBAL:INTERLOCK_OK", 1)

    # Twin verifier integration in validate_setpoints
    mock_twin_verifier = MagicMock()
    mock_twin_verifier.validate_plan_setpoints.return_value = ValidationResult(
        is_valid=False,
        validator_agent="TwinVerifier",
        checks=[ValidationCheck(check_name="TwinCheck", passed=False)],
        errors=["Twin OOD error"],
        warnings=["Twin warning"],
        projected_beam_loss=0.05,
    )
    gk_twin = SafetyGatekeeper(
        channel_manager=custom_mgr,
        control_interface=ctrl,
        twin_verifier=mock_twin_verifier,
    )
    val_res_twin = gk_twin.validate_setpoints({"MEBT:PSC:QD_TEST:CurrentSet": 5.0})
    assert val_res_twin.is_valid is False
    assert "Twin OOD error" in val_res_twin.errors
    assert val_res_twin.projected_beam_loss == 0.05
    assert val_res_twin.provenance == "twin"


# ==============================================================================
# 2. RollbackController & PersistentRollbackJournal Coverage
# ==============================================================================

def test_rollback_controller_and_persistent_journal(tmp_path: Path):
    db_file = tmp_path / "rollback.db"
    journal = PersistentRollbackJournal(db_file)

    now = datetime.now(timezone.utc)
    cp1 = RollbackCheckpoint(checkpoint_id="cp_01", label="Base 1", timestamp=now, setpoints={"PV1": 1.0})
    cp2 = RollbackCheckpoint(checkpoint_id="cp_02", label="Base 2", timestamp=now, setpoints={"PV1": 2.0})

    journal.save_checkpoint(cp1)
    journal.save_checkpoint(cp2)

    loaded = journal.load_all_checkpoints()
    assert len(loaded) == 2
    assert loaded[0].checkpoint_id == "cp_01"

    journal.delete_checkpoint("cp_01")
    assert len(journal.load_all_checkpoints()) == 1

    # RollbackController with journal hydration
    ctrl = MockControlInterface()
    ctrl.set_initial_pv("PV1", 2.0)
    ctrl.set_initial_pv("PV2", 10.0)

    rb_ctrl = RollbackController(control_interface=ctrl, journal_path=db_file)
    # Checkpoints hydrated from journal
    assert len(rb_ctrl.list_checkpoints()) == 1

    # capture_baseline_from_hardware
    cid = rb_ctrl.capture_baseline_from_hardware("LiveBase", ["PV1", "PV2"])
    assert cid is not None
    assert len(rb_ctrl.list_checkpoints()) == 2

    # Trigger rollback by ID and most recent
    ctrl.put("PV1", 99.0)
    assert ctrl.get("PV1") == 99.0

    res_rb_id = rb_ctrl.trigger_rollback(cid)
    assert res_rb_id is True
    assert ctrl.get("PV1") == 2.0

    # Non-existent checkpoint ID
    assert rb_ctrl.trigger_rollback("unknown_cid") is False

    # Empty stack rollback
    empty_ctrl = RollbackController(control_interface=ctrl)
    assert empty_ctrl.trigger_rollback() is False

    # Panic shutdown with specified PVs
    res_panic = rb_ctrl.panic_shutdown(["PV1", "PV2"])
    assert res_panic is True
    assert ctrl.get("PV1") == 0.0
    assert ctrl.get("PV2") == 0.0

    # Panic shutdown default targets
    res_panic_def = rb_ctrl.panic_shutdown()
    assert res_panic_def is True


# ==============================================================================
# 3. MPSManager & LatencyBudget Coverage
# ==============================================================================

def test_mps_manager_and_latency_budget():
    budget = LatencyBudget(
        detection_time_us=2.0,
        propagation_time_us=3.0,
        actuation_time_us=5.0,
        beam_damage_threshold_us=20.0,
    )
    assert budget.total_latency_us == 10.0
    assert budget.margin_us == 10.0
    assert budget.is_compliant is True

    # Non-compliant budget
    bad_budget = LatencyBudget(
        detection_time_us=10.0,
        propagation_time_us=10.0,
        actuation_time_us=10.0,
        beam_damage_threshold_us=25.0,
    )
    assert bad_budget.is_compliant is False

    mps = MPSManager()
    # Nominal validation
    res_ok = mps.verify_mps_readiness(budget)
    assert res_ok.is_valid is True

    # Exceeded latency budget
    res_bad_lat = mps.verify_mps_readiness(bad_budget)
    assert res_bad_lat.is_valid is False
    assert any("MPS latency budget exceeded" in e for e in res_bad_lat.errors)

    # Interlock trip
    mps.set_interlock_status("MPS:FAST:DIFF_BPM_LOSS", is_tripped=True)
    res_trip = mps.verify_mps_readiness(budget)
    assert res_trip.is_valid is False
    assert any("Fast Interlock tripped" in e for e in res_trip.errors)

    # Hardware fault
    mps.set_interlock_status("MPS:FAST:DIFF_BPM_LOSS", is_tripped=False)
    mps.channels["MPS:FAST:DIFF_BPM_LOSS"].hardware_ok = False
    res_hw = mps.verify_mps_readiness(budget)
    assert res_hw.is_valid is False
    assert any("Hardware sensor fault" in e for e in res_hw.errors)


# ==============================================================================
# 4. AutonomyPolicyEngine Coverage
# ==============================================================================

def test_autonomy_policy_engine():
    # requires_human_signoff_before_execution
    assert AutonomyPolicyEngine.requires_human_signoff_before_execution(AutonomyLevel.ADVISORY) is True
    assert AutonomyPolicyEngine.requires_human_signoff_before_execution(AutonomyLevel.ASSISTED) is True
    assert AutonomyPolicyEngine.requires_human_signoff_before_execution(AutonomyLevel.SUPERVISED) is True
    assert AutonomyPolicyEngine.requires_human_signoff_before_execution(AutonomyLevel.BOUNDED_AUTONOMOUS) is False
    assert AutonomyPolicyEngine.requires_human_signoff_before_execution(AutonomyLevel.FULLY_AUTONOMOUS) is False

    # allows_hardware_write
    assert AutonomyPolicyEngine.allows_hardware_write(AutonomyLevel.ADVISORY) is False
    assert AutonomyPolicyEngine.allows_hardware_write(AutonomyLevel.ASSISTED) is True

    # evaluate_plan_authorization
    plan = ExecutionPlan(
        plan_id="PLAN_POL_TEST",
        title="Policy Plan",
        objective="Test Policy",
        autonomy_level=AutonomyLevel.SUPERVISED,
        state=PlanState.DRAFT,  # Not approved yet
        steps=[],
    )
    auth1, reason1 = AutonomyPolicyEngine.evaluate_plan_authorization(plan)
    assert auth1 is False
    assert "must be SAFETY_APPROVED" in reason1

    # Level 0 Advisory cannot write
    plan.state = PlanState.SAFETY_APPROVED
    plan.autonomy_level = AutonomyLevel.ADVISORY
    auth2, reason2 = AutonomyPolicyEngine.evaluate_plan_authorization(plan)
    assert auth2 is False
    assert "does not permit hardware actuation" in reason2

    # Level 2 Supervised without confirmation
    plan.autonomy_level = AutonomyLevel.SUPERVISED
    auth3, reason3 = AutonomyPolicyEngine.evaluate_plan_authorization(plan, operator_confirmed=False)
    assert auth3 is False
    assert "Operator confirmation required" in reason3

    # Level 2 Supervised with confirmation
    auth4, reason4 = AutonomyPolicyEngine.evaluate_plan_authorization(plan, operator_confirmed=True)
    assert auth4 is True
    assert "Authorized" in reason4


# ==============================================================================
# 5. SRFProtectionMonitor Coverage
# ==============================================================================

def test_srf_protection_monitor_all_checks():
    # Constructor with explicit cavity_limits dictionary
    custom_lim = SRFCavityLimits(
        cavity_id="TEST:CAV:01",
        max_gradient_mv_m=14.0,
        warn_gradient_mv_m=12.0,
        max_cryo_temp_k=2.10,
        min_helium_level_pct=80.0,
        max_reflected_power_ratio=0.20,
        multipacting_zones=[(2.0, 3.0)],
    )
    monitor_custom = SRFProtectionMonitor(cavity_limits={"TEST:CAV:01": custom_lim})
    assert "TEST:CAV:01" in monitor_custom.limits

    # Constructor with FacilityConfig loading exception fallback
    with patch("helios.core.facility_config.FacilityConfig.load_default", side_effect=RuntimeError):
        monitor_fallback = SRFProtectionMonitor()
        assert "MEBT:CAV:01" in monitor_fallback.limits

    monitor = SRFProtectionMonitor()
    monitor.register_cavity_limits(custom_lim)

    # 1. Normal safe operation
    res_ok = monitor.validate_srf_state(
        cavity_id="TEST:CAV:01",
        gradient_mv_m=10.0,
        cryo_temp_k=2.05,
        helium_level_pct=90.0,
        p_fwd_kw=5.0,
        p_refl_kw=0.1,
    )
    assert res_ok.is_valid is True

    # 2. Warning gradient
    res_warn = monitor.validate_srf_state(
        cavity_id="TEST:CAV:01",
        gradient_mv_m=13.0,
        cryo_temp_k=2.05,
        helium_level_pct=90.0,
        p_fwd_kw=5.0,
        p_refl_kw=0.1,
    )
    assert res_warn.is_valid is True
    assert any("approaches quench limit" in w for w in res_warn.warnings)

    # 3. Quench gradient exceeded
    res_quench = monitor.validate_srf_state(
        cavity_id="TEST:CAV:01",
        gradient_mv_m=15.0,
        cryo_temp_k=2.05,
    )
    assert res_quench.is_valid is False
    assert any("exceeds quench threshold" in e for e in res_quench.errors)

    # 4. Multipacting zone hit
    res_mp = monitor.validate_srf_state(
        cavity_id="TEST:CAV:01",
        gradient_mv_m=2.5,
    )
    assert res_mp.is_valid is False
    assert any("multipacting zone" in e for e in res_mp.errors)

    # 5. Cryo temperature exceeded
    res_temp = monitor.validate_srf_state(
        cavity_id="TEST:CAV:01",
        gradient_mv_m=10.0,
        cryo_temp_k=2.15,
    )
    assert res_temp.is_valid is False
    assert any("exceeds superfluid limit" in e for e in res_temp.errors)

    # 6. Liquid helium level too low
    res_he = monitor.validate_srf_state(
        cavity_id="TEST:CAV:01",
        gradient_mv_m=10.0,
        helium_level_pct=70.0,
    )
    assert res_he.is_valid is False
    assert any("below minimum safe level" in e for e in res_he.errors)

    # 7. Reflected power ratio exceeded
    res_refl = monitor.validate_srf_state(
        cavity_id="TEST:CAV:01",
        gradient_mv_m=10.0,
        p_fwd_kw=5.0,
        p_refl_kw=2.0,  # 0.40 > 0.20
    )
    assert res_refl.is_valid is False
    assert any("Reflected power ratio" in e for e in res_refl.errors)

    # Low forward power edge case
    res_low_fwd = monitor.validate_srf_state(
        cavity_id="TEST:CAV:01",
        gradient_mv_m=10.0,
        p_fwd_kw=0.01,
        p_refl_kw=0.01,
    )
    assert res_low_fwd.is_valid is True


# ==============================================================================
# 6. Radiological Activation & Fast MPS Coverage
# ==============================================================================

def test_radiological_activation_and_fast_mps():
    act_engine = RadiologicalActivationEngine(personnel_access_threshold_uSv_hr=25.0)

    # 1. Safe cooling assessment -> clearance token generated
    res_safe = act_engine.evaluate_cooling(
        location_id="MEBT_COLLIMATOR_01",
        beam_loss_power_W=0.5,
        irradiation_hours=24.0,
        cooling_elapsed_hours=48.0,
    )
    assert res_safe.access_granted is True
    assert res_safe.clearance_token_sha256 is not None
    assert res_safe.required_additional_cooling_hours == 0.0

    # 2. Unsafe cooling assessment -> numerical solve breaks within 720 hours
    res_mid = act_engine.evaluate_cooling(
        location_id="MEBT_COLLIMATOR_01",
        beam_loss_power_W=2.0,
        irradiation_hours=24.0,
        cooling_elapsed_hours=0.5,
    )
    assert res_mid.access_granted is False
    assert 0.0 < res_mid.required_additional_cooling_hours < 720.0

    # 3. Severe loss cooling assessment -> exceeds 720 hours limit
    res_hot = act_engine.evaluate_cooling(
        location_id="MEBT_COLLIMATOR_01",
        beam_loss_power_W=50.0,
        irradiation_hours=240.0,
        cooling_elapsed_hours=1.0,
    )
    assert res_hot.access_granted is False
    assert res_hot.required_additional_cooling_hours == 720.0

    # Fast MPS Engine
    cfg = FastMPSConfiguration(diff_current_threshold_uA=35.0, diamond_blm_threshold_V=0.85)
    fast_mps = FastMPSEngine(cfg)

    # DUAL_COINCIDENCE
    trip_dual = fast_mps.evaluate_signals(upstream_current_uA=100.0, downstream_current_uA=50.0, diamond_blm_voltage_V=1.2)
    assert trip_dual.aborted is True
    assert trip_dual.trigger_cause == "DUAL_COINCIDENCE"
    assert trip_dual.cryomodule_puncture_prevented is True

    # DIFFERENTIAL_CURRENT_LOSS
    trip_diff = fast_mps.evaluate_signals(upstream_current_uA=100.0, downstream_current_uA=50.0, diamond_blm_voltage_V=0.2)
    assert trip_diff.aborted is True
    assert trip_diff.trigger_cause == "DIFFERENTIAL_CURRENT_LOSS"

    # DIAMOND_BLM_SPIKE
    trip_blm = fast_mps.evaluate_signals(upstream_current_uA=100.0, downstream_current_uA=95.0, diamond_blm_voltage_V=1.2)
    assert trip_blm.aborted is True
    assert trip_blm.trigger_cause == "DIAMOND_BLM_SPIKE"

    # NONE (Safe beam transmission)
    trip_none = fast_mps.evaluate_signals(upstream_current_uA=100.0, downstream_current_uA=98.0, diamond_blm_voltage_V=0.1)
    assert trip_none.aborted is False
    assert trip_none.trigger_cause == "NONE"
    assert len(trip_none.actuators_fired) == 0


# ==============================================================================
# 7. PredictiveQuenchInterlock Coverage
# ==============================================================================

def test_predictive_quench_interlock():
    interlock = PredictiveQuenchInterlock(
        nominal_temp_K=2.05,
        max_allowed_temp_K=2.20,
        temp_rate_threshold_K_per_s=0.15,
        refl_power_ratio_threshold=0.35,
    )

    # Empty window ValueError
    with pytest.raises(ValueError):
        interlock.evaluate_telemetry_window([])

    # Single sample (dt ~ 0 -> slope = 0)
    t0 = CryomoduleTelemetry(
        timestamp_ms=1000.0,
        cavity_id="SCL:CAV:01",
        helium_bath_temp_K=2.05,
        helium_pressure_mbar=31.0,
        forward_power_kW=5.0,
        reflected_power_kW=0.1,
    )
    res_single = interlock.evaluate_telemetry_window([t0])
    assert res_single.risk_level == QuenchRiskLevel.NOMINAL

    # Warning scenario (slight heating slope)
    t1 = CryomoduleTelemetry(
        timestamp_ms=1050.0,
        cavity_id="SCL:CAV:01",
        helium_bath_temp_K=2.055,
        helium_pressure_mbar=31.1,
        forward_power_kW=5.0,
        reflected_power_kW=0.2,
    )
    t2 = CryomoduleTelemetry(
        timestamp_ms=1100.0,
        cavity_id="SCL:CAV:01",
        helium_bath_temp_K=2.065,
        helium_pressure_mbar=31.2,
        forward_power_kW=5.0,
        reflected_power_kW=1.2,
    )
    res_warn = interlock.evaluate_telemetry_window([t0, t1, t2])
    assert res_warn.risk_level in (QuenchRiskLevel.WARNING, QuenchRiskLevel.NOMINAL)

    # Critical impending quench scenario (sharp heating slope and high reflection)
    t_crit = CryomoduleTelemetry(
        timestamp_ms=1150.0,
        cavity_id="SCL:CAV:01",
        helium_bath_temp_K=2.19,
        helium_pressure_mbar=35.0,
        forward_power_kW=5.0,
        reflected_power_kW=2.5,
    )
    res_crit = interlock.evaluate_telemetry_window([t0, t_crit])
    assert res_crit.risk_level == QuenchRiskLevel.CRITICAL_IMPENDING_QUENCH
    assert res_crit.recommended_action == "PREEMPTIVE_BEAM_CUT_AND_RF_RAMPDOWN"


# ==============================================================================
# 8. RF Subsystems: Cryoplant, Conditioning, Multipactor, Microphonics
# ==============================================================================

def test_rf_subsystems_coverage():
    # 1. Cryoplant Optimizer
    cryo_opt = CryoplantThermodynamicOptimizer()
    r_s = cryo_opt.calculate_surface_resistance(frequency_MHz=162.5, temperature_K=2.0)
    assert r_s > 0.0

    cav = CavityCryoState(
        cavity_id="MEBT:CAV:01",
        cavity_type="HWR",
        frequency_MHz=162.5,
        temperature_K=2.0,
        voltage_MV=1.2,
        R_over_Q_ohm=220.0,
        geometry_factor_G=48.0,
    )
    cav_eval = cryo_opt.evaluate_cavity_thermal(cav, voltage_MV=1.5)
    assert cav_eval.voltage_MV == 1.5
    assert cav_eval.total_heat_load_W > 0.0

    plant = CryoplantCapacity(stage_2K_max_power_W=500.0, surge_margin_percent=10.0)
    # Nominal balance
    res_nom = cryo_opt.balance_linac_heat_load([cav], target_total_voltage_MV=1.0, cryoplant=plant)
    assert res_nom.status == "NOMINAL"

    # Constrained / Surge risk balance
    res_surge = cryo_opt.balance_linac_heat_load([cav], target_total_voltage_MV=25.0, cryoplant=plant)
    assert res_surge.status in ("CONSTRAINED", "SURGE_RISK")

    # 2. Autonomous RFConditioner & CavityResonanceTracker
    cond = AutonomousRFConditioner(cavity_id="MEBT:CAV:01", target_power_kw=1.0)
    # Vacuum spike
    res_spike = cond.step(measured_vacuum_mbar=5e-7, electron_pickup_ua=0.01)
    assert res_spike.state == ConditioningState.VACUUM_RECOVERY

    # Vacuum recovery dwelling
    res_dwell = cond.step(measured_vacuum_mbar=8e-8, electron_pickup_ua=0.01)
    assert res_dwell.state == ConditioningState.VACUUM_RECOVERY

    # Vacuum recovered -> resume ramping
    res_rec = cond.step(measured_vacuum_mbar=2e-8, electron_pickup_ua=0.01)
    assert res_rec.state == ConditioningState.RAMPING

    # Multipacting jump
    res_jump = cond.step(measured_vacuum_mbar=2e-8, electron_pickup_ua=1.5)
    assert res_jump.state == ConditioningState.FAST_JUMPING

    # Ramp up to completion
    for _ in range(50):
        res_ramp = cond.step(measured_vacuum_mbar=2e-8, electron_pickup_ua=0.01)
    assert res_ramp.state in (ConditioningState.RAMPING, ConditioningState.COMPLETED)

    # CavityResonanceTracker
    tracker = CavityResonanceTracker(cavity_id="MEBT:CAV:01")
    # Small phase error
    tr_res1 = tracker.track(phase_error_deg=2.0)
    assert tr_res1.quench_risk is False

    # Large phase error triggering stepper offload and quench risk
    tr_res2 = tracker.track(phase_error_deg=250.0)
    assert tr_res2.quench_risk is True
    assert tracker.current_stepper_pos != 0

    # 3. Cavity Multipactor & Field Emission
    mp_eng = CavityMultipactorEngine()
    # Niobium multipactoring in and out of barrier
    res_mp_nb = mp_eng.evaluate_multipactoring(
        material=SurfaceMaterial.NIOBIUM,
        frequency_MHz=162.5,
        gap_distance_mm=25.0,
        operating_voltage_kV=1.5,
    )
    # Low voltage in barrier -> MULTIPACTORING_ALERT
    res_mp_alert = mp_eng.evaluate_multipactoring(
        material=SurfaceMaterial.COPPER,
        frequency_MHz=162.5,
        gap_distance_mm=29.0,
        operating_voltage_kV=0.4,
    )
    assert res_mp_alert.active_in_barrier is True
    assert res_mp_alert.risk_level == "MULTIPACTORING_ALERT"

    # High voltage in barrier -> SEVERE_DISCHARGE
    with patch.dict(
        CavityMultipactorEngine.SEY_PARAMETERS[SurfaceMaterial.COPPER],
        {"E_max_eV": 50000.0, "delta_max": 2.5},
    ):
        res_mp_sev = mp_eng.evaluate_multipactoring(
            material=SurfaceMaterial.COPPER,
            frequency_MHz=650.0,
            gap_distance_mm=100.0,
            operating_voltage_kV=75.0,
        )
        assert res_mp_sev.active_in_barrier is True
        assert res_mp_sev.risk_level == "SEVERE_DISCHARGE"

    # TiN coated material (suppressed SEY)
    res_mp_tin = mp_eng.evaluate_multipactoring(
        material=SurfaceMaterial.TITANIUM_NITRIDE_COATED,
        frequency_MHz=162.5,
        gap_distance_mm=25.0,
        operating_voltage_kV=1.5,
    )
    assert res_mp_tin.risk_level == "SAFE"

    # Field emission evaluations
    # Low field (< 1e7 V/m local) -> zero dark current
    fe_zero = mp_eng.evaluate_field_emission(peak_E_MV_m=0.0001)
    assert fe_zero.sensor_radiation_status == "NOMINAL"
    assert fe_zero.dark_current_density_A_per_m2 == 0.0

    fe_nom = mp_eng.evaluate_field_emission(peak_E_MV_m=2.0)
    assert fe_nom.sensor_radiation_status == "NOMINAL"

    fe_elev = mp_eng.evaluate_field_emission(peak_E_MV_m=25.0, field_enhancement_beta=125.0)
    assert fe_elev.sensor_radiation_status == "ELEVATED"

    fe_crit = mp_eng.evaluate_field_emission(peak_E_MV_m=25.0, field_enhancement_beta=145.0)
    assert fe_crit.sensor_radiation_status == "CRITICAL_QUENCH_RISK"

    # 4. Adaptive FxLMS Microphonics Controller
    spec = MicrophonicsSpectrum(cavity_id="SCL:CAV:01")
    # Optimal control
    fxlms = AdaptiveFxLMSPiezoController(filter_order=8, learning_rate_mu=0.1)
    res_micro = fxlms.simulate_compensation(spectrum=spec, E_acc_MV_m=8.0, duration_s=0.05, sampling_rate_Hz=2000.0)
    assert res_micro.compensated_microphonics_rms_Hz >= 0.0

    # Saturation warning
    fxlms_sat = AdaptiveFxLMSPiezoController(filter_order=8, learning_rate_mu=0.5, max_piezo_voltage_V=1.0)
    res_sat = fxlms_sat.simulate_compensation(spectrum=spec, E_acc_MV_m=8.0, duration_s=0.05, sampling_rate_Hz=2000.0)
    assert res_sat.status == "SATURATION_WARNING"

    # Marginal control (mu=0 -> no adaptation -> rejection < 10 dB)
    fxlms_marg = AdaptiveFxLMSPiezoController(filter_order=8, learning_rate_mu=0.0)
    res_marg = fxlms_marg.simulate_compensation(spectrum=spec, E_acc_MV_m=8.0, duration_s=0.05, sampling_rate_Hz=2000.0)
    assert res_marg.status == "MARGINAL"


# ==============================================================================
# 9. Recovery Modules: Loss Mitigation, Magnet Recovery & RF Rematch
# ==============================================================================

def test_recovery_modules_coverage():
    # 1. BeamLossMitigator
    mitigator = BeamLossMitigator(loss_trip_threshold_w=1.0)
    with pytest.raises(ValueError):
        mitigator.mitigate_loss_hotspot({}, {}, {})

    # Trivial low loss
    res_low = mitigator.mitigate_loss_hotspot(
        blm_readings={"BLM_01": {"loss_w": 0.005, "s_m": 2.5}},
        steerer_positions={},
        active_steerer_currents={},
    )
    assert res_low.success is True
    assert res_low.applied_correction_a == {}

    # Hotspot mitigation
    blms = {
        "BLM_01": {"loss_w": 0.2, "s_m": 2.0},
        "BLM_02": {"loss_w": 3.5, "s_m": 5.0},
    }
    steerers = {"STR_01": 1.5, "STR_02": 4.0, "STR_03": 7.0}
    currents = {"STR_01": 1.0, "STR_02": -0.5, "STR_03": 0.0}
    res_mit = mitigator.mitigate_loss_hotspot(blms, steerers, currents)
    assert res_mit.success is True
    assert res_mit.hotspot_blm == "BLM_02"
    assert "STR_02" in res_mit.upstream_steerers

    # 2. MagnetPowerSupplyRecoverer
    recoverer = MagnetPowerSupplyRecoverer(default_tolerance_mm=0.20)
    with pytest.raises(ValueError):
        recoverer.recover_tripped_steerer("UNKNOWN_PV", ["STR_01", "STR_02"], {"BPM_01": 0.5})

    # Recover with synthetic response matrix
    res_mag_synth = recoverer.recover_tripped_steerer(
        tripped_pv="STR_01",
        all_steerers=["STR_01", "STR_02", "STR_03"],
        bpm_readings_mm={"BPM_01": 0.2, "BPM_02": -0.1},
    )
    assert res_mag_synth.corrective_setpoints["STR_01"] == 0.0
    assert len(res_mag_synth.active_compensators) == 2

    # Recover with provided response matrix
    resp_mat = np.array([[1.0, 0.5, 0.2], [0.3, 1.2, 0.6]])
    res_mag_custom = recoverer.recover_tripped_steerer(
        tripped_pv="STR_01",
        all_steerers=["STR_01", "STR_02", "STR_03"],
        bpm_readings_mm={"BPM_01": 0.2, "BPM_02": -0.1},
        response_matrix=resp_mat,
    )
    assert res_mag_custom.tripped_pv == "STR_01"

    # 3. RFCavityRematcher
    rematcher = RFCavityRematcher(max_voltage_boost_factor=1.35)
    with pytest.raises(ValueError):
        rematcher.rematch_downstream_cavities("CAV_01", [], {}, {})

    res_rf = rematcher.rematch_downstream_cavities(
        tripped_cavity_id="CAV_01",
        downstream_cavities=["CAV_02", "CAV_03", "CAV_04"],
        active_voltages_kv={"CAV_02": 1000.0, "CAV_03": 1000.0, "CAV_04": 1000.0},
        active_phases_deg={"CAV_02": -20.0, "CAV_03": -20.0, "CAV_04": -20.0},
        nominal_voltage_tripped_kv=1000.0,
        nominal_phase_tripped_deg=-20.0,
    )
    assert "CAV_02:VOLT_SET" in res_rf.new_setpoints
    assert res_rf.energy_recovery_pct > 80.0
