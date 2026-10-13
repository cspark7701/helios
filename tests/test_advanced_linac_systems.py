"""Tests for HELIOS Phases 40-44: Advanced Heavy Ion Linac Systems."""

import numpy as np
import pytest

from helios.physics.rfq import (
    RFQDesignParameters,
    RFQSectionType,
    RFQVaneDynamicsEngine,
)
from helios.physics.liquid_stripper import (
    StripperMedium,
    LiquidStripperParameters,
    LiquidStripperEngine,
)
from helios.rf.cryoplant import (
    CavityCryoState,
    CryoplantCapacity,
    CryoplantThermodynamicOptimizer,
)
from helios.physics.tensornet import (
    TensorTrainDecomposer,
)
from helios.optimization.quantum import (
    QuantumAnnealingConfig,
    SimulatedQuantumAnnealer,
)
from helios.diagnostics.survey import (
    MagnetFiducialMeasurement,
    LaserTrackerSurveyAnalyzer,
)
from helios.ops.golden import (
    CertificationGrade,
    GoldenRunParameter,
    GoldenRunCertificationEngine,
)


def test_rfq_vane_modulation_and_cell_dynamics():
    """Verify RFQ cell generation, modulation ramping, and macroparticle transmission."""
    params = RFQDesignParameters(
        rf_frequency_MHz=81.25,
        vane_voltage_kV=85.0,
        mean_aperture_r0_mm=5.2,
        ion_mass_amu=238.0,
        ion_charge=33,
        input_energy_keV_u=10.0,
        output_energy_keV_u=500.0
    )
    engine = RFQVaneDynamicsEngine(params)
    cells = engine.generate_cells(total_cells=120)

    assert len(cells) == 120
    # Section sequence
    assert cells[0].section == RFQSectionType.RADIAL_MATCHING
    assert cells[20].section == RFQSectionType.SHAPER
    assert cells[60].section == RFQSectionType.GENTLE_BUNCHER
    assert cells[-1].section == RFQSectionType.ACCELERATOR

    # Modulation factor must ramp from 1.0 to > 1.6
    assert cells[0].modulation_m == 1.0
    assert cells[-1].modulation_m > 1.6
    # Energy must increase monotonically
    assert cells[-1].energy_keV_u > cells[0].energy_keV_u
    assert cells[-1].synchronous_phase_deg == -30.0

    # Simulate bunch
    summary = engine.simulate(cells, n_macroparticles=500)
    assert summary.transmission_efficiency_percent > 75.0
    assert summary.bunching_efficiency_percent > 65.0
    assert summary.total_length_m > 2.0


def test_liquid_stripper_hydrodynamics_and_charge_exchange():
    """Verify Liquid Lithium film hydrodynamic stability and high-charge stripping."""
    engine = LiquidStripperEngine()
    params = LiquidStripperParameters(
        medium=StripperMedium.LIQUID_LITHIUM_FILM,
        film_thickness_um=15.0,
        film_speed_m_s=35.0,
        operating_temperature_C=220.0,
        beam_power_deposited_kW=1.2,
        beam_spot_width_mm=4.0
    )

    result = engine.evaluate_stripper(
        params=params,
        ion_species="U238",
        ion_mass_amu=238.0,
        ion_initial_q=33,
        beam_energy_MeV_u=17.5
    )

    assert result.medium == StripperMedium.LIQUID_LITHIUM_FILM
    assert result.areal_density_mg_cm2 > 0.5  # ~ 0.76 mg/cm^2
    assert result.hydrodynamic_status in ["STABLE", "MARGINAL"]
    assert result.weber_number > 0.0
    # Uranium strips to ~78-89+ at 17.5 MeV/u
    assert 75 <= result.equilibrium_mean_charge_q <= 90
    assert result.energy_loss_MeV_per_u > 0.05
    assert result.film_temperature_rise_C < 400.0  # safe margin below 1342 C boiling point
    assert result.vaporization_rate_g_per_hr >= 0.0


def test_cryoplant_heat_load_balancing():
    """Verify SRF cavity BCS surface resistance and closed-loop cryoplant gradient balancing."""
    opt = CryoplantThermodynamicOptimizer()

    # Surface resistance check (Nb at 2.0 K and 162.5 MHz)
    rs = opt.calculate_surface_resistance(frequency_MHz=162.5, temperature_K=2.05, residual_nOhm=8.0)
    assert 8.0e-9 < rs < 15.0e-9  # Expect ~9-11 nOhm

    # Setup 4 SCL cryomodule cavities
    cavities = [
        CavityCryoState(
            cavity_id=f"CAV_SCL1_{i+1:02d}",
            cavity_type="HWR",
            frequency_MHz=162.5,
            temperature_K=2.05,
            voltage_MV=2.2,
            R_over_Q_ohm=220.0,
            geometry_factor_G=48.0,
            residual_resistance_nOhm=7.5 + i * 0.8
        )
        for i in range(4)
    ]

    cryoplant = CryoplantCapacity(
        stage_2K_max_power_W=120.0,  # Tight 2.0K budget
        surge_margin_percent=10.0
    )

    balance = opt.balance_linac_heat_load(
        cavities=cavities,
        target_total_voltage_MV=9.0,
        cryoplant=cryoplant
    )

    assert balance.total_2K_heat_load_W <= cryoplant.stage_2K_max_power_W
    assert balance.cooling_margin_percent >= 0.0
    assert balance.status in ["NOMINAL", "CONSTRAINED"]
    assert len(balance.adjusted_voltages_MV) == 4
    # Cavity with lowest residual resistance (highest Q0) should receive equal or higher voltage
    assert balance.adjusted_voltages_MV["CAV_SCL1_01"] >= balance.adjusted_voltages_MV["CAV_SCL1_04"]


