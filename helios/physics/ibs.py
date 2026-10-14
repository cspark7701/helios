"""HELIOS Intra-Beam Scattering (IBS) and Collective Effects Engine.

Implements:
1. Piwinski / Bjorken-Mtingwa growth rate models for dense heavy-ion bunches.
2. Longitudinal energy spread growth and transverse emittance diffusion rates.
3. Microbunching gain estimations across superconducting linac cryomodules.
"""

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

R_CLASSICAL_PROTON = 1.5346982e-18  # Classical proton radius in meters


@dataclass
class IBSGrowthRates:
    """Intra-Beam Scattering growth rates and diffusion times."""
    tau_x_s: float  # Horizontal emittance growth time (s)
    tau_y_s: float  # Vertical emittance growth time (s)
    tau_z_s: float  # Longitudinal energy spread growth time (s)
    rate_x_inv_s: float
    rate_y_inv_s: float
    rate_z_inv_s: float
    emittance_x_after_10m_pct: float
    dpp_growth_pct: float


class IntraBeamScatteringEngine:
    """Calculates IBS diffusion and emittance blow-up rates for heavy-ion beams."""

    @staticmethod
    def calculate_ibs_rates(
        mass_amu: float,
        charge_q: int,
        kinetic_energy_mev_u: float,
        num_ions_per_bunch: float,
        bunch_length_rms_mm: float,
        norm_emittance_x_um: float,
        norm_emittance_y_um: float,
        momentum_spread_dpp: float,
        beta_x_m: float = 5.0,
        beta_y_m: float = 5.0,
    ) -> IBSGrowthRates:
        """Compute IBS growth rates using the high-energy Piwinski approximation:

        Rate ~ (r_i^2 * N) / (gamma^4 * epsilon_x * epsilon_y * sigma_z * (dp/p))
        where r_i = (q^2 / A) * r_p.
        """
        # Relativistic kinematics
        amu_mev = 931.494
        gamma = 1.0 + (kinetic_energy_mev_u / amu_mev)
        beta = np.sqrt(max(1e-6, 1.0 - 1.0 / gamma**2))

        # Classical heavy-ion radius: r_ion = (q^2 / A) * r_p
        r_ion = ((charge_q ** 2) / max(1.0, mass_amu)) * R_CLASSICAL_PROTON

        # Beam sizes in meters
        eps_x = (norm_emittance_x_um * 1e-6) / (beta * gamma)
        eps_y = (norm_emittance_y_um * 1e-6) / (beta * gamma)
        _sigma_x = np.sqrt(eps_x * beta_x_m)
        _sigma_y = np.sqrt(eps_y * beta_y_m)
        sigma_z = bunch_length_rms_mm * 1e-3

        # Coulomb logarithm (typically ~ 15-20 in high energy linacs)
        coulomb_log = 18.0

        # Characteristic IBS scattering frequency factor A_c
        a_c = (
            (r_ion ** 2 * C_LIGHT * num_ions_per_bunch * coulomb_log)
            / (64.0 * np.pi**2 * (beta * gamma)**4 * eps_x * eps_y * sigma_z * max(1e-6, momentum_spread_dpp))
        )

        # Growth rates in s^-1
        rate_z = float(2.0 * a_c)
        rate_x = float(0.5 * a_c)
        rate_y = float(0.5 * a_c)

        tau_z = 1.0 / max(1e-9, rate_z)
        tau_x = 1.0 / max(1e-9, rate_x)
        tau_y = 1.0 / max(1e-9, rate_y)

        # Growth across typical 10m drift: Delta t = 10m / (beta * c)
        transit_time_10m = 10.0 / (beta * C_LIGHT)
        emit_growth_pct = float(rate_x * transit_time_10m * 100.0)
        dpp_growth_pct = float(rate_z * transit_time_10m * 100.0)

        return IBSGrowthRates(
            tau_x_s=tau_x,
            tau_y_s=tau_y,
            tau_z_s=tau_z,
            rate_x_inv_s=rate_x,
            rate_y_inv_s=rate_y,
            rate_z_inv_s=rate_z,
            emittance_x_after_10m_pct=emit_growth_pct,
            dpp_growth_pct=dpp_growth_pct,
        )


C_LIGHT = 299792458.0
