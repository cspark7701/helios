"""Unit tests targeting 100% test coverage for helios/physics/engine.py."""

from pathlib import Path
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from helios.physics.elements import DiagnosticElement, Drift, Quadrupole, RFCavity, Steerer
from helios.physics.engine import (
    AnalyticDigitalTwinEngine,
    ImpactZSimulator,
    TrackSimulator,
    TrajectoryPoint,
)
from helios.physics.lattice import Lattice


@pytest.fixture
def test_lattice():
    lat = Lattice(name="CoverageTestLattice")
    lat.add_element(Drift(name="DR_01", length_m=0.5))
    lat.add_element(Steerer(name="ST_CH_01", length_m=0.1, kick_x_mrad=0.0, kick_y_mrad=0.0))
    lat.add_element(Steerer(name="ST_CV_01", length_m=0.1, kick_x_mrad=0.0, kick_y_mrad=0.0))
    lat.add_element(RFCavity(name="CAV_01", length_m=0.4, voltage_kv=100.0, phase_deg=-20.0, frequency_mhz=162.5))
    lat.add_element(RFCavity(name="CAV_phase_01", length_m=0.4, voltage_kv=100.0, phase_deg=-20.0, frequency_mhz=162.5))
    lat.add_element(Quadrupole(name="QP_01", length_m=0.2, gradient_t_m=12.0))
    lat.add_element(DiagnosticElement(name="DIAG_BPM_01", length_m=0.05, diag_type="BPM"))
    return lat


def test_analytic_engine_apply_setpoints_and_losses(test_lattice):
    engine = AnalyticDigitalTwinEngine(baseline_lattice=test_lattice)

    setpoints = {
        "ST_CH_01": 1.25,
        "ST_CV_01": -0.85,
        "CAV_phase_01": -15.0,
        "CAV_01": 120.0,
        "QP_01": 14.5,
        "NONEXISTENT": 99.0,
    }
    engine.apply_setpoints(setpoints)

    assert test_lattice.get_element("ST_CH_01").kick_x_mrad == 1.25
    assert test_lattice.get_element("ST_CV_01").kick_y_mrad == -0.85
    assert test_lattice.get_element("CAV_phase_01").phase_deg == -15.0
    assert test_lattice.get_element("CAV_01").voltage_kv == 120.0
    assert test_lattice.get_element("QP_01").gradient_t_m == 14.5

    # Test run_simulation with setpoints
    traj = engine.run_simulation(test_lattice, setpoints={"QP_01": 13.0})
    assert len(traj) > 0
    assert test_lattice.get_element("QP_01").gradient_t_m == 13.0

    # Test losses
    losses = engine.estimate_losses(test_lattice)
    assert losses >= 0.0

    # Test empty trajectory loss
    with patch.object(engine, "run_simulation", return_value=[]):
        assert engine.estimate_losses(test_lattice) == 0.0


def test_track_simulator_is_available(tmp_path, monkeypatch):
    non_existent = tmp_path / "does_not_exist.exe"
    sim = TrackSimulator(track_exe=non_existent)
    assert not sim.is_available()

    exe_file = tmp_path / "mock_track.exe"
    exe_file.touch()
    sim_exe = TrackSimulator(track_exe=exe_file)

    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/wine" if cmd == "wine" else None)
    assert sim_exe.is_available()

    monkeypatch.setattr("shutil.which", lambda cmd: None)
    assert not sim_exe.is_available()

    bin_file = tmp_path / "mock_track_native"
    bin_file.touch()
    sim_bin = TrackSimulator(track_exe=bin_file)
    monkeypatch.setattr("os.access", lambda path, mode: True)
    assert sim_bin.is_available()


