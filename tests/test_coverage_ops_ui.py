"""Unit tests achieving 100% test coverage across operations, UI/dashboard, ontology, RL, and remaining linac edge branches."""

import asyncio
from datetime import datetime, timezone
import importlib
import json
import math
from pathlib import Path
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import numpy as np

from helios._optional import OptionalDependencyError
from helios.core.facility_config import FacilityConfig
from helios.core.llm import LLMMessage, MockLLMClient
from helios.core.plan_engine import PlanArtifactStore, PlanLifecycleManager, PlanStore
from helios.core.schemas import AutonomyLevel, ExecutionPlan, PlanState, PlanStep
from helios.dashboard.app import INDEX_HTML_PATH, create_dashboard_app
from helios.dashboard.deps import (
    get_control_interface,
    get_plan_store,
    get_rbac_manager,
    get_rollback_controller,
    require_permission,
)
import helios.dashboard.app as dash_app_mod
from helios.dashboard.routers.ws import websocket_telemetry
from fastapi import WebSocketDisconnect
import helios.envs as envs_pkg
import helios.models.surrogate as surr_mod
from helios.ontology.loader import LinkMLOntologyManager
import helios.optimization as opt_pkg
from helios.ui.visualizer import PhaseSpaceVisualizer
from helios.diagnostics.anomaly import AnomalyReport, AnomalySeverity, LinacAnomalyDetector
from helios.diagnostics.telemetry import TelemetryProcessor, TelemetrySnapshot
from helios.envs.linac_env import LinacGymEnv
import helios.envs.linac_env as envs_mod
from helios.interfaces.base import ControlInterfaceError
from helios.interfaces.channel_map import (
    ChannelManager,
    DeviceType,
    LinacDevice,
    create_baseline_mebt_channel_manager,
)
from helios.interfaces.epics import MockControlInterface
from helios.interfaces.pva import PVAccessInterface
import helios.interfaces.pva as pva_mod
import helios.interfaces.archiver as archiver_mod
from helios.models.calibration import OnlineModelCalibrator
from helios.ontology.graph import BeamlineKnowledgeGraph
from helios.ontology.rdf_exporter import RDFOntologyExporter
from helios.ops.audit import AuditEntry, AuditTrailLogger
from helios.ops.broker import DistributedEventBus, EventMessage, MessagePriority
from helios.ops.golden import CertificationGrade, GoldenRunCertificationEngine, GoldenRunParameter
from helios.ops.harness import VirtualLinacEPICSMock
from helios.ops.logbook import CircularBufferSample, LinacLogbookForensicsEngine, TripRootCause
from helios.optimization.algorithms import SVDOrbitCorrection
from helios.optimization.mpc import NeuralMPCController
from helios.optimization.rl_agent import ActorCriticNetwork, LinacRLAgent
import helios.optimization.rl_agent as rl_agent_mod
from helios.optimization.workflows import RFPhaseScanWorkflow
from helios.physics.beam_dump import BeamDumpParameters, BeamDumpThermalEngine, TargetMaterial
from helios.physics.differentiable import DifferentiableElement
import helios.physics.differentiable as diff_mod
from helios.physics.engine import ImpactZSimulator
from helios.physics.equipartition import HofmannEquipartitionEngine, LinacPhaseAdvance
from helios.physics.halo import BeamHaloQuantifier
from helios.physics.parallel import TensorParticleTracker
import helios.physics.parallel as parallel_mod
import helios.physics.twin.env as twin_env_mod
import helios.physics.twin.mpc as twin_mpc_mod
from helios.security.rbac import AuthToken, MPSHeartbeatWatchdog, Permission, RBACManager, UserRole
from helios.sim.cosim import ZeroCopyCoSimBridge
from helios.tuning.bba import BeamBasedAlignmentSolver
from helios.tuning.bunch_compressor import BunchCompressorChicaneOptimizer, ChicaneParameters
from helios.ui.voice import OperatorIntentParser


# ==============================================================================
# 1. Ops & Security Edge Coverage
# ==============================================================================

