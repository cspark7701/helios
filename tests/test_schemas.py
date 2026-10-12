"""Tests for HELIOS core data schemas and serialization."""

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from helios.core.schemas import (
    AnomalyReport,
    AnomalySeverity,
    AutonomyLevel,
    ExecutionPlan,
    MachineState,
    PlanState,
    PlanStep,
    SetpointBatch,
    SetpointTarget,
    StepStatus,
    TelemetrySnapshot,
    ValidationCheck,
    ValidationResult,
)


def test_execution_plan_lifecycle():
    """Test creating, modifying, and serializing an ExecutionPlan."""
    plan = ExecutionPlan(
        plan_id="00001",
        title="MEBT Orbit Flattening",
        objective="Minimize RMS trajectory displacement in MEBT to < 0.5 mm",
        autonomy_level=AutonomyLevel.SUPERVISED,
        state=PlanState.DRAFT,
        rollback_targets={"MEBT:PSC:CH01:CurrentSet": 2.50, "MEBT:PSC:CV01:CurrentSet": -1.20},
    )

    step1 = PlanStep(
        step_id="step_1",
        name="Acquire BPM Telemetry",
        target_agent="HELIOS-Diagnostics",
        action="read_bpm_orbit",
        parameters={"section": "MEBT"},
        required_capabilities=["telemetry_read", "bpm_analysis"],
    )

    step2 = PlanStep(
        step_id="step_2",
        name="Calculate Response Matrix Correction",
        target_agent="HELIOS-Tuner",
        action="calculate_orbit_correction",
        parameters={"method": "SVD", "target_rms_mm": 0.5},
        required_capabilities=["svd_orbit_correction"],
    )

    plan.add_step(step1)
    plan.add_step(step2)

    assert len(plan.steps) == 2
    assert plan.get_step("step_1").name == "Acquire BPM Telemetry"
    assert plan.get_step("non_existent") is None

    # Serialization test
    json_str = plan.model_dump_json()
    reconstructed = ExecutionPlan.model_validate_json(json_str)
    assert reconstructed.plan_id == "00001"
    assert reconstructed.autonomy_level == AutonomyLevel.SUPERVISED
    assert reconstructed.steps[1].target_agent == "HELIOS-Tuner"


def test_validation_result():
    """Test ValidationResult with checks and errors."""
    v_res = ValidationResult(
        is_valid=False,
        validator_agent="HELIOS-Safety",
        checks=[
            ValidationCheck(check_name="Current Limit", passed=True, measured_value=18.0, limit_value=25.0),
            ValidationCheck(check_name="Slew Rate", passed=False, measured_value=5.0, limit_value=2.0, message="Exceeds 2.0 A/s"),
        ],
        errors=["Slew rate check failed: 5.0 A/s > 2.0 A/s"],
    )

    assert not v_res.is_valid
    assert len(v_res.checks) == 2
    assert len(v_res.errors) == 1


def test_setpoint_batch():
    """Test SetpointBatch construction and validation."""
    batch = SetpointBatch(
        batch_id="batch_001",
        description="Apply MEBT steerer trims",
        setpoints=[
            SetpointTarget(channel="MEBT:PSC:CH01:CurrentSet", target_value=3.10, tolerance=0.01, units="A"),
            SetpointTarget(channel="MEBT:PSC:CV01:CurrentSet", target_value=-0.95, tolerance=0.01, units="A"),
        ],
    )
    assert len(batch.setpoints) == 2
    assert batch.setpoints[0].target_value == 3.10


def test_telemetry_and_machine_state():
    """Test TelemetrySnapshot and MachineState models."""
    telemetry = TelemetrySnapshot(
        section="MEBT",
        bpm_x={"MEBT:BPM01": 0.42, "MEBT:BPM02": -0.15},
        bpm_y={"MEBT:BPM01": -0.28, "MEBT:BPM02": 0.05},
        transmission_pct=98.5,
        beam_current_ma=10.2,
    )
    assert telemetry.transmission_pct == 98.5
    assert telemetry.bpm_x["MEBT:BPM01"] == 0.42

    machine_state = MachineState(
        snapshot_id="snap_100",
        lattice_name="mebt_baseline_v2",
        active_setpoints={"MEBT:QD01:CurrentSet": 15.2},
        telemetry=telemetry,
        interlocks_ok=True,
    )
    assert machine_state.interlocks_ok
    assert machine_state.telemetry.section == "MEBT"


def test_anomaly_report():
    """Test AnomalyReport schema."""
    report = AnomalyReport(
        severity=AnomalySeverity.CRITICAL,
        anomaly_type="RF_TRIP",
        description="MEBT Buncher Cavity 1 interlock tripped due to reflected power",
        affected_channels=["MEBT:RF01:PwrRefl", "MEBT:RF01:Status"],
        recommended_action="Suspend beam, ramp down amplitude, query vacuum status",
    )
    assert report.severity == AnomalySeverity.CRITICAL
    assert len(report.affected_channels) == 2
