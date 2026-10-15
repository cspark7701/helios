"""Orbit tuning and emergency machine protection routes for HELIOS dashboard."""

import asyncio
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends

from helios.dashboard.deps import get_rollback_controller, require_permission
from helios.safety.rollback import RollbackController
from helios.security.rbac import AuthToken, Permission
from helios.tuning.analytic import execute_analytic_orbit_correction

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Tuning & Safety"])


@router.post("/api/emergency/panic")
async def trigger_panic_shutdown(
    token: AuthToken = Depends(require_permission(Permission.PANIC_SHUTDOWN)),
    rollback_controller: RollbackController = Depends(get_rollback_controller),
) -> dict[str, Any]:
    """Emergency panic button endpoint triggering immediate machine dump."""
    ok = rollback_controller.panic_shutdown()
    logger.warning(f"[RBAC AUDIT] EMERGENCY PANIC triggered by user '{token.username}' (role '{token.role.value}')")
    return {"status": "PANIC_EXECUTED", "success": ok}


@router.post("/api/tune/orbit")
async def tune_orbit_endpoint(
    payload: dict[str, Any] | None = None,
    token: AuthToken = Depends(require_permission(Permission.EXECUTE_CAPUT)),
) -> dict[str, Any]:
    """API endpoint executing closed-loop orbit correction with steerer power supply currents."""
    req = payload or {}
    section = req.get("section", "LEBT")
    engine = req.get("engine", "analytic").lower()
    factor = float(req.get("conversion_factor", 0.168))
    step = float(req.get("current_increment", 0.01))
    logger.info(f"[RBAC AUDIT] Orbit tuning initiated by user '{token.username}' (role '{token.role.value}') on {section}")

    if section.upper() == "LEBT" and engine == "track":
        try:
            from examples.tune_orbit_lebt import run_tune_orbit_example
            res = await asyncio.to_thread(
                run_tune_orbit_example,
                model_dir=Path("examples/lebt"),
                conversion_factor_a_per_mrad=factor,
                current_increment_a=step,
            )
            return {
                "section": "LEBT",
                "engine": "track",
                "initial_rms_x_mm": res["initial_rms_x_mm"],
                "corrected_rms_x_mm": res["corrected_rms_x_mm"],
                "initial_rms_y_mm": res.get("initial_rms_y_mm", 0.0),
                "corrected_rms_y_mm": res.get("corrected_rms_y_mm", 0.0),
                "improvement_pct": res["improvement_pct"],
                "improvement_x_pct": res.get("improvement_x_pct", res["improvement_pct"]),
                "improvement_y_pct": res.get("improvement_y_pct", 0.0),
                "elapsed_time_s": res["elapsed_time_s"],
                "conversion_factor_a_per_mrad": factor,
                "current_increment_a": step,
                "steerers": res.get("steerers", []),
                "monitors": res.get("monitors", []),
            }
        except Exception as e:
            logger.warning(f"TRACK execution failed ({e}), falling back to analytic model")

    return execute_analytic_orbit_correction(
        section=section,
        conversion_factor_a_per_mrad=factor,
        current_increment_a=step,
    )
