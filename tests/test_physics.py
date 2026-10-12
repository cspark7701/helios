"""Tests for beamline elements, lattice tracking, ORM, and surrogate verifier."""

import numpy as np
import pytest

from helios.physics.elements import Drift, Quadrupole, RFCavity, Steerer
from helios.physics.engine import AnalyticDigitalTwinEngine, TraceWinSimulator
from helios.physics.lattice import Lattice, create_baseline_mebt_lattice
from helios.physics.surrogate import FastPhysicsSurrogate


def test_quadrupole_transfer_matrix():
    """Verify Quadrupole focusing and defocusing properties."""
    # Positive gradient: focuses in X, defocuses in Y
    qf = Quadrupole(name="QF", length=0.2, gradient_t_m=10.0)
    R = qf.transfer_matrix_6x6(kinetic_energy_mev_u=0.5)

    # In focusing plane, R[0,0] = cos(phi) < 1
    assert R[0, 0] < 1.0
    # In defocusing plane, R[2,2] = cosh(phi) > 1
    assert R[2, 2] > 1.0


def test_baseline_mebt_tracking():
    """Verify envelope tracking through baseline MEBT lattice."""
    lattice = create_baseline_mebt_lattice()
    assert len(lattice.elements) == 10
    assert lattice.total_length > 1.0

    traj = lattice.track_envelope(initial_sigma_x_mm=1.5, initial_sigma_y_mm=1.5)
    assert len(traj) == 11
    # Check that beam stays confined within aperture
    assert all(p.sigma_x_mm > 0.0 for p in traj)
    assert all(p.sigma_y_mm > 0.0 for p in traj)
    assert traj[-1].loss_fraction < 0.1  # Minimal or zero losses on baseline


def test_orbit_response_matrix_generation():
    """Verify computation of Orbit Response Matrix (ORM)."""
    lattice = create_baseline_mebt_lattice()
    Rx, Ry = lattice.compute_orbit_response_matrix(
        steerer_names=["MEBT_CH01"],
        bpm_names=["MEBT_BPM01", "MEBT_BPM02"],
        kick_mrad=0.5,
    )
    assert Rx.shape == (2, 1)
    assert Ry.shape == (2, 1)

    # Downstream BPMs should register positive response to horizontal and vertical kicks
    assert Rx[0, 0] > 0.0
    assert Rx[1, 0] > 0.0
    assert Ry[0, 0] > 0.0
    assert Ry[1, 0] > 0.0


def test_fast_physics_surrogate_preflight():
    """Verify FastPhysicsSurrogate validation produces valid ValidationResult."""
    surrogate = FastPhysicsSurrogate(max_allowed_loss_pct=1.0, max_rms_envelope_mm=8.0)

    # Safe setpoints
    safe_setpoints = {"MEBT_QD01": -3.5, "MEBT_QF02": 3.5}
    res_safe = surrogate.validate_plan_setpoints(safe_setpoints)
    assert res_safe.is_valid
    assert len(res_safe.errors) == 0

    # Dangerously strong defocusing to cause massive loss
    extreme_setpoints = {"MEBT_QD01": 50.0, "MEBT_QF02": 50.0}
    res_bad = surrogate.validate_plan_setpoints(extreme_setpoints)
    assert not res_bad.is_valid or res_bad.projected_beam_loss > 0.0
