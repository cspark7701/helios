"""Tests for Optimization algorithms and commissioning workflows."""

import numpy as np
import pytest

from helios.interfaces.channel_map import create_baseline_mebt_channel_manager
from helios.optimization.algorithms import (
    BayesianOptimizer,
    ExtremumSeekingController,
    SVDOrbitCorrection,
)
from helios.optimization.workflows import (
    OrbitCorrectionWorkflow,
    RFPhaseScanWorkflow,
)
from helios.physics.lattice import create_baseline_mebt_lattice


def test_svd_orbit_correction_inversion():
    """Verify SVD calculation reduces simulated orbit distortion."""
    # Simple 3 BPM x 2 Steerer response matrix
    R = np.array([
        [1.2, 0.4],
        [0.8, 1.5],
        [0.5, 0.9],
    ])
    # Distorted orbit: 1.5 mm, -2.0 mm, 0.8 mm
    measured_orbit = np.array([1.5, -2.0, 0.8])

    delta_kicks, stats = SVDOrbitCorrection.calculate_correction(
        response_matrix=R,
        measured_offsets_mm=measured_orbit,
        singular_value_cutoff=1e-4,
    )

    assert len(delta_kicks) == 2
    assert stats["predicted_rms_mm"] < stats["initial_rms_mm"]


def test_extremum_seeking_controller():
    """Verify ESC controller perturbation output and stepping."""
    esc = ExtremumSeekingController(num_parameters=2, dither_amplitude=0.1)

    # Initial step
    p1 = esc.step(objective_value=50.0, dt=0.1)
    assert len(p1) == 2
    p2 = esc.step(objective_value=55.0, dt=0.1)
    assert len(p2) == 2
    # Ensure parameter vector evolves
    assert not np.allclose(p1, p2)


def test_bayesian_optimizer_bounds_and_records():
    """Verify Bayesian optimizer bounds and observation tracking."""
    bounds = {"QD01": (-20.0, 20.0), "QF02": (-20.0, 20.0)}
    opt = BayesianOptimizer(param_bounds=bounds, maximize=True)

    cand1 = opt.suggest_next_candidate()
    assert -20.0 <= cand1["QD01"] <= 20.0
    assert -20.0 <= cand1["QF02"] <= 20.0

    # Record observations
    opt.record_observation({"QD01": -10.0, "QF02": 10.0}, score=85.0)
    opt.record_observation({"QD01": -12.0, "QF02": 12.0}, score=92.0)
    opt.record_observation({"QD01": -14.0, "QF02": 14.0}, score=96.0)

    cand2 = opt.suggest_next_candidate()
    assert -20.0 <= cand2["QD01"] <= 20.0


def test_orbit_correction_workflow():
    """Verify OrbitCorrectionWorkflow creates a valid ExecutionPlan."""
    lattice = create_baseline_mebt_lattice()
    channels = create_baseline_mebt_channel_manager()

    workflow = OrbitCorrectionWorkflow(lattice, channels)
    plan, proposed_setpoints = workflow.build_orbit_correction_plan(
        plan_id="00020",
        section="MEBT",
        steerer_names=["MEBT_CH01"],
        bpm_names=["MEBT_BPM01", "MEBT_BPM02"],
        measured_bpm_x={"MEBT_BPM01": 0.8, "MEBT_BPM02": 1.2},
        measured_bpm_y={"MEBT_BPM01": -0.4, "MEBT_BPM02": -0.6},
    )

    assert plan.plan_id == "00020"
    assert len(plan.steps) == 1
    assert "MEBT_CH01" in plan.steps[0].name
    assert len(proposed_setpoints) > 0


def test_rf_phase_scan_workflow():
    """Verify phase grid generation and fitting."""
    grid = RFPhaseScanWorkflow.generate_phase_grid(-90.0, 90.0, 30.0)
    assert len(grid) == 7
    assert grid[0] == -90.0
    assert grid[-1] == 90.0

    readings = {-60.0: 4.5, -30.0: 4.8, 0.0: 5.2, 30.0: 5.0, 60.0: 4.6}
    best_phase, max_e = RFPhaseScanWorkflow.fit_synchronous_phase(readings)
    assert best_phase == 0.0
    assert max_e == 5.2