def test_coverage_ops_and_security(tmp_path: Path):
    # --- helios/ops/broker.py ---
    bus = DistributedEventBus()
    msg = EventMessage(
        message_id="m1",
        topic="diagnostics.bpm",
        sender_agent="HELIOS-Diag",
        payload={"orbit_rms": 0.1},
        priority=MessagePriority.NORMAL,
    )
    json_str = msg.to_json()
    assert "diagnostics.bpm" in json_str

    # Unsubscribe
    handler = MagicMock()
    bus.subscribe("diagnostics.*", handler)
    bus.unsubscribe("diagnostics.*", handler)

    # get_history with and without topic_prefix
    bus.publish("test.topic", "AgentA", {"val": 1})
    assert len(bus.get_history()) >= 1
    assert len(bus.get_history(topic_prefix="test")) >= 1
    assert len(bus.get_history(topic_prefix="nonexistent")) == 0

    # Safety subscriber failure raising RuntimeError
    def bad_safety_handler(m):
        raise ValueError("Simulated fault")

    bus.subscribe("safety.trip", bad_safety_handler)
    with pytest.raises(RuntimeError) as exc_info:
        bus.publish("safety.trip", "SafetyAgent", {"trip": True})
    assert "Critical safety event subscriber failed" in str(exc_info.value)

    # --- helios/ops/logbook.py ---
    forensics = LinacLogbookForensicsEngine()
    # Shift report with zero trips
    rep_zero = forensics.generate_shift_handover(
        shift_id="S-001",
        beam_species="U238",
        target_energy_MeV_u=17.5,
        shift_hours=8.0,
        operating_hours=8.0,
        trips_count=0,
        beam_current_uA=10.0,
        golden_cert_id="G1",
    )
    assert rep_zero.mean_time_between_failures_min == 8.0 * 60.0

    # Empty buffer samples raises ValueError
    with pytest.raises(ValueError):
        forensics.analyze_trip_circular_buffer("T-001", [])

    # Vacuum surge threshold crossing
    vac_sample = CircularBufferSample(
        time_offset_ms=-20.0,
        bpm_rms_error_mm=0.1,
        blm_total_dose_rate_Gy_s=0.001,
        rf_reflected_power_kW=0.2,
        vacuum_pressure_mbar=5.0e-5,  # Surge > 1.0e-6
        piezo_voltage_V=50.0,
    )
    rep_vac = forensics.analyze_trip_circular_buffer("T-002", [vac_sample])
    assert rep_vac.root_cause == TripRootCause.VACUUM_SPIKE_RUNAWAY

    # Benign samples (no anomaly thresholds exceeded) -> OPERATOR manual abort
    benign_sample = CircularBufferSample(
        time_offset_ms=-10.0,
        bpm_rms_error_mm=0.1,
        blm_total_dose_rate_Gy_s=0.001,
        rf_reflected_power_kW=0.2,
        vacuum_pressure_mbar=1.0e-8,
        piezo_voltage_V=50.0,
    )
    rep_op = forensics.analyze_trip_circular_buffer("T-003", [benign_sample])
    assert rep_op.root_cause == TripRootCause.OPERATOR_MANUAL_ABORT

    # --- helios/ops/golden.py ---
    golden_eng = GoldenRunCertificationEngine()
    with pytest.raises(KeyError):
        golden_eng.certify_machine_state("UNKNOWN_RUN", "U238", 17.5, {})

    p1 = GoldenRunParameter(pv_name="PV:1", baseline_value=10.0, tolerance_abs=1.0)
    p2 = GoldenRunParameter(pv_name="PV:2", baseline_value=20.0, tolerance_abs=1.0)
    golden_eng.register_golden_run("RUN_TEST", [p1, p2])

    # Missing PV -> NaN live value and inf deviation
    cert_missing = golden_eng.certify_machine_state("RUN_TEST", "U238", 17.5, {"PV:1": 10.0})
    assert cert_missing.compliance_score_percent < 100.0

    # Minor deviation (score >= 85 and < 98)
    params_many = [GoldenRunParameter(pv_name=f"PV:{i}", baseline_value=10.0, tolerance_abs=1.0) for i in range(10)]
    golden_eng.register_golden_run("RUN_MANY", params_many)
    # 9 pass, 1 fails -> 90% score -> MINOR_DEVIATION
    live_vals = {f"PV:{i}": 10.0 for i in range(9)}
    live_vals["PV:9"] = 50.0  # Violation
    cert_minor = golden_eng.certify_machine_state("RUN_MANY", "U238", 17.5, live_vals)
    assert cert_minor.grade == CertificationGrade.MINOR_DEVIATION

    # --- helios/ops/harness.py ---
    mock_ioc = VirtualLinacEPICSMock()
    mock_ioc.caput("SCL1:PS_CV01:CurrentSet", 2.0)
    assert mock_ioc.caget("SCL1:BPM01:Y") != 0.0

    # --- helios/ops/audit.py ---
    audit = AuditTrailLogger(db_path=None)
    audit._init_sqlite()  # db_path is None branch
    audit._load_from_sqlite()  # db_path is None branch
    ok, err = audit.verify_integrity()  # empty entries branch
    assert ok is True and err is None

    audit.log_action("op1", "SET", "PV:TEST", 1.0, 2.0, "Test action")
    audit.log_action("op1", "SET", "PV:TEST", 2.0, 3.0, "Second action")
    # Corrupt second entry's prev_hash to trigger broken chain
    audit._entries[1].prev_hash = "bad_prev_hash"
    ok_bad, err_bad = audit.verify_integrity()
    assert ok_bad is False and "Broken chain link" in err_bad

    # --- helios/security/rbac.py ---
    rbac = RBACManager()
    token = rbac.issue_token("phys_user", UserRole.PHYSICIST, validity_seconds=-1.0)  # Immediately expired
    assert rbac.verify_permission(token.token_str, Permission.READ_TELEMETRY) is False

    watchdog = MPSHeartbeatWatchdog(timeout_seconds=0.01)
    time.sleep(0.02)
    assert watchdog.check_health() is False
    assert watchdog.is_interlocked is True