def test_track_simulator_run_simulation_and_parsers(tmp_path, test_lattice, monkeypatch):
    track_exe = tmp_path / "TRACKv39C.exe"
    track_exe.touch()
    dll_file = tmp_path / "support.dll"
    dll_file.touch()

    work_dir = tmp_path / "track_work"
    sim = TrackSimulator(track_exe=track_exe, work_dir=work_dir)

    # Test unavailable fallback
    monkeypatch.setattr(sim, "is_available", lambda: False)
    pts_unavail = sim.run_simulation(test_lattice)
    assert len(pts_unavail) > 0

    monkeypatch.setattr(sim, "is_available", lambda: True)

    # 1. beam.out success path (including a line with malformed float to trigger ValueError)
    def mock_subprocess_run(*args, **kwargs):
        work_dir.mkdir(parents=True, exist_ok=True)
        beam_line_good = ["1", "ST_CH_01", "0.5"] + ["0.0"] * 2 + ["0.15"] + ["0.0"] * 30
        beam_line_bad = ["2", "ST_BAD", "bad_float"] + ["0.0"] * 32
        content = "n_el name s ...\n" + " ".join(beam_line_good) + "\n" + " ".join(beam_line_bad) + "\n"
        (work_dir / "beam.out").write_text(content, encoding="utf-8")
        res = MagicMock()
        res.returncode = 0
        return res

    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    pts = sim.run_simulation(test_lattice)
    assert len(pts) > 0
    assert pts[0].element_name == "ST_CH_01"
    assert pts[0].sigma_x_mm == pytest.approx(1.5)

    # 2. envelop.out path (including bad float line to trigger ValueError)
    (work_dir / "beam.out").unlink()
    env_content = "10.0 0.05 0.08 0.12 0.14 0.0\ninvalid_s 0.0 0.0 0.0 0.0 0.0\n"
    (work_dir / "envelop.out").write_text(env_content, encoding="utf-8")

    def mock_subp_no_beam(*args, **kwargs):
        res = MagicMock()
        res.returncode = 0
        return res

    monkeypatch.setattr("subprocess.run", mock_subp_no_beam)
    pts_env = sim.run_simulation(test_lattice)
    assert len(pts_env) > 0
    assert pts_env[0].element_name == "TRACK_STEP"
    assert pts_env[0].x_mm == pytest.approx(0.5)

    # 3. Empty output fallback
    (work_dir / "envelop.out").unlink()
    pts_fallback = sim.run_simulation(test_lattice)
    assert len(pts_fallback) > 0
    assert pts_fallback[0].provenance == "fallback"

    # 4. Subprocess error fallback
    def mock_subp_error(*args, **kwargs):
        raise subprocess.SubprocessError("Wine fault")

    monkeypatch.setattr("subprocess.run", mock_subp_error)
    pts_err = sim.run_simulation(test_lattice)
    assert pts_err[0].provenance == "fallback"

    # 5. Native binary runner branch
    native_exe = tmp_path / "track_native"
    native_exe.touch()
    sim_native = TrackSimulator(track_exe=native_exe, work_dir=work_dir)
    monkeypatch.setattr(sim_native, "is_available", lambda: True)
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: MagicMock(returncode=0))
    pts_nat = sim_native.run_simulation(test_lattice)
    assert pts_nat[0].provenance == "fallback"

    # 6. estimate_losses
    losses = sim.estimate_losses(test_lattice)
    assert losses >= 0.0
    with patch.object(sim, "run_simulation", return_value=[]):
        assert sim.estimate_losses(test_lattice) == 0.0


