"""Tests for HELIOS Phases 45-49: High-Power Linac Physics, Multipactor & Safety."""

import pytest
from helios.physics.beam_dump import (
    TargetMaterial,
    BeamDumpParameters,
    BeamDumpThermalEngine,
)


def test_beam_dump_thermo_mechanics_and_chf_abort():
    """Verify Bragg peak shock pressure, von Mises thermal stress, and CHF abort."""
    engine = BeamDumpThermalEngine()

    # 1. Nominal 25 kW Glidcop beam stop (grazing angle 2.5 deg, 10 mm spot)
    nominal_dump = BeamDumpParameters(
        material=TargetMaterial.GLIDCOP,
        beam_power_kW=25.0,
        beam_energy_MeV_u=17.5,
        beam_spot_radius_mm=10.0,
        grazing_angle_deg=2.5,
        cooling_water_flow_m_s=6.0,
        water_pressure_bar=5.0
    )
    res_nom = engine.evaluate_beam_dump(nominal_dump)
    assert res_nom.material == TargetMaterial.GLIDCOP
    assert res_nom.bragg_peak_depth_mm > 0.1
    assert res_nom.stress_safety_factor > 1.2
    assert res_nom.chf_margin > 1.3
    assert not res_nom.abort_interlock_tripped
    assert res_nom.status in ["NOMINAL", "CONSTRAINED"]

    # 2. Overpowered 350 kW tightly focused beam -> thermal stress & CHF trip
    overpower_dump = BeamDumpParameters(
        material=TargetMaterial.GLIDCOP,
        beam_power_kW=350.0,
        beam_energy_MeV_u=17.5,
        beam_spot_radius_mm=1.2,  # very tight focus -> massive heat flux
        cooling_water_flow_m_s=2.0,
        water_pressure_bar=2.0
    )
    res_over = engine.evaluate_beam_dump(overpower_dump)
    assert res_over.abort_interlock_tripped
    assert res_over.status == "ABORT_REQUIRED"
    assert res_over.stress_safety_factor < 1.0 or res_over.chf_margin < 1.25


def test_cavity_multipactoring_and_field_emission():
    """Verify SEY resonant barriers and Fowler-Nordheim dark current scaling."""
    from helios.rf.multipactor import SurfaceMaterial, CavityMultipactorEngine

    engine = CavityMultipactorEngine()

    # 1. Niobium coaxial coupler at 162.5 MHz with 15 mm gap
    # Evaluate at resonance level
    res_mp = engine.evaluate_multipactoring(
        material=SurfaceMaterial.NIOBIUM,
        frequency_MHz=162.5,
        gap_distance_mm=15.0,
        operating_voltage_kV=1.2  # close to resonance
    )
    assert res_mp.resonant_order_1_voltage_kV > 0.0
    assert len(res_mp.barrier_voltage_bands_kV) == 2
    assert res_mp.secondary_emission_yield > 0.0

    # 2. TiN coating suppresses SEY (delta_max < 1.0) -> SAFE
    res_tin = engine.evaluate_multipactoring(
        material=SurfaceMaterial.TITANIUM_NITRIDE_COATED,
        frequency_MHz=162.5,
        gap_distance_mm=15.0,
        operating_voltage_kV=1.2
    )
    assert res_tin.risk_level == "SAFE"

    # 3. Fowler-Nordheim field emission at low vs high electric field
    fe_low = engine.evaluate_field_emission(peak_E_MV_m=12.0, field_enhancement_beta=50.0)
    assert fe_low.sensor_radiation_status == "NOMINAL"
    assert fe_low.radiation_dose_rate_mGy_per_hr < 1.0

    fe_high = engine.evaluate_field_emission(peak_E_MV_m=35.0, field_enhancement_beta=85.0)
    assert fe_high.total_dark_current_uA > 0.1
    assert fe_high.sensor_radiation_status in ["ELEVATED", "CRITICAL_QUENCH_RISK"]


