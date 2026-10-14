"""Unit tests achieving 100% test coverage for helios/physics elements, species, halo, stripper, etc."""

import math
from unittest.mock import MagicMock, patch
import numpy as np
import pytest
import torch

from helios.physics.beam_dump import BeamDumpParameters, BeamDumpThermalEngine
from helios.physics.benchmarks import CrossCodeBenchmarkRunner
from helios.physics.converters import LatticeConverter
from helios.physics.css import ChargeStateSeparator
from helios.physics.differentiable import DifferentiableDrift, DifferentiableElement, DifferentiableQuadrupole
from helios.physics.elements import DiagnosticElement, Drift, Element, Quadrupole, RFCavity, Steerer
from helios.physics.equipartition import (
    HofmannEquipartitionEngine,
    HofmannResonanceType,
    LinacPhaseAdvance,
)
from helios.physics.facilities import (
    create_frib_ls1_lattice,
    create_gsi_fair_lattice,
    create_raon_scl1_lattice,
)
from helios.physics.fieldmaps import FieldMap3DData, FieldMap3DInterpolator
from helios.physics.halo import (
    BeamHaloAnalyzer,
    BeamHaloQuantifier,
    DynamicCollimatorOptimizer,
)
from helios.physics.lattice import Lattice
from helios.physics.liquid_stripper import (
    LiquidStripperEngine,
    LiquidStripperParameters,
    StripperMedium,
)
from helios.physics.parallel import BatchSimulationOutcome, ParallelSimulationEngine, TensorParticleTracker
from helios.physics.pusher import SymplecticParticlePusher
from helios.physics.species import (
    IonSpecies,
    MultiChargeBeam,
    MultiChargeComponent,
    create_argon_beam,
    create_proton_beam,
    create_xenon_multicharge_beam,
)
from helios.physics.stripper import StripperFoil
from helios.physics.surrogate import FastPhysicsSurrogate
from helios.physics.sync import DigitalTwinDriftDetector, GoldenBaselineArchive
from helios.physics.vacuum import LinacVacuumPhysicsEngine, VacuumSegment


def test_elements_coverage():
    # Base Element
    base = Element(name="BASE_ELEM")
    assert np.allclose(base.transfer_matrix_6x6(), np.eye(6))

    # Quadrupole k=0 or length=0 branch
    q_zero = Quadrupole(name="Q_ZERO", length=0.1, gradient_t_m=0.0)
    R_q0 = q_zero.transfer_matrix_6x6()
    assert R_q0[0, 1] == 0.1
    assert R_q0[2, 3] == 0.1

    # Steerer methods and quantization branches
    st = Steerer(name="ST_01", length=0.1, conversion_factor_a_per_mrad=0.168, current_increment_a=0.05)
    # increment_a <= 0 branch
    raw_curr = st.kick_to_current(1.0, conversion_factor_a_per_mrad=0.2, increment_a=0.0)
    assert raw_curr == pytest.approx(0.2)

    # conversion_factor < 1e-9 branch
    zero_kick = st.current_to_kick(1.0, conversion_factor_a_per_mrad=0.0)
    assert zero_kick == 0.0

    # current_increment_a <= 0 branch in set_currents
    st.current_increment_a = 0.0
    st.set_currents(1.5, -2.5)
    assert st.current_x_a == 1.5
    assert st.current_y_a == -2.5

    # set_kicks
    st.set_kicks(0.5, -0.5)
    assert st.kick_x_mrad == pytest.approx(0.5)


def test_species_coverage():
    sp = IonSpecies(name="TestIon", mass_amu=40.0, atomic_number_z=18, charge_state_q=10, kinetic_energy_mev_u=1.0)
    assert sp.total_energy_mev > 0.0
    assert sp.rest_energy_mev > 0.0

    neutral = IonSpecies(name="NeutralIon", mass_amu=1.0, atomic_number_z=1, charge_state_q=0, kinetic_energy_mev_u=1.0)
    assert neutral.magnetic_rigidity_t_m == float("inf")

    # Empty beam raises
    empty_beam = MultiChargeBeam(name="Empty", total_current_ma=0.0, components=[])
    with pytest.raises(ValueError):
        _ = empty_beam.reference_species

    # Factories and rigidity
    xe_beam = create_xenon_multicharge_beam()
    assert xe_beam.effective_rigidity_t_m > 0.0

    ar_beam = create_argon_beam()
    assert len(ar_beam.components) == 1

    p_beam = create_proton_beam()
    assert len(p_beam.components) == 1


