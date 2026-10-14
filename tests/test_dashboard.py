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


def get_auth_headers(client, role="ADMIN", username="test_operator"):
    resp = client.post("/api/auth/token", json={"username": username, "role": role})
    token = resp.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_dashboard_plan_approval_and_panic(client):
    """Verify Human-in-the-Loop plan approval and emergency panic trigger with RBAC permissions."""
    # List plans (public telemetry/view)
    resp_plans = client.get("/api/plans")
    assert resp_plans.status_code == 200
    plans = resp_plans.json()
    assert len(plans) >= 1

    # 1. Unauthenticated approval fails with 401
    resp_unauth = client.post("/api/plans/00001/approve")
    assert resp_unauth.status_code == 401

    # 2. Viewer attempting approval fails with 403 Forbidden
    viewer_headers = get_auth_headers(client, role="VIEWER")
    resp_viewer = client.post("/api/plans/00001/approve", headers=viewer_headers)
    assert resp_viewer.status_code == 403

    # 3. Physicist / Operator approval succeeds
    phys_headers = get_auth_headers(client, role="PHYSICIST")
    resp_appr = client.post("/api/plans/00001/approve", headers=phys_headers)
    assert resp_appr.status_code == 200
    assert resp_appr.json()["status"] == "APPROVED"

    # 4. Plan rejection
    resp_rej = client.post("/api/plans/00001/reject", headers=phys_headers)
    assert resp_rej.status_code == 200
    assert resp_rej.json()["status"] == "REJECTED"

    # 5. Unauthenticated emergency panic fails with 401
    resp_panic_unauth = client.post("/api/emergency/panic")
    assert resp_panic_unauth.status_code == 401

    # 6. Physicist attempting panic fails with 403 (requires PANIC_SHUTDOWN permission)
    resp_panic_phys = client.post("/api/emergency/panic", headers=phys_headers)
    assert resp_panic_phys.status_code == 403

    # 7. Safety officer / Admin emergency panic succeeds
    safety_headers = get_auth_headers(client, role="SAFETY_OFFICER")
    resp_panic = client.post("/api/emergency/panic", headers=safety_headers)
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
    """Verify orbit tuning API endpoint executes with RBAC checks and returns steerer currents and monitors."""
    payload = {
        "section": "LEBT",
        "engine": "analytic",
        "conversion_factor": 0.168,
        "current_increment": 0.05,
    }

    # 1. Unauthenticated call fails with 401
    resp_unauth = client.post("/api/tune/orbit", json=payload)
    assert resp_unauth.status_code == 401

    # 2. Viewer call fails with 403 Forbidden
    viewer_headers = get_auth_headers(client, role="VIEWER")
    resp_viewer = client.post("/api/tune/orbit", json=payload, headers=viewer_headers)
    assert resp_viewer.status_code == 403

    # 3. Physicist call succeeds
    phys_headers = get_auth_headers(client, role="PHYSICIST")
    resp = client.post("/api/tune/orbit", json=payload, headers=phys_headers)
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


def test_dashboard_prompt_window_endpoint(client):
    """Verify side panel prompt endpoint parses natural language directives and formulates plans."""
    resp = client.post("/api/prompt", json={
        "prompt": "Flatten orbit distortion in LEBT",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "explanation" in data
    assert "plan" in data
    assert data["plan"]["title"]
    assert len(data["plan"]["steps"]) >= 1

    # Empty prompt validation
    resp_empty = client.post("/api/prompt", json={"prompt": ""})
    assert resp_empty.status_code == 400


def test_dashboard_llm_model_selection(client):
    """Verify listing available models and querying with selected model configuration."""
    resp_models = client.get("/api/llm/models")
    assert resp_models.status_code == 200
    models = resp_models.json()
    assert len(models) >= 4
    model_ids = [m["id"] for m in models]
    assert "mock-helios-planner" in model_ids
    assert "llama3" in model_ids

    # Query with explicit model selection
    resp_prompt = client.post("/api/prompt", json={
        "prompt": "Scan buncher cavity phase in MEBT",
        "provider": "mock",
        "model": "mock-helios-planner"
    })
    assert resp_prompt.status_code == 200
    data = resp_prompt.json()
    assert data["model"] == "mock-helios-planner"
    assert data["provider"] == "mock"
    assert data["success"] is True



