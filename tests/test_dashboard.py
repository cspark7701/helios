"""Unit tests for Web Dashboard and Real-Time Visualizations (Phase 13)."""

import pytest
from starlette.testclient import TestClient

from helios.dashboard.app import create_dashboard_app
from helios.dashboard.plots import (
    generate_blm_heatmap_data,
    generate_envelope_plot_data,
    generate_orbit_plot_data,
)


@pytest.fixture
def client():
    app = create_dashboard_app()
    return TestClient(app)


def test_dashboard_html_endpoint(client):
    """Verify root HTML operator dashboard renders."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "HELIOS Operator Console" in resp.text
    assert "EMERGENCY PANIC" in resp.text


def test_dashboard_status_and_telemetry(client):
    """Verify machine status and telemetry endpoints."""
    resp_stat = client.get("/api/status")
    assert resp_stat.status_code == 200
    data_stat = resp_stat.json()
    assert data_stat["status"] == "ONLINE"
    assert data_stat["autonomy_level"] == "ASSISTED"

    resp_telem = client.get("/api/telemetry")
    assert resp_telem.status_code == 200
    data_telem = resp_telem.json()
    assert "transmission_pct" in data_telem
    assert "bpm_telemetry" in data_telem


def test_dashboard_physics_plots_endpoints(client):
    """Verify plot dataset endpoints (orbit, envelope, blm)."""
    resp_orbit = client.get("/api/plots/orbit")
    assert resp_orbit.status_code == 200
    d_orbit = resp_orbit.json()
    assert "bpm_names" in d_orbit
    assert "x_mm" in d_orbit
    assert "tolerance_mm" in d_orbit

    resp_env = client.get("/api/plots/envelope")
    assert resp_env.status_code == 200
    d_env = resp_env.json()
    assert "envelope_3sig_x_pos_mm" in d_env
    assert "aperture_limit_mm" in d_env

    resp_blm = client.get("/api/plots/blm")
    assert resp_blm.status_code == 200
    d_blm = resp_blm.json()
    assert "loss_values_w" in d_blm
    assert "trip_threshold_w" in d_blm


def test_dashboard_plan_approval_and_panic(client):
    """Verify Human-in-the-Loop plan approval and emergency panic trigger."""
    # List plans
    resp_plans = client.get("/api/plans")
    assert resp_plans.status_code == 200
    plans = resp_plans.json()
    assert len(plans) >= 1

    # Approve plan
    resp_appr = client.post("/api/plans/00001/approve")
    assert resp_appr.status_code == 200
    assert resp_appr.json()["status"] == "APPROVED"

    # Emergency panic
    resp_panic = client.post("/api/emergency/panic")
    assert resp_panic.status_code == 200
    assert resp_panic.json()["status"] == "PANIC_EXECUTED"
    assert resp_panic.json()["success"] is True


def test_plot_generation_functions():
    """Unit test individual plot generation functions in plots.py."""
    # 1. Orbit plot
    bpm_data = {
        "BPM1": {"s_m": 0.5, "x_mm": 0.1, "y_mm": -0.2},
        "BPM2": {"s_m": 1.2, "x_mm": -0.3, "y_mm": 0.4},
    }
    orbit = generate_orbit_plot_data(bpm_data, tolerance_mm=0.25)
    assert orbit["bpm_names"] == ["BPM1", "BPM2"]
    assert orbit["tolerance_mm"] == 0.25

    # 2. Envelope plot
    env = generate_envelope_plot_data(
        s_positions=[0.0, 1.0],
        sigma_x_mm=[1.0, 2.0],
        sigma_y_mm=[1.5, 1.8],
        aperture_radius_mm=20.0,
    )
    assert len(env["envelope_3sig_x_pos_mm"]) == 2
    assert env["envelope_3sig_x_pos_mm"][1] == 6.0  # 3 * 2.0

    # 3. BLM Heatmap
    blm_data = {
        "BLM1": {"s_m": 0.8, "loss_w": 0.05},
        "BLM2": {"s_m": 2.1, "loss_w": 0.45},
    }
    blm = generate_blm_heatmap_data(blm_data, trip_threshold_w=1.0)
    assert blm["max_loss_w"] == 0.45
    assert blm["hotspot_location_m"] == 2.1


def test_dashboard_orbit_tuning_endpoint(client):
    """Verify orbit tuning API endpoint executes and returns steerer currents and monitors."""
    resp = client.post("/api/tune/orbit", json={
        "section": "LEBT",
        "engine": "analytic",
        "conversion_factor": 0.168,
        "current_increment": 0.05,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["section"] == "LEBT"
    assert "initial_rms_x_mm" in data
    assert "corrected_rms_x_mm" in data
    assert "steerers" in data
    assert len(data["steerers"]) == 5
    assert "current_x_a" in data["steerers"][0]
    assert "monitors" in data
    assert len(data["monitors"]) == 6
    assert "elapsed_time_s" in data