# ==============================================================================
# 2. Dashboard App, Deps & Routes Coverage
# ==============================================================================

def test_coverage_dashboard_routes(tmp_path: Path):
    from fastapi.testclient import TestClient

    # 1. app.py fallback HTML when index.html does not exist
    with patch.object(Path, "exists", return_value=False):
        app = create_dashboard_app(control_interface=MockControlInterface())
        client = TestClient(app)
        res_idx = client.get("/")
        assert "index.html not found" in res_idx.text

    # 2. app.py missing fastapi dependency
    with patch.dict("sys.modules", {"fastapi": None}):
        with pytest.raises(OptionalDependencyError):
            importlib.reload(dash_app_mod)
    importlib.reload(dash_app_mod)

    # 3. deps.py branch coverage
    app = create_dashboard_app(control_interface=MockControlInterface())
    client = TestClient(app)

    req_mock = MagicMock()
    req_mock.app.state.control_interface = MockControlInterface()
    assert get_control_interface(req_mock) is not None

    p = ExecutionPlan(plan_id="9999", title="Test Plan", objective="Test Objective", autonomy_level=AutonomyLevel.ASSISTED)
    app.state.plan_store.register_plan(p)

    # Authorization header without "bearer "
    rbac = app.state.rbac
    token = rbac.issue_token("test_user", UserRole.PHYSICIST, validity_seconds=60.0)
    res_auth_raw = client.post("/api/plans/9999/approve", headers={"Authorization": token.token_str})
    assert res_auth_raw.status_code == 200

    # X-Auth-Token header
    res_auth_x = client.post("/api/plans/9999/reject", headers={"X-Auth-Token": token.token_str})
    assert res_auth_x.status_code == 200

    # Expired token in dependency
    exp_token = rbac.issue_token("exp_user", UserRole.PHYSICIST, validity_seconds=-10.0)
    res_exp = client.post("/api/plans/9999/approve", headers={"Authorization": f"Bearer {exp_token.token_str}"})
    assert res_exp.status_code == 401

    # 4. status_router: invalid role fallback
    res_tok = client.post("/api/auth/token", json={"username": "bob", "role": "INVALID_ROLE"})
    assert res_tok.status_code == 200
    assert res_tok.json()["role"] == UserRole.PHYSICIST.value

    # 5. llm_router: base_url, ollama provider, server_key, and exception
    headers = {"Authorization": f"Bearer {token.token_str}"}
    with patch("helios.dashboard.routers.llm.create_llm_client") as mock_create_llm:
        mock_create_llm.return_value = MockLLMClient()
        res_llm_base = client.post(
            "/api/prompt",
            json={"prompt": "Correct MEBT orbit", "base_url": "http://mock-llm:8000/v1"},
        )
        assert res_llm_base.status_code == 200

        res_llm_ollama = client.post(
            "/api/prompt",
            json={"prompt": "Correct MEBT orbit", "provider": "ollama"},
        )
        assert res_llm_ollama.status_code == 200

    with patch.dict("os.environ", {"HELIOS_LLM_API_KEY": "secret-key"}):
        with patch("helios.dashboard.routers.llm.create_llm_client", return_value=MockLLMClient()):
            res_llm_key = client.post(
                "/api/prompt",
                json={"prompt": "Correct MEBT orbit"},
            )
            assert res_llm_key.status_code == 200

    # LLM exception -> 502
    with patch("helios.dashboard.routers.llm.create_llm_client", side_effect=RuntimeError("LLM API Down")):
        res_llm_fail = client.post(
            "/api/prompt",
            json={"prompt": "Correct MEBT orbit"},
        )
        assert res_llm_fail.status_code == 502

    # 6. plans_router: general exception handling in approve / reject
    plan_store: PlanStore = app.state.plan_store
    with patch.object(plan_store, "approve_plan", side_effect=RuntimeError("Transition failed")):
        res_appr_err = client.post("/api/plans/9999/approve", headers=headers)
        assert res_appr_err.status_code == 400

    with patch.object(plan_store, "reject_plan", side_effect=RuntimeError("Rejection failed")):
        res_rej_err = client.post("/api/plans/9999/reject", headers=headers)
        assert res_rej_err.status_code == 400

    # 7. tuning_router: panic, LEBT track execution, fallback on exception, and default payload
    admin_token = rbac.issue_token("admin_user", UserRole.ADMIN, validity_seconds=60.0)
    res_panic = client.post("/api/emergency/panic", headers={"Authorization": f"Bearer {admin_token.token_str}"})
    assert res_panic.status_code == 200
    assert res_panic.json()["status"] == "PANIC_EXECUTED"

    mock_tune_res = {
        "initial_rms_x_mm": 1.2,
        "corrected_rms_x_mm": 0.2,
        "improvement_pct": 83.3,
        "elapsed_time_s": 0.12,
        "steerers": [{"name": "S1"}],
        "monitors": [{"name": "B1"}],
    }
    with patch("examples.tune_orbit_lebt.run_tune_orbit_example", return_value=mock_tune_res):
        res_lebt = client.post(
            "/api/tune/orbit",
            headers=headers,
            json={"section": "LEBT", "engine": "track"},
        )
        assert res_lebt.status_code == 200
        assert res_lebt.json()["section"] == "LEBT"
        assert len(res_lebt.json()["steerers"]) == 1

    # Exception in track execution triggers fallback to analytic model (lines 64-66)
    with patch("examples.tune_orbit_lebt.run_tune_orbit_example", side_effect=RuntimeError("Simulation engine error")):
        res_fb = client.post(
            "/api/tune/orbit",
            headers=headers,
            json={"section": "LEBT", "engine": "track"},
        )
        assert res_fb.status_code == 200
        assert "initial_rms_x_mm" in res_fb.json()

    # None payload / default payload test
    res_default = client.post("/api/tune/orbit", headers=headers)
    assert res_default.status_code == 200
    assert "initial_rms_x_mm" in res_default.json()

    # 8. ws_router: WebSocketDisconnect cleanup
    mock_ws = AsyncMock()
    mock_ws_app = MagicMock()
    mock_ws_app.state.connected_clients = []
    mock_ws.app = mock_ws_app
    mock_ws.send_text.side_effect = WebSocketDisconnect()
    asyncio.run(websocket_telemetry(mock_ws))
    assert len(mock_ws_app.state.connected_clients) == 0


