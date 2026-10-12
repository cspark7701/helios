"""HELIOS Strongly-Typed Data Schemas and State Models.

Alignd with LBNL Osprey's Plan-First paradigm, these models represent
plans, steps, validation outcomes, telemetry, setpoints, and accelerator states.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PlanState(str, Enum):
    """Lifecycle states of an execution plan."""
    DRAFT = "DRAFT"
    SIMULATION_VERIFIED = "SIMULATION_VERIFIED"
    SAFETY_APPROVED = "SAFETY_APPROVED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class StepStatus(str, Enum):
    """Lifecycle states of an individual plan step."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    ROLLED_BACK = "ROLLED_BACK"


class AutonomyLevel(int, Enum):
    """Operational autonomy levels for human-in-the-loop gating."""
    ADVISORY = 0
    ASSISTED = 1
    SUPERVISED = 2
    BOUNDED_AUTONOMOUS = 3
    FULLY_AUTONOMOUS = 4


class AnomalySeverity(str, Enum):
    """Severity ratings for accelerator telemetry anomalies."""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class SetpointTarget(BaseModel):
    """Single channel or PV setpoint actuation target."""
    channel: str = Field(..., description="Semantic channel name or EPICS PV")
    target_value: float = Field(..., description="Target value to set")
    tolerance: float = Field(0.01, description="Acceptable readback convergence tolerance")
    max_slew_rate: Optional[float] = Field(None, description="Maximum rate of change per second")
    units: str = Field("", description="Engineering units (e.g. A, kV, deg)")


class SetpointBatch(BaseModel):
    """Batch of coordinated setpoints for atomic execution."""
    batch_id: str = Field(..., description="Unique batch identifier")
    description: str = Field("", description="Purpose of this setpoint batch")
    setpoints: List[SetpointTarget] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    timeout_seconds: float = Field(10.0, description="Timeout for readback verification")


class TelemetrySnapshot(BaseModel):
    """Real-time diagnostic telemetry reading across linac sections."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    section: str = Field("ALL", description="Linac section (LEBT, RFQ, MEBT, SCL, HEBT)")
    bpm_x: Dict[str, float] = Field(default_factory=dict, description="BPM X offsets (mm)")
    bpm_y: Dict[str, float] = Field(default_factory=dict, description="BPM Y offsets (mm)")
    bpm_phase: Dict[str, float] = Field(default_factory=dict, description="BPM phase readings (deg)")
    blm_loss: Dict[str, float] = Field(default_factory=dict, description="BLM dose rates (Gy/s or V)")
    transmission_pct: float = Field(100.0, description="Beam transmission percentage (0-100)")
    beam_current_ma: float = Field(0.0, description="Peak or average beam current (mA)")
    raw_pvs: Dict[str, Any] = Field(default_factory=dict, description="Additional low-level PVs")


class MachineState(BaseModel):
    """Comprehensive snapshot of the accelerator machine state."""
    snapshot_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    lattice_name: str = Field("default", description="Active accelerator lattice definition")
    active_setpoints: Dict[str, float] = Field(default_factory=dict)
    telemetry: Optional[TelemetrySnapshot] = None
    interlocks_ok: bool = Field(True, description="Machine Protection System interlock status")
    rf_tripped: bool = Field(False, description="Whether any RF station is currently tripped")


class AnomalyReport(BaseModel):
    """Structured report of an operational anomaly or hardware fault."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    severity: AnomalySeverity = AnomalySeverity.WARNING
    anomaly_type: str = Field(..., description="e.g. RF_TRIP, BEAM_LOSS_SPIKE, ORBIT_DRIFT")
    description: str = Field(..., description="Human-readable description of the anomaly")
    affected_channels: List[str] = Field(default_factory=list)
    recommended_action: Optional[str] = None


class ValidationCheck(BaseModel):
    """Specific check outcome within a validation result."""
    check_name: str
    passed: bool
    message: str = ""
    measured_value: Optional[float] = None
    limit_value: Optional[float] = None


class ValidationResult(BaseModel):
    """Evaluation result from Physics or Safety agents."""
    is_valid: bool = Field(..., description="Whether proposed plan/step passed checks")
    validator_agent: str = Field(..., description="e.g. HELIOS-Physics or HELIOS-Safety")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    checks: List[ValidationCheck] = Field(default_factory=list)
    projected_beam_loss: float = Field(0.0, description="Projected beam loss in Watts or %")
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class PlanStep(BaseModel):
    """An individual atomic or sub-task action in an ExecutionPlan."""
    step_id: str
    name: str
    target_agent: str = Field(..., description="Designated agent (HELIOS-Tuner, Safety, etc.)")
    action: str = Field(..., description="Action name or tool function")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    required_capabilities: List[str] = Field(default_factory=list)
    preconditions: List[str] = Field(default_factory=list)
    timeout_seconds: float = Field(30.0)
    status: StepStatus = StepStatus.PENDING
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ExecutionPlan(BaseModel):
    """High-level Plan-First execution plan following LBNL Osprey principles."""
    plan_id: str
    title: str
    description: str = ""
    objective: str = Field(..., description="High-level operational goal")
    autonomy_level: AutonomyLevel = AutonomyLevel.ASSISTED
    state: PlanState = PlanState.DRAFT
    steps: List[PlanStep] = Field(default_factory=list)
    validation_records: List[ValidationResult] = Field(default_factory=list)
    rollback_targets: Dict[str, float] = Field(default_factory=dict, description="Baseline PV setpoints for safe rollback")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    provenance_metadata: Dict[str, Any] = Field(default_factory=dict)

    def add_step(self, step: PlanStep) -> None:
        """Append a step to the plan."""
        self.steps.append(step)
        self.updated_at = datetime.now(timezone.utc)

    def get_step(self, step_id: str) -> Optional[PlanStep]:
        """Retrieve a step by ID."""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None
