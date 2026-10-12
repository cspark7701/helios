"""HELIOS Graduated Autonomy Policy Engine.

Enforces operational boundaries and human-in-the-loop (HITL) authorization
protocols across the 5 autonomy levels defined in HELIOS AGENTS.md.
"""

from typing import Tuple
from helios.core.schemas import AutonomyLevel, ExecutionPlan, PlanState


class AutonomyPolicyEngine:
    """Enforces tiered permission and approval rules according to active AutonomyLevel."""

    @staticmethod
    def requires_human_signoff_before_execution(autonomy_level: AutonomyLevel) -> bool:
        """Determines if the active autonomy level mandates human operator confirmation."""
        # Levels 0, 1, 2 mandate human operator approval before execution begins
        return autonomy_level in (
            AutonomyLevel.ADVISORY,
            AutonomyLevel.ASSISTED,
            AutonomyLevel.SUPERVISED,
        )

    @staticmethod
    def allows_hardware_write(autonomy_level: AutonomyLevel) -> bool:
        """Determines if the active autonomy level allows any hardware actuation."""
        # Level 0 (Advisory) strictly prohibits hardware writes
        return autonomy_level != AutonomyLevel.ADVISORY

    @staticmethod
    def evaluate_plan_authorization(
        plan: ExecutionPlan,
        operator_confirmed: bool = False,
    ) -> Tuple[bool, str]:
        """Check whether a plan is authorized to proceed to execution.

        Returns:
            (authorized: bool, reason: str)
        """
        # Safety gate check
        if plan.state != PlanState.SAFETY_APPROVED:
            return False, f"Plan state is {plan.state.value}; must be SAFETY_APPROVED before execution"

        # Hardware permission check
        if not AutonomyPolicyEngine.allows_hardware_write(plan.autonomy_level):
            return False, f"Autonomy level {plan.autonomy_level.name} (Level 0) does not permit hardware actuation"

        # Human operator sign-off check
        if AutonomyPolicyEngine.requires_human_signoff_before_execution(plan.autonomy_level):
            if not operator_confirmed:
                return False, f"Operator confirmation required for autonomy level {plan.autonomy_level.name}"

        return True, "Authorized for execution"
