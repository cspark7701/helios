"""HELIOS Phase 41: Advanced Liquid Metal & Windowless Gas Jet Stripper Systems.

Models high-power liquid metal (Liquid Lithium film) and recirculating windowless gas jet
strippers for high-intensity heavy-ion linacs (FRIB/RAON/RIKEN class). Evaluates hydrodynamic
film stability, thermal vaporization under multi-kW beam deposition, equilibrium charge
distributions, and non-linear energy loss.
"""

import math
from enum import Enum

from pydantic import BaseModel, Field


class StripperMedium(str, Enum):
    LIQUID_LITHIUM_FILM = "liquid_lithium_film"
    WINDOWLESS_HELIUM_GAS = "windowless_helium_gas"
    LIQUID_BISMUTH_JET = "liquid_bismuth_jet"


class LiquidStripperParameters(BaseModel):
    """Engineering and operational parameters for heavy-ion stripper targets."""
    medium: StripperMedium = StripperMedium.LIQUID_LITHIUM_FILM
    film_thickness_um: float = Field(default=15.0, ge=1.0, le=100.0, description="Stripper film thickness in microns")
    film_speed_m_s: float = Field(default=35.0, ge=5.0, le=100.0, description="Flow velocity in m/s")
    operating_temperature_C: float = Field(default=220.0, description="Target bulk temperature in C")
    beam_power_deposited_kW: float = Field(default=1.2, ge=0.0, description="Power deposited by heavy-ion beam in kW")
    beam_spot_width_mm: float = Field(default=4.0, description="FWHM beam transverse width in mm")


class StripperPhysicsResult(BaseModel):
    """Calculated hydrodynamic and beam-interaction properties."""
    medium: StripperMedium
    areal_density_mg_cm2: float
    equilibrium_mean_charge_q: float
    selected_charge_state: int
    selected_state_fraction: float
    charge_state_distribution: dict[int, float]
    energy_loss_MeV_per_u: float
    rms_energy_straggling_keV_per_u: float
    film_temperature_rise_C: float
    weber_number: float
    hydrodynamic_status: str  # STABLE, MARGINAL, SPRAYING
    vaporization_rate_g_per_hr: float