def test_hofmann_stability_charts_and_rematching():
    """Verify Hofmann space-charge stability mapping and resonance rematching."""
    from helios.physics.equipartition import (
        LinacPhaseAdvance,
        HofmannResonanceType,
        HofmannEquipartitionEngine,
    )

    engine = HofmannEquipartitionEngine()

    # 1. Unstable operating point near 2*sigma_t - sigma_l = 0 resonance
    # sigma_t = 30 deg, sigma_l = 60 deg -> 2*30 - 60 = 0!
    unstable_linac = LinacPhaseAdvance(
        section_id="SCL1_PERIOD_04",
        sigma_0t_deg=65.0,
        sigma_0l_deg=75.0,
        sigma_t_deg=30.0,
        sigma_l_deg=60.0,
        emit_norm_t_mm_mrad=0.35,
        emit_norm_l_deg_MeV=2.5
    )
    res_unst = engine.evaluate_stability(unstable_linac)
    assert res_unst.active_resonance == HofmannResonanceType.SECOND_ORDER_DIFFERENCE
    assert res_unst.stability_status == "UNSTABLE_EMITTANCE_EXCHANGE"
    assert res_unst.recommended_sigma_t_deg > res_unst.tune_depression_t * 65.0

    # 2. Stable operating point well separated from stopbands
    # sigma_t = 55 deg, sigma_l = 45 deg -> 2*55 - 45 = 65 deg away!
    stable_linac = LinacPhaseAdvance(
        section_id="SCL1_PERIOD_08",
        sigma_0t_deg=70.0,
        sigma_0l_deg=60.0,
        sigma_t_deg=55.0,
        sigma_l_deg=45.0,
        emit_norm_t_mm_mrad=0.30,
        emit_norm_l_deg_MeV=3.0
    )
    res_st = engine.evaluate_stability(stable_linac)
    assert res_st.active_resonance == HofmannResonanceType.NONE
    assert res_st.stability_status == "STABLE"


def test_zero_copy_cosimulation_bridge():
    """Verify in-memory zero-copy IPC co-simulation streaming and clock sync."""
    import numpy as np
    from helios.sim.cosim import ZeroCopyCoSimBridge

    bridge = ZeroCopyCoSimBridge(buffer_capacity=4)

    # Create dummy 6D bunch and loss density
    n_part = 1000
    particles = np.zeros((n_part, 6))
    particles[:, 0] = np.random.normal(0, 0.001, n_part)
    loss_density = np.array([0.0, 0.0, 1.2, 0.5, 0.0])

    pvs = {"MEBT:BPM01:X": 0.02, "SCL1:CAV01:Amp": 2.1}

    # Publish frames at 10 Hz
    h1 = bridge.publish_frame(rep_rate_Hz=10.0, particles_6d=particles, loss_density_W_m=loss_density, epics_pvs=pvs)
    assert h1.frame_id == 1
    assert h1.macroparticle_count == 1000
    assert h1.total_loss_power_W == 1.7
    assert h1.epics_pv_snapshot["MEBT:BPM01:X"] == 0.02

    # Consume latest frame
    consumed = bridge.consume_latest_frame()
    assert consumed is not None
    hdr, bunch_arr, loss_arr = consumed
    assert hdr.frame_id == 1
    assert bunch_arr.shape == (1000, 6)
    assert len(loss_arr) == 5

    # Test clock drift synchronization
    drift_ms = bridge.synchronize_clock(target_rep_rate_Hz=10.0, elapsed_real_time_s=0.1)
    assert abs(drift_ms) < 10.0  # 1 tick at 10 Hz in 0.1s -> 0 ms drift!


def test_radiological_activation_and_cooling_interlock():
    """Verify Bateman decay cooling curve, tunnel access interlock, and RPO clearance token."""
    from helios.safety.activation import RadiologicalActivationEngine

    engine = RadiologicalActivationEngine(personnel_access_threshold_uSv_hr=25.0)

    # 1. High-loss hot spot immediately after shutdown (0.5 hour cool-down) -> ACCESS DENIED
    res_hot = engine.evaluate_cooling(
        location_id="MEBT_COLLIMATOR_01",
        beam_loss_power_W=50.0,
        irradiation_hours=100.0,
        cooling_elapsed_hours=0.5
    )
    assert res_hot.prompt_dose_rate_uSv_hr > 500.0
    assert not res_hot.access_granted
    assert res_hot.required_additional_cooling_hours > 0.0
    assert res_hot.clearance_token_sha256 is None
    assert "Mn-56" in res_hot.dominant_isotopes

    # 2. Low-loss section or long cool-down (e.g. 1 W loss after 24 hours cooling) -> ACCESS GRANTED
    res_cool = engine.evaluate_cooling(
        location_id="SCL1_BEAMPIPE_02",
        beam_loss_power_W=1.0,
        irradiation_hours=100.0,
        cooling_elapsed_hours=24.0
    )
    assert res_cool.current_residual_dose_rate_uSv_hr < 25.0
    assert res_cool.access_granted
    assert res_cool.required_additional_cooling_hours == 0.0
    assert res_cool.clearance_token_sha256 is not None
    assert len(res_cool.clearance_token_sha256) == 64




