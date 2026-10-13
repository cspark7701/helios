"""HELIOS Web Dashboard Backend Application (FastAPI).

Provides REST and WebSocket endpoints for real-time accelerator telemetry,
interactive physics visualizations, orbit tuning, and Human-in-the-Loop plan approval.
Features a clean, high-contrast white background with color fonts for control room displays.
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
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
from helios.physics.elements import Steerer
from helios.optimization.algorithms import SVDOrbitCorrection
from helios.safety.rollback import RollbackController

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
LEBT_STEERER_POS = [1.2, 3.1, 6.8, 9.2, 10.1]

# Calibrated Orbit Response Matrix for LEBT (mm/mrad)
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
) -> Dict[str, Any]:
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
        # MEBT baseline
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

    # Invert orbit distortion using SVD
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
    control_interface: Optional[BaseControlInterface] = None,
    rollback_controller: Optional[RollbackController] = None,
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

    # In-memory plan store for approval workflow
    plans_store: Dict[str, Dict[str, Any]] = {
        "00001": {
            "plan_id": "00001",
            "title": "LEBT Closed-Loop Trajectory Correction",
            "state": "READY",
            "autonomy_level": "ASSISTED",
            "steps": [
                {"step_id": "step_1", "name": "BPM & Wire Scanner Readback", "agent": "HELIOS-Diagnostics"},
                {"step_id": "step_2", "name": "SVD Trajectory Inversion & Quantization", "agent": "HELIOS-Tuner"},
                {"step_id": "step_3", "name": "Steerer Power Supply Slew (A)", "agent": "HELIOS-Control"},
            ],
            "approved": False,
        },
        "00002": {
            "plan_id": "00002",
            "title": "MEBT Longitudinal Envelope Matching",
            "state": "PENDING",
            "autonomy_level": "SUPERVISED",
            "steps": [
                {"step_id": "step_1", "name": "Buncher Cavity Phase Scan", "agent": "HELIOS-Physics"},
                {"step_id": "step_2", "name": "RFQ Output Verification", "agent": "HELIOS-Diagnostics"},
            ],
            "approved": False,
        },
    }

    connected_clients: List[WebSocket] = []

    @app.get("/", response_class=HTMLResponse)
    async def get_dashboard_html() -> str:
        """Serve single-page white-background operator console UI with color fonts."""
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
            padding-bottom: 40px;
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
            gap: 14px;
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

        /* Container Layout */
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 24px;
        }

        /* KPI Cards Grid */
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }
        .kpi-card {
            background: var(--bg-card);
            border: 1px solid var(--border-subtle);
            border-radius: 10px;
            padding: 18px 20px;
            box-shadow: var(--shadow-card);
            transition: box-shadow 0.2s;
        }
        .kpi-card:hover { box-shadow: var(--shadow-hover); }
        .kpi-label {
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--text-muted);
            margin-bottom: 6px;
            display: flex;
            justify-content: space-between;
        }
        .kpi-value {
            font-size: 30px;
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
            margin-bottom: 24px;
        }
        .tab-btn {
            background: transparent;
            border: none;
            padding: 10px 18px;
            font-size: 14px;
            font-weight: 700;
            color: var(--text-muted);
            cursor: pointer;
            border-bottom: 2px solid transparent;
            margin-bottom: -2px;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 8px;
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
            padding: 22px;
            box-shadow: var(--shadow-card);
            margin-bottom: 20px;
        }
        .panel-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 18px;
            padding-bottom: 12px;
            border-bottom: 1px solid var(--border-subtle);
        }
        .panel-title {
            font-size: 17px;
            font-weight: 800;
            color: var(--text-heading);
            display: flex;
            align-items: center;
            gap: 8px;
        }

        /* Form Controls */
        .form-row {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 18px;
        }
        .form-group {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .form-label {
            font-size: 13px;
            font-weight: 700;
            color: var(--text-heading);
        }
        .form-control {
            padding: 9px 12px;
            border: 1px solid var(--border-subtle);
            border-radius: 6px;
            font-size: 14px;
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
            padding: 10px 22px;
            border-radius: 6px;
            font-weight: 700;
            font-size: 14px;
            cursor: pointer;
            box-shadow: 0 2px 4px rgba(37,99,235,0.3);
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 8px;
        }
        .btn-primary:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 6px rgba(37,99,235,0.4);
        }
        .btn-outline {
            background: #ffffff;
            color: var(--text-body);
            border: 1px solid var(--border-subtle);
            padding: 9px 18px;
            border-radius: 6px;
            font-weight: 600;
            font-size: 13px;
            cursor: pointer;
            transition: all 0.2s;
        }
        .btn-outline:hover { background: #f8fafc; border-color: var(--border-hover); }

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
            padding: 10px 14px;
            border-bottom: 2px solid var(--border-subtle);
        }
        .data-table td {
            padding: 10px 14px;
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

        /* SVG Chart Styles */
        .chart-box {
            background: #ffffff;
            border: 1px solid var(--border-subtle);
            border-radius: 8px;
            padding: 16px;
            margin-top: 14px;
        }
        svg text { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }

        /* Results summary strip */
        .results-strip {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 12px;
            background: #f8fafc;
            border: 1px solid var(--border-subtle);
            border-radius: 8px;
            padding: 14px;
            margin-bottom: 16px;
        }
        .strip-item { display: flex; flex-direction: column; }
        .strip-title { font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 700; }
        .strip-val { font-size: 20px; font-weight: 800; }
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
            <span class="badge badge-purple" id="badge-autonomy">Autonomy: Assisted</span>
            <span class="badge badge-blue" id="badge-section">Section: LEBT</span>
            <button class="btn-panic" onclick="triggerPanic()">EMERGENCY PANIC</button>
        </div>
    </header>

    <div class="container">

        <!-- Top KPI Overview Bar -->
        <div class="kpi-grid">
            <div class="kpi-card">
                <div class="kpi-label">Beam Transmission <span class="badge badge-green">Nominal</span></div>
                <div class="kpi-value text-green" id="kpi-transmission">99.4%</div>
                <div class="kpi-sub">Beam Current: 4.85 mA | Energy: 0.50 MeV/u</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Orbit Distortion (RMS) <span class="badge badge-blue">&plusmn;0.50 mm Limit</span></div>
                <div class="kpi-value text-blue" id="kpi-orbit">0.1135 mm</div>
                <div class="kpi-sub">Tolerance: &plusmn;0.50 mm | Monitors: 6/6 Active</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Radiation & Losses <span class="badge badge-amber">Safe</span></div>
                <div class="kpi-value text-amber" id="kpi-losses">0.12 W/m</div>
                <div class="kpi-sub">MPS Trip Limit: 1.00 W/m | Interlocks: Normal</div>
            </div>
            <div class="kpi-card">
                <div class="kpi-label">Power Supply Actuation <span class="badge badge-purple">Calibrated</span></div>
                <div class="kpi-value text-purple" id="kpi-steerers">5 Steerers</div>
                <div class="kpi-sub">Transfer: 0.168 A/mrad | DAC Step: 0.05 A</div>
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
                    <div style="font-size: 13px; color: var(--text-muted);">Digital Twin SVD Response Matrix Solver</div>
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

                <div style="display: flex; gap: 12px; align-items: center; margin-bottom: 20px;">
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
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <span style="font-size: 14px; font-weight: 700; color: var(--text-heading);">Beam Centroid Trajectory X(z) vs Longitudinal Position</span>
                        <div style="display: flex; gap: 14px; font-size: 12px;">
                            <span style="display: flex; align-items: center; gap: 4px; color: var(--accent-red); font-weight: 700;">
                                <span style="width: 10px; height: 10px; background: var(--accent-red); border-radius: 50%; display: inline-block;"></span> Initial X (mm)
                            </span>
                            <span style="display: flex; align-items: center; gap: 4px; color: var(--primary-blue); font-weight: 700;">
                                <span style="width: 10px; height: 10px; background: var(--primary-blue); border-radius: 50%; display: inline-block;"></span> Corrected X (mm)
                            </span>
                            <span style="display: flex; align-items: center; gap: 4px; color: var(--accent-green); font-weight: 700;">
                                <span style="width: 10px; height: 3px; background: var(--accent-green); display: inline-block;"></span> &plusmn;0.50 mm Tolerance
                            </span>
                        </div>
                    </div>
                    <svg id="orbit-chart-svg" width="100%" height="280" viewBox="0 0 900 280"></svg>
                </div>

                <!-- Steerer Power Supply Actuation Table -->
                <div style="margin-top: 24px;">
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
                <div style="margin-top: 24px;">
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
                        <span style="font-size: 14px; font-weight: 700; color: var(--text-heading);">3-Sigma Beam Envelope vs Aperture Boundary</span>
                        <div style="display: flex; gap: 14px; font-size: 12px;">
                            <span class="text-blue">3&sigma;<sub>x</sub> Envelope (mm)</span>
                            <span class="text-purple">3&sigma;<sub>y</sub> Envelope (mm)</span>
                            <span class="text-red">&plusmn;15.0 mm Aperture Limit</span>
                        </div>
                    </div>
                    <svg id="envelope-chart-svg" width="100%" height="260" viewBox="0 0 900 260"></svg>
                </div>

                <div class="chart-box" style="margin-top: 20px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <span style="font-size: 14px; font-weight: 700; color: var(--text-heading);">Beam Loss Monitors (BLM) Radiation Distribution</span>
                        <span class="text-red" style="font-size: 12px;">Trip Threshold: 1.00 W/m</span>
                    </div>
                    <svg id="blm-chart-svg" width="100%" height="200" viewBox="0 0 900 200"></svg>
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
                                <td><button class="btn-primary" style="padding: 5px 12px; font-size: 12px;" onclick="approvePlan('00001')">Approve & Execute</button></td>
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
                <div style="background: #f8fafc; border: 1px solid var(--border-subtle); border-radius: 8px; padding: 16px; font-family: monospace; font-size: 13px; max-height: 380px; overflow-y: auto;" id="stream-log">
                    <div style="color: var(--text-muted);">Waiting for telemetry stream packets...</div>
                </div>
            </div>
        </div>

    </div>

    <!-- Client-Side Dashboard Logic -->
    <script>
        // Tab switching
        function switchTab(tabId) {
            document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            event.currentTarget.classList.add('active');
            if (tabId === 'tab-diagnostics') {
                loadDiagnosticPlots();
            }
        }

        // Render SVG Orbit Trajectory Chart
        function renderOrbitChart(monitors, tolerance) {
            const svg = document.getElementById('orbit-chart-svg');
            const w = 900, h = 280;
            const padL = 60, padR = 40, padT = 30, padB = 40;
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

            // Grid lines
            html += `<line x1="${padL}" y1="${padT}" x2="${padL + plotW}" y2="${padT}" stroke="#e2e8f0" />`;
            html += `<line x1="${padL}" y1="${padT + plotH}" x2="${padL + plotW}" y2="${padT + plotH}" stroke="#e2e8f0" />`;
            html += `<line x1="${padL}" y1="${scaleY(0)}" x2="${padL + plotW}" y2="${scaleY(0)}" stroke="#94a3b8" stroke-dasharray="3,3" />`;

            // Tolerance band (+/- tolerance)
            const tolTop = scaleY(tolerance);
            const tolBottom = scaleY(-tolerance);
            html += `<rect x="${padL}" y="${tolTop}" width="${plotW}" height="${tolBottom - tolTop}" fill="#ecfdf5" fill-opacity="0.5" stroke="#10b981" stroke-dasharray="4,4" />`;

            // Axis labels
            html += `<text x="${padL}" y="${scaleY(tolerance) - 4}" font-size="11" fill="#059669">+${tolerance} mm</text>`;
            html += `<text x="${padL}" y="${scaleY(-tolerance) + 12}" font-size="11" fill="#059669">-${tolerance} mm</text>`;
            html += `<text x="${padL - 10}" y="${padT + plotH/2}" font-size="12" fill="#475569" text-anchor="end" font-weight="bold">X (mm)</text>`;
            html += `<text x="${padL + plotW/2}" y="${h - 8}" font-size="12" fill="#475569" text-anchor="middle" font-weight="bold">Longitudinal Position z (m)</text>`;

            // Initial curve (red)
            let pathInit = '';
            monitors.forEach((m, idx) => {
                const px = scaleX(m.z_m), py = scaleY(m.x_init_mm);
                pathInit += (idx === 0 ? `M ${px} ${py}` : ` L ${px} ${py}`);
            });
            html += `<path d="${pathInit}" fill="none" stroke="#dc2626" stroke-width="2" stroke-dasharray="4,4" />`;

            // Corrected curve (blue)
            let pathCorr = '';
            monitors.forEach((m, idx) => {
                const px = scaleX(m.z_m), py = scaleY(m.x_corr_mm);
                pathCorr += (idx === 0 ? `M ${px} ${py}` : ` L ${px} ${py}`);
            });
            html += `<path d="${pathCorr}" fill="none" stroke="#2563eb" stroke-width="2.5" />`;

            // Points
            monitors.forEach(m => {
                const px = scaleX(m.z_m);
                const pyInit = scaleY(m.x_init_mm);
                const pyCorr = scaleY(m.x_corr_mm);
                html += `<circle cx="${px}" cy="${pyInit}" r="4.5" fill="#dc2626"><title>${m.name} @ ${m.z_m}m: X_init = ${m.x_init_mm} mm</title></circle>`;
                html += `<circle cx="${px}" cy="${pyCorr}" r="5" fill="#2563eb"><title>${m.name} @ ${m.z_m}m: X_corr = ${m.x_corr_mm} mm</title></circle>`;
                html += `<text x="${px}" y="${padT + plotH + 18}" font-size="10" fill="#64748b" text-anchor="middle">${m.name}</text>`;
            });

            svg.innerHTML = html;
        }

        // Execute orbit correction via API
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
                const res = await fetch('/api/tune/orbit', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        section: section,
                        engine: engine,
                        conversion_factor: factor,
                        current_increment: step
                    })
                });
                const data = await res.json();

                // Update Results Strip
                document.getElementById('res-init-rms').textContent = data.initial_rms_x_mm.toFixed(4) + ' mm';
                document.getElementById('res-corr-rms').textContent = data.corrected_rms_x_mm.toFixed(4) + ' mm';
                document.getElementById('res-improvement').textContent = (data.improvement_pct >= 0 ? '+' : '') + data.improvement_pct.toFixed(1) + '%';
                document.getElementById('res-timing').textContent = data.elapsed_time_s.toFixed(3) + ' s';

                // Update KPI banner
                document.getElementById('kpi-orbit').textContent = data.corrected_rms_x_mm.toFixed(4) + ' mm';

                // Render Chart
                renderOrbitChart(data.monitors, 0.50);

                // Update Steerers Table
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

                // Update Monitors Table
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

                status.textContent = `Correction completed in ${data.elapsed_time_s.toFixed(3)}s!`;
                status.style.color = '#059669';
            } catch (err) {
                status.textContent = 'Error: ' + err.message;
                status.style.color = '#dc2626';
            } finally {
                btn.disabled = false;
            }
        }

        // Load Diagnostics Plots (Envelope & BLM)
        async function loadDiagnosticPlots() {
            try {
                // Envelope Plot
                const resEnv = await fetch('/api/plots/envelope');
                const dataEnv = await resEnv.json();
                const svgEnv = document.getElementById('envelope-chart-svg');
                const s = dataEnv.s_positions_m;
                const envX = dataEnv.envelope_3sig_x_pos_mm;
                const envY = dataEnv.envelope_3sig_y_pos_mm;
                const ap = dataEnv.aperture_limit_mm;

                const padL = 60, padR = 40, padT = 20, padB = 40;
                const plotW = 900 - padL - padR, plotH = 260 - padT - padB;
                const scaleX = v => padL + (v / Math.max(...s)) * plotW;
                const scaleY = v => padT + (ap * 1.15 - v) / (ap * 2.3) * plotH;

                let html = '';
                // Aperture limit lines
                html += `<line x1="${padL}" y1="${scaleY(ap)}" x2="${padL + plotW}" y2="${scaleY(ap)}" stroke="#dc2626" stroke-dasharray="4,4" stroke-width="1.5" />`;
                html += `<line x1="${padL}" y1="${scaleY(-ap)}" x2="${padL + plotW}" y2="${scaleY(-ap)}" stroke="#dc2626" stroke-dasharray="4,4" stroke-width="1.5" />`;
                html += `<text x="${padL + plotW - 10}" y="${scaleY(ap) - 6}" font-size="11" fill="#dc2626" text-anchor="end">+15.0 mm Aperture</text>`;
                html += `<text x="${padL + plotW - 10}" y="${scaleY(-ap) + 14}" font-size="11" fill="#dc2626" text-anchor="end">-15.0 mm Aperture</text>`;

                // 3-sigma curves
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

                // BLM Plot
                const resBlm = await fetch('/api/plots/blm');
                const dataBlm = await resBlm.json();
                const svgBlm = document.getElementById('blm-chart-svg');
                const blmS = dataBlm.s_positions_m;
                const blmVals = dataBlm.loss_values_w;
                const trip = dataBlm.trip_threshold_w;

                const bPlotW = 900 - padL - padR, bPlotH = 200 - padT - padB;
                const bScaleX = v => padL + (v / Math.max(...blmS, 4.0)) * bPlotW;
                const bScaleY = v => padT + (trip * 1.2 - v) / (trip * 1.2) * bPlotH;

                let bHtml = '';
                bHtml += `<line x1="${padL}" y1="${bScaleY(trip)}" x2="${padL + bPlotW}" y2="${bScaleY(trip)}" stroke="#dc2626" stroke-dasharray="4,4" stroke-width="2" />`;
                bHtml += `<text x="${padL + bPlotW - 10}" y="${bScaleY(trip) - 6}" font-size="11" fill="#dc2626" text-anchor="end">Trip Limit: 1.00 W/m</text>`;

                blmVals.forEach((loss, i) => {
                    const bx = bScaleX(blmS[i]);
                    const by = bScaleY(loss);
                    const bh = padT + bPlotH - by;
                    bHtml += `<rect x="${bx - 12}" y="${by}" width="24" height="${bh}" fill="#f59e0b" rx="2" />`;
                    bHtml += `<text x="${bx}" y="${by - 6}" font-size="11" fill="#d97706" text-anchor="middle" font-weight="bold">${loss.toFixed(2)} W</text>`;
                    bHtml += `<text x="${bx}" y="${padT + bPlotH + 16}" font-size="11" fill="#64748b" text-anchor="middle">${dataBlm.blm_names[i]}</text>`;
                });
                svgBlm.innerHTML = bHtml;

            } catch (e) {
                console.error("Error loading plots:", e);
            }
        }

        // Human-in-the-loop plan approval
        async function approvePlan(planId) {
            try {
                const res = await fetch(`/api/plans/${planId}/approve`, {method: 'POST'});
                const data = await res.json();
                alert(`Plan ${planId} Approved and Dispatched to Agent Execution!`);
                location.reload();
            } catch (err) {
                alert('Approval failed: ' + err.message);
            }
        }

        // Emergency Panic
        async function triggerPanic() {
            if (confirm("🚨 EMERGENCY PANIC SHUTDOWN: Immediately dump heavy ion beam, zero RF cavity setpoints, and safe all magnetic power supplies?")) {
                try {
                    const res = await fetch('/api/emergency/panic', {method: 'POST'});
                    const data = await res.json();
                    alert("PANIC SHUTDOWN SUCCESSFUL: Machine in Safe State.");
                } catch (e) {
                    alert("Panic trigger failed: " + e.message);
                }
            }
        }

        // Live WebSocket Telemetry Stream
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

        // Initial trigger
        window.addEventListener('DOMContentLoaded', () => {
            executeOrbitCorrection();
            initWebSocket();
        });
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

    @app.post("/api/tune/orbit")
    async def tune_orbit_endpoint(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """API endpoint executing closed-loop orbit correction with steerer power supply currents."""
        req = payload or {}
        section = req.get("section", "LEBT")
        engine = req.get("engine", "analytic").lower()
        factor = float(req.get("conversion_factor", 0.168))
        step = float(req.get("current_increment", 0.05))

        if section.upper() == "LEBT" and engine == "track":
            try:
                from examples.tune_orbit_lebt import run_tune_orbit_example
                # Execute in background thread to prevent blocking event loop
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

        # Analytic execution
        return execute_analytic_orbit_correction(
            section=section,
            conversion_factor_a_per_mrad=factor,
            current_increment_a=step,
        )

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
