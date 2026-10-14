"""HELIOS Web Dashboard Backend Application (FastAPI).

Provides REST and WebSocket endpoints for real-time accelerator telemetry,
interactive physics visualizations, orbit tuning, Human-in-the-Loop plan approval,
and an interactive side panel Natural Language Prompt Window with selectable Language Models.
Features a clean, high-contrast white background with color fonts.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

try:
    from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse
    HAVE_FASTAPI = True
except ImportError:
    FastAPI = None
    HAVE_FASTAPI = False

from helios.core.llm import create_llm_client
from helios.core.plan_engine import PlanStore
from helios.core.schemas import AutonomyLevel, ExecutionPlan, PlanState, PlanStep
from helios.dashboard.plots import (
    generate_blm_heatmap_data,
    generate_envelope_plot_data,
    generate_orbit_plot_data,
)
from helios.interfaces.base import BaseControlInterface
from helios.interfaces.epics import MockControlInterface
from helios.optimization.algorithms import SVDOrbitCorrection
from helios.physics.elements import Steerer
from helios.safety.rollback import RollbackController
from helios.security.rbac import AuthToken, Permission, RBACManager, UserRole

logger = logging.getLogger(__name__)


# Standard baseline diagnostics and response data for fast analytic GUI tuning
LEBT_STATION_DATA = [
    {"name": "WS_1", "z_m": 1.9812, "x_init": 0.0424, "y_init": 0.0001},
    {"name": "Allison", "z_m": 4.0082, "x_init": -0.0264, "y_init": -0.0002},
    {"name": "WS_2", "z_m": 7.6402, "x_init": 0.0967, "y_init": 0.0003},
    {"name": "WS_3", "z_m": 9.9872, "x_init": -0.1155, "y_init": -0.0001},
    {"name": "WS_4", "z_m": 10.7672, "x_init": -0.2281, "y_init": 0.0002},
    {"name": "BPM_EXIT", "z_m": 12.2832, "x_init": -0.0111, "y_init": -0.0003},
]

LEBT_STEERER_NAMES = ["STM_1", "STM_2", "STM_3", "STM_4", "STM_5"]

LEBT_RX = np.array([
    [-0.039,  0.000,  0.000,  0.000,  0.000],
    [-0.045,  0.155,  0.000,  0.000,  0.000],
    [-0.038,  0.182,  0.095,  0.000,  0.000],
    [-0.035,  0.210,  0.110, -0.095,  0.000],
    [-0.038,  0.235,  0.125, -0.108,  0.071],
    [-0.039,  0.254,  0.137, -0.120,  0.086],
])

LEBT_RY = np.array([
    [-0.075,  0.000,  0.000,  0.000,  0.000],
    [-0.078,  0.215,  0.000,  0.000,  0.000],
    [-0.072,  0.245,  0.130,  0.000,  0.000],
    [-0.068,  0.280,  0.150, -0.130,  0.000],
    [-0.070,  0.310,  0.170, -0.150, -0.240],
    [-0.075,  0.340,  0.190, -0.170, -0.241],
])


def execute_analytic_orbit_correction(
    section: str = "LEBT",
    conversion_factor_a_per_mrad: float = 0.168,
    current_increment_a: float = 0.05,
) -> dict[str, Any]:
    """Perform rapid analytic orbit correction for interactive operator console."""
    start_time = time.perf_counter()

    if section.upper() == "LEBT":
        stations = LEBT_STATION_DATA
        steerers = LEBT_STEERER_NAMES
        Rx = LEBT_RX
        Ry = LEBT_RY
        x_init = np.array([s["x_init"] for s in stations])
        y_init = np.array([s["y_init"] for s in stations])
    else:
        stations = [
            {"name": f"MEBT_BPM_{i+1:02d}", "z_m": round(0.5 + i * 0.45, 3), "x_init": round(0.15 * np.sin(i * 0.9), 4), "y_init": round(-0.10 * np.cos(i * 0.8), 4)}
            for i in range(8)
        ]
        steerers = ["MEBT_ST_01", "MEBT_ST_02", "MEBT_ST_03", "MEBT_ST_04"]
        m, n = len(stations), len(steerers)
        Rx = np.zeros((m, n))
        Ry = np.zeros((m, n))
        for i in range(m):
            for j in range(n):
                if i >= j * 2:
                    Rx[i, j] = 0.25 * (i - j * 2 + 1)
                    Ry[i, j] = 0.22 * (i - j * 2 + 1)
        x_init = np.array([s["x_init"] for s in stations])
        y_init = np.array([s["y_init"] for s in stations])

    rms_x_init = float(np.sqrt(np.mean(x_init**2)))
    rms_y_init = float(np.sqrt(np.mean(y_init**2)))

    kicks_x, _ = SVDOrbitCorrection.calculate_correction(
        response_matrix=Rx,
        measured_offsets_mm=x_init,
        singular_value_cutoff=1e-3,
        tikhonov_regularization=1e-4,
    )
    kicks_y, _ = SVDOrbitCorrection.calculate_correction(
        response_matrix=Ry,
        measured_offsets_mm=y_init,
        singular_value_cutoff=1e-3,
        tikhonov_regularization=1e-4,
    )

    steerers_result = []
    eff_kicks_x = []
    eff_kicks_y = []

    for idx, stm in enumerate(steerers):
        curr_x = Steerer.kick_to_current(float(kicks_x[idx]), conversion_factor_a_per_mrad, current_increment_a)
        curr_y = Steerer.kick_to_current(float(kicks_y[idx]), conversion_factor_a_per_mrad, current_increment_a)
        eff_kx = Steerer.current_to_kick(curr_x, conversion_factor_a_per_mrad)
        eff_ky = Steerer.current_to_kick(curr_y, conversion_factor_a_per_mrad)

        eff_kicks_x.append(eff_kx)
        eff_kicks_y.append(eff_ky)

        steerers_result.append({
            "name": stm,
            "kick_x_mrad": round(eff_kx, 4),
            "current_x_a": round(curr_x, 4),
            "kick_y_mrad": round(eff_ky, 4),
            "current_y_a": round(curr_y, 4),
        })

    x_corr = x_init + Rx @ np.array(eff_kicks_x)
    y_corr = y_init + Ry @ np.array(eff_kicks_y)

    rms_x_corr = float(np.sqrt(np.mean(x_corr**2)))
    rms_y_corr = float(np.sqrt(np.mean(y_corr**2)))
    improvement_x_pct = ((rms_x_init - rms_x_corr) / max(1e-6, rms_x_init)) * 100.0

    monitors_result = []
    for i, s in enumerate(stations):
        monitors_result.append({
            "name": s["name"],
            "z_m": s["z_m"],
            "x_init_mm": round(float(x_init[i]), 4),
            "x_corr_mm": round(float(x_corr[i]), 4),
            "y_init_mm": round(float(y_init[i]), 4),
            "y_corr_mm": round(float(y_corr[i]), 4),
        })

    elapsed_time_s = time.perf_counter() - start_time

    return {
        "section": section,
        "engine": "analytic",
        "initial_rms_x_mm": round(rms_x_init, 4),
        "corrected_rms_x_mm": round(rms_x_corr, 4),
        "initial_rms_y_mm": round(rms_y_init, 4),
        "corrected_rms_y_mm": round(rms_y_corr, 4),
        "improvement_pct": round(improvement_x_pct, 1),
        "elapsed_time_s": round(elapsed_time_s, 3),
        "conversion_factor_a_per_mrad": conversion_factor_a_per_mrad,
        "current_increment_a": current_increment_a,
        "steerers": steerers_result,
        "monitors": monitors_result,
    }


def create_dashboard_app(
    control_interface: BaseControlInterface | None = None,
    rollback_controller: RollbackController | None = None,
    rbac_manager: RBACManager | None = None,
    plan_store: PlanStore | None = None,
) -> Any:
    """Factory creating configured FastAPI dashboard application."""
    if not HAVE_FASTAPI:
        raise RuntimeError("FastAPI is not installed. Install with 'pip install fastapi uvicorn'.")

    app = FastAPI(
        title="HELIOS Heavy Ion Linac Operator Dashboard",
        description="Autonomous AI Agent Monitoring and Human-in-the-Loop Control Room Console",
        version="0.2.0",
    )

    ctrl = control_interface or MockControlInterface()
    rc = rollback_controller or RollbackController(control_interface=ctrl)
    rbac = rbac_manager or RBACManager()
    ps = plan_store or PlanStore()
    app.state.rbac = rbac
    app.state.plan_store = ps

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

    def require_permission(required_perm: Permission):
        async def dependency(
            authorization: str | None = Header(None, alias="Authorization"),
            x_auth_token: str | None = Header(None, alias="X-Auth-Token"),
        ) -> AuthToken:
            token_str = None
            if authorization:
                if authorization.lower().startswith("bearer "):
                    token_str = authorization[7:].strip()
                else:
                    token_str = authorization.strip()
            elif x_auth_token:
                token_str = x_auth_token.strip()

            if not token_str:
                raise HTTPException(
                    status_code=401,
                    detail="Authentication credentials were not provided. Expected Bearer or X-Auth-Token.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            token = rbac._active_tokens.get(token_str)
            if not token or time.time() > token.expires_at:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid or expired session authorization token.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            if not rbac.verify_permission(token_str, required_perm):
                raise HTTPException(
                    status_code=403,
                    detail=f"Forbidden: role '{token.role.value}' lacks required permission '{required_perm.value}'.",
                )

            return token

        return dependency

    connected_clients: list[WebSocket] = []

    @app.get("/", response_class=HTMLResponse)
    async def get_dashboard_html() -> str:
        """Serve single-page operator console UI with side panel prompt window and model selector."""
        return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HELIOS Operator Console</title>
    <style>
        :root {
            --bg-page: #ffffff;
            --bg-card: #ffffff;
            --bg-header: #ffffff;
            --border-subtle: #e2e8f0;
            --border-hover: #cbd5e1;
            --text-heading: #0f172a;
            --text-body: #334155;
            --text-muted: #64748b;
            --primary-blue: #2563eb;
            --primary-blue-dark: #1d4ed8;
            --accent-navy: #1e3a8a;
            --accent-green: #059669;
            --accent-green-bg: #ecfdf5;
            --accent-purple: #7c3aed;
            --accent-purple-bg: #f5f3ff;
            --accent-amber: #d97706;
            --accent-amber-bg: #fffbeb;
            --accent-red: #dc2626;
            --accent-red-bg: #fef2f2;
            --accent-cyan: #0284c7;
            --accent-cyan-bg: #f0f9ff;
            --shadow-card: 0 1px 3px 0 rgba(0,0,0,0.08), 0 1px 2px -1px rgba(0,0,0,0.06);
            --shadow-hover: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -2px rgba(0,0,0,0.06);
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: var(--bg-page);
            color: var(--text-body);
            line-height: 1.5;
            padding-bottom: 30px;
        }

        /* Top Navigation Bar */
        .navbar {
            background: var(--bg-header);
            border-bottom: 2px solid var(--border-subtle);
            padding: 14px 28px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            top: 0;
            z-index: 100;
        }
        .brand {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .brand-logo {
            font-size: 24px;
            font-weight: 900;
            color: var(--primary-blue);
            letter-spacing: -0.5px;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .brand-tag {
            font-size: 13px;
            color: var(--text-muted);
            font-weight: 500;
            border-left: 2px solid var(--border-subtle);
            padding-left: 12px;
        }
        .nav-actions {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-size: 12px;
            font-weight: 700;
            padding: 4px 10px;
            border-radius: 9999px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .badge-green { background: var(--accent-green-bg); color: var(--accent-green); border: 1px solid #a7f3d0; }
        .badge-blue { background: var(--accent-cyan-bg); color: var(--accent-cyan); border: 1px solid #bae6fd; }
        .badge-purple { background: var(--accent-purple-bg); color: var(--accent-purple); border: 1px solid #ddd6fe; }
        .badge-red { background: var(--accent-red-bg); color: var(--accent-red); border: 1px solid #fecaca; }
        .pulse-dot {
            width: 8px;
            height: 8px;
            background: var(--accent-green);
            border-radius: 50%;
            display: inline-block;
            box-shadow: 0 0 0 2px rgba(5,150,105,0.2);
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(5,150,105,0.5); }
            70% { transform: scale(1); box-shadow: 0 0 0 6px rgba(5,150,105,0); }
            100% { transform: scale(0.95); box-shadow: 0 0 0 0 rgba(5,150,105,0); }
        }

        .btn-panic {
            background: var(--accent-red);
            color: #ffffff;
            border: none;
            padding: 7px 16px;
            border-radius: 6px;
            font-weight: 700;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.2s;
            box-shadow: 0 2px 4px rgba(220,38,38,0.25);
        }
        .btn-panic:hover { background: #b91c1c; transform: translateY(-1px); }

        /* Two-Column Layout with Side Panel */
        .layout-grid {
            display: grid;
            grid-template-columns: 1fr 410px;
            gap: 22px;
            max-width: 1720px;
            margin: 0 auto;
            padding: 22px 28px;
        }
        @media (max-width: 1200px) {
            .layout-grid {
                grid-template-columns: 1fr;
            }
        }

        .main-col { min-width: 0; }
        .side-col { min-width: 0; }

        /* KPI Cards Grid */
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px;
            margin-bottom: 22px;
        }
        .kpi-card {
            background: var(--bg-card);
            border: 1px solid var(--border-subtle);
            border-radius: 10px;
            padding: 16px 18px;
            box-shadow: var(--shadow-card);
            transition: box-shadow 0.2s;
        }
        .kpi-card:hover { box-shadow: var(--shadow-hover); }
        .kpi-label {
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            margin-bottom: 4px;
            display: flex;
            justify-content: space-between;
        }
        .kpi-value {
            font-size: 28px;
            font-weight: 800;
            letter-spacing: -0.5px;
        }
        .kpi-sub {
            font-size: 12px;
            color: var(--text-muted);
            margin-top: 4px;
        }

        /* Tabs Navigation */
        .tabs-nav {
            display: flex;
            gap: 8px;
            border-bottom: 2px solid var(--border-subtle);
            margin-bottom: 22px;
        }
        .tab-btn {
            background: transparent;
            border: none;
            padding: 10px 16px;
            font-size: 13px;
            font-weight: 700;
            color: var(--text-muted);
            cursor: pointer;
            border-bottom: 2px solid transparent;
            margin-bottom: -2px;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .tab-btn:hover { color: var(--primary-blue); }
        .tab-btn.active {
            color: var(--primary-blue);
            border-bottom-color: var(--primary-blue);
        }

        .tab-pane { display: none; }
        .tab-pane.active { display: block; }

        /* Panels and Cards */
        .panel {
            background: var(--bg-card);
            border: 1px solid var(--border-subtle);
            border-radius: 10px;
            padding: 20px;
            box-shadow: var(--shadow-card);
            margin-bottom: 20px;
        }
        .panel-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid var(--border-subtle);
        }
        .panel-title {
            font-size: 16px;
            font-weight: 800;
            color: var(--text-heading);
            display: flex;
            align-items: center;
            gap: 8px;
        }

        /* Form Controls */
        .form-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 14px;
            margin-bottom: 16px;
        }
        .form-group {
            display: flex;
            flex-direction: column;
            gap: 5px;
        }
        .form-label {
            font-size: 12px;
            font-weight: 700;
            color: var(--text-heading);
        }
        .form-control {
            padding: 8px 12px;
            border: 1px solid var(--border-subtle);
            border-radius: 6px;
            font-size: 13px;
            color: var(--text-body);
            background: #ffffff;
            outline: none;
            transition: border-color 0.2s;
        }
        .form-control:focus {
            border-color: var(--primary-blue);
            box-shadow: 0 0 0 3px rgba(37,99,235,0.15);
        }

        /* Action Buttons */
        .btn-primary {
            background: linear-gradient(135deg, var(--primary-blue) 0%, var(--primary-blue-dark) 100%);
            color: #ffffff;
            border: none;
            padding: 9px 18px;
            border-radius: 6px;
            font-weight: 700;
            font-size: 13px;
            cursor: pointer;
            box-shadow: 0 2px 4px rgba(37,99,235,0.3);
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }
        .btn-primary:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 6px rgba(37,99,235,0.4);
        }

        /* Tables */
        .table-wrap { overflow-x: auto; margin-top: 12px; }
        .data-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            text-align: left;
        }
        .data-table th {
            background: #f8fafc;
            color: var(--text-heading);
            font-weight: 700;
            padding: 9px 12px;
            border-bottom: 2px solid var(--border-subtle);
        }
        .data-table td {
            padding: 9px 12px;
            border-bottom: 1px solid var(--border-subtle);
            color: var(--text-body);
        }
        .data-table tr:hover td { background: #f8fafc; }

        /* Color Font Utilities */
        .text-blue { color: var(--primary-blue); font-weight: 700; }
        .text-green { color: var(--accent-green); font-weight: 700; }
        .text-purple { color: var(--accent-purple); font-weight: 700; }
        .text-amber { color: var(--accent-amber); font-weight: 700; }
        .text-red { color: var(--accent-red); font-weight: 700; }

        /* Results strip */
        .results-strip {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 12px;
            background: #f8fafc;
            border: 1px solid var(--border-subtle);
            border-radius: 8px;
            padding: 12px 14px;
            margin-bottom: 16px;
        }
        .strip-item { display: flex; flex-direction: column; }
        .strip-title { font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 700; }
        .strip-val { font-size: 18px; font-weight: 800; }

        .chart-box {
            background: #ffffff;
            border: 1px solid var(--border-subtle);
            border-radius: 8px;
            padding: 14px;
            margin-top: 14px;
        }

        /* SIDE PANEL PROMPT WINDOW STYLES */
        .prompt-panel {
            background: #ffffff;
            border: 1px solid var(--border-subtle);
            border-radius: 10px;
            box-shadow: var(--shadow-card);
            display: flex;
            flex-direction: column;
            height: calc(100vh - 120px);
            position: sticky;
            top: 86px;
        }
        .prompt-header {
            padding: 12px 16px;
            border-bottom: 1px solid var(--border-subtle);
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #ffffff;
            border-top-left-radius: 10px;
            border-top-right-radius: 10px;
        }
        .prompt-title {
            font-size: 15px;
            font-weight: 800;
            color: var(--text-heading);
            display: flex;
            align-items: center;
            gap: 8px;
        }

        /* Model Selector Strip */
        .model-selector-box {
            padding: 10px 14px;
            background: #f8fafc;
            border-bottom: 1px solid var(--border-subtle);
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .model-selector-row {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .model-select-control {
            flex: 1;
            padding: 6px 10px;
            border: 1px solid var(--border-subtle);
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            color: var(--text-heading);
            background: #ffffff;
            outline: none;
            cursor: pointer;
        }
        .model-select-control:focus {
            border-color: var(--primary-blue);
        }
        .btn-gear {
            background: #ffffff;
            border: 1px solid var(--border-subtle);
            border-radius: 6px;
            padding: 5px 8px;
            cursor: pointer;
            font-size: 13px;
            color: var(--text-muted);
            transition: all 0.15s;
        }
        .btn-gear:hover {
            color: var(--primary-blue);
            border-color: var(--primary-blue);
        }
        .model-config-drawer {
            display: none;
            flex-direction: column;
            gap: 6px;
            background: #ffffff;
            border: 1px solid var(--border-subtle);
            border-radius: 6px;
            padding: 10px;
            margin-top: 4px;
            font-size: 11px;
        }
        .model-config-drawer.open {
            display: flex;
        }

        .prompt-messages {
            flex: 1;
            overflow-y: auto;
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            background: #fafafa;
        }
        .chat-bubble {
            border-radius: 8px;
            padding: 12px 14px;
            font-size: 13px;
            line-height: 1.45;
            box-shadow: 0 1px 2px rgba(0,0,0,0.04);
            animation: fadeIn 0.2s ease-in;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(4px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .bubble-user {
            background: #eff6ff;
            border: 1px solid #bfdbfe;
            margin-left: 20px;
        }
        .bubble-user-label {
            font-size: 11px;
            font-weight: 800;
            color: var(--primary-blue);
            margin-bottom: 4px;
            text-transform: uppercase;
        }
        .bubble-user-text {
            color: var(--accent-navy);
            font-weight: 600;
        }
        .bubble-assistant {
            background: #ffffff;
            border: 1px solid var(--border-subtle);
            margin-right: 10px;
        }
        .bubble-assistant-label {
            font-size: 11px;
            font-weight: 800;
            color: var(--accent-green);
            margin-bottom: 4px;
            text-transform: uppercase;
            display: flex;
            align-items: center;
            gap: 4px;
        }
        .plan-card-inline {
            background: #f8fafc;
            border: 1px solid #cbd5e1;
            border-radius: 6px;
            padding: 10px;
            margin-top: 8px;
            font-size: 12px;
        }
        .plan-step-item {
            display: flex;
            justify-content: space-between;
            padding: 3px 0;
            border-bottom: 1px dashed #e2e8f0;
            color: var(--text-body);
        }
        .quick-chips-box {
            padding: 10px 14px;
            background: #ffffff;
            border-top: 1px solid var(--border-subtle);
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }
        .chip-btn {
            background: #ffffff;
            border: 1px solid var(--border-subtle);
            border-radius: 9999px;
            padding: 4px 10px;
            font-size: 11px;
            font-weight: 600;
            color: var(--text-body);
            cursor: pointer;
            transition: all 0.15s;
        }
        .chip-btn:hover {
            border-color: var(--primary-blue);
            color: var(--primary-blue);
            background: var(--accent-cyan-bg);
        }
        .prompt-input-area {
            padding: 12px 14px;
            border-top: 1px solid var(--border-subtle);
            background: #ffffff;
            border-bottom-left-radius: 10px;
            border-bottom-right-radius: 10px;
        }
        .prompt-textarea {
            width: 100%;
            height: 68px;
            padding: 8px 12px;
            border: 1px solid var(--border-subtle);
            border-radius: 6px;
            font-size: 13px;
            font-family: inherit;
            color: var(--text-body);
            background: #ffffff;
            resize: none;
            outline: none;
            transition: border-color 0.2s;
        }
        .prompt-textarea:focus {
            border-color: var(--primary-blue);
            box-shadow: 0 0 0 3px rgba(37,99,235,0.15);
        }
        .prompt-actions {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 8px;
        }
    </style>
</head>
<body>

    <!-- Header Navigation Bar -->
    <header class="navbar">
        <div class="brand">
            <div class="brand-logo">⚡ HELIOS</div>
            <div class="brand-tag">Heavy Ion Linac Operator Console</div>
        </div>
        <div class="nav-actions">
            <span class="badge badge-green"><span class="pulse-dot"></span> System Online</span>
            <span class="badge badge-purple" id="badge-llm">LLM: mock-helios-planner</span>
            <span class="badge badge-blue" id="badge-section">Section: LEBT</span>
            <button class="btn-panic" onclick="triggerPanic()">EMERGENCY PANIC</button>
        </div>
    </header>

    <!-- Main Two-Column Layout Grid -->
    <div class="layout-grid">

        <!-- LEFT COLUMN: Main Operator Console -->
        <main class="main-col">

            <!-- Top KPI Overview Bar -->
            <div class="kpi-grid">
                <div class="kpi-card">
                    <div class="kpi-label">Beam Transmission <span class="badge badge-green">Nominal</span></div>
                    <div class="kpi-value text-green" id="kpi-transmission">99.4%</div>
                    <div class="kpi-sub">Beam Current: 4.85 mA | Energy: 0.50 MeV/u</div>
                </div>
                <div class="kpi-card">
                    <div class="kpi-label">Orbit Distortion (RMS) <span class="badge badge-blue">&plusmn;0.50 mm</span></div>
                    <div class="kpi-value text-blue" id="kpi-orbit">0.1135 mm</div>
                    <div class="kpi-sub">Tolerance: &plusmn;0.50 mm | Monitors: 6/6 Active</div>
                </div>
                <div class="kpi-card">
                    <div class="kpi-label">Radiation Losses <span class="badge badge-amber">Safe</span></div>
                    <div class="kpi-value text-amber" id="kpi-losses">0.12 W/m</div>
                    <div class="kpi-sub">MPS Trip Limit: 1.00 W/m | Interlocks: Normal</div>
                </div>
                <div class="kpi-card">
                    <div class="kpi-label">Corrector Current <span class="badge badge-purple">Calibrated</span></div>
                    <div class="kpi-value text-purple" id="kpi-steerers">5 Steerers</div>
                    <div class="kpi-sub">Transfer: 0.168 A/mrad | Step: 0.05 A</div>
                </div>
            </div>

            <!-- Tabbed Navigation Bar -->
            <div class="tabs-nav">
                <button class="tab-btn active" onclick="switchTab('tab-tuning')">🎯 Closed-Loop Orbit Tuning</button>
                <button class="tab-btn" onclick="switchTab('tab-diagnostics')">📊 Beam Diagnostics & Optics</button>
                <button class="tab-btn" onclick="switchTab('tab-safety')">🛡️ Safety Plans & MPS Interlocks</button>
                <button class="tab-btn" onclick="switchTab('tab-stream')">📡 Real-Time Telemetry Stream</button>
            </div>

            <!-- TAB 1: CLOSED-LOOP ORBIT TUNING -->
            <div id="tab-tuning" class="tab-pane active">
                <div class="panel">
                    <div class="panel-header">
                        <div class="panel-title">🎯 Closed-Loop Trajectory Tuning & Current Actuation</div>
                        <div style="font-size: 13px; color: var(--text-muted);">SVD Orbit Response Matrix Solver</div>
                    </div>

                    <div class="form-row">
                        <div class="form-group">
                            <label class="form-label">Linac Section</label>
                            <select class="form-control" id="tune-section">
                                <option value="LEBT" selected>LEBT (5 Steerers, 6 Diagnostic Stations)</option>
                                <option value="MEBT">MEBT (4 Steerers, 8 BPM Stations)</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label class="form-label">Physics Engine</label>
                            <select class="form-control" id="tune-engine">
                                <option value="analytic" selected>Fast Analytic SVD Engine (&lt; 0.05s)</option>
                                <option value="track">TRACK Beam Dynamics Simulator (Wine)</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label class="form-label">Steerer Calibration Factor (A/mrad)</label>
                            <input type="number" step="0.001" class="form-control" id="tune-factor" value="0.168">
                        </div>
                        <div class="form-group">
                            <label class="form-label">Current Step Limit (A)</label>
                            <input type="number" step="0.01" class="form-control" id="tune-step" value="0.05">
                        </div>
                    </div>

                    <div style="display: flex; gap: 12px; align-items: center; margin-bottom: 18px;">
                        <button class="btn-primary" id="btn-run-tune" onclick="executeOrbitCorrection()">
                            <span>⚡ Run Closed-Loop Orbit Correction</span>
                        </button>
                        <span id="tune-status" style="font-size: 13px; font-weight: 600; color: var(--text-muted);">Ready to tune.</span>
                    </div>

                    <!-- Results Strip -->
                    <div class="results-strip" id="tune-results-strip">
                        <div class="strip-item">
                            <span class="strip-title">Initial Orbit RMS</span>
                            <span class="strip-val text-red" id="res-init-rms">0.1135 mm</span>
                        </div>
                        <div class="strip-item">
                            <span class="strip-title">Corrected Orbit RMS</span>
                            <span class="strip-val text-green" id="res-corr-rms">0.0820 mm</span>
                        </div>
                        <div class="strip-item">
                            <span class="strip-title">RMS Improvement</span>
                            <span class="strip-val text-blue" id="res-improvement">+27.8%</span>
                        </div>
                        <div class="strip-item">
                            <span class="strip-title">Orbit Correction Time</span>
                            <span class="strip-val text-purple" id="res-timing">0.042 s</span>
                        </div>
                    </div>

                    <!-- Interactive Orbit Trajectory Chart (SVG) -->
                    <div class="chart-box">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                            <span style="font-size: 13px; font-weight: 700; color: var(--text-heading);">Beam Centroid Trajectory X(z) vs Longitudinal Position</span>
                            <div style="display: flex; gap: 14px; font-size: 11px;">
                                <span style="display: flex; align-items: center; gap: 4px; color: var(--accent-red); font-weight: 700;">
                                    <span style="width: 8px; height: 8px; background: var(--accent-red); border-radius: 50%; display: inline-block;"></span> Initial X (mm)
                                </span>
                                <span style="display: flex; align-items: center; gap: 4px; color: var(--primary-blue); font-weight: 700;">
                                    <span style="width: 8px; height: 8px; background: var(--primary-blue); border-radius: 50%; display: inline-block;"></span> Corrected X (mm)
                                </span>
                                <span style="display: flex; align-items: center; gap: 4px; color: var(--accent-green); font-weight: 700;">
                                    <span style="width: 8px; height: 3px; background: var(--accent-green); display: inline-block;"></span> &plusmn;0.50 mm Tolerance
                                </span>
                            </div>
                        </div>
                        <svg id="orbit-chart-svg" width="100%" height="260" viewBox="0 0 900 260"></svg>
                    </div>

                    <!-- Steerer Power Supply Actuation Table -->
                    <div style="margin-top: 22px;">
                        <div class="panel-title" style="margin-bottom: 8px;">⚡ Actuated Steerer Power Supply Currents</div>
                        <div class="table-wrap">
                            <table class="data-table">
                                <thead>
                                    <tr>
                                        <th>Corrector Magnet</th>
                                        <th>Deflection Kick &theta;<sub>x</sub> (mrad)</th>
                                        <th>Power Supply I<sub>x</sub> (A)</th>
                                        <th>Deflection Kick &theta;<sub>y</sub> (mrad)</th>
                                        <th>Power Supply I<sub>y</sub> (A)</th>
                                        <th>DAC Status</th>
                                    </tr>
                                </thead>
                                <tbody id="steerers-table-body">
                                    <tr>
                                        <td><strong>STM_1</strong></td>
                                        <td class="text-blue">+0.0000 mrad</td>
                                        <td class="text-purple">+0.00 A</td>
                                        <td class="text-blue">+0.0000 mrad</td>
                                        <td class="text-purple">+0.00 A</td>
                                        <td><span class="badge badge-green">APPLIED</span></td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <!-- Diagnostic Stations Readings Table -->
                    <div style="margin-top: 22px;">
                        <div class="panel-title" style="margin-bottom: 8px;">📡 Diagnostic Observation Stations Summary</div>
                        <div class="table-wrap">
                            <table class="data-table">
                                <thead>
                                    <tr>
                                        <th>Monitor Station</th>
                                        <th>Position z (m)</th>
                                        <th>Initial X (mm)</th>
                                        <th>Corrected X (mm)</th>
                                        <th>Offset Residual &Delta;X (mm)</th>
                                    </tr>
                                </thead>
                                <tbody id="monitors-table-body">
                                    <tr>
                                        <td>WS_1</td>
                                        <td>1.9812 m</td>
                                        <td class="text-red">+0.0424 mm</td>
                                        <td class="text-green">+0.0424 mm</td>
                                        <td>0.0000 mm</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </div>

                </div>
            </div>

            <!-- TAB 2: BEAM DIAGNOSTICS & OPTICS -->
            <div id="tab-diagnostics" class="tab-pane">
                <div class="panel">
                    <div class="panel-header">
                        <div class="panel-title">📊 Transverse Beam Envelope & Radiation Losses</div>
                    </div>

                    <div class="chart-box">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                            <span style="font-size: 13px; font-weight: 700; color: var(--text-heading);">3-Sigma Beam Envelope vs Aperture Boundary</span>
                            <div style="display: flex; gap: 14px; font-size: 11px;">
                                <span class="text-blue">3&sigma;<sub>x</sub> Envelope (mm)</span>
                                <span class="text-purple">3&sigma;<sub>y</sub> Envelope (mm)</span>
                                <span class="text-red">&plusmn;15.0 mm Aperture Limit</span>
                            </div>
                        </div>
                        <svg id="envelope-chart-svg" width="100%" height="240" viewBox="0 0 900 240"></svg>
                    </div>

                    <div class="chart-box" style="margin-top: 18px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                            <span style="font-size: 13px; font-weight: 700; color: var(--text-heading);">Beam Loss Monitors (BLM) Radiation Distribution</span>
                            <span class="text-red" style="font-size: 11px;">Trip Threshold: 1.00 W/m</span>
                        </div>
                        <svg id="blm-chart-svg" width="100%" height="190" viewBox="0 0 900 190"></svg>
                    </div>
                </div>
            </div>

            <!-- TAB 3: SAFETY & PLANS -->
            <div id="tab-safety" class="tab-pane">
                <div class="panel">
                    <div class="panel-header">
                        <div class="panel-title">🛡️ Active Operational Execution Plans (Human-in-the-Loop)</div>
                    </div>

                    <div class="table-wrap">
                        <table class="data-table">
                            <thead>
                                <tr>
                                    <th>Plan ID</th>
                                    <th>Operational Directive</th>
                                    <th>Autonomy Level</th>
                                    <th>Workflow State</th>
                                    <th>Operator Actions</th>
                                </tr>
                            </thead>
                            <tbody id="plans-table-body">
                                <tr>
                                    <td><strong class="text-blue">00001</strong></td>
                                    <td>LEBT Closed-Loop Trajectory Correction</td>
                                    <td><span class="badge badge-purple">ASSISTED</span></td>
                                    <td><span class="badge badge-blue">READY</span></td>
                                    <td><button class="btn-primary" style="padding: 4px 10px; font-size: 11px;" onclick="approvePlan('00001')">Approve & Execute</button></td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>

            <!-- TAB 4: REAL-TIME TELEMETRY STREAM -->
            <div id="tab-stream" class="tab-pane">
                <div class="panel">
                    <div class="panel-header">
                        <div class="panel-title">📡 Live WebSocket Telemetry Feed</div>
                        <div id="ws-status" class="badge badge-green"><span class="pulse-dot"></span> Live Stream Active</div>
                    </div>
                    <div style="background: #f8fafc; border: 1px solid var(--border-subtle); border-radius: 8px; padding: 14px; font-family: monospace; font-size: 12px; max-height: 380px; overflow-y: auto;" id="stream-log">
                        <div style="color: var(--text-muted);">Waiting for telemetry stream packets...</div>
                    </div>
                </div>
            </div>

        </main>

        <!-- RIGHT COLUMN: SIDE PANEL PROMPT WINDOW WITH MODEL SELECTOR -->
        <aside class="side-col">
            <div class="prompt-panel">
                <div class="prompt-header">
                    <div class="prompt-title">
                        <span>💬 AI Assistant Prompt</span>
                    </div>
                    <span class="badge badge-purple" id="panel-model-badge">mock-helios-planner</span>
                </div>

                <!-- Model Selection Bar -->
                <div class="model-selector-box">
                    <div class="model-selector-row">
                        <select class="model-select-control" id="llm-model-select" onchange="onModelChange()">
                            <optgroup label="Offline / Deterministic (No Network)">
                                <option value="mock|mock-helios-planner" selected>🤖 Offline (mock-helios-planner)</option>
                            </optgroup>
                            <optgroup label="Local GPU (Ollama / On-Premise)">
                                <option value="ollama|llama3">🦙 Ollama: Llama 3 (Local)</option>
                                <option value="ollama|mistral">⚡ Ollama: Mistral (Local)</option>
                                <option value="ollama|deepseek-r1">🧠 Ollama: DeepSeek-R1 (Local)</option>
                                <option value="ollama|qwen2.5">🌐 Ollama: Qwen 2.5 (Local)</option>
                            </optgroup>
                            <optgroup label="Cloud API (OpenAI / External)">
                                <option value="openai|gpt-4o-mini">🌐 OpenAI: GPT-4o Mini</option>
                                <option value="openai|gpt-4o">🌐 OpenAI: GPT-4o</option>
                            </optgroup>
                            <optgroup label="Custom Endpoint">
                                <option value="custom|custom">⚙️ Custom Endpoint (vLLM / LocalAI)...</option>
                            </optgroup>
                        </select>
                        <button class="btn-gear" onclick="toggleModelConfig()" title="Configure Custom Endpoint or API Key">⚙️</button>
                    </div>

                    <!-- Collapsible Model Config Drawer -->
                    <div class="model-config-drawer" id="model-config-drawer">
                        <div>
                            <label style="font-weight: 700; color: var(--text-heading);">Base URL:</label>
                            <input type="text" class="form-control" id="custom-base-url" placeholder="http://localhost:11434/v1" style="font-size: 11px; padding: 4px 8px;">
                        </div>
                        <div>
                            <label style="font-weight: 700; color: var(--text-heading);">Model Name:</label>
                            <input type="text" class="form-control" id="custom-model-name" placeholder="llama3 or gpt-4o" style="font-size: 11px; padding: 4px 8px;">
                        </div>
                        <div style="font-size: 11px; color: var(--text-muted); padding-top: 4px;">
                            <span style="font-weight: 600;">Server Auth:</span> Keys configured via server environment (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)
                        </div>
                    </div>
                </div>

                <!-- Chat Messages Scroll Area -->
                <div class="prompt-messages" id="prompt-messages">
                    <div class="chat-bubble bubble-assistant">
                        <div class="bubble-assistant-label"><span>🤖 HELIOS Orchestrator</span></div>
                        <div style="color: var(--text-body);">
                            Control room console ready. Enter an operational directive (e.g. <em>"Correct orbit in LEBT"</em> or <em>"Calculate steerer currents with 0.168 A/mrad"</em>) to synthesize and execute a validated plan.
                        </div>
                    </div>
                </div>

                <!-- Quick Prompt Suggestion Chips -->
                <div class="quick-chips-box">
                    <button class="chip-btn" onclick="sendQuickPrompt('Correct orbit in LEBT with 0.168 A/mrad')">🎯 Correct LEBT Orbit</button>
                    <button class="chip-btn" onclick="sendQuickPrompt('Scan buncher cavity phase in MEBT')">⚡ Cavity Phase Scan</button>
                    <button class="chip-btn" onclick="sendQuickPrompt('Verify linac beam transmission and radiation losses')">📊 Check Losses</button>
                </div>

                <!-- Input Box -->
                <div class="prompt-input-area">
                    <textarea class="prompt-textarea" id="prompt-input" placeholder="Type directive: e.g. 'Flatten LEBT orbit with 0.168 A/mrad'..." onkeydown="handlePromptKey(event)"></textarea>
                    <div class="prompt-actions">
                        <span style="font-size: 11px; color: var(--text-muted);" id="prompt-char-count">Press Enter ↵ to send</span>
                        <div style="display: flex; gap: 8px;">
                            <button class="btn-primary" id="btn-send-prompt" onclick="submitPrompt()" style="padding: 6px 14px; font-size: 12px;">
                                <span>⚡ Send</span>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </aside>

    </div>

    <!-- Client-Side Dashboard Logic -->
    <script>
        let authToken = null;
        async function getAuthToken() {
            if (!authToken) {
                try {
                    const res = await fetch('/api/auth/token', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({username: 'control_operator', role: 'ADMIN'})
                    });
                    if (res.ok) {
                        const d = await res.json();
                        authToken = d.token;
                    }
                } catch (e) {
                    console.warn('Could not acquire session token', e);
                }
            }
            return authToken;
        }

        function switchTab(tabId) {
            document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            event.currentTarget.classList.add('active');
            if (tabId === 'tab-diagnostics') {
                loadDiagnosticPlots();
            }
        }

        // Language Model Selector Logic
        function onModelChange() {
            const val = document.getElementById('llm-model-select').value;
            const [provider, model] = val.split('|');
            const drawer = document.getElementById('model-config-drawer');
            const badgeTop = document.getElementById('badge-llm');
            const badgeSide = document.getElementById('panel-model-badge');

            if (provider === 'custom') {
                drawer.classList.add('open');
                badgeTop.textContent = 'LLM: Custom';
                badgeSide.textContent = 'Custom';
            } else {
                drawer.classList.remove('open');
                badgeTop.textContent = `LLM: ${model}`;
                badgeSide.textContent = model;
            }
        }

        function toggleModelConfig() {
            const drawer = document.getElementById('model-config-drawer');
            drawer.classList.toggle('open');
        }

        function renderOrbitChart(monitors, tolerance) {
            const svg = document.getElementById('orbit-chart-svg');
            const w = 900, h = 260;
            const padL = 60, padR = 40, padT = 25, padB = 35;
            const plotW = w - padL - padR;
            const plotH = h - padT - padB;

            if (!monitors || monitors.length === 0) return;

            const zMin = 0;
            const zMax = Math.max(...monitors.map(m => m.z_m)) * 1.08;
            const maxVal = Math.max(tolerance * 1.2, ...monitors.map(m => Math.max(Math.abs(m.x_init_mm), Math.abs(m.x_corr_mm))));
            const yMin = -maxVal, yMax = maxVal;

            const scaleX = z => padL + (z - zMin) / (zMax - zMin) * plotW;
            const scaleY = val => padT + (yMax - val) / (yMax - yMin) * plotH;

            let html = '';

            html += `<line x1="${padL}" y1="${padT}" x2="${padL + plotW}" y2="${padT}" stroke="#e2e8f0" />`;
            html += `<line x1="${padL}" y1="${padT + plotH}" x2="${padL + plotW}" y2="${padT + plotH}" stroke="#e2e8f0" />`;
            html += `<line x1="${padL}" y1="${scaleY(0)}" x2="${padL + plotW}" y2="${scaleY(0)}" stroke="#94a3b8" stroke-dasharray="3,3" />`;

            const tolTop = scaleY(tolerance);
            const tolBottom = scaleY(-tolerance);
            html += `<rect x="${padL}" y="${tolTop}" width="${plotW}" height="${tolBottom - tolTop}" fill="#ecfdf5" fill-opacity="0.5" stroke="#10b981" stroke-dasharray="4,4" />`;

            html += `<text x="${padL}" y="${scaleY(tolerance) - 4}" font-size="10" fill="#059669">+${tolerance} mm</text>`;
            html += `<text x="${padL}" y="${scaleY(-tolerance) + 12}" font-size="10" fill="#059669">-${tolerance} mm</text>`;
            html += `<text x="${padL - 10}" y="${padT + plotH/2}" font-size="11" fill="#475569" text-anchor="end" font-weight="bold">X (mm)</text>`;
            html += `<text x="${padL + plotW/2}" y="${h - 6}" font-size="11" fill="#475569" text-anchor="middle" font-weight="bold">Longitudinal Position z (m)</text>`;

            let pathInit = '';
            monitors.forEach((m, idx) => {
                const px = scaleX(m.z_m), py = scaleY(m.x_init_mm);
                pathInit += (idx === 0 ? `M ${px} ${py}` : ` L ${px} ${py}`);
            });
            html += `<path d="${pathInit}" fill="none" stroke="#dc2626" stroke-width="2" stroke-dasharray="4,4" />`;

            let pathCorr = '';
            monitors.forEach((m, idx) => {
                const px = scaleX(m.z_m), py = scaleY(m.x_corr_mm);
                pathCorr += (idx === 0 ? `M ${px} ${py}` : ` L ${px} ${py}`);
            });
            html += `<path d="${pathCorr}" fill="none" stroke="#2563eb" stroke-width="2.5" />`;

            monitors.forEach(m => {
                const px = scaleX(m.z_m);
                const pyInit = scaleY(m.x_init_mm);
                const pyCorr = scaleY(m.x_corr_mm);
                html += `<circle cx="${px}" cy="${pyInit}" r="4" fill="#dc2626"><title>${m.name}: X_init = ${m.x_init_mm} mm</title></circle>`;
                html += `<circle cx="${px}" cy="${pyCorr}" r="4.5" fill="#2563eb"><title>${m.name}: X_corr = ${m.x_corr_mm} mm</title></circle>`;
                html += `<text x="${px}" y="${padT + plotH + 16}" font-size="10" fill="#64748b" text-anchor="middle">${m.name}</text>`;
            });

            svg.innerHTML = html;
        }

        async function executeOrbitCorrection() {
            const btn = document.getElementById('btn-run-tune');
            const status = document.getElementById('tune-status');
            const section = document.getElementById('tune-section').value;
            const engine = document.getElementById('tune-engine').value;
            const factor = parseFloat(document.getElementById('tune-factor').value) || 0.168;
            const step = parseFloat(document.getElementById('tune-step').value) || 0.05;

            btn.disabled = true;
            status.textContent = 'Executing orbit correction sequence...';
            status.style.color = '#2563eb';

            try {
                const token = await getAuthToken();
                const headers = {'Content-Type': 'application/json'};
                if (token) headers['Authorization'] = `Bearer ${token}`;

                const res = await fetch('/api/tune/orbit', {
                    method: 'POST',
                    headers: headers,
                    body: JSON.stringify({
                        section: section,
                        engine: engine,
                        conversion_factor: factor,
                        current_increment: step
                    })
                });
                const data = await res.json();

                document.getElementById('res-init-rms').textContent = data.initial_rms_x_mm.toFixed(4) + ' mm';
                document.getElementById('res-corr-rms').textContent = data.corrected_rms_x_mm.toFixed(4) + ' mm';
                document.getElementById('res-improvement').textContent = (data.improvement_pct >= 0 ? '+' : '') + data.improvement_pct.toFixed(1) + '%';
                document.getElementById('res-timing').textContent = data.elapsed_time_s.toFixed(3) + ' s';
                document.getElementById('kpi-orbit').textContent = data.corrected_rms_x_mm.toFixed(4) + ' mm';

                renderOrbitChart(data.monitors, 0.50);

                const tbodyS = document.getElementById('steerers-table-body');
                tbodyS.innerHTML = data.steerers.map(s => `
                    <tr>
                        <td><strong>${s.name}</strong></td>
                        <td class="text-blue">${(s.kick_x_mrad >= 0 ? '+' : '') + s.kick_x_mrad.toFixed(4)} mrad</td>
                        <td class="text-purple">${(s.current_x_a >= 0 ? '+' : '') + s.current_x_a.toFixed(2)} A</td>
                        <td class="text-blue">${(s.kick_y_mrad >= 0 ? '+' : '') + s.kick_y_mrad.toFixed(4)} mrad</td>
                        <td class="text-purple">${(s.current_y_a >= 0 ? '+' : '') + s.current_y_a.toFixed(2)} A</td>
                        <td><span class="badge badge-green">APPLIED</span></td>
                    </tr>
                `).join('');

                const tbodyM = document.getElementById('monitors-table-body');
                tbodyM.innerHTML = data.monitors.map(m => {
                    const diff = m.x_corr_mm - m.x_init_mm;
                    return `
                        <tr>
                            <td><strong>${m.name}</strong></td>
                            <td>${m.z_m.toFixed(4)} m</td>
                            <td class="text-red">${(m.x_init_mm >= 0 ? '+' : '') + m.x_init_mm.toFixed(4)} mm</td>
                            <td class="text-green">${(m.x_corr_mm >= 0 ? '+' : '') + m.x_corr_mm.toFixed(4)} mm</td>
                            <td>${(diff >= 0 ? '+' : '') + diff.toFixed(4)} mm</td>
                        </tr>
                    `;
                }).join('');

                status.textContent = `Completed in ${data.elapsed_time_s.toFixed(3)}s!`;
                status.style.color = '#059669';
                return data;
            } catch (err) {
                status.textContent = 'Error: ' + err.message;
                status.style.color = '#dc2626';
            } finally {
                btn.disabled = false;
            }
        }

        async function loadDiagnosticPlots() {
            try {
                const resEnv = await fetch('/api/plots/envelope');
                const dataEnv = await resEnv.json();
                const svgEnv = document.getElementById('envelope-chart-svg');
                const s = dataEnv.s_positions_m;
                const envX = dataEnv.envelope_3sig_x_pos_mm;
                const envY = dataEnv.envelope_3sig_y_pos_mm;
                const ap = dataEnv.aperture_limit_mm;

                const padL = 60, padR = 40, padT = 20, padB = 35;
                const plotW = 900 - padL - padR, plotH = 240 - padT - padB;
                const scaleX = v => padL + (v / Math.max(...s)) * plotW;
                const scaleY = v => padT + (ap * 1.15 - v) / (ap * 2.3) * plotH;

                let html = '';
                html += `<line x1="${padL}" y1="${scaleY(ap)}" x2="${padL + plotW}" y2="${scaleY(ap)}" stroke="#dc2626" stroke-dasharray="4,4" stroke-width="1.5" />`;
                html += `<line x1="${padL}" y1="${scaleY(-ap)}" x2="${padL + plotW}" y2="${scaleY(-ap)}" stroke="#dc2626" stroke-dasharray="4,4" stroke-width="1.5" />`;
                html += `<text x="${padL + plotW - 10}" y="${scaleY(ap) - 6}" font-size="10" fill="#dc2626" text-anchor="end">+15.0 mm Aperture</text>`;
                html += `<text x="${padL + plotW - 10}" y="${scaleY(-ap) + 14}" font-size="10" fill="#dc2626" text-anchor="end">-15.0 mm Aperture</text>`;

                let pXPos = '', pXNeg = '', pYPos = '', pYNeg = '';
                s.forEach((z, i) => {
                    const px = scaleX(z);
                    pXPos += (i === 0 ? `M ${px} ${scaleY(envX[i])}` : ` L ${px} ${scaleY(envX[i])}`);
                    pXNeg += (i === 0 ? `M ${px} ${scaleY(-envX[i])}` : ` L ${px} ${scaleY(-envX[i])}`);
                    pYPos += (i === 0 ? `M ${px} ${scaleY(envY[i])}` : ` L ${px} ${scaleY(envY[i])}`);
                    pYNeg += (i === 0 ? `M ${px} ${scaleY(-envY[i])}` : ` L ${px} ${scaleY(-envY[i])}`);
                });
                html += `<path d="${pXPos}" fill="none" stroke="#2563eb" stroke-width="2" />`;
                html += `<path d="${pXNeg}" fill="none" stroke="#2563eb" stroke-width="2" />`;
                html += `<path d="${pYPos}" fill="none" stroke="#7c3aed" stroke-width="2" stroke-dasharray="3,3" />`;
                html += `<path d="${pYNeg}" fill="none" stroke="#7c3aed" stroke-width="2" stroke-dasharray="3,3" />`;

                svgEnv.innerHTML = html;

                const resBlm = await fetch('/api/plots/blm');
                const dataBlm = await resBlm.json();
                const svgBlm = document.getElementById('blm-chart-svg');
                const blmS = dataBlm.s_positions_m;
                const blmVals = dataBlm.loss_values_w;
                const trip = dataBlm.trip_threshold_w;

                const bPlotW = 900 - padL - padR, bPlotH = 190 - padT - padB;
                const bScaleX = v => padL + (v / Math.max(...blmS, 4.0)) * bPlotW;
                const bScaleY = v => padT + (trip * 1.2 - v) / (trip * 1.2) * bPlotH;

                let bHtml = '';
                bHtml += `<line x1="${padL}" y1="${bScaleY(trip)}" x2="${padL + bPlotW}" y2="${bScaleY(trip)}" stroke="#dc2626" stroke-dasharray="4,4" stroke-width="2" />`;
                bHtml += `<text x="${padL + bPlotW - 10}" y="${bScaleY(trip) - 6}" font-size="10" fill="#dc2626" text-anchor="end">Trip Limit: 1.00 W/m</text>`;

                blmVals.forEach((loss, i) => {
                    const bx = bScaleX(blmS[i]);
                    const by = bScaleY(loss);
                    const bh = padT + bPlotH - by;
                    bHtml += `<rect x="${bx - 12}" y="${by}" width="24" height="${bh}" fill="#f59e0b" rx="2" />`;
                    bHtml += `<text x="${bx}" y="${by - 6}" font-size="10" fill="#d97706" text-anchor="middle" font-weight="bold">${loss.toFixed(2)} W</text>`;
                    bHtml += `<text x="${bx}" y="${padT + bPlotH + 16}" font-size="10" fill="#64748b" text-anchor="middle">${dataBlm.blm_names[i]}</text>`;
                });
                svgBlm.innerHTML = bHtml;

            } catch (e) {
                console.error("Error loading plots:", e);
            }
        }

        async function approvePlan(planId) {
            try {
                const token = await getAuthToken();
                const headers = {'Content-Type': 'application/json'};
                if (token) headers['Authorization'] = `Bearer ${token}`;

                const res = await fetch(`/api/plans/${planId}/approve`, {method: 'POST', headers: headers});
                if (!res.ok) {
                    const errData = await res.json();
                    throw new Error(errData.detail || `Server returned ${res.status}`);
                }
                const data = await res.json();
                alert(`Plan ${planId} Approved and Dispatched to Agent Execution!`);
                location.reload();
            } catch (err) {
                alert('Approval failed: ' + err.message);
            }
        }

        async function triggerPanic() {
            if (confirm("🚨 EMERGENCY PANIC SHUTDOWN: Immediately dump heavy ion beam, zero RF cavity setpoints, and safe all magnetic power supplies?")) {
                try {
                    const token = await getAuthToken();
                    const headers = {'Content-Type': 'application/json'};
                    if (token) headers['Authorization'] = `Bearer ${token}`;

                    const res = await fetch('/api/emergency/panic', {method: 'POST', headers: headers});
                    if (!res.ok) {
                        const errData = await res.json();
                        throw new Error(errData.detail || `Server returned ${res.status}`);
                    }
                    const data = await res.json();
                    alert("PANIC SHUTDOWN SUCCESSFUL: Machine in Safe State.");
                } catch (e) {
                    alert("Panic trigger failed: " + e.message);
                }
            }
        }

        function handlePromptKey(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submitPrompt();
            }
        }

        function sendQuickPrompt(text) {
            document.getElementById('prompt-input').value = text;
            submitPrompt();
        }

        async function submitPrompt() {
            const input = document.getElementById('prompt-input');
            const promptText = input.value.trim();
            if (!promptText) return;

            const msgsBox = document.getElementById('prompt-messages');
            const btn = document.getElementById('btn-send-prompt');

            // Determine selected provider and model
            const modelVal = document.getElementById('llm-model-select').value;
            let [provider, model] = modelVal.split('|');
            let baseUrl = null;

            if (provider === 'custom') {
                baseUrl = document.getElementById('custom-base-url').value.trim() || 'http://localhost:11434/v1';
                model = document.getElementById('custom-model-name').value.trim() || 'llama3';
                provider = 'local';
            } else if (provider === 'ollama') {
                baseUrl = 'http://localhost:11434/v1';
            }

            // Append User message
            const userBubble = document.createElement('div');
            userBubble.className = 'chat-bubble bubble-user';
            userBubble.innerHTML = `
                <div class="bubble-user-label">Physicist Directive</div>
                <div class="bubble-user-text">${promptText}</div>
            `;
            msgsBox.appendChild(userBubble);
            input.value = '';
            msgsBox.scrollTop = msgsBox.scrollHeight;

            btn.disabled = true;

            // Append Assistant placeholder
            const assistBubble = document.createElement('div');
            assistBubble.className = 'chat-bubble bubble-assistant';
            assistBubble.innerHTML = `
                <div class="bubble-assistant-label"><span>🤖 HELIOS Orchestrator (${model})</span></div>
                <div style="color: var(--text-muted); font-style: italic;">Querying ${model} & formulating execution plan...</div>
            `;
            msgsBox.appendChild(assistBubble);
            msgsBox.scrollTop = msgsBox.scrollHeight;

            try {
                const res = await fetch('/api/prompt', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        prompt: promptText,
                        provider: provider,
                        model: model,
                        base_url: baseUrl
                    })
                });

                if (!res.ok) {
                    const errData = await res.json();
                    throw new Error(errData.detail || `Server returned ${res.status}`);
                }

                const data = await res.json();

                let stepsHtml = '';
                if (data.plan && data.plan.steps) {
                    stepsHtml = `
                        <div class="plan-card-inline">
                            <div style="font-weight: 700; color: var(--accent-navy); margin-bottom: 4px;">Proposed Plan: ${data.plan.title} (ID: ${data.plan.plan_id})</div>
                            ${data.plan.steps.map(s => `
                                <div class="plan-step-item">
                                    <span><strong>${s.name}</strong> (${s.agent})</span>
                                    <span class="badge badge-blue" style="font-size: 9px;">${s.action}</span>
                                </div>
                            `).join('')}
                            <div style="margin-top: 8px;">
                                <button class="btn-primary" style="padding: 4px 10px; font-size: 11px;" onclick="executePlanFromChat('${data.plan.plan_id}')">⚡ Execute Plan</button>
                            </div>
                        </div>
                    `;
                }

                assistBubble.innerHTML = `
                    <div class="bubble-assistant-label"><span>🤖 HELIOS Orchestrator (${data.model || model})</span></div>
                    <div style="color: var(--text-body);">${data.explanation}</div>
                    ${stepsHtml}
                `;
            } catch (err) {
                assistBubble.innerHTML = `
                    <div class="bubble-assistant-label"><span style="color:var(--accent-red)">⚠️ Model Error (${model})</span></div>
                    <div style="color: var(--accent-red); margin-bottom: 6px;">Failed to generate plan: ${err.message}</div>
                    <div style="font-size: 11px; color: var(--text-muted);">Tip: If local Ollama or cloud API is unreachable, switch to <strong>Offline (mock-helios-planner)</strong> in the dropdown above.</div>
                `;
            } finally {
                btn.disabled = false;
                msgsBox.scrollTop = msgsBox.scrollHeight;
            }
        }

        async function executePlanFromChat(planId) {
            const msgsBox = document.getElementById('prompt-messages');
            const note = document.createElement('div');
            note.className = 'chat-bubble bubble-assistant';
            note.innerHTML = `
                <div class="bubble-assistant-label"><span>⚡ Executing Plan ${planId}</span></div>
                <div style="color: var(--text-muted);">Actuating power supplies & verifying closed-loop orbit...</div>
            `;
            msgsBox.appendChild(note);
            msgsBox.scrollTop = msgsBox.scrollHeight;

            const result = await executeOrbitCorrection();
            if (result) {
                note.innerHTML = `
                    <div class="bubble-assistant-label"><span style="color: var(--accent-green)">✔ Plan ${planId} Executed</span></div>
                    <div style="color: var(--text-body);">
                        Orbit corrected successfully! Horizontal RMS: <strong>${result.initial_rms_x_mm} mm &rarr; ${result.corrected_rms_x_mm} mm</strong> (${result.improvement_pct >= 0 ? '+' : ''}${result.improvement_pct}%).
                        Execution time: <strong>${result.elapsed_time_s}s</strong>.
                    </div>
                `;
            } else {
                note.innerHTML = `
                    <div class="bubble-assistant-label"><span style="color: var(--accent-red)">⚠️ Plan ${planId} Failed</span></div>
                    <div style="color: var(--accent-red);">Execution encountered an error. Check machine telemetry.</div>
                `;
            }
            msgsBox.scrollTop = msgsBox.scrollHeight;
        }

        function initWebSocket() {
            const loc = window.location;
            const wsUri = (loc.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + loc.host + '/ws/telemetry';
            const streamLog = document.getElementById('stream-log');
            const ws = new WebSocket(wsUri);

            ws.onmessage = evt => {
                const d = JSON.parse(evt.data);
                const line = document.createElement('div');
                line.style.marginBottom = '4px';
                line.innerHTML = `<span style="color:#64748b;">[${d.timestamp.split('T')[1].split('.')[0]}]</span> ` +
                    `<span style="color:#059669; font-weight:bold;">Transmission: ${d.transmission_pct.toFixed(2)}%</span> | ` +
                    `<span style="color:#2563eb; font-weight:bold;">Orbit RMS: ${d.orbit_rms_mm.toFixed(3)} mm</span>`;
                streamLog.insertBefore(line, streamLog.firstChild);
                if (streamLog.childNodes.length > 50) streamLog.removeChild(streamLog.lastChild);
            };

            ws.onerror = () => {
                document.getElementById('ws-status').className = 'badge badge-red';
                document.getElementById('ws-status').textContent = 'Stream Offline';
            };
        }

        window.addEventListener('DOMContentLoaded', () => {
            executeOrbitCorrection();
            initWebSocket();
        });
    </script>
</body>
</html>"""

    @app.get("/api/status")
    async def get_machine_status() -> dict[str, Any]:
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
    async def get_telemetry() -> dict[str, Any]:
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
    async def get_orbit_plot() -> dict[str, Any]:
        """Fetch processed dataset for interactive orbit trajectory plots."""
        bpms = {
            "MEBT:BPM:01": {"s_m": 0.5, "x_mm": 0.12, "y_mm": -0.05},
            "MEBT:BPM:02": {"s_m": 1.8, "x_mm": -0.08, "y_mm": 0.15},
            "MEBT:BPM:03": {"s_m": 3.2, "x_mm": 0.22, "y_mm": -0.02},
        }
        return generate_orbit_plot_data(bpm_telemetry=bpms, tolerance_mm=0.5)

    @app.get("/api/plots/envelope")
    async def get_envelope_plot() -> dict[str, Any]:
        """Fetch 3-sigma beam envelope and aperture limit dataset."""
        s = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
        sig_x = [1.2, 1.4, 1.1, 1.6, 1.3, 1.5, 1.2, 1.4, 1.3]
        sig_y = [1.3, 1.1, 1.5, 1.2, 1.4, 1.1, 1.6, 1.2, 1.4]
        return generate_envelope_plot_data(s_positions=s, sigma_x_mm=sig_x, sigma_y_mm=sig_y, aperture_radius_mm=15.0)

    @app.get("/api/plots/blm")
    async def get_blm_plot() -> dict[str, Any]:
        """Fetch beam loss radiation heatmap dataset."""
        blms = {
            "MEBT:BLM:01": {"s_m": 1.0, "loss_w": 0.05},
            "MEBT:BLM:02": {"s_m": 2.5, "loss_w": 0.12},
            "MEBT:BLM:03": {"s_m": 3.8, "loss_w": 0.02},
        }
        return generate_blm_heatmap_data(blm_readings=blms, trip_threshold_w=1.0)

    @app.get("/api/plans")
    async def list_plans() -> list[dict[str, Any]]:
        """List current operational plans."""
        plans = ps.list_plans()
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

    @app.post("/api/auth/token")
    async def issue_auth_token(payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Issue an authenticated session token for operator or viewer."""
        req = payload or {}
        username = str(req.get("username", "control_room_operator"))
        role_str = str(req.get("role", "PHYSICIST")).upper()
        try:
            role = UserRole(role_str)
        except ValueError:
            role = UserRole.PHYSICIST
        token = rbac.issue_token(username=username, role=role)
        return {
            "token": token.token_str,
            "username": token.username,
            "role": token.role.value,
            "expires_at": token.expires_at,
        }

    @app.post("/api/plans/{plan_id}/approve")
    async def approve_plan(
        plan_id: str,
        token: AuthToken = Depends(require_permission(Permission.EXECUTE_CAPUT)),
    ) -> dict[str, Any]:
        """Operator approval trigger for Human-in-the-Loop workflows."""
        try:
            plan = ps.approve_plan(plan_id, operator_approval=True)
        except KeyError:
            raise HTTPException(status_code=404, detail="Plan ID not found")
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        logger.info(f"[RBAC AUDIT] Plan {plan_id} approved by user '{token.username}' (role '{token.role.value}')")
        return {"status": "APPROVED", "plan_id": plan_id, "state": plan.state.value}

    @app.post("/api/plans/{plan_id}/reject")
    async def reject_plan(
        plan_id: str,
        token: AuthToken = Depends(require_permission(Permission.PROPOSE_SETPOINT)),
    ) -> dict[str, Any]:
        """Operator rejection trigger."""
        try:
            plan = ps.reject_plan(plan_id, reason=f"Rejected by user '{token.username}'")
        except KeyError:
            raise HTTPException(status_code=404, detail="Plan ID not found")
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        logger.info(f"[RBAC AUDIT] Plan {plan_id} rejected by user '{token.username}' (role '{token.role.value}')")
        return {"status": "REJECTED", "plan_id": plan_id, "state": plan.state.value}

    @app.post("/api/emergency/panic")
    async def trigger_panic_shutdown(
        token: AuthToken = Depends(require_permission(Permission.PANIC_SHUTDOWN)),
    ) -> dict[str, Any]:
        """Emergency panic button endpoint triggering immediate machine dump."""
        ok = rc.panic_shutdown()
        logger.warning(f"[RBAC AUDIT] EMERGENCY PANIC triggered by user '{token.username}' (role '{token.role.value}')")
        return {"status": "PANIC_EXECUTED", "success": ok}

    @app.post("/api/tune/orbit")
    async def tune_orbit_endpoint(
        payload: dict[str, Any] | None = None,
        token: AuthToken = Depends(require_permission(Permission.EXECUTE_CAPUT)),
    ) -> dict[str, Any]:
        """API endpoint executing closed-loop orbit correction with steerer power supply currents."""
        req = payload or {}
        section = req.get("section", "LEBT")
        engine = req.get("engine", "analytic").lower()
        factor = float(req.get("conversion_factor", 0.168))
        step = float(req.get("current_increment", 0.05))
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
                    "improvement_pct": res["improvement_pct"],
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

    @app.get("/api/llm/models")
    async def get_llm_models_endpoint() -> list[dict[str, Any]]:
        """List selectable LLM models and local/cloud providers."""
        return [
            {
                "id": "mock-helios-planner",
                "name": "Offline Deterministic (mock-helios-planner)",
                "provider": "mock",
                "type": "Offline / Air-Gapped",
                "description": "Deterministic rule-based physics planner for air-gapped linac control.",
            },
            {
                "id": "llama3",
                "name": "Ollama: Llama 3",
                "provider": "ollama",
                "base_url": "http://localhost:11434/v1",
                "type": "Local GPU (Private)",
                "description": "On-premise LLM served via Ollama.",
            },
            {
                "id": "mistral",
                "name": "Ollama: Mistral",
                "provider": "ollama",
                "base_url": "http://localhost:11434/v1",
                "type": "Local GPU (Private)",
                "description": "Fast lightweight local model via Ollama.",
            },
            {
                "id": "deepseek-r1",
                "name": "Ollama: DeepSeek-R1",
                "provider": "ollama",
                "base_url": "http://localhost:11434/v1",
                "type": "Local GPU (Private)",
                "description": "Reasoning model running locally via Ollama.",
            },
            {
                "id": "gpt-4o-mini",
                "name": "OpenAI: GPT-4o Mini",
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "type": "Cloud API",
                "description": "Fast cloud LLM with structured tool calling.",
            },
            {
                "id": "gpt-4o",
                "name": "OpenAI: GPT-4o",
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "type": "Cloud API",
                "description": "Advanced reasoning cloud LLM.",
            },
        ]

    @app.post("/api/prompt")
    async def process_prompt_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
        """Process conversational directive with user-selected Language Model."""
        prompt = payload.get("prompt", "").strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="Prompt cannot be empty")

        provider = str(payload.get("provider", "mock")).lower()
        model_name = str(payload.get("model", "mock-helios-planner"))
        base_url = payload.get("base_url")

        llm_kwargs: dict[str, Any] = {}
        if model_name:
            llm_kwargs["model"] = model_name
        if base_url:
            llm_kwargs["base_url"] = base_url
        elif provider == "ollama":
            llm_kwargs["base_url"] = "http://localhost:11434/v1"

        # Resolve API keys strictly from server environment, never trust or log client-supplied keys
        server_key = (
            os.environ.get("HELIOS_LLM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
        )
        if server_key:
            llm_kwargs["api_key"] = server_key

        try:
            llm_client = create_llm_client(provider=provider, **llm_kwargs)
            from helios.agents.planner import NaturalLanguagePlanner
            planner = NaturalLanguagePlanner(llm_client=llm_client)
            plan, explanation = planner.formulate_plan_from_prompt(prompt)
        except Exception as e:
            logger.error(f"Error querying model {model_name} via {provider}: {e}")
            raise HTTPException(
                status_code=502,
                detail=f"Error querying model '{model_name}' via provider '{provider}': {str(e)}",
            )

        ps.register_plan(plan)

        return {
            "explanation": explanation,
            "model": model_name,
            "provider": provider,
            "plan": {
                "plan_id": plan.plan_id,
                "title": plan.title,
                "steps": [
                    {
                        "step_id": s.step_id,
                        "name": s.name,
                        "agent": s.target_agent,
                        "action": s.action,
                        "parameters": s.parameters,
                    }
                    for s in plan.steps
                ],
            },
            "success": True,
        }

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
                    "orbit_rms_mm": 0.1135 + 0.005 * np.random.randn(),
                }
                await websocket.send_text(json.dumps(payload))
                await asyncio.sleep(1.0)
        except WebSocketDisconnect:
            connected_clients.remove(websocket)

    return app
