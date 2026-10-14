"""Unit tests achieving 100% test coverage for helios/physics/twin package."""

import importlib
from unittest.mock import MagicMock, patch
import numpy as np
import pytest
import torch

from helios.core.schemas import ValidationResult
from helios.physics.twin import (
    AnalyticTwinFallbackPlugin,
    FacilityTwin,
    LinacSurrogateGymEnv,
    MockFacilityPlugin,
    TwinDomain,
    TwinNeuralMPC,
    TwinPreFlightVerifier,
    TwinStateSynchronizer,
    discover_facility_plugins,
    get_facility_twin,
)
from helios.physics.twin.protocol import FacilityPlugin
from helios.physics.twin.registry import MockSurrogate


# ==============================================================================
# 1. Twin Protocol & Domain Edge Cases
# ==============================================================================

def test_twin_protocol_and_domain_coverage():
    domain = TwinDomain(
        names=["U1", "U2"],
        lower={"U1": -5.0},  # U2 missing lower bound (-np.inf)
        upper={"U2": 5.0},   # U1 missing upper bound (+np.inf)
    )

    # out_of_domain with ndarray input
    arr_in = np.array([0.0, 1.0])
    assert domain.out_of_domain(arr_in) == []

    arr_viol = np.array([-10.0, 10.0])
    violations = domain.out_of_domain(arr_viol)
    assert violations == ["U1", "U2"]

    # out_of_domain with dict input (partial and extra keys)
    dict_viol = {"U1": -6.0, "U2": 2.0, "UNKNOWN": 99.0}
    assert domain.out_of_domain(dict_viol) == ["U1"]

    # FacilityTwin with surrogate returning ndarray
    class ArraySurrogate:
        def predict(self, controls):
            return np.array([1.23, 4.56], dtype=np.float32)

        def predict_tensor(self, x):
            return x

    twin_arr = FacilityTwin(
        facility="TEST",
        section="MEBT",
        surrogate=ArraySurrogate(),
        control_names=["U1"],
        diagnostic_names=["DIAG1", "DIAG2"],
    )
    pred_arr = twin_arr.predict({"U1": 0.0})
    assert pred_arr["DIAG1"] == pytest.approx(1.23)
    assert pred_arr["DIAG2"] == pytest.approx(4.56)

    # FacilityTwin with surrogate returning non-dict, non-array
    class NoneSurrogate:
        def predict(self, controls):
            return None

    twin_none = FacilityTwin(
        facility="TEST",
        section="MEBT",
        surrogate=NoneSurrogate(),
        control_names=["U1"],
    )
    assert twin_none.predict({}) == {}


# ==============================================================================
# 2. Registry, Plugins, and Fallbacks Coverage
# ==============================================================================