def test_track_simulator_run_from_directory(tmp_path, monkeypatch):
    dll_dir = tmp_path / "bin_with_dll"
    dll_dir.mkdir()
    (dll_dir / "wine_support.dll").touch()
    track_exe = dll_dir / "TRACKv39C.exe"
    track_exe.touch()
    work_dir = tmp_path / "run_from_dir_work"
    sim = TrackSimulator(track_exe=track_exe, work_dir=work_dir)

    # Non-existent input dir
    with pytest.raises(FileNotFoundError):
        sim.run_from_directory(tmp_path / "nonexistent")

    input_dir = tmp_path / "input_deck"
    input_dir.mkdir()
    sclinac_content = "stM      01   0.0   0.0\ncorr STM_02   0.0   0.0\nother line\n"
    (input_dir / "sclinac.dat").write_text(sclinac_content, encoding="utf-8")

    # Test steerer resolution with quantization and zero conversion factor
    eff = sim._resolve_effective_kicks(
        steerer_kicks={"STM_01": (0.1, 0.2)},
        steerer_currents={"STM_02": (1.0, -1.0)},
        conversion_factor_a_per_mrad=0.0,
        current_increment_a=0.0,
    )
    assert eff["STM_01"] == (0.1, 0.2)
    assert eff["STM_02"] == (0.0, 0.0)

    # Test run_from_directory with beam.out
    def mock_subp_dir(*args, **kwargs):
        beam_line = ["1", "STM_01", "1.0"] + ["0.0"] * 2 + ["0.2"] + ["0.0"] * 30
        (work_dir / "beam.out").write_text(" ".join(beam_line) + "\n", encoding="utf-8")
        return MagicMock(returncode=0)

    monkeypatch.setattr("subprocess.run", mock_subp_dir)
    res_pts = sim.run_from_directory(
        input_dir,
        steerer_kicks={"STM_01": (0.05, 0.05)},
        steerer_currents={"STM_02": (0.5, 0.5)},
    )
    assert len(res_pts) > 0

    # Test run_from_directory with envelop.out
    (work_dir / "beam.out").unlink()
    (work_dir / "envelop.out").write_text("10.0 0.1 0.1 0.2 0.2 0.0\n", encoding="utf-8")
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: MagicMock(returncode=0))
    res_env = sim.run_from_directory(input_dir)
    assert len(res_env) > 0

    # Test failure with no output file
    if (work_dir / "beam.out").exists():
        (work_dir / "beam.out").unlink()
    if (work_dir / "envelop.out").exists():
        (work_dir / "envelop.out").unlink()
    monkeypatch.setattr("subprocess.run", lambda *a, **kw: MagicMock(returncode=1, stderr=b"TRACK run error"))
    with pytest.raises(RuntimeError):
        sim.run_from_directory(input_dir)


def test_impactz_simulator(tmp_path, test_lattice, monkeypatch):
    work_dir = tmp_path / "impact_work"
    sim = ImpactZSimulator(work_dir=work_dir)

    # Test _check_lume_impact when import fails
    with patch.dict("sys.modules", {"impact": None}):
        sim._check_lume_impact()
        assert not sim.is_available()

    # 1. When lume-impact is unavailable
    sim._has_lume_impact = False
    assert not sim.is_available()
    pts_fallback = sim.run_simulation(test_lattice)
    assert pts_fallback[0].provenance == "fallback"

    # 2. When lume-impact is available, but ImpactZ.in is missing
    sim._has_lume_impact = True
    assert sim.is_available()
    pts_no_in = sim.run_simulation(test_lattice)
    assert pts_no_in[0].provenance == "fallback"

    # 3. When ImpactZ.in exists and mock run succeeds
    (work_dir / "ImpactZ.in").write_text("! mock impact input\n", encoding="utf-8")
    mock_impact_mod = MagicMock()
    mock_impact_instance = MagicMock()
    mock_impact_mod.ImpactZ.return_value = mock_impact_instance

    monkeypatch.setitem(__import__("sys").modules, "impact", mock_impact_mod)
    pts_ok = sim.run_simulation(test_lattice)
    assert pts_ok[0].provenance == "impactz"
    mock_impact_instance.run.assert_called_once()

    # 4. When mock run raises RuntimeError
    mock_impact_instance.run.side_effect = RuntimeError("Impact execution fault")
    pts_err = sim.run_simulation(test_lattice)
    assert pts_err[0].provenance == "fallback"

    # 5. estimate_losses
    losses = sim.estimate_losses(test_lattice)
    assert losses >= 0.0
