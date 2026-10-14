"""HELIOS Web Dashboard Backend Application (FastAPI).

Provides REST and WebSocket endpoints for real-time accelerator telemetry,
interactive physics visualizations, orbit tuning, Human-in-the-Loop plan approval,
and an interactive side panel Natural Language Prompt Window with selectable Language Models.
"""

import logging
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, WebSocket
    from fastapi.responses import HTMLResponse
except ImportError as e:
    from helios._optional import OptionalDependencyError
    raise OptionalDependencyError("fastapi", extra="dashboard", feature="Operator Web Dashboard") from e

from helios.core.plan_engine import PlanStore
from helios.core.schemas import AutonomyLevel, ExecutionPlan, PlanState, PlanStep
from helios.dashboard.routers import (
    llm_router,
    plans_router,
    status_router,
    tuning_router,
    ws_router,
)
from helios.interfaces.base import BaseControlInterface
from helios.interfaces.epics import MockControlInterface
from helios.safety.rollback import RollbackController
from helios.security.rbac import RBACManager
from helios.tuning.analytic import (
    LEBT_RX,
    LEBT_RY,
    LEBT_STATION_DATA,
    LEBT_STEERER_NAMES,
    execute_analytic_orbit_correction,
)

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
INDEX_HTML_PATH = STATIC_DIR / "index.html"

__all__ = [
    "INDEX_HTML_PATH",
    "LEBT_RX",
    "LEBT_RY",
    "LEBT_STATION_DATA",
    "LEBT_STEERER_NAMES",
    "STATIC_DIR",
    "create_dashboard_app",
    "execute_analytic_orbit_correction",
]


def create_dashboard_app(
    control_interface: BaseControlInterface | None = None,
    rollback_controller: RollbackController | None = None,
    rbac_manager: RBACManager | None = None,
    plan_store: PlanStore | None = None,
) -> Any:
    """Factory creating configured FastAPI dashboard application."""
    app = FastAPI(
        title="HELIOS Heavy Ion Linac Operator Dashboard",
        description="Autonomous AI Agent Monitoring and Human-in-the-Loop Control Room Console",
        version="0.2.0",
    )

    ctrl = control_interface or MockControlInterface()
    rc = rollback_controller or RollbackController(control_interface=ctrl)
    rbac = rbac_manager or RBACManager()
    ps = plan_store or PlanStore()

    connected_clients: list[WebSocket] = []

    # Bind application state
    app.state.control_interface = ctrl
    app.state.rollback_controller = rc
    app.state.rbac = rbac
    app.state.plan_store = ps
    app.state.connected_clients = connected_clients

    # Seed demonstration plans if not present
    if ps.get_plan("00001") is None:
        ps.register_plan(
            ExecutionPlan(
                plan_id="00001",
                title="LEBT Closed-Loop Trajectory Correction",
                objective="LEBT closed-loop trajectory correction",
                state=PlanState.SAFETY_APPROVED,
                autonomy_level=AutonomyLevel.ASSISTED,
                steps=[
                    PlanStep(step_id="step_1", name="BPM & Wire Scanner Readback", target_agent="HELIOS-Diagnostics", action="read_telemetry"),
                    PlanStep(step_id="step_2", name="SVD Trajectory Inversion & Quantization", target_agent="HELIOS-Tuner", action="svd_inversion"),
                    PlanStep(step_id="step_3", name="Steerer Power Supply Slew (A)", target_agent="HELIOS-Control", action="steerer_slew"),
                ],
            )
        )
    if ps.get_plan("00002") is None:
        ps.register_plan(
            ExecutionPlan(
                plan_id="00002",
                title="MEBT Longitudinal Envelope Matching",
                objective="MEBT longitudinal envelope matching",
                state=PlanState.DRAFT,
                autonomy_level=AutonomyLevel.SUPERVISED,
                steps=[
                    PlanStep(step_id="step_1", name="Buncher Cavity Phase Scan", target_agent="HELIOS-Physics", action="phase_scan"),
                    PlanStep(step_id="step_2", name="RFQ Output Verification", target_agent="HELIOS-Diagnostics", action="verify_output"),
                ],
            )
        )

    @app.get("/", response_class=HTMLResponse)
    async def get_dashboard_html() -> str:
        """Serve single-page operator console UI from static directory."""
        if INDEX_HTML_PATH.exists():
            return INDEX_HTML_PATH.read_text(encoding="utf-8")
        return "<html><body><h1>HELIOS Dashboard: index.html not found</h1></body></html>"

    # Register modular routers
    app.include_router(status_router)
    app.include_router(plans_router)
    app.include_router(tuning_router)
    app.include_router(llm_router)
    app.include_router(ws_router)

    return app