# ==============================================================================
# 3. Ontology, Graph & Voice Coverage
# ==============================================================================

def test_coverage_ontology_and_voice():
    # --- helios/ontology/rdf_exporter.py ---
    exporter = RDFOntologyExporter()
    elements = [
        {
            "id": "CAV01",
            "name": "MEBT_CAV01",
            "section": "MEBT",
            "voltage_kv": 120.0,
            "phase_deg": -25.0,
            "readback_pv": "MEBT:RF:CAV01:AmpAct",
            "z_position_m": 1.2,
        },
        {
            "id": "BLM01",
            "name": "MEBT_BLM01",
            "section": "MEBT",
            "loss_rate_gy_per_s": 0.005,
            "z_position_m": 1.5,
        },
    ]
    exporter.export_elements_to_graph(elements, lattice_name="MEBT_TEST")
    owl_xml = exporter.serialize_owl_xml()
    assert "RFCavityElement" in owl_xml or "MEBT_CAV01" in owl_xml

    # --- helios/ontology/graph.py ---
    graph = BeamlineKnowledgeGraph(elements)
    assert graph.get_element("CAV01") is not None

    with pytest.raises(KeyError):
        graph.find_nearest_neighbors("NON_EXISTENT")

    # upstream_only and downstream_only filtering
    up_neighbors = graph.find_nearest_neighbors("BLM01", upstream_only=True)
    down_neighbors = graph.find_nearest_neighbors("CAV01", downstream_only=True)
    assert len(up_neighbors) >= 1
    assert len(down_neighbors) >= 1

    elements_3 = [
        {"id": "E1", "name": "E1", "z_position_m": 1.0, "type": "quad"},
        {"id": "E2", "name": "E2", "z_position_m": 2.0, "type": "quad"},
        {"id": "E3", "name": "E3", "z_position_m": 3.0, "type": "quad"},
    ]
    graph_3 = BeamlineKnowledgeGraph(elements_3)
    up_e2 = graph_3.find_nearest_neighbors("E2", upstream_only=True)
    assert len(up_e2) == 1 and up_e2[0].element_id == "E1"
    down_e2 = graph_3.find_nearest_neighbors("E2", downstream_only=True)
    assert len(down_e2) == 1 and down_e2[0].element_id == "E3"

    # --- helios/ui/voice.py ---
    parser = OperatorIntentParser()
    cmd_xe = parser.parse_command("switch beam to xenon at 15 kv")
    assert cmd_xe.parameters.get("target_species") == "Xe124"
    assert cmd_xe.parameters.get("target_value") == 15.0

    cmd_ar = parser.parse_command("tune orbit for argon 40")
    assert cmd_ar.parameters.get("target_species") == "Ar40"

    cmd_o = parser.parse_command("inject oxygen beam into linac")
    assert cmd_o.parameters.get("target_species") == "O16"