def test_twin_registry_coverage():
    # MockSurrogate predict with ndarray and predict_tensor
    surr = MockSurrogate(["C1", "C2"], ["D1", "D2"])
    res_arr = surr.predict(np.array([1.0, 2.0]))
    assert "D1" in res_arr
    assert "D2" in res_arr

    # predict_tensor with torch
    t_in = torch.ones(1, 2, dtype=torch.float32)
    t_out = surr.predict_tensor(t_in)
    assert t_out.shape == (1, 2)

    # predict_tensor ImportError fallback
    with patch.dict("sys.modules", {"torch": None}):
        assert surr.predict_tensor("dummy_obj") == "dummy_obj"

    # MockFacilityPlugin load_twin("MEBT"), to_actuator_commands, make_env
    mock_plugin = MockFacilityPlugin()
    twin_mebt = mock_plugin.load_twin("MEBT")
    assert twin_mebt.facility == "MOCK"
    assert "MEBT:DCH:01" in twin_mebt.control_names

    cmds = mock_plugin.to_actuator_commands("MEBT", {"MEBT:DCH:01": 2.5})
    assert cmds["MEBT:DCH:01:CurrentSet"] == 2.5

    env = mock_plugin.make_env("MEBT", max_steps=10)
    assert isinstance(env, LinacSurrogateGymEnv)

    # AnalyticTwinFallbackPlugin load_twin, predict, predict_tensor, to_actuator_commands, make_env
    analytic_plugin = AnalyticTwinFallbackPlugin()
    assert analytic_plugin.available_sections() == ["MEBT"]
    twin_ana = analytic_plugin.load_twin("MEBT")
    pred_ana = twin_ana.predict({"MEBT:DCH:01": 1.0})
    assert "BPM01:x_mm" in pred_ana
    assert twin_ana.surrogate.predict_tensor("tensor_input") == "tensor_input"

    cmds_ana = analytic_plugin.to_actuator_commands("MEBT", {"MEBT:DCH:01": 1.5})
    assert cmds_ana["MEBT:DCH:01:CurrentSet"] == 1.5

    env_ana = analytic_plugin.make_env("MEBT", max_steps=5)
    assert isinstance(env_ana, LinacSurrogateGymEnv)

    # discover_facility_plugins entry points handling
    mock_ep_good = MagicMock()
    mock_ep_good.name = "custom_fac"
    mock_ep_good.load.return_value = MockFacilityPlugin

    mock_ep_bad = MagicMock()
    mock_ep_bad.name = "broken_fac"
    mock_ep_bad.load.side_effect = RuntimeError("Broken plugin")

    with patch("importlib.metadata.entry_points", return_value=[mock_ep_good, mock_ep_bad]):
        plugins = discover_facility_plugins()
        assert "custom_fac" in plugins
        assert "broken_fac" not in plugins

    # discover_facility_plugins metadata entry points raises exception
    with patch("importlib.metadata.entry_points", side_effect=Exception("Metadata failure")):
        plugins_fb = discover_facility_plugins()
        assert "mock" in plugins_fb
        assert "analytic" in plugins_fb

    # get_facility_twin fallback branches
    # 1. Unknown facility with unknown section falls back to analytic MEBT
    twin_fallback = get_facility_twin("UNKNOWN_FACILITY", section="NONEXISTENT_SEC")
    assert twin_fallback.facility == "ANALYTIC"

    # 2. Known facility (mock) with unknown section falls back to mock LEBT or analytic
    twin_sec_fb = get_facility_twin("mock", section="UNKNOWN_SEC")
    assert twin_sec_fb.facility == "ANALYTIC"


# ==============================================================================
# 3. Gym Environment Edge Cases Coverage
# ==============================================================================

def test_twin_gym_env_coverage():
    twin = get_facility_twin("mock", "LEBT")
    env = LinacSurrogateGymEnv(twin=twin, max_steps=2, target_rms_mm=0.1, jitter_std=0.0)

    # Reset
    obs, info = env.reset(seed=42)
    assert len(obs) == len(twin.diagnostic_names) + len(twin.control_names)
    assert "controls" in info

    # Step 1: Normal step
    action = np.zeros(len(twin.control_names), dtype=np.float32)
    obs1, rew1, term1, trunc1, info1 = env.step(action)
    assert not trunc1

    # Step 2: Step reaching max_steps -> truncated
    obs2, rew2, term2, trunc2, info2 = env.step(action)
    assert trunc2

    # Target reached bonus branch
    env_bonus = LinacSurrogateGymEnv(twin=twin, max_steps=10, target_rms_mm=100.0)  # Very high tolerance
    env_bonus.reset()
    _, rew_bonus, term_bonus, _, _ = env_bonus.step(action)
    assert rew_bonus > 0.0  # Includes +10.0 bonus
    assert term_bonus  # rms < target * 0.5 triggers termination

    # Missing gymnasium dependency branch
    with patch("helios.physics.twin.env._HAS_GYM", False):
        with pytest.raises(Exception):
            LinacSurrogateGymEnv(twin=twin)


# ==============================================================================
# 4. Neural MPC Optimizer Coverage
# ==============================================================================

