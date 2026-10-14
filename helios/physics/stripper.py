"""HELIOS Stripper Foil and Charge Stripping Dynamics.

Models heavy ion charge state redistribution, mean energy loss (dE/dx),
multiple Coulomb scattering angular spread, and stripper foil lifetime degradation.
"""

import math
from dataclasses import dataclass

import numpy as np

from helios.physics.species import (
    C_LIGHT,
    IonSpecies,
    MultiChargeBeam,
    MultiChargeComponent,
)

BOHR_VELOCITY_M_S = 2.18769126364e6  # Bohr velocity v0 = e^2 / (4*pi*eps0*hbar)


@dataclass
class StripperFoil:
    """Stripper foil parameters and health state."""
    foil_id: str
    material: str = "Carbon"              # Carbon, LiquidLithium, or Gas
    thickness_ug_cm2: float = 300.0       # Area density in ug/cm^2
    density_g_cm3: float = 2.20           # Material volumetric density
    max_fluence_ions_cm2: float = 5.0e17  # Lifetime degradation threshold
    accumulated_fluence_ions_cm2: float = 0.0

    @property
    def thickness_um(self) -> float:
        """Physical thickness in micrometers."""
        # ug/cm^2 / (g/cm^3 * 1e6 ug/g) * 1e4 um/cm = ug/cm^2 / (density * 100)
        return self.thickness_ug_cm2 / (self.density_g_cm3 * 100.0)

    @property
    def degradation_pct(self) -> float:
        """Percentage of maximum operational lifetime consumed."""
        return min(100.0, (self.accumulated_fluence_ions_cm2 / self.max_fluence_ions_cm2) * 100.0)

    @property
    def needs_replacement(self) -> bool:
        """Whether degradation exceeds safe operational boundary (80%)."""
        return self.degradation_pct >= 80.0


@dataclass
class StrippingOutcome:
    """Physics results of passage through the charge stripper."""
    incoming_species: IonSpecies
    outgoing_beam: MultiChargeBeam
    mean_charge_state: float
    energy_loss_mev_u: float
    final_energy_mev_u: float
    rms_scattering_angle_mrad: float
    temperature_rise_k: float
    foil_degradation_pct: float
    replacement_warning: bool


class StripperPhysicsEngine:
    """Calculates charge distribution, energy loss, and foil heating."""

    def __init__(self, foil: StripperFoil | None = None):
        self.foil = foil or StripperFoil(foil_id="STRIPPER_01")

    def estimate_equilibrium_charge(self, incoming: IonSpecies) -> float:
        """Estimate mean equilibrium charge state after foil using Baron's empirical formula."""
        v = incoming.beta * C_LIGHT
        ratio = v / BOHR_VELOCITY_M_S
        z = incoming.atomic_number_z
        # Baron formula: Q_mean = Z * (1 - exp(-0.83 * (v/v0) / Z^0.45))
        q_mean = z * (1.0 - math.exp(-0.83 * ratio / (z ** 0.45)))
        return float(np.clip(q_mean, 1.0, float(z)))

    def calculate_energy_loss_mev_u(self, incoming: IonSpecies) -> float:
        """Calculate heavy ion energy loss dE/dx in thin carbon foil (Bethe-Bloch approximation)."""
        # Effective stopping power approximation: ~ 0.005 - 0.02 MeV/u per 100 ug/cm2
        thickness_factor = self.foil.thickness_ug_cm2 / 300.0
        z_eff = self.estimate_equilibrium_charge(incoming)
        b = max(0.01, incoming.beta)
        dE_mev_u = 0.015 * ((z_eff / 30.0) ** 2) * (0.05 / (b ** 2)) * thickness_factor
        return float(min(dE_mev_u, incoming.kinetic_energy_mev_u * 0.15))

    def calculate_scattering_angle_mrad(self, incoming: IonSpecies) -> float:
        """Multiple Coulomb scattering Highland formula approximation."""
        # theta_rms [mrad] ~ (13.6 MeV / (beta * p * c)) * z_ion * sqrt(x / X0)
        p_c = incoming.momentum_mev_c
        b = max(0.01, incoming.beta)
        # Radiation length for Carbon: X0 ~ 42.7 g/cm^2 = 4.27e7 ug/cm^2
        x_over_x0 = self.foil.thickness_ug_cm2 / 4.27e7
        theta_rad = (13.6 / (b * p_c)) * incoming.charge_state_q * math.sqrt(x_over_x0)
        return float(theta_rad * 1000.0)  # mrad

    def strip_beam(
        self,
        incoming: IonSpecies,
        beam_current_ma: float,
        exposure_hours: float = 0.0,
    ) -> StrippingOutcome:
        """Simulate beam passage through stripper foil."""
        q_mean = self.estimate_equilibrium_charge(incoming)
        dE = self.calculate_energy_loss_mev_u(incoming)
        final_energy = max(0.01, incoming.kinetic_energy_mev_u - dE)
        theta_mrad = self.calculate_scattering_angle_mrad(incoming)

        # Generate Gaussian charge state distribution around q_mean
        q_center = int(round(q_mean))
        spread = max(0.8, 0.05 * incoming.atomic_number_z)

        charge_states = [q_center - 1, q_center, q_center + 1]
        weights = []
        for q in charge_states:
            w = math.exp(-((q - q_mean) ** 2) / (2.0 * spread ** 2))
            weights.append(w)
        total_w = sum(weights)
        norm_weights = [w / total_w for w in weights]

        components = []
        for q, w in zip(charge_states, norm_weights):
            sp = IonSpecies(
                name=f"{incoming.name}_stripped_{q}+",
                mass_amu=incoming.mass_amu,
                atomic_number_z=incoming.atomic_number_z,
                charge_state_q=q,
                kinetic_energy_mev_u=final_energy,
            )
            components.append(MultiChargeComponent(species=sp, fractional_weight=w))

        out_beam = MultiChargeBeam(
            name=f"{incoming.name}_Stripped",
            total_current_ma=beam_current_ma,
            components=components,
        )

        # Update foil fluence and degradation
        # 1 mA = 6.24e15 ions/s / q_in
        ions_per_sec = (beam_current_ma * 1e-3 * 6.2415e18) / max(1, incoming.charge_state_q)
        added_fluence = (ions_per_sec * exposure_hours * 3600.0) / 0.5  # assuming 0.5 cm^2 spot
        self.foil.accumulated_fluence_ions_cm2 += added_fluence

        # Thermal heating estimate: delta_T = Power_deposited / (heat_capacity + cooling)
        power_w = beam_current_ma * 1e-3 * dE * 1e6 * incoming.mass_amu
        temp_rise_k = float(power_w * 45.0)  # K approximation for thin foil in vacuum

        return StrippingOutcome(
            incoming_species=incoming,
            outgoing_beam=out_beam,
            mean_charge_state=q_mean,
            energy_loss_mev_u=dE,
            final_energy_mev_u=final_energy,
            rms_scattering_angle_mrad=theta_mrad,
            temperature_rise_k=temp_rise_k,
            foil_degradation_pct=self.foil.degradation_pct,
            replacement_warning=self.foil.needs_replacement,
        )