# ==============================================================================
# 4. Optimization, Envs & Tuning Edge Coverage
# ==============================================================================

def test_coverage_optimization_and_envs():
    # --- helios/envs/linac_env.py ---
    env_exp = LinacGymEnv(steerer_pvs=["S1"], bpm_pvs=["B1"])
    assert env_exp.steerer_pvs == ["S1"]
    assert env_exp.bpm_pvs == ["B1"]

    with patch("helios.core.facility_config.FacilityConfig.load_default", side_effect=Exception):
        env_fallback = LinacGymEnv()
        assert len(env_fallback.steerer_pvs) == 4
        assert len(env_fallback.bpm_pvs) == 4

    with patch("helios.envs.linac_env._HAS_GYM", False):
        with pytest.raises(OptionalDependencyError):
            LinacGymEnv()

    with patch.dict("sys.modules", {"gymnasium": None}):
        importlib.reload(envs_mod)
        assert envs_mod._HAS_GYM is False
    importlib.reload(envs_mod)

    # --- helios/optimization/rl_agent.py ---
    with patch("helios.optimization.rl_agent._HAS_TORCH", False):
        with pytest.raises(OptionalDependencyError):
            ActorCriticNetwork(obs_dim=4, action_dim=2)
        with pytest.raises(OptionalDependencyError):
            LinacRLAgent(obs_dim=4, action_dim=2)

    with patch.dict("sys.modules", {"torch": None}):
        importlib.reload(rl_agent_mod)
        assert rl_agent_mod.torch is None
    importlib.reload(rl_agent_mod)

    # --- helios/optimization/mpc.py ---
    mpc_exp = NeuralMPCController(actuator_keys=["S1", "S2"])
    assert mpc_exp.actuator_keys == ["S1", "S2"]

    with patch("helios.core.facility_config.FacilityConfig.load_default", side_effect=Exception):
        mpc_fb = NeuralMPCController()
        assert len(mpc_fb.actuator_keys) == 4

    # --- helios/optimization/workflows.py ---
    assert RFPhaseScanWorkflow.fit_synchronous_phase({}) == (0.0, 0.0)

    # --- helios/optimization/algorithms.py ---
    svd = SVDOrbitCorrection()
    R = np.eye(2)
    deltas, stats = svd.calculate_correction(R, measured_offsets_mm=[1.0, 1.0], target_offsets_mm=[0.2, 0.2])
    assert len(deltas) == 2

    # --- helios/tuning/bba.py ---
    with pytest.raises(ValueError):
        BeamBasedAlignmentSolver.solve_quad_offset(
            delta_k1=0.0,
            bpm_reading_nominal_mm=0.5,
            bpm_reading_modulated_mm=0.6,
            transfer_r12=0.0,
        )

    # --- helios/tuning/bunch_compressor.py ---
    chicane = BunchCompressorChicaneOptimizer()
    params_over = ChicaneParameters(
        dipole_bend_angle_deg=20.0,
        rf_chirp_voltage_MV=10.0,
        rf_chirp_phase_deg=-90.0,
    )
    res_over = chicane.evaluate_chicane(params_over)
    assert res_over.longitudinal_dispersion_status == "OVER_COMPRESSED"

    # --- helios/models/calibration.py ---
    calib = OnlineModelCalibrator()
    res_quads = calib.calibrate_quadrupole_factors(
        measured_orbit_mm={"MEBT:BPM:01:X": 0.5},
        active_setpoints={"MEBT:QUAD:01:B_SET": 10.0},
        adjustable_quads=["MEBT:QUAD:01:B_SET"],
    )
    assert "MEBT:QUAD:01:B_SET" in res_quads.calibrated_factors

    with patch("helios.core.facility_config.FacilityConfig.load_default", side_effect=Exception):
        res_fb = calib.calibrate_quadrupole_factors(
            measured_orbit_mm={"MEBT:BPM:01:X": 0.5},
            active_setpoints={"MEBT:QUAD:01:B_SET": 10.0},
            adjustable_quads=None,
        )
        assert len(res_fb.calibrated_factors) == 4


