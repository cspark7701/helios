"""HELIOS Phase 53: UHV Pressure Profiles & Heavy-Ion Residual Gas Stripping Losses.

Simulates 1D Ultra-High Vacuum (UHV) pressure distributions along warm and superconducting
cold-bore linac sections, models heavy-ion atomic charge exchange cross-sections
(stripping and electron capture), and evaluates ion-induced desorption vacuum runaway margins.
"""

from typing import Dict, List, Any, Optional, Tuple
import math
import numpy as np
from pydantic import BaseModel, Field


class VacuumSegment(BaseModel):
    """Section of beamline vacuum chamber with pumps and outgassing properties."""
    section_name: str
    length_m: float
    tube_diameter_mm: float
    is_cryogenic: bool = False
    ion_pump_speed_l_per_s: float = 120.0
    outgassing_rate_mbar_l_s_cm2: float = 1.0e-11
    temperature_K: float = 293.15


class VacuumLossResult(BaseModel):
    """Calculated pressure profile and heavy-ion transmission loss."""
    section_name: str
    mean_pressure_mbar: float
    peak_pressure_mbar: float
    gas_number_density_per_m3: float
    total_loss_cross_section_cm2: float
    fractional_beam_loss_percent: float
    lost_beam_power_W: float
    ion_desorption_yield_molecules_per_ion: float
    vacuum_runaway_safety_margin: float
    vacuum_status: str  # EXCELLENT_UHV, ACCEPTABLE, RUNAWAY_RISK


class LinacVacuumPhysicsEngine:
    """Calculates molecular gas conductance, UHV pressure profiles, and beam-gas stripping."""

    # Atomic cross-section parameters (scaling for heavy ions in H2 / N2 residual gas)
    # sigma ~ Z_target^0.67 * (q_ion / beta)^1.5 * 1e-18 cm^2
    K_B = 1.380649e-23  # J/K

    def evaluate_segment_vacuum(
        self,
        segment: VacuumSegment,
        ion_species: str = "U238",
        ion_charge: int = 33,
        beam_energy_MeV_u: float = 17.5,
        beam_current_uA: float = 500.0,
        beam_power_kW: float = 25.0
    ) -> VacuumLossResult:
        """Calculate UHV pressure distribution, cross sections, and transmission loss."""
        d_cm = segment.tube_diameter_mm * 0.1
        L_cm = segment.length_m * 100.0
        surf_area_cm2 = math.pi * d_cm * L_cm

        # Molecular conductance of circular pipe for N2/CO: C ~ 12.1 * d^3 / L (l/s)
        conductance_l_s = (12.1 * (d_cm ** 3)) / max(1.0, L_cm)

        # Cryogenic cold-bore condensation pumping effect (condensation of H2O, CO, N2 on 2K/4K walls)
        s_cryo = 2500.0 if segment.is_cryogenic else 0.0
        total_pumping_l_s = segment.ion_pump_speed_l_per_s + s_cryo

        # Gas load Q = q_out * Area (mbar * l / s)
        q_gas = segment.outgassing_rate_mbar_l_s_cm2 * surf_area_cm2
        if segment.is_cryogenic:
            q_gas *= 0.05  # Cryogenic freezing drastically reduces outgassing

        # Average pressure P ~ Q / S + Q / (12 * C)
        p_base = q_gas / max(1.0, total_pumping_l_s)
        p_gradient = q_gas / max(1.0, 12.0 * conductance_l_s)
        mean_p_mbar = p_base + 0.5 * p_gradient
        peak_p_mbar = p_base + p_gradient

        # Gas number density: n = P (Pa) / (k_B * T)
        p_Pa = mean_p_mbar * 100.0
        n_gas_m3 = p_Pa / (self.K_B * segment.temperature_K)
        n_gas_cm3 = n_gas_m3 * 1e-6

        # Heavy-ion charge exchange stripping & capture cross section:
        # In low-energy / medium-energy linacs: sigma_loss ~ 4e-17 cm^2 for U33+ in residual gas
        beta = math.sqrt(2.0 * beam_energy_MeV_u / 931.494)
        sigma_loss_cm2 = 3.5e-17 * math.pow(ion_charge / 33.0, 1.2) * math.pow(0.19 / max(0.05, beta), 1.5)

        # Fractional beam loss over segment length L: dN/N ~ n_gas * sigma * L
        frac_loss = n_gas_cm3 * sigma_loss_cm2 * L_cm
        frac_loss = max(0.0, min(1.0, frac_loss))
        frac_loss_pct = frac_loss * 100.0

        # Lost beam power
        p_lost_W = (beam_power_kW * 1e3) * frac_loss

        # Ion-induced desorption yield eta (molecules released per lost ion hitting wall)
        # Heavy ions deposit high electronic dE/dx on chamber wall, desorbing 1000 - 10000 molecules/ion
        eta_des = 2500.0 * (beam_energy_MeV_u / 10.0)

        # Vacuum runaway condition: eta * (dN/dt) compared to effective pumping speed S_eff
        # If gas desorbed per second exceeds pumping speed, pressure runs away!
        ions_lost_per_s = (beam_current_uA * 1e-6 / (ion_charge * 1.602e-19)) * frac_loss
        gas_inflow_mbar_l_s = (ions_lost_per_s * eta_des * self.K_B * segment.temperature_K * 10.0)

        runaway_margin = total_pumping_l_s / max(1e-6, gas_inflow_mbar_l_s / max(1e-12, mean_p_mbar))

        if runaway_margin < 1.5:
            status = "RUNAWAY_RISK"
        elif mean_p_mbar < 1.0e-8:
            status = "EXCELLENT_UHV"
        else:
            status = "ACCEPTABLE"

        return VacuumLossResult(
            section_name=segment.section_name,
            mean_pressure_mbar=float(f"{mean_p_mbar:.2e}"),
            peak_pressure_mbar=float(f"{peak_p_mbar:.2e}"),
            gas_number_density_per_m3=float(f"{n_gas_m3:.2e}"),
            total_loss_cross_section_cm2=float(f"{sigma_loss_cm2:.2e}"),
            fractional_beam_loss_percent=round(float(frac_loss_pct), 4),
            lost_beam_power_W=round(float(p_lost_W), 3),
            ion_desorption_yield_molecules_per_ion=round(float(eta_des), 1),
            vacuum_runaway_safety_margin=round(float(runaway_margin), 2),
            vacuum_status=status
        )