class LiquidStripperEngine:
    """Simulates hydrodynamic film stability and heavy-ion atomic charge exchange."""

    # Material properties at operating point
    MATERIAL_PROPS = {
        StripperMedium.LIQUID_LITHIUM_FILM: {
            "density_g_cm3": 0.512,
            "specific_heat_J_g_K": 4.18,
            "surface_tension_N_m": 0.385,
            "Z_target": 3,
            "A_target": 6.94,
        },
        StripperMedium.WINDOWLESS_HELIUM_GAS: {
            "density_g_cm3": 0.178e-3,
            "specific_heat_J_g_K": 5.19,
            "surface_tension_N_m": 0.0,
            "Z_target": 2,
            "A_target": 4.00,
        },
        StripperMedium.LIQUID_BISMUTH_JET: {
            "density_g_cm3": 10.05,
            "specific_heat_J_g_K": 0.15,
            "surface_tension_N_m": 0.375,
            "Z_target": 83,
            "A_target": 208.98,
        },
    }

    def evaluate_stripper(
        self,
        params: LiquidStripperParameters,
        ion_species: str = "U238",
        ion_mass_amu: float = 238.0,
        ion_initial_q: int = 33,
        beam_energy_MeV_u: float = 17.5,
    ) -> StripperPhysicsResult:
        """Evaluate thermodynamic heating, hydrodynamics, and charge state distribution."""
        props = self.MATERIAL_PROPS[params.medium]
        density_g_cm3 = props["density_g_cm3"]

        # Areal density = rho * thickness (in mg/cm^2)
        # thickness in um = 1e-4 cm
        areal_mg_cm2 = density_g_cm3 * (params.film_thickness_um * 1e-4) * 1e3

        # Hydrodynamic Weber number We = rho * v^2 * t / sigma
        if props["surface_tension_N_m"] > 0:
            rho_kg_m3 = density_g_cm3 * 1e3
            t_m = params.film_thickness_um * 1e-6
            weber = (rho_kg_m3 * (params.film_speed_m_s ** 2) * t_m) / props["surface_tension_N_m"]
        else:
            weber = 0.0

        if weber < 1500.0:
            hydro_status = "STABLE"
        elif weber < 3500.0:
            hydro_status = "MARGINAL"
        else:
            hydro_status = "SPRAYING"

        # Thermal heating across moving film
        # Mass flow passing beam spot: dm/dt = rho * v * width * thickness
        width_m = params.beam_spot_width_mm * 1e-3
        t_m = params.film_thickness_um * 1e-6
        rho_kg_m3 = density_g_cm3 * 1e3
        mass_flow_kg_s = rho_kg_m3 * params.film_speed_m_s * width_m * t_m
        mass_flow_g_s = mass_flow_kg_s * 1e3

        c_p = props["specific_heat_J_g_K"]
        heat_power_W = params.beam_power_deposited_kW * 1e3

        if mass_flow_g_s > 1e-6:
            delta_T = heat_power_W / (mass_flow_g_s * c_p)
        else:
            delta_T = 50.0

        # Evaporative loss rate via Langmuir formula: G ~ P_vap * sqrt(M / 2*pi*R*T)
        peak_temp_K = (params.operating_temperature_C + delta_T) + 273.15
        # Li vapor pressure approx: log10(P_Torr) = 8.0 - 8100 / T
        if params.medium == StripperMedium.LIQUID_LITHIUM_FILM:
            p_torr = 10.0 ** (8.0 - 8100.0 / max(300.0, peak_temp_K))
            vap_rate_g_hr = round(p_torr * 0.045 * 3600.0, 4)
        else:
            vap_rate_g_hr = 0.01

        # Baron / Schiwietz equilibrium mean charge state for heavy ions in low-Z stripper
        # q_bar / Z ~ [1 + (v / (v' * Z^alpha))^(-1/k)]^(-k)
        # In lithium/carbon at ~17.5 MeV/u, Uranium strips to ~ 78+ - 86+ (e.g. U78+, U86+)
        z_ion = 92.0 if ion_species == "U238" else 54.0
        beta = math.sqrt(2.0 * beam_energy_MeV_u / 931.494)
        v_over_v0 = beta * 137.036  # relative to Bohr velocity v0 = c / 137
        
        # Low-Z gas/liquid stripper formula
        q_bar = z_ion * (1.0 - math.exp(-0.88 * math.pow(v_over_v0 / math.pow(z_ion, 0.45), 1.05)))
        q_bar_rounded = round(q_bar, 2)
        q_peak = int(round(q_bar))

        # Charge distribution around q_peak (Gaussian width ~ 1.8)
        sigma_q = 1.85
        csd: dict[int, float] = {}
        for q in range(q_peak - 5, q_peak + 6):
            prob = math.exp(-0.5 * ((q - q_peak) / sigma_q) ** 2) / (sigma_q * math.sqrt(2 * math.pi))
            csd[q] = round(float(prob), 4)

        # Normalize csd
        total_p = sum(csd.values())
        csd = {q: round(p / total_p, 4) for q, p in csd.items()}
        selected_frac = csd.get(q_peak, 0.0)

        # Energy loss dE/dx (Bethe-Bloch approx for heavy ion in mg/cm^2)
        # dE/dx ~ 0.15 - 0.45 MeV/u per mg/cm^2 in Li at 17.5 MeV/u
        stopping_power_mev_per_mg_cm2 = 0.28 * (props["Z_target"] / props["A_target"]) * (q_peak / z_ion) ** 2
        dE = stopping_power_mev_per_mg_cm2 * areal_mg_cm2

        # Straggling energy spread (Bohr straggling)
        straggling_keV_u = 12.0 * math.sqrt(areal_mg_cm2)

        return StripperPhysicsResult(
            medium=params.medium,
            areal_density_mg_cm2=round(float(areal_mg_cm2), 4),
            equilibrium_mean_charge_q=round(float(q_bar_rounded), 2),
            selected_charge_state=q_peak,
            selected_state_fraction=round(float(selected_frac), 4),
            charge_state_distribution=csd,
            energy_loss_MeV_per_u=round(float(dE), 4),
            rms_energy_straggling_keV_per_u=round(float(straggling_keV_u), 3),
            film_temperature_rise_C=round(float(delta_T), 2),
            weber_number=round(float(weber), 1),
            hydrodynamic_status=hydro_status,
            vaporization_rate_g_per_hr=vap_rate_g_hr
        )