# ==============================================================================
# 5. Interfaces, Core & Diagnostics Edge Coverage
# ==============================================================================

def test_coverage_interfaces_and_core(tmp_path: Path):
    # --- helios/interfaces/channel_map.py ---
    with patch("helios.core.facility_config.FacilityConfig.load_default", side_effect=Exception("No facility config")):
        mgr_fb = create_baseline_mebt_channel_manager()
        assert mgr_fb.get_device("MEBT", "QD01") is not None
        assert mgr_fb.get_device("MEBT", "CH01") is not None
        assert mgr_fb.get_device("MEBT", "BPM01") is not None

    # --- helios/interfaces/pva.py ---
    with patch("helios.interfaces.pva.require"):
        mock_ctx = MagicMock()
        with patch.dict("sys.modules", {"p4p": MagicMock(), "p4p.client": MagicMock(), "p4p.client.thread": MagicMock(Context=mock_ctx)}):
            pva_live = PVAccessInterface(use_mock=False)
            assert pva_live.pva_ctxt is not None

    with patch.dict("sys.modules", {
        "p4p": MagicMock(),
        "p4p.client": MagicMock(),
        "p4p.client.thread": MagicMock(),
        "p4p.nt": MagicMock(),
    }):
        importlib.reload(pva_mod)
        assert pva_mod.PvaContext is not None
        assert pva_mod.NTTable is not None
    importlib.reload(pva_mod)

    with patch.dict("sys.modules", {"p4p": None, "p4p.client.thread": None}):
        importlib.reload(pva_mod)
        assert pva_mod.PvaContext is None
    importlib.reload(pva_mod)

    # --- helios/interfaces/archiver.py ---
    with patch.dict("sys.modules", {"requests": None}):
        importlib.reload(archiver_mod)
        assert archiver_mod.requests is None
    importlib.reload(archiver_mod)

    # --- helios/interfaces/epics.py ---
    mock_epics = MockControlInterface(readback_noise_std=0.05)
    mock_epics.set_initial_pv("PV:NOISE", 10.0)
    assert isinstance(mock_epics.get("PV:NOISE"), float)

    # --- helios/core/facility_config.py ---
    with patch.object(Path, "is_file", return_value=True):
        with patch.object(FacilityConfig, "from_yaml", side_effect=Exception("YAML read error")):
            cfg_mebt = FacilityConfig.load_default("MEBT")
            assert cfg_mebt.name == "HELIOS_MEBT_DEFAULT"

    # --- helios/core/llm.py ---
    mock_llm = MockLLMClient()
    resp_scl = mock_llm.generate([LLMMessage(role="user", content="correct orbit in scl linac")])
    assert resp_scl.tool_calls[0].arguments["section"] == "SCL"

    resp_fallback = mock_llm.generate([LLMMessage(role="user", content="Hello linac orchestrator")])
    assert "received directive" in resp_fallback.content

    # --- helios/core/plan_engine.py ---
    art_store = PlanArtifactStore(tmp_path)
    corrupted_plan_file = art_store.active_dir / "00099_corrupted_plan.md"
    corrupted_plan_file.write_text("```json\n{invalid json format}\n```", encoding="utf-8")
    disk_plan = art_store.load_plan("00099")
    assert disk_plan is not None

    store = PlanStore(artifact_store=art_store)
    plans = store.list_plans()
    assert any(p.plan_id == "00099" for p in plans)

    # --- helios/diagnostics/anomaly.py ---
    detector = LinacAnomalyDetector(max_rms_orbit_mm=1.0)
    telem = TelemetrySnapshot(
        timestamp=datetime.now(timezone.utc),
        transmission_pct=99.5,
        beam_current_ma=5.0,
        bpm_x={"B1": 0.2},
        bpm_y={"B1": 3.5},  # Excursion only in y
        blm_loss={"BLM1": 0.01},
    )
    reports = detector.inspect_telemetry(telem)
    assert any(r.anomaly_type == "ORBIT_EXCURSION" for r in reports)

    # --- helios/diagnostics/telemetry.py ---
    proc = TelemetryProcessor()
    with patch("math.radians", return_value=-0.1):  # Simulated negative phase
        e_neg = proc.calculate_energy_from_tof(phase_deg_1=100.0, phase_deg_2=50.0, distance_m=1.0)
        assert e_neg > 0

    class CustomPhase:
        def __sub__(self, other):
            return self
        def __mod__(self, other):
            return -10.0

    e_mod = proc.calculate_energy_from_tof(phase_deg_1=0.0, phase_deg_2=CustomPhase(), distance_m=1.0)
    assert e_mod > 0


