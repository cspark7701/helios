"""HELIOS Phase 45: High-Power Target & Beam Dump Thermo-Mechanical Stress Simulation.

Simulates heavy-ion Bragg peak energy deposition profiles, instantaneous thermo-elastic
hydrodynamic shock pressures via the Grüneisen equation of state, von Mises thermal stress,
and critical heat flux (CHF) cooling water boiling margins up to 400 kW beam power.
"""

from typing import Dict, List, Any, Optional
from enum import Enum
import math
import numpy as np
from pydantic import BaseModel, Field


class TargetMaterial(str, Enum):
    GRAPHITE = "graphite"
    COPPER_OFHC = "copper_ofhc"
    TUNGSTEN = "tungsten"
    GLIDCOP = "glidcop"


class BeamDumpParameters(BaseModel):
    """Geometry and cooling conditions for high-power beam dump / target."""
    material: TargetMaterial = TargetMaterial.GLIDCOP
    beam_power_kW: float = Field(..., ge=0.1, le=500.0, description="Incident continuous or macro-pulse beam power in kW")
    beam_energy_MeV_u: float = Field(..., ge=1.0, description="Beam kinetic energy per nucleon in MeV/u")
    ion_mass_amu: float = Field(default=238.0, description="Ion species mass in amu")
    beam_spot_radius_mm: float = Field(default=5.0, ge=0.5, description="Transverse beam RMS radius at target face in mm")
    grazing_angle_deg: float = Field(default=3.5, ge=0.5, le=90.0, description="Cone/slant grazing incidence angle in degrees")
    cooling_water_flow_m_s: float = Field(default=6.0, ge=1.0, description="Cooling channel flow velocity in m/s")
    water_pressure_bar: float = Field(default=5.0, description="Cooling water supply pressure in bar")


class BeamDumpStressResult(BaseModel):
    """Calculated thermo-mechanical and hydrodynamic shock response."""
    material: TargetMaterial
    bragg_peak_depth_mm: float
    peak_energy_density_J_per_g: float
    hydrodynamic_shock_pressure_MPa: float
    peak_temperature_rise_C: float
    von_mises_thermal_stress_MPa: float
    yield_strength_MPa: float
    stress_safety_factor: float
    surface_heat_flux_MW_per_m2: float
    critical_heat_flux_MW_per_m2: float
    chf_margin: float
    abort_interlock_tripped: bool
    status: str  # NOMINAL, CONSTRAINED, ABORT_REQUIRED


