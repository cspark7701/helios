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

    # R-06 regression: verifier rejects results that fell back when high-fidelity backend requested
    res_fallback_rejected = surrogate.validate_plan_setpoints(safe_setpoints, required_backend="TRACK")
    assert not res_fallback_rejected.is_valid
    assert any("fell back from TRACK" in err for err in res_fallback_rejected.errors)


def test_track_simulator_deck_generation(tmp_path):
    """Verify TrackSimulator deck generation (track.dat and sclinac.dat)."""
    from helios.physics.engine import TrackSimulator

    sim = TrackSimulator(work_dir=tmp_path)
    lat = create_baseline_mebt_lattice()

    track_dat = tmp_path / "track.dat"
    sclinac_dat = tmp_path / "sclinac.dat"

    sim.generate_track_dat(lat, track_dat)
    sim.generate_sclinac_dat(lat, sclinac_dat)

    assert track_dat.exists()
    assert sclinac_dat.exists()

    track_content = track_dat.read_text(encoding="utf-8")
    assert "&tran" in track_content
    assert "Win" in track_content

    sclinac_content = sclinac_dat.read_text(encoding="utf-8")
    assert "QUAD" in sclinac_content
    assert "DRIFT" in sclinac_content
    assert "END" in sclinac_content


def test_track_and_impact_simulation_run():
    """Verify TrackSimulator and ImpactZSimulator run and return TrajectoryPoints."""
    from helios.physics.engine import ImpactZSimulator, TrackSimulator

    lat = create_baseline_mebt_lattice()

    track_sim = TrackSimulator()
    traj_track = track_sim.run_simulation(lat)
    assert len(traj_track) > 0
    assert traj_track[-1].s_m > 0.0

    impact_sim = ImpactZSimulator()
    traj_impact = impact_sim.run_simulation(lat)
    assert len(traj_impact) > 0
    assert traj_impact[-1].s_m > 0.0


def test_track_run_from_directory_and_lebt_orbit_tuning(tmp_path):
    """Verify TrackSimulator running from directory decks and LEBT orbit tuning with SVD."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from helios.physics.engine import TrackSimulator
    from examples.tune_orbit_lebt import extract_diagnostic_orbit, STEERERS
    from helios.optimization.algorithms import SVDOrbitCorrection
    import numpy as np

    model_dir = Path("examples/lebt")
    if not model_dir.exists():
        return

    sim = TrackSimulator(work_dir=tmp_path)
    if not sim.is_available():
        return

    # Run baseline
    traj_base = sim.run_from_directory(model_dir, steerer_kicks={"STM_1": (0.0, 0.0)})
    assert len(traj_base) > 0
    assert traj_base[-1].s_m > 12.0

    x0, y0, sx0, sy0 = extract_diagnostic_orbit(traj_base)
    assert len(x0) == 6
    assert np.all(np.isfinite(x0))
    assert len(sx0) == 6

    # Single steerer perturbation test
    traj_kicked = sim.run_from_directory(model_dir, steerer_kicks={"STM_1": (1.0, 0.0)})
    xk, _, _, _ = extract_diagnostic_orbit(traj_kicked)
    assert not np.allclose(x0, xk)


def test_steerer_current_conversion_and_quantization():
    """Verify Steerer kick <-> current conversion calibration and 0.05A DAC quantization."""
    from helios.physics.elements import Steerer

    conversion_factor = 0.168  # A / mrad
    increment = 0.05  # A

    # 1. Test 1 mrad kick -> raw 0.168 A -> quantized to nearest 0.05 A (0.15 A)
    current_1 = Steerer.kick_to_current(1.0, conversion_factor, increment)
    assert current_1 == 0.15
    kick_1_eff = Steerer.current_to_kick(current_1, conversion_factor)
    assert round(kick_1_eff, 4) == round(0.15 / 0.168, 4)

    # 2. Test 2 mrad kick -> raw 0.336 A -> quantized to 0.35 A
    current_2 = Steerer.kick_to_current(2.0, conversion_factor, increment)
    assert current_2 == 0.35

    # 3. Test steerer model setting currents directly
    st = Steerer(
        name="LEBT:STR01",
        length=0.1,
        conversion_factor_a_per_mrad=conversion_factor,
        current_increment_a=increment,
    )
    st.set_currents(0.19, -0.34)
    assert st.current_x_a == 0.20  # quantized from 0.19 to 0.20
    assert st.current_y_a == -0.35  # quantized from -0.34 to -0.35
    assert st.kick_x_mrad == 0.20 / 0.168
    assert st.kick_y_mrad == -0.35 / 0.168


