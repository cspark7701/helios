"""Unit tests achieving 100% test coverage for helios core orchestration, LLM, mesh, and agents."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import urllib.error
import pytest

from helios.agents.cotuner import GameTheoreticCoTuner, ProposedSubsystemActuation
from helios.agents.orchestrator import HeliosOrchestrator
from helios.agents.planner import NaturalLanguagePlanner
from helios.core.capabilities import Capability, CapabilityDomain, CapabilityRegistry, get_default_registry
from helios.core.facility_config import FacilityConfig
from helios.core.llm import (
    BaseLLMClient,
    LLMMessage,
    LLMResponse,
    MockLLMClient,
    OpenAICompatibleLLMClient,
    ToolCall,
    create_llm_client,
)
from helios.core.mesh import (
    AgentMeshMessage,
    AgentMeshNode,
    DistributedAgentMesh,
    MeshNodeType,
    NodeStatus,
)
from helios.core.plan_engine import (
    PlanArtifactStore,
    PlanLifecycleManager,
    PlanStore,
    PlanTransitionError,
)
from helios.core.schemas import (
    AutonomyLevel,
    ExecutionPlan,
    PlanState,
    PlanStep,
    StepStatus,
    ValidationCheck,
    ValidationResult,
)
from helios.interfaces.channel_map import ChannelLimits, DeviceType, LinacDevice
from helios.interfaces.base import ControlInterfaceError, MissingReadbackError
from helios.interfaces.epics import MockControlInterface


# ==============================================================================
# 1. Core LLM Client Coverage
# ==============================================================================

def test_llm_client_coverage():
    # MockLLMClient loss/trip/anomaly intent rule
    mock_client = MockLLMClient()
    loss_msg = [LLMMessage(role="user", content="Beam loss detected on BLM01 with MPS trip")]
    resp_loss = mock_client.generate(loss_msg)
    assert len(resp_loss.tool_calls) == 1
    assert resp_loss.tool_calls[0].name == "diagnose_linac_anomalies"

    # OpenAICompatibleLLMClient initialization and generate
    openai_client = OpenAICompatibleLLMClient(
        base_url="https://mock.llm.local/v1/",
        api_key="secret-key",
        model="mock-gpt",
        timeout_seconds=5.0,
    )
    assert openai_client.base_url == "https://mock.llm.local/v1"
    assert openai_client.api_key == "secret-key"

    # Successful HTTP response with tool calls
    mock_payload = {
        "model": "mock-gpt",
        "choices": [
            {
                "message": {
                    "content": "Running diagnostic plan.",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "measure_bpm_orbit",
                                "arguments": json.dumps({"section": "MEBT"}),
                            },
                        }
                    ],
                }
            }
        ],
        "usage": {"total_tokens": 42},
    }

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = openai_client.generate(
            [LLMMessage(role="user", content="Check MEBT orbit")],
            tools=[{"type": "function", "function": {"name": "measure_bpm_orbit"}}],
        )
        assert res.content == "Running diagnostic plan."
        assert len(res.tool_calls) == 1
        assert res.tool_calls[0].name == "measure_bpm_orbit"
        assert res.tool_calls[0].arguments == {"section": "MEBT"}
        assert res.usage == {"total_tokens": 42}

    # Exception handling in OpenAI client
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        with pytest.raises(Exception):
            openai_client.generate([LLMMessage(role="user", content="Hello")])

    # create_llm_client factory branches
    c_openai = create_llm_client("openai")
    assert isinstance(c_openai, OpenAICompatibleLLMClient)
    c_ollama = create_llm_client("ollama")
    assert isinstance(c_ollama, OpenAICompatibleLLMClient)
    c_unknown = create_llm_client("some-weird-provider")
    assert isinstance(c_unknown, MockLLMClient)


# ==============================================================================
# 2. Plan Lifecycle Manager & Artifact Store Coverage
# ==============================================================================

def test_plan_lifecycle_manager_coverage(tmp_path):
    # Physics validation failure branch
    plan_fail_phys = ExecutionPlan(
        plan_id="00021",
        title="Physics Fail Plan",
        objective="Test physics reject",
        autonomy_level=AutonomyLevel.ASSISTED,
        steps=[],
    )
    mgr_phys = PlanLifecycleManager(plan_fail_phys)
    mgr_phys.attach_physics_validation(ValidationResult(is_valid=False, validator_agent="HELIOS-Physics"))
    assert plan_fail_phys.state == PlanState.FAILED

    # Transition error attaching physics validation when not in DRAFT
    with pytest.raises(PlanTransitionError):
        mgr_phys.attach_physics_validation(ValidationResult(is_valid=True, validator_agent="HELIOS-Physics"))

    # Safety validation failure branch
    plan_fail_safe = ExecutionPlan(
        plan_id="00022",
        title="Safety Fail Plan",
        objective="Test safety reject",
        autonomy_level=AutonomyLevel.ASSISTED,
        steps=[],
    )
    mgr_safe = PlanLifecycleManager(plan_fail_safe)
    mgr_safe.attach_physics_validation(ValidationResult(is_valid=True, validator_agent="HELIOS-Physics"))
    assert plan_fail_safe.state == PlanState.SIMULATION_VERIFIED

    # Transition error attaching safety validation when not in SIMULATION_VERIFIED
    plan_draft = ExecutionPlan(
        plan_id="00023",
        title="Draft Safety Plan",
        objective="Test draft safety",
        autonomy_level=AutonomyLevel.ASSISTED,
        steps=[],
    )
    mgr_draft = PlanLifecycleManager(plan_draft)
    with pytest.raises(PlanTransitionError):
        mgr_draft.attach_safety_validation(ValidationResult(is_valid=True, validator_agent="HELIOS-Safety"))

    # Safety validation is_valid=False
    mgr_safe.attach_safety_validation(ValidationResult(is_valid=False, validator_agent="HELIOS-Safety"))
    assert plan_fail_safe.state == PlanState.FAILED

    # Authorize execution when not in SAFETY_APPROVED
    with pytest.raises(PlanTransitionError):
        mgr_safe.authorize_execution(operator_approval=True)

    # Authorize execution without operator approval for ASSISTED
    plan_app = ExecutionPlan(
        plan_id="00024",
        title="Approval Plan",
        objective="Test approval",
        autonomy_level=AutonomyLevel.ASSISTED,
        steps=[PlanStep(step_id="s1", name="step1", target_agent="Tuner", action="act")],
    )
    mgr_app = PlanLifecycleManager(plan_app)
    mgr_app.attach_physics_validation(ValidationResult(is_valid=True, validator_agent="HELIOS-Physics"))
    mgr_app.attach_safety_validation(ValidationResult(is_valid=True, validator_agent="HELIOS-Safety"))
    with pytest.raises(PermissionError):
        mgr_app.authorize_execution(operator_approval=False)

    # Complete plan when not in EXECUTING
    with pytest.raises(PlanTransitionError):
        mgr_app.complete_plan()

    # Authorize and test step completion failure when steps are still PENDING
    mgr_app.authorize_execution(operator_approval=True)
    assert plan_app.state == PlanState.EXECUTING
    with pytest.raises(ValueError):
        mgr_app.complete_plan()

    # Mark rolled back from EXECUTING
    mgr_app.mark_rolled_back()
    assert plan_app.state == PlanState.ROLLED_BACK

    # Illegal state transition from ROLLED_BACK
    with pytest.raises(PlanTransitionError):
        mgr_app._transition_to(PlanState.EXECUTING)


def test_plan_artifact_store_and_store_coverage(tmp_path):
    store = PlanArtifactStore(tmp_path)

    # Markdown rendering with errors, warnings, and rollback targets
    val_rec = ValidationResult(
        is_valid=False,
        validator_agent="HELIOS-Physics",
        checks=[ValidationCheck(check_name="Loss Check", passed=False, message="Loss exceeds 1%")],
        errors=["High beam loss in MEBT"],
        warnings=["Aperture clearance low"],
    )
    plan = ExecutionPlan(
        plan_id="00030",
        title="Render Test Plan",
        objective="Verify render formatting",
        autonomy_level=AutonomyLevel.BOUNDED_AUTONOMOUS,
        steps=[PlanStep(step_id="step_1", name="S1", target_agent="Tuner", action="tune", status=StepStatus.SUCCESS)],
        validation_records=[val_rec],
        rollback_targets={"MEBT:PSC:CH01:CurrentSet": 2.5},
    )

    md = store.render_markdown(plan)
    assert "- **Errors**: High beam loss in MEBT" in md
    assert "- **Warnings**: Aperture clearance low" in md
    assert "MEBT:PSC:CH01:CurrentSet" in md

    # Save active and archive completed
    active_path = store.save_active(plan)
    assert active_path.exists()

    completed_path = store.archive_completed(plan)
    assert completed_path.exists()
    assert not active_path.exists()

    # Load non-existent file
    assert store.load_plan_from_file(tmp_path / "nonexistent.md") is None

    # Load markdown file without JSON block (fallback to header parsing)
    fallback_file = tmp_path / "00031_custom_header_plan.md"
    fallback_file.write_text("# Plan without json code block\nJust markdown text.", encoding="utf-8")
    loaded_fb = store.load_plan_from_file(fallback_file)
    assert loaded_fb is not None
    assert loaded_fb.plan_id == "00031"
    assert loaded_fb.title == "Custom Header Plan"

    # Load plan search
    assert store.load_plan("00030") is not None
    assert store.load_plan("99999") is None

    # PlanStore coverage
    p_store = PlanStore(base_dir=tmp_path, persist_artifacts=True)
    p_store.register_plan(plan)
    assert p_store.get_manager("00030") is not None

    # get_plan loading from artifact store
    p_store_clean = PlanStore(base_dir=tmp_path, persist_artifacts=False)
    p_from_disk = p_store_clean.get_plan("00030")
    assert p_from_disk is not None

    # list_plans loading disk plans
    all_plans = p_store_clean.list_plans()
    assert len(all_plans) >= 1

    # approve_plan unknown id
    with pytest.raises(KeyError):
        p_store_clean.approve_plan("unknown_id")

    # reject_plan unknown id
    with pytest.raises(KeyError):
        p_store_clean.reject_plan("unknown_id")

    # approve_plan auto-transitions DRAFT -> SIMULATION_VERIFIED -> SAFETY_APPROVED -> EXECUTING
    draft_p = ExecutionPlan(
        plan_id="00032",
        title="Draft Auto Approve",
        objective="Auto approve draft",
        autonomy_level=AutonomyLevel.SUPERVISED,
        steps=[],
    )
    p_store.register_plan(draft_p)
    app_res = p_store.approve_plan("00032", operator_approval=True)
    assert app_res.state == PlanState.EXECUTING

    # reject_plan on active plan and already failed plan
    rej_res = p_store.reject_plan("00032", reason="Safety concern")
    assert rej_res.state == PlanState.FAILED
    rej_again = p_store.reject_plan("00032", reason="Redundant reject")
    assert rej_again.state == PlanState.FAILED


# ==============================================================================
# 3. Distributed Agent Mesh Coverage
# ==============================================================================

def test_distributed_agent_mesh_coverage():
    mesh = DistributedAgentMesh(heartbeat_timeout_s=0.1)

    node_edge = AgentMeshNode(
        node_id="edge_1",
        node_type=MeshNodeType.EDGE_IOC,
        address="192.168.1.50",
        capabilities=["epics_ca", "fast_feedback"],
    )
    node_orch1 = AgentMeshNode(
        node_id="orch_1",
        node_type=MeshNodeType.ORCHESTRATOR,
        address="192.168.1.10",
        priority_rank=10,
    )
    node_orch2 = AgentMeshNode(
        node_id="orch_2",
        node_type=MeshNodeType.ORCHESTRATOR,
        address="192.168.1.11",
        priority_rank=20,  # Higher rank
    )

    mesh.register_node(node_edge)
    assert mesh.active_orchestrator_id is None

    mesh.register_node(node_orch1)
    assert mesh.active_orchestrator_id == "orch_1"

    mesh.register_node(node_orch2)
    assert mesh.active_orchestrator_id == "orch_2"

    # Heartbeat
    assert mesh.heartbeat("edge_1") is True
    assert mesh.heartbeat("non_existent_node") is False

    # Publish and Subscribe
    received_msgs = []
    mesh.subscribe("orbit_updates", lambda msg: received_msgs.append(msg))

    msg = AgentMeshMessage(
        sender_id="edge_1",
        target_id="*",
        topic="orbit_updates",
        payload={"rms_x": 0.12},
    )
    delivered = mesh.publish(msg)
    assert delivered == 1
    assert len(received_msgs) == 1

    # Edge offline buffer and sync reconnection
    offline_msg = AgentMeshMessage(
        sender_id="edge_1",
        target_id="orch_2",
        topic="orbit_updates",
        payload={"buffered": True},
    )
    mesh.buffer_edge_offline_action("edge_1", offline_msg)
    assert len(mesh.edge_offline_buffers["edge_1"]) == 1

    synced_count = mesh.sync_reconnection("edge_1")
    assert synced_count == 1
    assert len(mesh.edge_offline_buffers.get("edge_1", [])) == 0
    assert len(received_msgs) == 2

    # Liveness check and failover election
    import time
    time.sleep(0.15)
    # Both orchestrators have timed out
    elected = mesh.check_liveness_and_elect_orchestrator()
    assert elected is None

    # Revive orch_1
    mesh.heartbeat("orch_1")
    elected_revived = mesh.check_liveness_and_elect_orchestrator()
    assert elected_revived == "orch_1"


# ==============================================================================
# 4. Game-Theoretic Co-Tuner Coverage
# ==============================================================================

def test_game_theoretic_cotuner_coverage():
    # 1. No conflicts
    p1 = ProposedSubsystemActuation(
        agent_id="OpticsAgent",
        subsystem="MEBT",
        proposed_setpoints={"MEBT:PSC:CH01:CurrentSet": 1.5},
        priority=5,
        expected_gain_pct=10.0,
        rationale="Center horizontal orbit",
    )
    p2 = ProposedSubsystemActuation(
        agent_id="RFAgent",
        subsystem="MEBT",
        proposed_setpoints={"MEBT:RF:CAV01:PhaseSet": -25.0},
        priority=6,
        expected_gain_pct=8.0,
        rationale="Synchronous phase alignment",
    )
    res_no_conflict = GameTheoreticCoTuner.arbitrate_conflicts([p1, p2])
    assert res_no_conflict.conflicts_detected == 0
    assert res_no_conflict.approved_setpoints["MEBT:PSC:CH01:CurrentSet"] == 1.5
    assert res_no_conflict.approved_setpoints["MEBT:RF:CAV01:PhaseSet"] == -25.0

    # 2. Strict priority override (priority diff > 2)
    p_safety = ProposedSubsystemActuation(
        agent_id="SafetyAgent",
        subsystem="MEBT",
        proposed_setpoints={"MEBT:PSC:QD01:CurrentSet": 5.0},
        priority=10,
        expected_gain_pct=50.0,
        rationale="Prevent beam chamber overheating",
    )
    p_optics = ProposedSubsystemActuation(
        agent_id="OpticsAgent",
        subsystem="MEBT",
        proposed_setpoints={"MEBT:PSC:QD01:CurrentSet": 12.0},
        priority=5,  # 10 > 5 + 2 -> strict override
        expected_gain_pct=15.0,
        rationale="Envelope matching",
    )
    res_override = GameTheoreticCoTuner.arbitrate_conflicts([p_safety, p_optics])
    assert res_override.conflicts_detected == 1
    assert res_override.approved_setpoints["MEBT:PSC:QD01:CurrentSet"] == 5.0
    assert len(res_override.rejected_proposals) == 1

    # 3. Cooperative Nash compromise (priority diff <= 2)
    p_opt1 = ProposedSubsystemActuation(
        agent_id="Tuner1",
        subsystem="MEBT",
        proposed_setpoints={"MEBT:PSC:QF02:CurrentSet": 10.0},
        priority=6,
        expected_gain_pct=10.0,  # weight = 60
        rationale="Focusing tune 1",
    )
    p_opt2 = ProposedSubsystemActuation(
        agent_id="Tuner2",
        subsystem="MEBT",
        proposed_setpoints={"MEBT:PSC:QF02:CurrentSet": 20.0},
        priority=6,
        expected_gain_pct=10.0,  # weight = 60
        rationale="Focusing tune 2",
    )
    res_compromise = GameTheoreticCoTuner.arbitrate_conflicts([p_opt1, p_opt2])
    assert res_compromise.conflicts_detected == 1
    assert res_compromise.approved_setpoints["MEBT:PSC:QF02:CurrentSet"] == pytest.approx(15.0)
    assert len(res_compromise.compromises_made) == 1


# ==============================================================================
# 5. Master Orchestrator Coverage
# ==============================================================================

def test_master_orchestrator_coverage(tmp_path):
    mock_ctrl = MockControlInterface()
    orch = HeliosOrchestrator(control_interface=mock_ctrl, base_dir=tmp_path)

    # 1. Missing BPM readback raises MissingReadbackError
    with patch.object(mock_ctrl, "get", return_value=None):
        with pytest.raises(MissingReadbackError):
            orch.read_bpm_telemetry("MEBT", ["MEBT_BPM01"])

    # 2. validate_plan_safety_and_physics failures
    plan = ExecutionPlan(
        plan_id="00040",
        title="Orch Test Plan",
        objective="Test orch",
        autonomy_level=AutonomyLevel.ASSISTED,
        steps=[],
    )
    mgr = PlanLifecycleManager(plan)

    # Physics invalid
    with patch.object(orch.physics_surrogate, "validate_plan_setpoints", return_value=ValidationResult(is_valid=False, validator_agent="HELIOS-Physics")):
        assert orch.validate_plan_safety_and_physics(plan, mgr, {"MEBT:PSC:CH01:CurrentSet": 1.0}) is False

    # Safety invalid
    plan_safe = ExecutionPlan(
        plan_id="00041",
        title="Safe Plan",
        objective="Test safe",
        autonomy_level=AutonomyLevel.ASSISTED,
        steps=[],
    )
    mgr_safe = PlanLifecycleManager(plan_safe)
    with patch.object(orch.physics_surrogate, "validate_plan_setpoints", return_value=ValidationResult(is_valid=True, validator_agent="HELIOS-Physics")):
        with patch.object(orch.safety_gatekeeper, "validate_setpoints", return_value=ValidationResult(is_valid=False, validator_agent="HELIOS-Safety")):
            assert orch.validate_plan_safety_and_physics(plan_safe, mgr_safe, {"MEBT:PSC:CH01:CurrentSet": 1.0}) is False

    # Missing readback on setpoint PV
    plan_sp = ExecutionPlan(
        plan_id="00042",
        title="SP Plan",
        objective="Test sp",
        autonomy_level=AutonomyLevel.ASSISTED,
        steps=[],
    )
    mgr_sp = PlanLifecycleManager(plan_sp)
    with patch.object(orch.physics_surrogate, "validate_plan_setpoints", return_value=ValidationResult(is_valid=True, validator_agent="HELIOS-Physics")):
        with patch.object(orch.safety_gatekeeper, "validate_setpoints", return_value=ValidationResult(is_valid=True, validator_agent="HELIOS-Safety")):
            with patch.object(mock_ctrl, "get", return_value=None):
                with pytest.raises(MissingReadbackError):
                    orch.validate_plan_safety_and_physics(plan_sp, mgr_sp, {"MEBT:PSC:CH01:CurrentSet": 1.0})

    # 3. authorize_and_actuate withheld
    plan_auth = ExecutionPlan(
        plan_id="00043",
        title="Auth Plan",
        objective="Test auth",
        autonomy_level=AutonomyLevel.ADVISORY,  # ADVISORY cannot actuate hardware
        steps=[],
    )
    mgr_auth = PlanLifecycleManager(plan_auth)
    auth_ok = orch.authorize_and_actuate(
        plan_auth, mgr_auth, "MEBT", ["MEBT_BPM01"], {"MEBT:PSC:CH01:CurrentSet": 1.0}, operator_confirmed=True
    )
    assert not auth_ok

    # 4. authorize_and_actuate failure during execute triggers rollback
    plan_exec_fail = ExecutionPlan(
        plan_id="00044",
        title="Exec Fail Plan",
        objective="Test rollback",
        autonomy_level=AutonomyLevel.ASSISTED,
        state=PlanState.SAFETY_APPROVED,
        steps=[PlanStep(step_id="s1", name="step1", target_agent="Tuner", action="act")],
    )
    mgr_exec_fail = PlanLifecycleManager(plan_exec_fail)
    with patch.object(orch.safety_gatekeeper, "execute", side_effect=ControlInterfaceError("EPICS timeout")):
        with patch.object(orch.rollback_controller, "trigger_rollback") as mock_rb:
            act_res = orch.authorize_and_actuate(
                plan_exec_fail,
                mgr_exec_fail,
                "MEBT",
                ["MEBT_BPM01"],
                {"MEBT:PSC:CH01:CurrentSet": 1.0},
                operator_confirmed=True,
            )
            assert not act_res
            mock_rb.assert_called_once()
            assert plan_exec_fail.state == PlanState.ROLLED_BACK

    # 5. _verify_post_actuation_telemetry missing readback
    with patch.object(mock_ctrl, "get", return_value=None):
        with pytest.raises(MissingReadbackError):
            orch._verify_post_actuation_telemetry(plan, "MEBT", ["MEBT_BPM01"])

    # 6. run_orbit_correction_loop validation failure branch
    mock_ctrl.put("MEBT:DIAG:BPM01:X_POS", 0.1)
    mock_ctrl.put("MEBT:DIAG:BPM01:Y_POS", -0.1)
    mock_ctrl.put("MEBT:DIAG:BPM02:X_POS", 0.05)
    mock_ctrl.put("MEBT:DIAG:BPM02:Y_POS", -0.05)
    mock_ctrl.put("MEBT:PSC:CH01:CurrentSet", 0.0)
    mock_ctrl.put("MEBT:PSC:CV01:CurrentSet", 0.0)
    with patch.object(orch, "validate_plan_safety_and_physics", return_value=False):
        loop_res = orch.run_orbit_correction_loop("00045")
        assert loop_res.plan_id == "00045"


# ==============================================================================
# 6. Facility Config, Capabilities & Planner Agent Coverage
# ==============================================================================

def test_facility_config_capabilities_and_planner_coverage(tmp_path):
    # FacilityConfig.from_yaml FileNotFoundError
    with pytest.raises(FileNotFoundError):
        FacilityConfig.from_yaml(tmp_path / "nonexistent_config.yaml")

    # FacilityConfig.from_yaml with already-instantiated LinacDevice
    dev_obj = LinacDevice(
        name="MEBT_QD01",
        device_id="QD01",
        device_type=DeviceType.QUADRUPOLE,
        section="MEBT",
        setpoint_pv="MEBT:PSC:QD01:CurrentSet",
        readback_pv="MEBT:PSC:QD01:CurrentRB",
        limits=ChannelLimits(min_val=-150.0, max_val=150.0),
    )
    cfg_data = {
        "name": "TEST_FACILITY",
        "section": "MEBT",
        "devices": [dev_obj],
    }
    cfg_yaml = tmp_path / "facility_dev_test.yaml"
    import yaml
    with open(cfg_yaml, "w", encoding="utf-8") as f:
        yaml.safe_dump({"name": "TEST_FACILITY", "section": "MEBT", "devices": [dev_obj.model_dump(mode="json")]}, f)
    loaded_cfg = FacilityConfig.from_yaml(cfg_yaml)
    assert len(loaded_cfg.devices) == 1

    # Also test line 48: when device is already a LinacDevice instance in data
    with patch("yaml.safe_load", return_value={"name": "TEST", "devices": [dev_obj]}):
        cfg_inst = FacilityConfig.from_yaml(cfg_yaml)
        assert len(cfg_inst.devices) == 1

    # FacilityConfig.load_default non-MEBT fallback
    scl_cfg = FacilityConfig.load_default("SCL")
    assert scl_cfg.section == "SCL"

    # CapabilityRegistry get, list_all, filter_by_agent
    reg = CapabilityRegistry()
    assert reg.get("non_existent") is None
    cap = Capability(
        name="test_tune",
        description="Test capability",
        target_agent="HELIOS-Tuner",
        domain=CapabilityDomain.OPTICS,
    )
    reg.register(cap)
    assert reg.get("test_tune") == cap
    assert len(reg.list_all()) == 1
    assert len(reg.filter_by_agent("HELIOS-Tuner")) == 1
    assert len(reg.filter_by_agent("HELIOS-Safety")) == 0

    # NaturalLanguagePlanner without tool calls -> fallback observation plan
    planner = NaturalLanguagePlanner()
    with patch.object(planner.llm, "generate", return_value=LLMResponse(content="Just watching", tool_calls=[])):
        plan_obs, msg_obs = planner.formulate_plan_from_prompt("Observe beam status", plan_id="00050")
        assert plan_obs.title == "Telemetry Inspection"
        assert len(plan_obs.steps) == 1

    # NaturalLanguagePlanner with unknown tool name -> default diagnostic check plan
    with patch.object(
        planner.llm,
        "generate",
        return_value=LLMResponse(
            content="Unknown action",
            tool_calls=[ToolCall(name="unknown_arbitrary_tool", arguments={"foo": "bar"})],
        ),
    ):
        plan_unknown, msg_un = planner.formulate_plan_from_prompt("Do arbitrary action", plan_id="00051")
        assert plan_unknown.title == "Diagnostic Health Verification"
        assert len(plan_unknown.steps) == 1
