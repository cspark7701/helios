"""Operational plan endpoints for HELIOS dashboard."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from helios.core.plan_engine import PlanStore
from helios.core.schemas import PlanState
from helios.dashboard.deps import get_plan_store, require_permission
from helios.security.rbac import AuthToken, Permission

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Plans"])


@router.get("/api/plans")
async def list_plans(
    plan_store: PlanStore = Depends(get_plan_store),
) -> list[dict[str, Any]]:
    """List current operational plans."""
    plans = plan_store.list_plans()
    return [
        {
            "plan_id": p.plan_id,
            "title": p.title,
            "objective": p.objective,
            "state": p.state.value if hasattr(p.state, "value") else str(p.state),
            "autonomy_level": p.autonomy_level.name if hasattr(p.autonomy_level, "name") else str(p.autonomy_level),
            "steps": [
                {
                    "step_id": s.step_id,
                    "name": s.name,
                    "agent": s.target_agent,
                    "action": s.action,
                    "status": s.status.value if hasattr(s.status, "value") else str(s.status),
                }
                for s in p.steps
            ],
            "approved": p.state in (PlanState.EXECUTING, PlanState.COMPLETED),
        }
        for p in plans
    ]


@router.post("/api/plans/{plan_id}/approve")
async def approve_plan(
    plan_id: str,
    token: AuthToken = Depends(require_permission(Permission.EXECUTE_CAPUT)),
    plan_store: PlanStore = Depends(get_plan_store),
) -> dict[str, Any]:
    """Operator approval trigger for Human-in-the-Loop workflows."""
    try:
        plan = plan_store.approve_plan(plan_id, operator_approval=True)
    except KeyError:
        raise HTTPException(status_code=404, detail="Plan ID not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info(f"[RBAC AUDIT] Plan {plan_id} approved by user '{token.username}' (role '{token.role.value}')")
    return {"status": "APPROVED", "plan_id": plan_id, "state": plan.state.value}


@router.post("/api/plans/{plan_id}/reject")
async def reject_plan(
    plan_id: str,
    token: AuthToken = Depends(require_permission(Permission.PROPOSE_SETPOINT)),
    plan_store: PlanStore = Depends(get_plan_store),
) -> dict[str, Any]:
    """Operator rejection trigger."""
    try:
        plan = plan_store.reject_plan(plan_id, reason=f"Rejected by user '{token.username}'")
    except KeyError:
        raise HTTPException(status_code=404, detail="Plan ID not found")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info(f"[RBAC AUDIT] Plan {plan_id} rejected by user '{token.username}' (role '{token.role.value}')")
    return {"status": "REJECTED", "plan_id": plan_id, "state": plan.state.value}
