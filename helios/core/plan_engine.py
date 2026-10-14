"""HELIOS Plan-First Execution Engine.

Implements the Osprey-aligned plan lifecycle management, state transitions,
validation gating, step execution tracking, and artifact persistence.
"""

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from helios.core.schemas import (
    AutonomyLevel,
    ExecutionPlan,
    PlanState,
    StepStatus,
    ValidationResult,
)

logger = logging.getLogger(__name__)


class PlanTransitionError(Exception):
    """Raised when an invalid plan lifecycle state transition is requested."""


class PlanLifecycleManager:
    """Manages state transitions and validation gates for ExecutionPlan instances."""

    VALID_TRANSITIONS: dict[PlanState, list[PlanState]] = {
        PlanState.DRAFT: [PlanState.SIMULATION_VERIFIED, PlanState.FAILED],
        PlanState.SIMULATION_VERIFIED: [PlanState.SAFETY_APPROVED, PlanState.FAILED, PlanState.DRAFT],
        PlanState.SAFETY_APPROVED: [PlanState.EXECUTING, PlanState.FAILED, PlanState.DRAFT],
        PlanState.EXECUTING: [PlanState.COMPLETED, PlanState.FAILED, PlanState.ROLLED_BACK],
        PlanState.COMPLETED: [],
        PlanState.FAILED: [PlanState.ROLLED_BACK],
        PlanState.ROLLED_BACK: [],
    }

    def __init__(self, plan: ExecutionPlan):
        self.plan = plan

    def attach_physics_validation(self, result: ValidationResult) -> None:
        """Attach physics digital twin validation results and transition to SIMULATION_VERIFIED if passed."""
        if self.plan.state != PlanState.DRAFT:
            raise PlanTransitionError(f"Cannot attach physics validation to plan in state {self.plan.state}")

        self.plan.validation_records.append(result)
        if result.is_valid:
            self._transition_to(PlanState.SIMULATION_VERIFIED)
        else:
            self._transition_to(PlanState.FAILED)

    def attach_safety_validation(self, result: ValidationResult) -> None:
        """Attach safety verification results and transition to SAFETY_APPROVED if passed."""
        if self.plan.state != PlanState.SIMULATION_VERIFIED:
            raise PlanTransitionError(f"Cannot attach safety validation to plan in state {self.plan.state}")

        self.plan.validation_records.append(result)
        if result.is_valid:
            self._transition_to(PlanState.SAFETY_APPROVED)
        else:
            self._transition_to(PlanState.FAILED)

    def authorize_execution(self, operator_approval: bool = False) -> None:
        """Authorize plan execution based on active AutonomyLevel and operator sign-off."""
        if self.plan.state != PlanState.SAFETY_APPROVED:
            raise PlanTransitionError(f"Plan must be in SAFETY_APPROVED state to authorize, currently {self.plan.state}")

        if self.plan.autonomy_level in (AutonomyLevel.ADVISORY, AutonomyLevel.ASSISTED, AutonomyLevel.SUPERVISED):
            if not operator_approval:
                raise PermissionError(
                    f"Operator approval required for plan '{self.plan.title}' at autonomy level {self.plan.autonomy_level.name}"
                )

        self._transition_to(PlanState.EXECUTING)

    def complete_plan(self) -> None:
        """Mark all steps executed and finalize the plan."""
        if self.plan.state != PlanState.EXECUTING:
            raise PlanTransitionError(f"Plan must be in EXECUTING state to complete, currently {self.plan.state}")

        # Check if all steps succeeded or were skipped
        for step in self.plan.steps:
            if step.status not in (StepStatus.SUCCESS, StepStatus.SKIPPED):
                raise ValueError(f"Cannot complete plan: step {step.step_id} is in status {step.status}")

        self._transition_to(PlanState.COMPLETED)

    def abort_or_fail(self, reason: str = "") -> None:
        """Mark plan as failed."""
        self.plan.provenance_metadata["failure_reason"] = reason
        self._transition_to(PlanState.FAILED)

    def mark_rolled_back(self) -> None:
        """Mark plan as rolled back."""
        self._transition_to(PlanState.ROLLED_BACK)

    def _transition_to(self, new_state: PlanState) -> None:
        allowed = self.VALID_TRANSITIONS.get(self.plan.state, [])
        if new_state not in allowed:
            raise PlanTransitionError(
                f"Illegal state transition from {self.plan.state} to {new_state}"
            )
        self.plan.state = new_state
        self.plan.updated_at = datetime.now(timezone.utc)