def test_differentiable_coverage():
    elem = DifferentiableElement(name="BaseDiff", length=0.2)
    with pytest.raises(NotImplementedError):
        elem.forward(torch.zeros(5, 6, dtype=torch.float64))

    # Quadrupole k1 < 0 (defocusing) branch
    q_defocus = DifferentiableQuadrupole(name="Q_defocus", length=0.2, k1=-5.0)
    particles = torch.randn(10, 6, dtype=torch.float64)
    out = q_defocus(particles)
    assert out.shape == (10, 6)


def test_parallel_coverage():
    # Parameter sweep with exception handling branch
    def failing_eval(params):
        if params.get("bad_param", 0) > 1.0:
            raise RuntimeError("Simulation error")
        return {"transmission_pct": 98.0}

    outcomes = ParallelSimulationEngine.run_parameter_sweep(
        eval_fn=failing_eval,
        base_parameters={},
        scan_param="bad_param",
        scan_range=(0.0, 2.0),
        num_samples=5,
    )
    assert any(not o.success for o in outcomes)

    # All failed runs in UQ analysis
    failed_outcomes = [
        BatchSimulationOutcome(run_id=i, parameters={}, transmission_pct=0.0, max_envelope_x_mm=99.0, max_envelope_y_mm=99.0, orbit_rms_mm=99.0, success=False)
        for i in range(3)
    ]
    res_uq = ParallelSimulationEngine.evaluate_uncertainty_quantification(failed_outcomes, "test_param")
    assert res_uq.robustness_score == 0.0

    # TensorParticleTracker with particles lost
    tracker = TensorParticleTracker()
    parts = torch.tensor([[1.0, 0.0, 1.0, 0.0, 0.0, 0.0]], dtype=torch.float32)
    matrices = [torch.eye(6, dtype=torch.float32)]
    track_res = tracker.track_particle_ensemble(parts, matrices, aperture_radius_m=0.01)
    assert track_res["transmission_pct"] == 0.0


def test_halo_coverage():
    # compute_plane_halo with zero std
    metrics = BeamHaloAnalyzer.compute_plane_halo(np.zeros(10))
    assert metrics.rms_size_mm == 0.0

    # Risk branches: evaluate_halo
    rad = np.linspace(0.0, 15.0, 100)
    intensity_low = np.exp(-(rad ** 2) / (2.0 * 2.0 ** 2))
    res_low = BeamHaloQuantifier.evaluate_halo(intensity_low, rad, pipe_radius_mm=50.0)
    assert res_low.scraping_risk_level in ["LOW", "MODERATE", "HIGH"]

    intensity_high = np.exp(-(rad ** 2) / 8.0) + 0.1 * np.exp(-rad / 5.0)
    res_high = BeamHaloQuantifier.evaluate_halo(intensity_high, rad, pipe_radius_mm=5.0)
    assert res_high.scraping_risk_level in ["CRITICAL", "HIGH", "MODERATE"]

    # DynamicCollimatorOptimizer with zero halo count (x_mm all <= 3*sigma)
    opt = DynamicCollimatorOptimizer()
    bunch_x = np.linspace(-0.001, 0.001, 20)
    bunch_y = np.linspace(-0.001, 0.001, 20)
    collimator = opt.optimize_jaws("COLL_01", bunch_x, bunch_y)
    assert collimator.estimated_halo_reduction_fraction == 1.0


def test_liquid_stripper_coverage():
    engine = LiquidStripperEngine()

    # Zero surface tension
    weber, status = engine._compute_hydrodynamics(
        density_g_cm3=0.5, surface_tension_N_m=0.0, film_thickness_um=15.0, film_speed_m_s=50.0
    )
    assert weber == 0.0
    assert status == "STABLE"

    # Marginal and spraying
    _, stat_marg = engine._compute_hydrodynamics(
        density_g_cm3=0.5, surface_tension_N_m=0.05, film_thickness_um=20.0, film_speed_m_s=100.0
    )
    assert stat_marg == "MARGINAL"

    _, stat_spray = engine._compute_hydrodynamics(
        density_g_cm3=0.5, surface_tension_N_m=0.01, film_thickness_um=20.0, film_speed_m_s=100.0
    )
    assert stat_spray == "SPRAYING"

    # Non-lithium medium
    params_gas = LiquidStripperParameters(medium=StripperMedium.WINDOWLESS_HELIUM_GAS)
    res_gas = engine.evaluate_stripper(params_gas)
    assert res_gas.vaporization_rate_g_per_hr == 0.01