# ==============================================================================
# 6. Physics Remaining Edge Coverage
# ==============================================================================

def test_coverage_physics_remaining():
    # --- helios/physics/engine.py ---
    with patch.dict("sys.modules", {"impact": MagicMock(), "impact.ImpactZ": MagicMock()}):
        sim = ImpactZSimulator()
        assert sim.is_available() is True

    # --- helios/physics/halo.py ---
    r = np.linspace(0, 25, 200)
    p_uniform = np.where(r < 5.0, 1.0, 0.0)
    res_low = BeamHaloQuantifier.evaluate_halo(p_uniform, r, pipe_radius_mm=30.0)
    assert res_low.scraping_risk_level == "LOW"

    res_high = BeamHaloQuantifier.evaluate_halo(p_uniform, r, pipe_radius_mm=7.8)
    assert res_high.scraping_risk_level == "HIGH"

    # --- helios/physics/beam_dump.py ---
    dump_eng = BeamDumpThermalEngine()
    params_dump = BeamDumpParameters(
        material=TargetMaterial.GLIDCOP,
        beam_power_kW=15.0,
        beam_energy_MeV_u=20.0,
    )
    res_dump = dump_eng.evaluate_beam_dump(params_dump)
    assert res_dump.status == "CONSTRAINED"

    # --- helios/physics/equipartition.py ---
    hof_eng = HofmannEquipartitionEngine()
    params_hof = LinacPhaseAdvance(
        section_id="MEBT",
        sigma_0t_deg=80.0,
        sigma_0l_deg=80.0,
        sigma_t_deg=30.0,
        sigma_l_deg=40.0,
        emit_norm_t_mm_mrad=0.3,
        emit_norm_l_deg_MeV=0.2,
    )
    res_hof = hof_eng.evaluate_stability(params_hof)
    assert res_hof.stability_status == "MARGINAL"

    # --- helios/physics/parallel.py ---
    with patch.dict("sys.modules", {"torch": None}):
        with patch("helios.physics.parallel.torch", None):
            with pytest.raises(OptionalDependencyError):
                TensorParticleTracker()

    with patch.dict("sys.modules", {"torch": None}):
        importlib.reload(parallel_mod)
        assert parallel_mod.torch is None
    importlib.reload(parallel_mod)

    # --- helios/sim/cosim.py ---
    cosim = ZeroCopyCoSimBridge(buffer_capacity=1)
    assert cosim.consume_latest_frame() is None
    bunch = np.zeros((10, 6))
    loss = np.zeros(10)
    cosim.publish_frame(10.0, bunch, loss)
    cosim.publish_frame(10.0, bunch, loss)  # Capacity overflow pop
    assert len(cosim._headers) == 1

    # --- helios/physics/differentiable.py ---
    with patch.dict("sys.modules", {"torch": None}):
        with pytest.raises(OptionalDependencyError):
            importlib.reload(diff_mod)
    importlib.reload(diff_mod)

    # --- helios/physics/twin/env.py & mpc.py ---
    with patch.dict("sys.modules", {"gymnasium": None}):
        importlib.reload(twin_env_mod)
        assert twin_env_mod._HAS_GYM is False
    importlib.reload(twin_env_mod)

    with patch.dict("sys.modules", {"torch": None}):
        importlib.reload(twin_mpc_mod)
        assert twin_mpc_mod._HAS_TORCH is False
    importlib.reload(twin_mpc_mod)


