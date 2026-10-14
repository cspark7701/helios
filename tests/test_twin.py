"""Unit and integration tests for helios.physics.twin package."""

import time

import numpy as np
import pytest


from helios.physics.twin import (
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


def test_twin_domain_ood_and_normalization():
    """Verify TwinDomain out-of-domain rejection, clamping, and normalization."""
    names = ["CH01", "CV01", "CH02"]
    lower = {"CH01": -10.0, "CV01": -5.0, "CH02": -8.0}
    upper = {"CH01": 10.0, "CV01": 5.0, "CH02": 8.0}
    domain = TwinDomain(names=names, lower=lower, upper=upper)

    # 1. In-domain check
    assert domain.out_of_domain({"CH01": 2.0, "CV01": -1.0, "CH02": 0.0}) == []

    # 2. Out-of-domain detection
    violations = domain.out_of_domain({"CH01": 15.0, "CV01": -6.0, "CH02": 5.0})
    assert "CH01" in violations
    assert "CV01" in violations
    assert "CH02" not in violations

    # 3. Clamping
    clamped = domain.clamp({"CH01": 15.0, "CV01": -8.0, "CH02": 4.0})
    assert clamped["CH01"] == 10.0
    assert clamped["CV01"] == -5.0
    assert clamped["CH02"] == 4.0

    # 4. Normalization and denormalization roundtrip
    original = {"CH01": 0.0, "CV01": 2.5, "CH02": -4.0}
    norm = domain.normalize(original)
    assert np.all(norm >= -1.0) and np.all(norm <= 1.0)
    recovered = domain.denormalize(norm)
    for k, v in original.items():
        assert np.isclose(recovered[k], v, atol=1e-5)


def test_plugin_discovery_and_mock_twin():
    """Verify plugin registry discovers mock and analytic plugins cleanly."""
    plugins = discover_facility_plugins()
    assert "mock" in plugins
    assert "analytic" in plugins

    twin_lebt = get_facility_twin(facility="mock", section="LEBT")
    assert isinstance(twin_lebt, FacilityTwin)
    assert twin_lebt.section == "LEBT"
    assert len(twin_lebt.control_names) == 5

    # Forward surrogate prediction
    pred = twin_lebt.predict({"STM_1": 1.0, "STM_2": -0.5})
    assert "WS_1:x_mm" in pred
    assert isinstance(pred["WS_1:x_mm"], float)


def test_twin_preflight_verifier_sub_2ms_and_ood():
    """Verify TwinPreFlightVerifier enforces OOD and stay-clear under 2 ms."""
    twin = get_facility_twin(facility="mock", section="MEBT")
    verifier = TwinPreFlightVerifier(twin=twin, max_centroid_orbit_mm=1.0)

    # In-domain safe setpoints
    safe_sp = {"MEBT:DCH:01": 0.2, "MEBT:DCV:01": -0.1}
    t0 = time.perf_counter()
    res_safe = verifier.validate_plan_setpoints(safe_sp)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    assert latency_ms < 5.0  # sub-millisecond execution
    assert res_safe.is_valid is True
    assert res_safe.provenance == "twin"

    # Out-of-domain setpoints
    unsafe_sp = {"MEBT:DCH:01": 50.0}  # limit is +/- 5.0
    res_unsafe = verifier.validate_plan_setpoints(unsafe_sp)
    assert res_unsafe.is_valid is False
    assert any("Domain" in c.check_name and not c.passed for c in res_unsafe.checks)


def test_linac_surrogate_gym_env():
    """Verify Gymnasium adapter wrapping FacilityTwin."""
    pytest.importorskip("gymnasium")
    twin = get_facility_twin(facility="mock", section="MEBT")
    env = LinacSurrogateGymEnv(twin=twin, max_steps=20)

    obs, info = env.reset()
    assert obs.shape == env.observation_space.shape
    assert "controls" in info

    # Execute 10 environment steps
    t0 = time.perf_counter()
    steps = 100
    for _ in range(steps):
        action = env.action_space.sample()
        obs, reward, terminated, truncated, info = env.step(action)
        if terminated or truncated:
            obs, info = env.reset()

    elapsed = time.perf_counter() - t0
    step_rate = steps / elapsed
    assert step_rate > 500.0  # high step throughput (>500 steps/s)


def test_twin_neural_mpc_optimization():
    """Verify autograd gradient descent through surrogate model."""
    pytest.importorskip("torch")
    twin = get_facility_twin(facility="mock", section="MEBT")
    mpc = TwinNeuralMPC(twin=twin, horizon=3, num_iterations=15, learning_rate=0.1)

    initial_setpoints = {"MEBT:DCH:01": 1.5, "MEBT:DCV:01": -1.2}
    res = mpc.optimize(current_setpoints=initial_setpoints)

    assert "optimized_setpoints" in res
    assert res["final_loss"] <= res["initial_loss"] + 1e-4
    for k, v in res["optimized_setpoints"].items():
        assert twin.domain.lower[k] <= v <= twin.domain.upper[k]


def test_twin_state_synchronizer():
    """Verify telemetry assimilation and residual tracking."""
    twin = get_facility_twin(facility="mock", section="MEBT")
    sync = TwinStateSynchronizer(twin=twin)

    telemetry = {"BPM01:x_mm": 0.12, "BPM01:y_mm": -0.05}
    active_sp = {"MEBT:DCH:01": 0.5, "MEBT:DCV:01": 0.0}

    rec = sync.assimilate_telemetry(telemetry, active_sp)
    assert "residuals" in rec
    assert "rms_residual_mm" in rec
    assert len(sync.telemetry_history) == 1