class BeamDumpThermalEngine:
    """Calculates heavy-ion energy deposition, thermal shocks, and cooling limits."""

    MATERIAL_PROPS = {
        TargetMaterial.GRAPHITE: {
            "density_g_cm3": 1.85,
            "specific_heat_J_g_K": 0.71,
            "thermal_conductivity_W_m_K": 120.0,
            "thermal_expansion_1_K": 4.5e-6,
            "youngs_modulus_GPa": 10.0,
            "poissons_ratio": 0.20,
            "yield_strength_MPa": 45.0,
            "gruneisen_param": 0.45,
        },
        TargetMaterial.COPPER_OFHC: {
            "density_g_cm3": 8.96,
            "specific_heat_J_g_K": 0.385,
            "thermal_conductivity_W_m_K": 390.0,
            "thermal_expansion_1_K": 16.5e-6,
            "youngs_modulus_GPa": 115.0,
            "poissons_ratio": 0.34,
            "yield_strength_MPa": 70.0,
            "gruneisen_param": 2.0,
        },
        TargetMaterial.TUNGSTEN: {
            "density_g_cm3": 19.3,
            "specific_heat_J_g_K": 0.134,
            "thermal_conductivity_W_m_K": 170.0,
            "thermal_expansion_1_K": 4.5e-6,
            "youngs_modulus_GPa": 400.0,
            "poissons_ratio": 0.28,
            "yield_strength_MPa": 550.0,
            "gruneisen_param": 1.6,
        },
        TargetMaterial.GLIDCOP: {
            "density_g_cm3": 8.90,
            "specific_heat_J_g_K": 0.390,
            "thermal_conductivity_W_m_K": 365.0,
            "thermal_expansion_1_K": 16.6e-6,
            "youngs_modulus_GPa": 130.0,
            "poissons_ratio": 0.33,
            "yield_strength_MPa": 320.0,
            "gruneisen_param": 1.95,
        },
    }

    def evaluate_beam_dump(self, params: BeamDumpParameters) -> BeamDumpStressResult:
        """Evaluate thermo-mechanical shock and cooling margins."""
        props = self.MATERIAL_PROPS[params.material]
        rho = props["density_g_cm3"]

        # Approximate Bragg peak penetration depth: R (g/cm^2) ~ A * (E/A)^1.75 / (Z^2 ...)
        range_g_cm2 = 0.08 * math.pow(params.beam_energy_MeV_u / 10.0, 1.7)
        depth_mm = (range_g_cm2 / rho) * 10.0

        # Incident beam spot area: A = pi * r^2
        r_cm = params.beam_spot_radius_mm * 0.1
        spot_area_cm2 = math.pi * (r_cm ** 2)
        # Grazing angle geometric area expansion
        sin_grazing = math.sin(math.radians(max(0.5, params.grazing_angle_deg)))
        effective_surface_area_cm2 = spot_area_cm2 / sin_grazing
        effective_surface_area_m2 = effective_surface_area_cm2 * 1e-4

        # Deposition volume around Bragg peak
        peak_volume_cm3 = effective_surface_area_cm2 * (depth_mm * 0.1 * 0.5)
        peak_mass_g = rho * max(1e-4, peak_volume_cm3)

        # Beam power in W
        p_beam_W = params.beam_power_kW * 1e3

        # Surface heat flux: q'' = P_beam / effective_surface_area_m2 (MW/m^2)
        heat_flux_MW_m2 = (p_beam_W * 1e-6) / max(1e-6, effective_surface_area_m2)

        # Steady-state conduction temperature drop across 2 mm wall to cooling water
        wall_thickness_m = 0.002
        k_th = props["thermal_conductivity_W_m_K"]
        delta_T_conduction = (heat_flux_MW_m2 * 1e6 * wall_thickness_m) / k_th

        # Pulse shock contribution (assuming 1 ms macro-pulse front)
        dt_pulse = 0.001
        e_pulse_J = p_beam_W * dt_pulse * 0.5
        e_density_J_g = e_pulse_J / max(1e-3, peak_mass_g)
        p_shock_MPa = props["gruneisen_param"] * rho * e_density_J_g * 0.001

        delta_T = delta_T_conduction + (e_density_J_g / props["specific_heat_J_g_K"])

        # Von Mises thermal stress: sigma = (E * alpha * dT) / (1 - nu)
        E_Pa = props["youngs_modulus_GPa"] * 1e9
        alpha = props["thermal_expansion_1_K"]
        nu = props["poissons_ratio"]
        sigma_th_Pa = (E_Pa * alpha * delta_T) / (1.0 - nu)
        sigma_th_MPa = sigma_th_Pa * 1e-6

        yield_MPa = props["yield_strength_MPa"]
        safety_factor = yield_MPa / max(1e-3, sigma_th_MPa)

        # Critical Heat Flux (CHF) via modified Tong correlation for subcooled water:
        chf_MW_m2 = (1.0 + 0.18 * params.cooling_water_flow_m_s) * math.sqrt(params.water_pressure_bar) * 3.2
        chf_margin = chf_MW_m2 / max(1e-3, heat_flux_MW_m2)

        # Abort interlock triggered if safety factor < 1.0 or chf_margin < 1.20
        trip = (safety_factor < 1.0) or (chf_margin < 1.20)
        if trip:
            status = "ABORT_REQUIRED"
        elif safety_factor < 1.4 or chf_margin < 1.5:
            status = "CONSTRAINED"
        else:
            status = "NOMINAL"

        return BeamDumpStressResult(
            material=params.material,
            bragg_peak_depth_mm=round(float(depth_mm), 3),
            peak_energy_density_J_per_g=round(float(e_density_J_g), 2),
            hydrodynamic_shock_pressure_MPa=round(float(p_shock_MPa), 3),
            peak_temperature_rise_C=round(float(delta_T), 2),
            von_mises_thermal_stress_MPa=round(float(sigma_th_MPa), 2),
            yield_strength_MPa=round(float(yield_MPa), 1),
            stress_safety_factor=round(float(safety_factor), 3),
            surface_heat_flux_MW_per_m2=round(float(heat_flux_MW_m2), 3),
            critical_heat_flux_MW_per_m2=round(float(chf_MW_m2), 3),
            chf_margin=round(float(chf_margin), 3),
            abort_interlock_tripped=trip,
            status=status
        )
