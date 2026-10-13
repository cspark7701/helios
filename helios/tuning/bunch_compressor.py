"""HELIOS Phase 52: Magnetic Bunch Compressor Chicane & Longitudinal Chirp Tuning.

Models 4-dipole symmetric magnetic bunch compressor chicanes (R_56, T_566) and optimizes
upstream RF cavity energy-chirp phase/voltage to compress heavy-ion bunch length and
enhance peak current before target or stripper delivery without non-linear filamentation.
"""

from typing import Dict, List, Any, Optional, Tuple
import math
import numpy as np
from pydantic import BaseModel, Field


class ChicaneParameters(BaseModel):
    """4-dipole C-type magnetic bunch compressor chicane configuration."""
    dipole_bend_angle_deg: float = Field(default=8.5, ge=1.0, le=30.0, description="Dipole bending angle in degrees")
    dipole_length_m: float = Field(default=0.45, ge=0.1, description="Magnetic dipole length in meters")
    drift_12_m: float = Field(default=1.2, ge=0.2, description="Drift distance between dipole 1 and 2 in meters")
    drift_23_m: float = Field(default=0.8, ge=0.1, description="Drift distance between dipole 2 and 3 in meters")
    rf_chirp_voltage_MV: float = Field(default=2.5, ge=0.1, description="Upstream RF cavity chirp voltage in MV")
    rf_chirp_phase_deg: float = Field(default=-90.0, description="RF chirp cavity synchronous phase in degrees")
    rf_frequency_MHz: float = Field(default=162.5, description="Chirp RF cavity frequency in MHz")


class ChicaneOpticsResult(BaseModel):
    """Longitudinal dispersion and bunch compression performance."""
    R56_mm: float
    T566_mm: float
    chirp_slope_h_per_m: float
    initial_bunch_length_ps: float
    compressed_bunch_length_ps: float
    compression_factor: float
    peak_current_enhancement: float
    final_rms_energy_spread_percent: float
    longitudinal_dispersion_status: str  # OPTIMAL_COMPRESSION, UNDER_COMPRESSED, OVER_COMPRESSED


class BunchCompressorChicaneOptimizer:
    """Calculates chicane transfer matrix terms and optimizes chirp parameters."""

    def evaluate_chicane(
        self,
        params: ChicaneParameters,
        beam_energy_MeV_u: float = 17.5,
        initial_bunch_length_ps: float = 85.0,
        initial_energy_spread_percent: float = 0.25
    ) -> ChicaneOpticsResult:
        """Calculate R56, T566, and bunch compression factor."""
        theta_rad = math.radians(params.dipole_bend_angle_deg)
        Lb = params.dipole_length_m
        Ld = params.drift_12_m

        # Standard 4-dipole symmetric chicane longitudinal dispersion:
        # R56 = -2 * theta^2 * (Ld + (2/3) * Lb)
        r56_m = -2.0 * (theta_rad ** 2) * (Ld + (2.0 / 3.0) * Lb)
        r56_mm = r56_m * 1e3
        # Second-order term T566 ~ -3/2 * R56
        t566_mm = -1.5 * r56_mm

        # RF chirp slope h = d(delta) / dz = -(2 * pi * f / (beta * c)) * (q * V / E0) * sin(phi)
        c = 299792458.0
        beta = math.sqrt(2.0 * beam_energy_MeV_u / 931.494)
        k_rf = (2.0 * math.pi * (params.rf_frequency_MHz * 1e6)) / (beta * c)

        e_total_MeV_u = beam_energy_MeV_u + 931.494
        # Relativistic fractional momentum deviation delta = (1 / beta^2) * (dE / E_tot)
        chirp_amp = params.rf_chirp_voltage_MV / (max(1e-4, beta ** 2) * e_total_MeV_u)
        h_per_m = -k_rf * chirp_amp * math.sin(math.radians(params.rf_chirp_phase_deg))

        # Compression ratio: z_f = z_i * (1 + h * R56) + T566 * delta^2
        # For full compression: 1 + h * R56 = 0
        comp_transfer = abs(1.0 + h_per_m * r56_m)
        comp_factor = 1.0 / max(0.05, comp_transfer)

        # Compressed bunch length in ps
        final_bunch_ps = initial_bunch_length_ps / comp_factor
        # Energy spread after chirp: delta_f ~ sqrt(delta_0^2 + (h * sigma_z)^2)
        sigma_z_m = (initial_bunch_length_ps * 1e-12) * beta * c
        chirp_spread = abs(h_per_m * sigma_z_m) * 100.0
        final_spread_pct = math.sqrt(initial_energy_spread_percent ** 2 + chirp_spread ** 2)

        peak_current_boost = comp_factor

        if abs(comp_transfer) < 0.25:
            status = "OPTIMAL_COMPRESSION"
        elif (1.0 + h_per_m * r56_m) > 0.25:
            status = "UNDER_COMPRESSED"
        else:
            status = "OVER_COMPRESSED"

        return ChicaneOpticsResult(
            R56_mm=round(float(r56_mm), 3),
            T566_mm=round(float(t566_mm), 3),
            chirp_slope_h_per_m=round(float(h_per_m), 4),
            initial_bunch_length_ps=round(initial_bunch_length_ps, 2),
            compressed_bunch_length_ps=round(float(final_bunch_ps), 2),
            compression_factor=round(float(comp_factor), 2),
            peak_current_enhancement=round(float(peak_current_boost), 2),
            final_rms_energy_spread_percent=round(float(final_spread_pct), 3),
            longitudinal_dispersion_status=status
        )

    def optimize_chirp_voltage(
        self,
        params: ChicaneParameters,
        target_compression_factor: float = 4.0,
        beam_energy_MeV_u: float = 17.5
    ) -> float:
        """Find optimal RF chirp voltage to achieve target bunch compression factor."""
        best_v = params.rf_chirp_voltage_MV
        best_err = float("inf")

        for v_cand in np.linspace(0.5, 8.0, 50):
            p = params.model_copy()
            p.rf_chirp_voltage_MV = float(v_cand)
            res = self.evaluate_chicane(p, beam_energy_MeV_u=beam_energy_MeV_u)
            err = abs(res.compression_factor - target_compression_factor)
            if err < best_err:
                best_err = err
                best_v = float(v_cand)

        return round(best_v, 2)