def test_twin_neural_mpc_coverage():
    twin = get_facility_twin("mock", "LEBT")
    mpc = TwinNeuralMPC(
        twin=twin,
        horizon=3,
        num_iterations=5,
        learning_rate=0.01,
        weight_tracking=1.0,
        weight_actuator_reg=0.01,
        weight_slew_rate=0.05,
    )

    # 1. Optimize with target diagnostics
    target_y = {d: 0.05 for d in twin.diagnostic_names}
    res_tgt = mpc.optimize(current_setpoints={"STM_1": 1.0}, target_diagnostics=target_y)
    assert "optimized_setpoints" in res_tgt
    assert "horizon_trajectory" in res_tgt
    assert len(res_tgt["horizon_trajectory"]) == 3
    assert res_tgt["final_loss"] >= 0.0

    # 2. Optimize without target diagnostics (default zero)
    res_zero = mpc.optimize(current_setpoints={"STM_1": -2.0})
    assert "optimized_setpoints" in res_zero

    # 3. Missing PyTorch branch
    with patch("helios.physics.twin.mpc._HAS_TORCH", False):
        with pytest.raises(Exception):
            TwinNeuralMPC(twin=twin)


# ==============================================================================
# 5. Twin State Synchronizer & Pre-Flight Verifier Coverage
# ==============================================================================

def test_twin_state_synchronizer_and_verifier():
    twin = get_facility_twin("mock", "LEBT")

    # State Synchronizer
    sync = TwinStateSynchronizer(twin)
    # Assimilate with partial telemetry
    telemetry = {twin.diagnostic_names[0]: 0.1}
    rec = sync.assimilate_telemetry(telemetry, active_setpoints={"STM_1": 0.5})
    assert rec["telemetry_count"] == 1
    assert rec["rms_residual_mm"] >= 0.0

    # Fill history buffer over 100 to trigger pop(0)
    for _ in range(105):
        sync.assimilate_telemetry(telemetry, active_setpoints={"STM_1": 0.0})
    assert len(sync.telemetry_history) == 100

    # Refine beam state Twiss update
    twiss = sync.refine_beam_state({"sigma_x_mm": 2.0, "sigma_y_mm": 1.5})
    assert twiss["beta_x_m"] > 0.0
    assert twiss["beta_y_m"] > 0.0

    # Pre-Flight Verifier
    verifier = TwinPreFlightVerifier(twin, max_centroid_orbit_mm=1.0, aperture_limit_mm=2.0)

    # In-domain safe plan
    res_safe = verifier.validate_plan_setpoints({"STM_1": 0.0})
    assert res_safe.is_valid is True

    # OOD failure branch
    res_ood = verifier.validate_plan_setpoints({"STM_1": 999.0})
    assert res_ood.is_valid is False
    assert any("outside Twin Domain" in c.message for c in res_ood.checks)

    # Orbit exceedance and aperture warning branch
    # Mock predict returning huge orbit
    with patch.object(twin, "predict", return_value={twin.diagnostic_names[0]: 5.0}):
        res_huge = verifier.validate_plan_setpoints({"STM_1": 0.0})
        assert res_huge.is_valid is False
        assert res_huge.projected_beam_loss > 0.0
        assert len(res_huge.warnings) > 0


def test_twin_init_import_fallbacks():
    import helios.physics.twin as twin_mod

    # Verify attributes exposed
    assert hasattr(twin_mod, "FacilityTwin")
    assert hasattr(twin_mod, "TwinDomain")
    assert hasattr(twin_mod, "get_facility_twin")

    # Fallback to mock when facility not found
    twin_fallback = get_facility_twin(facility="nonexistent_facility", section="LEBT")
    assert twin_fallback.facility == "MOCK"

    # Reload __init__ with exceptions to cover lines 24-25 and 29-30
    import importlib
    with patch.dict("sys.modules", {"helios.physics.twin.env": None, "helios.physics.twin.mpc": None}):
        importlib.reload(twin_mod)
        assert twin_mod.LinacSurrogateGymEnv is None
        assert twin_mod.TwinNeuralMPC is None
    # Reload again to restore
    importlib.reload(twin_mod)
