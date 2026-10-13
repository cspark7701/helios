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

