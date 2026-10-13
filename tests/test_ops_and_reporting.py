"""Tests for HELIOS Operations, Broker, and Reporting (Phase 18).

Validates:
1. AuditTrailLogger: SHA-256 hash chaining, database persistence, and tamper detection.
2. DistributedEventBus: In-process pub/sub, wildcard topic routing, and multi-subscriber delivery.
3. CommissioningReportGenerator: Markdown shift report and LaTeX export generation.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import pytest

from helios.ops.audit import AuditTrailLogger, AuditEntry
from helios.ops.broker import DistributedEventBus, EventMessage
from helios.ops.reporting import CommissioningReportGenerator, ShiftSummaryData
from helios.core.schemas import ExecutionPlan, PlanStep, AutonomyLevel


def test_audit_trail_logging_and_verification(tmp_path: Path):
    db_file = tmp_path / "test_audit.db"
    audit = AuditTrailLogger(db_path=db_file)

    # Log initial setpoints
    e1 = audit.log_action(
        operator_id="operator_1",
        action="caput",
        pv_name="MEBT:PS_Q01:I_Set",
        previous_value=12.5,
        new_value=14.0,
        rationale="Match horizontal beam envelope",
    )

    e2 = audit.log_action(
        operator_id="HELIOS-Tuner",
        action="caput",
        pv_name="MEBT:PS_Q02:I_Set",
        previous_value=8.0,
        new_value=7.2,
        rationale="Match vertical beam envelope",
    )

    assert len(audit.get_entries()) == 2
    valid, err = audit.verify_integrity()
    assert valid is True
    assert err is None

    # Check persistence by reloading from SQLite
    audit2 = AuditTrailLogger(db_path=db_file)
    assert len(audit2.get_entries()) == 2
    valid2, err2 = audit2.verify_integrity()
    assert valid2 is True
    assert err2 is None


def test_audit_trail_tamper_detection(tmp_path: Path):
    db_file = tmp_path / "tamper_audit.db"
    audit = AuditTrailLogger(db_path=db_file)

    audit.log_action("op1", "caput", "PV1", 0.0, 1.0, "step 1")
    audit.log_action("op1", "caput", "PV2", 1.0, 2.0, "step 2")
    audit.log_action("op1", "caput", "PV3", 2.0, 3.0, "step 3")
    valid, _ = audit.verify_integrity()
    assert valid is True

    # Tamper with an in-memory entry
    audit._entries[1].new_value = 999.0
    valid_tampered, err = audit.verify_integrity()
    assert valid_tampered is False
    assert "Tampered entry" in err


def test_distributed_event_bus_pub_sub():
    bus = DistributedEventBus()
    received_messages = []

    def on_telemetry(msg: EventMessage):
        received_messages.append(msg)

    # Subscribe with exact topic
    bus.subscribe("telemetry.bpm", on_telemetry)

    # Publish to matching and non-matching topics
    bus.publish("telemetry.bpm", "HELIOS-Diagnostics", {"rms_mm": 0.35})
    bus.publish("telemetry.blm", "HELIOS-Diagnostics", {"losses": [0.01, 0.02]})

    assert len(received_messages) == 1
    assert received_messages[0].topic == "telemetry.bpm"
    assert received_messages[0].payload["rms_mm"] == 0.35

    # Subscribe with wildcard pattern
    wildcard_messages = []
    bus.subscribe("telemetry.*", lambda m: wildcard_messages.append(m))

    bus.publish("telemetry.bpm", "HELIOS-Diagnostics", {"rms_mm": 0.40})
    bus.publish("telemetry.blm", "HELIOS-Diagnostics", {"losses": [0.05]})
    bus.publish("safety.trip", "HELIOS-Safety", {"pv": "CAV1"})

    # Wildcard should have matched the two telemetry events
    assert len(wildcard_messages) == 2


def test_commissioning_report_generator():
    summary = ShiftSummaryData(
        shift_label="Shift-2026-10-13-Day",
        physicist_on_duty="Dr. C. Spark",
        facility_name="RAON SCL1",
        start_time=datetime(2026, 10, 13, 8, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 10, 13, 16, 0, tzinfo=timezone.utc),
        executed_plans_count=3,
        initial_orbit_rms_mm=1.25,
        final_orbit_rms_mm=0.28,
        initial_transmission_pct=91.5,
        final_transmission_pct=98.8,
        total_anomalies_detected=1,
        interlocks_tripped_count=0,
        notes="Commissioning achieved record transmission after quadrupole rematch.",
    )

    plan = ExecutionPlan(
        plan_id="plan_001",
        title="SCL1 Orbit Optimization",
        objective="Minimize orbit deviation across SCL1 section",
        autonomy_level=AutonomyLevel.ASSISTED,
        steps=[
            PlanStep(
                step_id="step_1",
                name="Run TRACK digital twin pre-flight check",
                target_agent="HELIOS-Physics",
                action="run_track_simulation",
                parameters={"lattice": "raon_scl1"},
            )
        ],
    )

    # Markdown export
    md_report = CommissioningReportGenerator.generate_markdown_report(summary, plans=[plan])
    assert "# HELIOS Commissioning Shift Report: Shift-2026-10-13-Day" in md_report
    assert "RAON SCL1" in md_report
    assert "Dr. C. Spark" in md_report
    assert "1.250 mm" in md_report
    assert "0.280 mm" in md_report
    assert "SCL1 Orbit Optimization" in md_report

    # LaTeX export
    latex_report = CommissioningReportGenerator.generate_latex_report(summary)
    assert r"\documentclass" in latex_report
    assert r"\title" in latex_report
    assert "HELIOS Commissioning Shift Handover Report" in latex_report
    assert "RAON SCL1" in latex_report
    assert r"\end{document}" in latex_report