class PlanArtifactStore:
    """Manages disk persistence and markdown rendering of ExecutionPlans in docs/exec-plans/."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.active_dir = base_dir / "docs" / "exec-plans" / "active"
        self.completed_dir = base_dir / "docs" / "exec-plans" / "completed"
        self.active_dir.mkdir(parents=True, exist_ok=True)
        self.completed_dir.mkdir(parents=True, exist_ok=True)

    def _sanitize_filename(self, text: str) -> str:
        text = re.sub(r"[^\w\s-]", "", text).strip().lower()
        return re.sub(r"[-\s]+", "_", text)

    def render_markdown(self, plan: ExecutionPlan) -> str:
        """Render plan into human-readable Markdown with an embedded JSON provenance block."""
        md_lines = [
            f"# Execution Plan: {plan.plan_id.zfill(5)} - {plan.title}",
            "",
            f"- **Objective**: {plan.objective}",
            f"- **State**: `{plan.state.value}`",
            f"- **Autonomy Level**: `{plan.autonomy_level.name}` ({plan.autonomy_level.value})",
            f"- **Created At**: {plan.created_at.isoformat()}",
            f"- **Updated At**: {plan.updated_at.isoformat()}",
            "",
            "## 1. Description & Context",
            "",
            plan.description or "No extended description provided.",
            "",
            "## 2. Execution Steps",
            "",
            "| Step ID | Name | Target Agent | Action | Status |",
            "| :--- | :--- | :--- | :--- | :--- |",
        ]

        for step in plan.steps:
            md_lines.append(
                f"| `{step.step_id}` | {step.name} | `{step.target_agent}` | `{step.action}` | `{step.status.value}` |"
            )

        md_lines.extend([
            "",
            "## 3. Validation Summary",
            "",
        ])

        if not plan.validation_records:
            md_lines.append("No validation records logged yet.")
        else:
            for v in plan.validation_records:
                status_icon = "PASS" if v.is_valid else "FAIL"
                md_lines.append(f"### [{status_icon}] Validation by `{v.validator_agent}` ({v.timestamp.isoformat()})")
                for c in v.checks:
                    c_status = "OK" if c.passed else "FAIL"
                    md_lines.append(f"- **[{c_status}]** `{c.check_name}`: {c.message}")
                if v.errors:
                    md_lines.append(f"- **Errors**: {'; '.join(v.errors)}")
                if v.warnings:
                    md_lines.append(f"- **Warnings**: {'; '.join(v.warnings)}")

        md_lines.extend([
            "",
            "## 4. Rollback Targets",
            "",
        ])

        if not plan.rollback_targets:
            md_lines.append("No rollback setpoints registered.")
        else:
            md_lines.append("| Channel / PV | Baseline Setpoint |")
            md_lines.append("| :--- | :--- |")
            for ch, val in plan.rollback_targets.items():
                md_lines.append(f"| `{ch}` | `{val}` |")

        md_lines.extend([
            "",
            "## 5. Machine-Readable Provenance",
            "",
            "```json",
            plan.model_dump_json(indent=2),
            "```",
            "",
        ])

        return "\n".join(md_lines)

    def save_active(self, plan: ExecutionPlan) -> Path:
        """Save plan to active directory."""
        slug = self._sanitize_filename(plan.title)
        prefix = plan.plan_id.zfill(5)
        filename = f"{prefix}_{slug}.md"
        target_path = self.active_dir / filename
        target_path.write_text(self.render_markdown(plan), encoding="utf-8")
        return target_path

    def archive_completed(self, plan: ExecutionPlan) -> Path:
        """Move plan from active to completed directory and update artifact."""
        slug = self._sanitize_filename(plan.title)
        prefix = plan.plan_id.zfill(5)
        filename = f"{prefix}_{slug}.md"
        active_path = self.active_dir / filename
        completed_path = self.completed_dir / filename

        completed_path.write_text(self.render_markdown(plan), encoding="utf-8")
        if active_path.exists():
            active_path.unlink()
        return completed_path
