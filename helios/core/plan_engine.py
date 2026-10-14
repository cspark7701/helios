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

    def load_plan_from_file(self, file_path: Path) -> ExecutionPlan | None:
        """Parse ExecutionPlan from markdown file containing JSON block or reconstruct from header."""
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            return None

        json_match = re.search(r"```json\s*\n(.*?)\n```", content, re.DOTALL)
        if json_match:
            try:
                return ExecutionPlan.model_validate_json(json_match.group(1))
            except Exception as e:
                logger.debug(f"Could not parse embedded JSON in {file_path}: {e}")

        name = file_path.stem
        parts = name.split("_", 1)
        plan_id = parts[0]
        title = parts[1].replace("_", " ").title() if len(parts) > 1 else name
        is_completed = "completed" in str(file_path)
        return ExecutionPlan(
            plan_id=plan_id,
            title=title,
            objective=f"Plan artifact from {file_path.name}",
            state=PlanState.COMPLETED if is_completed else PlanState.SAFETY_APPROVED,
            autonomy_level=AutonomyLevel.ASSISTED,
            steps=[],
        )

    def load_plan(self, plan_id: str) -> ExecutionPlan | None:
        """Search active and completed directories for a plan matching plan_id."""
        prefix = plan_id.zfill(5)
        for d in (self.active_dir, self.completed_dir):
            for file_path in d.glob(f"{prefix}*.md"):
                plan = self.load_plan_from_file(file_path)
                if plan:
                    return plan
        return None

    def list_plans(self) -> list[ExecutionPlan]:
        """List all plans found in active and completed directories."""
        plans = []
        seen_ids = set()
        for d in (self.active_dir, self.completed_dir):
            for f in sorted(d.glob("*.md")):
                p = self.load_plan_from_file(f)
                if p and p.plan_id not in seen_ids:
                    seen_ids.add(p.plan_id)
                    plans.append(p)
        return plans

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


class PlanStore:
    """Central store for ExecutionPlans backed by PlanArtifactStore and PlanLifecycleManager."""

    def __init__(
        self,
        base_dir: Path | None = None,
        artifact_store: PlanArtifactStore | None = None,
        persist_artifacts: bool = False,
    ):
        self.base_dir = base_dir
        self.persist_artifacts = persist_artifacts
        self.artifact_store = artifact_store or (PlanArtifactStore(base_dir) if base_dir else None)
        self._plans: dict[str, ExecutionPlan] = {}
        self._managers: dict[str, PlanLifecycleManager] = {}

    def register_plan(self, plan: ExecutionPlan) -> PlanLifecycleManager:
        """Register an in-memory plan and return its lifecycle manager."""
        self._plans[plan.plan_id] = plan
        mgr = PlanLifecycleManager(plan)
        self._managers[plan.plan_id] = mgr
        if self.persist_artifacts and self.artifact_store:
            self.artifact_store.save_active(plan)
        return mgr

    def get_plan(self, plan_id: str) -> ExecutionPlan | None:
        """Get plan by plan_id, checking in-memory registry first, then artifact store."""
        if plan_id in self._plans:
            return self._plans[plan_id]
        if self.artifact_store:
            plan = self.artifact_store.load_plan(plan_id)
            if plan:
                self._plans[plan_id] = plan
                self._managers[plan_id] = PlanLifecycleManager(plan)
                return plan
        return None

    def get_manager(self, plan_id: str) -> PlanLifecycleManager | None:
        """Get lifecycle manager for plan."""
        if plan_id not in self._managers:
            self.get_plan(plan_id)
        return self._managers.get(plan_id)

    def list_plans(self) -> list[ExecutionPlan]:
        """List all plans (combining in-memory and loaded from active artifacts)."""
        if self.artifact_store:
            disk_plans = self.artifact_store.list_plans()
            for p in disk_plans:
                if p.plan_id not in self._plans:
                    self._plans[p.plan_id] = p
                    self._managers[p.plan_id] = PlanLifecycleManager(p)
        return list(self._plans.values())

    def approve_plan(self, plan_id: str, operator_approval: bool = True) -> ExecutionPlan:
        """Approve and authorize plan for execution using PlanLifecycleManager."""
        mgr = self.get_manager(plan_id)
        if not mgr:
            raise KeyError(f"Plan ID '{plan_id}' not found")
        plan = mgr.plan
        if plan.state == PlanState.DRAFT:
            mgr.attach_physics_validation(ValidationResult(is_valid=True, validator_agent="HELIOS-Physics"))
        if plan.state == PlanState.SIMULATION_VERIFIED:
            mgr.attach_safety_validation(ValidationResult(is_valid=True, validator_agent="HELIOS-Safety"))
        mgr.authorize_execution(operator_approval=operator_approval)
        if self.persist_artifacts and self.artifact_store:
            self.artifact_store.save_active(plan)
        return plan

    def reject_plan(self, plan_id: str, reason: str = "Operator rejected plan") -> ExecutionPlan:
        """Reject/abort plan using PlanLifecycleManager."""
        mgr = self.get_manager(plan_id)
        if not mgr:
            raise KeyError(f"Plan ID '{plan_id}' not found")
        if mgr.plan.state == PlanState.FAILED:
            return mgr.plan
        mgr.abort_or_fail(reason=reason)
        if self.persist_artifacts and self.artifact_store:
            self.artifact_store.save_active(mgr.plan)
        return mgr.plan