def test_tensor_train_bunch_compression():
    """Verify low-rank MPS / Tensor Train macroparticle distribution compression."""
    np.random.seed(42)
    n_part = 2000
    bunch = np.zeros((n_part, 6))
    bunch[:, 0] = np.random.normal(0, 0.002, n_part)
    bunch[:, 1] = np.random.normal(0, 0.001, n_part)
    bunch[:, 2] = np.random.normal(0, 0.0025, n_part)
    bunch[:, 3] = np.random.normal(0, 0.0008, n_part)
    bunch[:, 4] = np.random.normal(0, 0.01, n_part)
    bunch[:, 5] = np.random.normal(0, 0.0005, n_part)

    decomposer = TensorTrainDecomposer(max_bond_dimension=12, svd_tolerance=1e-3)
    cores, metrics = decomposer.compress_bunch_density_6d(bunch, grid_bins_per_dim=8)

    assert len(cores) == 3
    assert metrics.compression_ratio > 5.0
    assert metrics.relative_frobenius_error < 0.25
    assert abs(metrics.reconstructed_rms_x - metrics.original_rms_x) < 1e-6


def test_quantum_combinatorial_annealer():
    """Verify Trotter-Suzuki Simulated Quantum Annealing on discrete Ising tuning."""
    N = 8
    # Local field and random antiferromagnetic coupling
    h = np.array([0.2, -0.3, 0.1, -0.4, 0.5, -0.1, 0.2, -0.2])
    np.random.seed(42)
    J = np.zeros((N, N))
    for i in range(N):
        for j in range(i + 1, N):
            J[i, j] = 0.3 * np.random.randn()
            J[j, i] = J[i, j]

    config = QuantumAnnealingConfig(
        num_spins=N,
        trotter_replicas=8,
        sweeps=100
    )
    annealer = SimulatedQuantumAnnealer(config)
    res = annealer.solve_ising(h, J)

    assert len(res.best_spin_configuration) == N
    assert all(s in [-1, 1] for s in res.best_spin_configuration)
    assert res.tunneling_transitions > 0
    assert res.best_energy < 0.0  # Successfully found lower energy state


def test_laser_tracker_survey_and_girder_realignment():
    """Verify laser tracker fiducial processing and motorized girder realignment."""
    # Create 3 magnets on a girder with 0.8 mm offset and 0.5 mrad yaw error
    girder_elements = [
        MagnetFiducialMeasurement(
            element_id=f"QUAD_MEBT_{i+1:02d}",
            girder_id="GIRDER_MEBT_01",
            s_longitudinal_m=1.0 * i,
            measured_x_mm=0.85 + 0.45 * (i - 1.0),
            measured_y_mm=-0.50 + 0.20 * (i - 1.0),
            measured_z_mm=0.0,
            pitch_mrad=0.20,
            yaw_mrad=0.45,
            roll_mrad=0.15
        )
        for i in range(3)
    ]

    analyzer = LaserTrackerSurveyAnalyzer()
    misalignments = analyzer.evaluate_misalignments(girder_elements)
    assert len(misalignments) == 3
    assert abs(misalignments["QUAD_MEBT_01"]["delta_x_mm"]) > 0.3

    adjustment = analyzer.optimize_girder_realignment("GIRDER_MEBT_01", girder_elements)
    assert adjustment.girder_id == "GIRDER_MEBT_01"
    assert adjustment.rms_residual_error_mm < 0.10  # Clean alignment after shift/yaw
    assert adjustment.projected_corrector_current_reduction_percent > 70.0


def test_golden_run_certification_engine():
    """Verify cryptographic SHA-256 Golden Run certification."""
    engine = GoldenRunCertificationEngine()
    golden_params = [
        GoldenRunParameter(pv_name="MEBT:PSC:Q01:CurrentSet", baseline_value=45.2, tolerance_abs=0.2),
        GoldenRunParameter(pv_name="MEBT:PSC:Q02:CurrentSet", baseline_value=-42.8, tolerance_abs=0.2),
        GoldenRunParameter(pv_name="SCL1:RF:CAV01:AmpSet", baseline_value=2.15, tolerance_abs=0.05),
    ]
    engine.register_golden_run("URANIUM_NOMINAL_2026", golden_params)

    # 1. Matching state -> CERTIFIED
    live_ok = {
        "MEBT:PSC:Q01:CurrentSet": 45.25,
        "MEBT:PSC:Q02:CurrentSet": -42.75,
        "SCL1:RF:CAV01:AmpSet": 2.16,
    }
    cert_ok = engine.certify_machine_state("URANIUM_NOMINAL_2026", "U238", 17.5, live_ok)
    assert cert_ok.grade == CertificationGrade.CERTIFIED
    assert cert_ok.compliance_score_percent == 100.0
    assert len(cert_ok.sha256_fingerprint) == 64
    assert len(cert_ok.violating_parameters) == 0

    # 2. Deviating state -> NON_COMPLIANT
    live_bad = {
        "MEBT:PSC:Q01:CurrentSet": 48.0,  # off by 2.8 A!
        "MEBT:PSC:Q02:CurrentSet": -42.8,
        "SCL1:RF:CAV01:AmpSet": 1.80,    # off by 0.35 MV!
    }
    cert_bad = engine.certify_machine_state("URANIUM_NOMINAL_2026", "U238", 17.5, live_bad)
    assert cert_bad.grade == CertificationGrade.NON_COMPLIANT
    assert cert_bad.compliance_score_percent < 50.0
    assert len(cert_bad.violating_parameters) == 2
