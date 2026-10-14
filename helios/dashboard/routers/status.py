"""Status, telemetry, plots, and authentication routes for HELIOS dashboard."""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends

from helios.dashboard.deps import get_rbac_manager
from helios.dashboard.plots import (
    generate_blm_heatmap_data,
    generate_envelope_plot_data,
    generate_orbit_plot_data,
)
from helios.security.rbac import RBACManager, UserRole

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Status & Telemetry"])


@router.get("/api/status")
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


@router.get("/api/telemetry")
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


@router.get("/api/plots/orbit")
async def get_orbit_plot() -> dict[str, Any]:
    """Fetch processed dataset for interactive orbit trajectory plots."""
    bpms = {
        "MEBT:BPM:01": {"s_m": 0.5, "x_mm": 0.12, "y_mm": -0.05},
        "MEBT:BPM:02": {"s_m": 1.8, "x_mm": -0.08, "y_mm": 0.15},
        "MEBT:BPM:03": {"s_m": 3.2, "x_mm": 0.22, "y_mm": -0.02},
    }
    return generate_orbit_plot_data(bpm_telemetry=bpms, tolerance_mm=0.5)


@router.get("/api/plots/envelope")
async def get_envelope_plot() -> dict[str, Any]:
    """Fetch 3-sigma beam envelope and aperture limit dataset."""
    s = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    sig_x = [1.2, 1.4, 1.1, 1.6, 1.3, 1.5, 1.2, 1.4, 1.3]
    sig_y = [1.3, 1.1, 1.5, 1.2, 1.4, 1.1, 1.6, 1.2, 1.4]
    return generate_envelope_plot_data(s_positions=s, sigma_x_mm=sig_x, sigma_y_mm=sig_y, aperture_radius_mm=15.0)


@router.get("/api/plots/blm")
async def get_blm_plot() -> dict[str, Any]:
    """Fetch beam loss radiation heatmap dataset."""
    blms = {
        "MEBT:BLM:01": {"s_m": 1.0, "loss_w": 0.05},
        "MEBT:BLM:02": {"s_m": 2.5, "loss_w": 0.12},
        "MEBT:BLM:03": {"s_m": 3.8, "loss_w": 0.02},
    }
    return generate_blm_heatmap_data(blm_readings=blms, trip_threshold_w=1.0)


@router.post("/api/auth/token")
async def issue_auth_token(
    payload: dict[str, Any] | None = None,
    rbac: RBACManager = Depends(get_rbac_manager),
) -> dict[str, Any]:
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