# ==============================================================================
# 7. Final Edge Coverage: Envs, Optimization, Ontology, Visualizer & Surrogate
# ==============================================================================

def test_coverage_final_remaining_branches():
    # --- helios/envs/__init__.py ---
    with patch.dict("sys.modules", {"helios.envs.linac_env": None}):
        importlib.reload(envs_pkg)
        assert envs_pkg.LinacGymEnv is None
    importlib.reload(envs_pkg)

    # --- helios/optimization/__init__.py ---
    with patch.dict("sys.modules", {"helios.optimization.rl_agent": None}):
        importlib.reload(opt_pkg)
        assert opt_pkg.LinacRLAgent is None
    importlib.reload(opt_pkg)

    # --- helios/ontology/loader.py ---
    with pytest.raises(FileNotFoundError):
        LinkMLOntologyManager(schema_path="nonexistent.yaml")

    mgr = LinkMLOntologyManager()
    with pytest.raises(KeyError):
        mgr.get_slots_for_class("NonExistent")

    js = mgr.generate_json_schema(target_class="Quadrupole")
    assert isinstance(js, dict)

    res_bad = mgr.validate_dict({}, target_class="NonExistent")
    assert res_bad.is_valid is False

    dev_cav = LinacDevice(name="CAV01", section="MEBT", device_type=DeviceType.RF_CAVITY, z_position_m=1.0)
    rec_cav = mgr.convert_linac_device_to_linkml(dev_cav)
    assert rec_cav["voltage_kv"] == 1200.0

    q_el = mgr.convert_linkml_to_helios_element({"name": "Q1", "k1_m_minus2": 2.0})
    assert q_el.name == "Q1"

    c_el = mgr.convert_linkml_to_helios_element({"name": "C1", "voltage_kv": 1200.0})
    assert c_el.name == "C1"

    d_el = mgr.convert_linkml_to_helios_element({"name": "D1"})
    assert d_el.name == "D1"

    # --- helios/ui/visualizer.py ---
    viz = PhaseSpaceVisualizer()
    tw_zero = viz.calculate_twiss(np.zeros(10), np.zeros(10))
    assert tw_zero.emittance_rms_mm_mrad == 0.0
    assert tw_zero.beta_m == 1.0

    bunch = np.random.randn(20, 6)
    proj_y = viz.project(bunch, plane="y")
    proj_z = viz.project(bunch, plane="z")
    assert proj_y.plane == "y" and proj_z.plane == "z"

    ascii_y = viz.render_ascii(bunch, plane="y")
    ascii_z = viz.render_ascii(bunch, plane="z")
    assert "y" in ascii_y and "z" in ascii_z

    # --- helios/models/surrogate.py ---
    s_custom = surr_mod.NeuralLinacSurrogate(input_keys=["Q1", "Q2"])
    assert s_custom.input_keys == ["Q1", "Q2"]
    pred_fallback = s_custom._analytic_fallback_predict([1.0, 2.0])
    assert pred_fallback.transmission == 0.99

    with patch.dict("sys.modules", {"torch": None, "torch.nn": None, "torch.optim": None}):
        importlib.reload(surr_mod)
        assert surr_mod._HAS_TORCH is False
        with pytest.raises(OptionalDependencyError):
            surr_mod.ResidualBlock(64)
        with pytest.raises(OptionalDependencyError):
            surr_mod.LinacSurrogateNet()
        with pytest.raises(OptionalDependencyError):
            surr_mod.NeuralLinacSurrogate()
    importlib.reload(surr_mod)

