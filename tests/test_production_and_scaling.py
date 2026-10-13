"""Unit tests for HELIOS Production Scale Modules (Phases 24 - 28).

Validates:
1. Phase 24: ParallelSimulationEngine, UQAnalysisResult, and TensorParticleTracker.
2. Phase 25: DigitalTwinKalmanFilter, DigitalTwinDriftDetector, and GoldenBaselineArchive.
3. Phase 26: MultiObjectiveParetoOptimizer (NSGA-II).
4. Phase 27: RBACManager (token verification) and MPSHeartbeatWatchdog.
"""

from datetime import datetime
import numpy as np
import pytest
import torch

from helios.physics.parallel import ParallelSimulationEngine, TensorParticleTracker
from helios.physics.sync import DigitalTwinKalmanFilter, DigitalTwinDriftDetector, GoldenBaselineArchive
from helios.tuning.pareto import MultiObjectiveParetoOptimizer
from helios.security.rbac import RBACManager, MPSHeartbeatWatchdog, UserRole, Permission


def test_parallel_simulation_and_tensor_tracking():
    # 1. Parameter sweep
    def mock_eval(params):
        k1 = params.get("quad_gradient", 15.0)
        # Quad gradient detuning causes loss beyond 16.5
        loss = max(0.0, (abs(k1 - 15.0) - 1.0) * 10.0)
        return {
            "transmission_pct": max(0.0, 100.0 - loss),
            "max_env_x_mm": 4.5 + abs(k1 - 15.0),
            "orbit_rms_mm": 0.15,
        }

    outcomes = ParallelSimulationEngine.run_parameter_sweep(
        eval_fn=mock_eval,
        base_parameters={"quad_gradient": 15.0},
        scan_param="quad_gradient",
        scan_range=(14.0, 16.0),
        num_samples=10,
    )
    assert len(outcomes) == 10
    assert all(o.success for o in outcomes)

    # 2. Uncertainty Quantification
    uq = ParallelSimulationEngine.evaluate_uncertainty_quantification(outcomes, "quad_gradient")
    assert uq.sample_count == 10
    assert uq.mean_transmission_pct > 90.0
    assert uq.robustness_score > 0.5

    # 3. Tensor Particle Tracker (PyTorch)
    tracker = TensorParticleTracker(device="cpu")
    # 100 particles with small gaussian spread
    particles = torch.randn(100, 6) * 0.001
    # 2 drift/identity matrices
    m1 = torch.eye(6)
    m2 = torch.eye(6)
    track_res = tracker.track_particle_ensemble(particles, [m1, m2], aperture_radius_m=0.02)
    assert track_res["initial_particles"] == 100
    assert track_res["final_particles"] == 100
    assert track_res["transmission_pct"] == 100.0


def test_digital_twin_kalman_and_golden_baseline():
    # 1. Kalman Filter state estimation
    kf = DigitalTwinKalmanFilter(num_bpms=2)
    bpm_x = np.array([0.5, 0.7])
    bpm_y = np.array([-0.3, -0.4])
    est_state = kf.update(bpm_x, bpm_y)
    assert len(est_state.orbit_x_mm) == 2
    assert est_state.state_covariance_trace > 0.0

    # 2. Drift Detector
    pred_x = np.array([0.5, 0.7])
    measured_x = np.array([0.9, 1.2])  # Significant drift
    drift = DigitalTwinDriftDetector.detect_drift(pred_x, measured_x, drift_threshold_mm=0.2)
    assert drift.drift_detected is True
    assert drift.recalibration_recommended is True
    assert len(drift.affected_subsystems) > 0

    # 3. Golden Baseline Archive & Diff
    archive = GoldenBaselineArchive()
    archive.save_golden("MEBT_GOLDEN_2026", {"MEBT:PS_Q01:I_Set": 14.5, "MEBT:PS_Q02:I_Set": 12.0})
    diff = archive.diff_against_golden(
        "MEBT_GOLDEN_2026",
        {"MEBT:PS_Q01:I_Set": 15.0, "MEBT:PS_Q02:I_Set": 12.0},  # Q01 altered
    )
    assert diff["deviated_pvs_count"] == 1
    assert "MEBT:PS_Q01:I_Set" in diff["deviations"]


def test_multi_objective_pareto_nsga2():
    # Synthetic objective function: trade-off between transmission, envelope, and dpp
    def eval_physics(params):
        q1 = params["q1"]
        q2 = params["q2"]
        # Maximize transmission near (15, 12), minimize envelope
        trans = 100.0 - (q1 - 15.0)**2 - (q2 - 12.0)**2
        env = 4.0 + 0.1 * (q1 - 15.0)
        dpp = 0.001 * (q2 / 10.0)
        return float(np.clip(trans, 50.0, 100.0)), float(env), float(dpp)

    bounds = {"q1": (14.0, 16.0), "q2": (11.0, 13.0)}
    res = MultiObjectiveParetoOptimizer.optimize_nsga2(
        eval_fn=eval_physics,
        parameter_bounds=bounds,
        population_size=12,
        generations=4,
    )
    assert len(res.pareto_front) > 0
    assert res.best_transmission_solution.transmission_pct >= 95.0
    assert res.best_envelope_solution.envelope_rms_mm > 0.0


def test_rbac_security_and_mps_watchdog():
    rbac = RBACManager()

    # Physicist token
    phys_token = rbac.issue_token("cspark", UserRole.PHYSICIST)
    assert rbac.verify_permission(phys_token.token_str, Permission.READ_TELEMETRY) is True
    assert rbac.verify_permission(phys_token.token_str, Permission.EXECUTE_CAPUT) is True
    # Physicist cannot trigger panic shutdown
    assert rbac.verify_permission(phys_token.token_str, Permission.PANIC_SHUTDOWN) is False

    # Safety Officer token
    safety_token = rbac.issue_token("safety_chief", UserRole.SAFETY_OFFICER)
    assert rbac.verify_permission(safety_token.token_str, Permission.PANIC_SHUTDOWN) is True

    # MPS Heartbeat Watchdog
    watchdog = MPSHeartbeatWatchdog(timeout_seconds=0.1)
    assert watchdog.check_health() is True
    watchdog.ping()
    assert watchdog.check_health() is True