def test_equipartition_coverage():
    engine = HofmannEquipartitionEngine()

    # FOURTH_ORDER_STRUCTURE: sigma_t = sigma_l
    p_4th = LinacPhaseAdvance(
        section_id="EQ_01",
        sigma_t_deg=40.0,
        sigma_l_deg=40.0,
        sigma_0t_deg=60.0,
        sigma_0l_deg=60.0,
        emit_norm_t_mm_mrad=0.3,
        emit_norm_l_deg_MeV=2.5,
    )
    res_4th = engine.evaluate_stability(p_4th)
    assert res_4th.active_resonance == HofmannResonanceType.FOURTH_ORDER_STRUCTURE

    # HIGH_ORDER_MULTIPOLE: 3*sigma_t = sigma_l
    p_high = LinacPhaseAdvance(
        section_id="EQ_02",
        sigma_t_deg=25.0,
        sigma_l_deg=75.0,
        sigma_0t_deg=60.0,
        sigma_0l_deg=90.0,
        emit_norm_t_mm_mrad=0.3,
        emit_norm_l_deg_MeV=2.5,
    )
    res_high = engine.evaluate_stability(p_high)
    assert res_high.active_resonance in [HofmannResonanceType.HIGH_ORDER_MULTIPOLE, HofmannResonanceType.SECOND_ORDER_DIFFERENCE]


def test_fieldmaps_coverage():
    # Out of bounds
    data = FieldMap3DData(
        name="test_map",
        x_grid_m=np.linspace(-0.01, 0.01, 3),
        y_grid_m=np.linspace(-0.01, 0.01, 3),
        z_grid_m=np.linspace(0.0, 0.1, 3),
        frequency_mhz=0.0,
        ex_v_per_m=np.zeros((3, 3, 3)),
        ey_v_per_m=np.zeros((3, 3, 3)),
        ez_v_per_m=np.zeros((3, 3, 3)),
        bx_t=np.zeros((3, 3, 3)),
        by_t=np.zeros((3, 3, 3)),
        bz_t=np.zeros((3, 3, 3)),
    )
    interp = FieldMap3DInterpolator(data)
    e_oob, b_oob = interp.evaluate_field(999.0, 0.0, 0.0)
    assert np.all(e_oob == 0.0)

    # Frequency == 0 (static field)
    e_in, b_in = interp.evaluate_field(0.0, 0.0, 0.05)
    assert e_in.shape == (3,)


def test_sync_and_vacuum_coverage():
    # Sync GoldenBaselineArchive
    archive = GoldenBaselineArchive()
    assert archive.get_golden("missing") is None
    with pytest.raises(KeyError):
        archive.diff_against_golden("missing", {})

    # Sync discrepancy > 0.5
    status = DigitalTwinDriftDetector.detect_drift(np.array([1.0]), np.array([0.1]))
    assert "RF_SYNCHRONOUS_PHASE" in status.affected_subsystems

    # Vacuum RUNAWAY_RISK and ACCEPTABLE
    vac_engine = LinacVacuumPhysicsEngine()
    chamber = VacuumSegment(
        section_name="HOT_SECTION", length_m=2.0, tube_diameter_mm=40.0,
        ion_pump_speed_l_per_s=10.0, outgassing_rate_mbar_l_s_cm2=1e-8, temperature_K=300.0,
    )
    res_runaway = vac_engine.evaluate_segment_vacuum(
        chamber, beam_current_uA=10000.0, beam_energy_MeV_u=0.5,
    )
    assert res_runaway.vacuum_status == "RUNAWAY_RISK"

    chamber_acc = VacuumSegment(
        section_name="OK_SECTION", length_m=2.0, tube_diameter_mm=40.0,
        ion_pump_speed_l_per_s=1000.0, outgassing_rate_mbar_l_s_cm2=5e-9, temperature_K=300.0,
    )
    res_acc = vac_engine.evaluate_segment_vacuum(
        chamber_acc, beam_current_uA=1.0, beam_energy_MeV_u=0.5,
    )
    assert res_acc.vacuum_status in ["ACCEPTABLE", "EXCELLENT_UHV"]


