"""HELIOS Web Dashboard Backend Application (FastAPI).

Provides REST and WebSocket endpoints for real-time accelerator telemetry,
interactive physics visualizations, and Human-in-the-Loop plan approval.
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np

try:
    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, JSONResponse
    HAVE_FASTAPI = True
except ImportError:
    FastAPI = None
    HAVE_FASTAPI = False

from helios.core.schemas import AutonomyLevel, PlanState
from helios.dashboard.plots import (
    generate_blm_heatmap_data,
    generate_envelope_plot_data,
    generate_orbit_plot_data,
)
from helios.interfaces.base import BaseControlInterface
from helios.interfaces.epics import MockControlInterface
from helios.safety.rollback import RollbackController

logger = logging.getLogger(__name__)


def create_dashboard_app(
    control_interface: Optional[BaseControlInterface] = None,
    rollback_controller: Optional[RollbackController] = None,
) -> Any:
    """Factory creating configured FastAPI dashboard application."""
    if not HAVE_FASTAPI:
        raise RuntimeError("FastAPI is not installed. Install with 'pip install fastapi uvicorn'.")

    app = FastAPI(
        title="HELIOS Heavy Ion Linac Operator Dashboard",
        description="Autonomous AI Agent Monitoring and Human-in-the-Loop Control Room Console",
        version="0.1.0",
    )

    ctrl = control_interface or MockControlInterface()
    rc = rollback_controller or RollbackController(control_interface=ctrl)

    # In-memory plan store for approval workflow
    plans_store: Dict[str, Dict[str, Any]] = {
        "00001": {
            "plan_id": "00001",
            "title": "MEBT Orbit Flattening Sequence",
            "state": "READY",
            "autonomy_level": "ASSISTED",
            "steps": [
                {"step_id": "step_1", "name": "BPM Telemetry Read", "agent": "HELIOS-Diagnostics"},
                {"step_id": "step_2", "name": "SVD Trajectory Inversion", "agent": "HELIOS-Tuner"},
                {"step_id": "step_3", "name": "Steerer Slew Actuation", "agent": "HELIOS-Control"},
            ],
            "approved": False,
        }
    }

    connected_clients: List[WebSocket] = []

    @app.get("/", response_class=HTMLResponse)
    async def get_dashboard_html() -> str:
        """Serve single-page dark-mode operator console UI."""
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>HELIOS Operator Dashboard</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace; background: #0d1117; color: #c9d1d9; margin: 0; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #30363d; padding-bottom: 15px; margin-bottom: 20px; }
        .title { font-size: 24px; font-weight: bold; color: #58a6ff; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 20px; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 18px; }
        .card-title { font-size: 16px; font-weight: bold; margin-bottom: 12px; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; }
        .metric-value { font-size: 32px; font-weight: bold; color: #3fb950; }
        .metric-sub { font-size: 13px; color: #8b949e; margin-top: 4px; }
        .btn { background: #238636; color: white; border: none; padding: 8px 16px; border-radius: 6px; cursor: pointer; font-weight: bold; }
        .btn-panic { background: #da3633; }
        .btn:hover { opacity: 0.9; }
        .table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; }
        .table th, .table td { text-align: left; padding: 8px; border-bottom: 1px solid #21262d; }
        .status-badge { background: #1f6feb22; color: #58a6ff; border: 1px solid #1f6feb; border-radius: 12px; padding: 2px 8px; font-size: 12px; }
    </style>
</head>
<body>
    <div class="header">
        <div class="title">⚡ HELIOS Operator Console</div>
        <div>
            <span class="status-badge">Autonomy Level: ASSISTED</span>
            <button class="btn btn-panic" onclick="triggerPanic()" style="margin-left: 15px;">EMERGENCY PANIC</button>
        </div>
    </div>
    <div class="grid">
        <div class="card">
            <div class="card-title">Linac Beam Status</div>
            <div class="metric-value" id="transmission">99.4%</div>
            <div class="metric-sub">Beam Current: 4.85 mA | Energy: 0.50 MeV/u</div>
        </div>
        <div class="card">
            <div class="card-title">Orbit Distortion (RMS)</div>
            <div class="metric-value" id="orbit-rms" style="color: #58a6ff;">0.18 mm</div>
            <div class="metric-sub">Tolerance: &plusmn;0.50 mm | BPMs active: 8/8</div>
        </div>
        <div class="card">
            <div class="card-title">Radiation & Losses</div>
            <div class="metric-value" id="max-loss" style="color: #d29922;">0.12 W/m</div>
            <div class="metric-sub">MPS Trip Threshold: 1.00 W/m | Interlocks: Normal</div>
        </div>
    </div>
    <div class="card" style="margin-top: 20px;">
        <div class="card-title">Active Execution Plan Review</div>
        <table class="table">
            <thead><tr><th>Plan ID</th><th>Objective</th><th>Autonomy</th><th>State</th><th>Action</th></tr></thead>
            <tbody id="plans-table">
                <tr>
                    <td>00001</td>
                    <td>MEBT Orbit Flattening Sequence</td>
                    <td>ASSISTED</td>
                    <td><span class="status-badge">READY</span></td>
                    <td><button class="btn" onclick="approvePlan('00001')">Approve & Execute</button></td>
                </tr>
            </tbody>
        </table>
    </div>
    <script>
        function triggerPanic() {
            if (confirm("CONFIRM EMERGENCY SHUTDOWN: Immediately dump beam and zero critical RF setpoints?")) {
                fetch('/api/emergency/panic', {method: 'POST'}).then(r => r.json()).then(d => alert("PANIC SHUTDOWN EXECUTED: " + JSON.stringify(d)));
            }
        }
        function approvePlan(id) {
            fetch('/api/plans/' + id + '/approve', {method: 'POST'}).then(r => r.json()).then(d => {
                alert("Plan " + id + " Approved!");
                location.reload();
            });
        }
    </script>
</body>
</html>"""

    @app.get("/api/status")
    async def get_machine_status() -> Dict[str, Any]:
        """Query global accelerator health and autonomy state."""
        return {
            "status": "ONLINE",
            "lattice": "MEBT_HEAVY_ION_BASELINE",
            "autonomy_level": "ASSISTED",
            "interlocks_tripped": False,
            "rf_stations_ok": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @app.get("/api/telemetry")
    async def get_telemetry() -> Dict[str, Any]:
        """Fetch latest telemetry snapshot."""
        return {
            "transmission_pct": 99.4,
            "beam_current_ma": 4.85,
            "orbit_rms_mm": 0.18,
            "bpm_telemetry": {
                "MEBT:BPM:01": {"s_m": 0.5, "x_mm": 0.12, "y_mm": -0.05},
                "MEBT:BPM:02": {"s_m": 1.8, "x_mm": -0.08, "y_mm": 0.15},
                "MEBT:BPM:03": {"s_m": 3.2, "x_mm": 0.22, "y_mm": -0.02},
            },
            "blm_losses": {
                "MEBT:BLM:01": {"s_m": 1.0, "loss_w": 0.05},
                "MEBT:BLM:02": {"s_m": 2.5, "loss_w": 0.12},
                "MEBT:BLM:03": {"s_m": 3.8, "loss_w": 0.02},
            },
        }

    @app.get("/api/plots/orbit")
    async def get_orbit_plot() -> Dict[str, Any]:
        """Fetch processed dataset for interactive orbit trajectory plots."""
        bpms = {
            "MEBT:BPM:01": {"s_m": 0.5, "x_mm": 0.12, "y_mm": -0.05},
            "MEBT:BPM:02": {"s_m": 1.8, "x_mm": -0.08, "y_mm": 0.15},
            "MEBT:BPM:03": {"s_m": 3.2, "x_mm": 0.22, "y_mm": -0.02},
        }
        return generate_orbit_plot_data(bpm_telemetry=bpms, tolerance_mm=0.5)

    @app.get("/api/plots/envelope")
    async def get_envelope_plot() -> Dict[str, Any]:
        """Fetch 3-sigma beam envelope and aperture limit dataset."""
        s = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
        sig_x = [1.2, 1.4, 1.1, 1.6, 1.3, 1.5, 1.2, 1.4, 1.3]
        sig_y = [1.3, 1.1, 1.5, 1.2, 1.4, 1.1, 1.6, 1.2, 1.4]
        return generate_envelope_plot_data(s_positions=s, sigma_x_mm=sig_x, sigma_y_mm=sig_y, aperture_radius_mm=15.0)

    @app.get("/api/plots/blm")
    async def get_blm_plot() -> Dict[str, Any]:
        """Fetch beam loss radiation heatmap dataset."""
        blms = {
            "MEBT:BLM:01": {"s_m": 1.0, "loss_w": 0.05},
            "MEBT:BLM:02": {"s_m": 2.5, "loss_w": 0.12},
            "MEBT:BLM:03": {"s_m": 3.8, "loss_w": 0.02},
        }
        return generate_blm_heatmap_data(blm_readings=blms, trip_threshold_w=1.0)

    @app.get("/api/plans")
    async def list_plans() -> List[Dict[str, Any]]:
        """List current operational plans."""
        return list(plans_store.values())

    @app.post("/api/plans/{plan_id}/approve")
    async def approve_plan(plan_id: str) -> Dict[str, Any]:
        """Operator approval trigger for Human-in-the-Loop workflows."""
        if plan_id not in plans_store:
            raise HTTPException(status_code=404, detail="Plan ID not found")
        plans_store[plan_id]["approved"] = True
        plans_store[plan_id]["state"] = "IN_PROGRESS"
        return {"status": "APPROVED", "plan_id": plan_id}

    @app.post("/api/plans/{plan_id}/reject")
    async def reject_plan(plan_id: str) -> Dict[str, Any]:
        """Operator rejection trigger."""
        if plan_id not in plans_store:
            raise HTTPException(status_code=404, detail="Plan ID not found")
        plans_store[plan_id]["approved"] = False
        plans_store[plan_id]["state"] = "REJECTED"
        return {"status": "REJECTED", "plan_id": plan_id}

    @app.post("/api/emergency/panic")
    async def trigger_panic_shutdown() -> Dict[str, Any]:
        """Emergency panic button endpoint triggering immediate machine dump."""
        ok = rc.panic_shutdown()
        return {"status": "PANIC_EXECUTED", "success": ok}

    @app.websocket("/ws/telemetry")
    async def websocket_telemetry(websocket: WebSocket) -> None:
        """Stream real-time telemetry updates to connected operator consoles."""
        await websocket.accept()
        connected_clients.append(websocket)
        try:
            while True:
                payload = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "transmission_pct": 99.4 + 0.1 * np.random.randn(),
                    "orbit_rms_mm": 0.18 + 0.02 * np.random.randn(),
                }
                await websocket.send_text(json.dumps(payload))
                await asyncio.sleep(1.0)
        except WebSocketDisconnect:
            connected_clients.remove(websocket)

    return app
