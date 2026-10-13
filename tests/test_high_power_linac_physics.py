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