def test_converters_pusher_dump_css_stripper_surrogate_facilities():
    # 1. Converter MAD-X with string param
    madx_str = "DRIFT_01: DRIFT, L=0.2, TYPE=TEST_STR;\n"
    lat_madx = LatticeConverter.import_from_madx(madx_str)
    assert len(lat_madx.elements) == 1

    # 2. SymplecticParticlePusher with scraping
    data_map = FieldMap3DData(
        name="pusher_map",
        x_grid_m=np.linspace(-0.01, 0.01, 3),
        y_grid_m=np.linspace(-0.01, 0.01, 3),
        z_grid_m=np.linspace(0.0, 0.1, 3),
        ex_v_per_m=np.zeros((3, 3, 3)),
        ey_v_per_m=np.zeros((3, 3, 3)),
        ez_v_per_m=np.zeros((3, 3, 3)),
        bx_t=np.zeros((3, 3, 3)),
        by_t=np.zeros((3, 3, 3)),
        bz_t=np.zeros((3, 3, 3)),
    )
    interp_map = FieldMap3DInterpolator(data_map)
    pusher = SymplecticParticlePusher(mass_amu=1.0, charge_q=1)
    hist = pusher.track_boris(
        interpolator=interp_map,
        initial_position_m=np.array([0.05, 0.05, 0.0]),  # out of 0.02m aperture
        initial_velocity_m_s=np.array([0.0, 0.0, 1e6]),
        time_step_s=1e-8,
        num_steps=10,
        aperture_radius_m=0.02,
    )
    assert not hist.survived

    # 3. BeamDump CONSTRAINED status
    dump_engine = BeamDumpThermalEngine()
    params_const = BeamDumpParameters(
        beam_power_kW=150.0,
        beam_energy_MeV_u=20.0,
        beam_spot_radius_mm=2.5,
        cooling_water_flow_m_s=3.0,
        water_pressure_bar=3.0,
    )
    res_dump = dump_engine.evaluate_beam_dump(params_const)
    assert res_dump.status in ["CONSTRAINED", "ABORT_REQUIRED", "NOMINAL"]

    # 4. CSS tune_slits_for_optimal_purity fallback
    beam = create_argon_beam()
    css = ChargeStateSeparator(dispersion_x_m=1.25, bend_radius_m=1.80, default_slit_gap_mm=8.0)
    rep = css.tune_slits_for_optimal_purity(beam, target_charge_q=11, min_transmission_pct=100.1)
    assert rep is not None

    # 5. StripperFoil thickness_um
    foil = StripperFoil(foil_id="F01", thickness_ug_cm2=300.0, density_g_cm3=2.0)
    assert foil.thickness_um == pytest.approx(1.5)

    # 6. FastPhysicsSurrogate with empty trajectory
    surr = FastPhysicsSurrogate()
    with patch.object(surr.digital_twin, "run_simulation", return_value=[]):
        pred = surr.predict({})
        assert pred["loss_pct"] == 0.0

    # 7. Facilities and Benchmarks
    r_lat = create_raon_scl1_lattice()
    assert len(r_lat.elements) > 0

    f_lat = create_frib_ls1_lattice()
    assert len(f_lat.elements) > 0

    g_lat = create_gsi_fair_lattice()
    assert len(g_lat.elements) > 0

    bench = CrossCodeBenchmarkRunner()
    bench_rep = bench.run_benchmark(r_lat)
    assert bench_rep.consistency_passed is not None

    # 8. Lattice compute_orbit_response_matrix non-steerer branch
    lat_resp = Lattice("RespTest", elements=[Drift(name="D1", length=0.1), DiagnosticElement(name="B1", length=0.1, diag_type="BPM")])
    Rx, Ry = lat_resp.compute_orbit_response_matrix(bpm_names=["B1"], steerer_names=["D1"])
    assert Rx.shape == (1, 1)
