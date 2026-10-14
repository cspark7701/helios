"""HELIOS Multi-Species and Multi-Charge-State (MCS) Heavy Ion Dynamics.

Provides relativistic kinematics, magnetic rigidity (Brho) calculations,
and composite multi-charge state beam tracking for heavy ion linear accelerators.
"""

import math
from dataclasses import dataclass

import numpy as np

# Physical constants
AMU_MEV = 931.49410242  # Atomic mass unit in MeV/c^2
C_LIGHT = 299792458.0   # Speed of light in m/s


@dataclass
class IonSpecies:
    """Defines a specific heavy ion isotope and charge state."""
    name: str
    mass_amu: float
    atomic_number_z: int
    charge_state_q: int
    kinetic_energy_mev_u: float

    @property
    def total_energy_mev(self) -> float:
        """Total relativistic energy in MeV."""
        return (AMU_MEV + self.kinetic_energy_mev_u) * self.mass_amu

    @property
    def rest_energy_mev(self) -> float:
        """Rest mass energy in MeV."""
        return AMU_MEV * self.mass_amu

    @property
    def gamma(self) -> float:
        """Relativistic Lorentz factor gamma."""
        return 1.0 + (self.kinetic_energy_mev_u / AMU_MEV)

    @property
    def beta(self) -> float:
        """Relativistic velocity beta = v/c."""
        g = self.gamma
        return math.sqrt(max(0.0, 1.0 - (1.0 / (g * g))))

    @property
    def momentum_mev_c(self) -> float:
        """Relativistic momentum in MeV/c."""
        g = self.gamma
        b = self.beta
        return self.mass_amu * AMU_MEV * g * b

    @property
    def magnetic_rigidity_t_m(self) -> float:
        """Magnetic rigidity B*rho in Tesla-meters: B*rho = p / (q * e)."""
        if self.charge_state_q <= 0:
            return float("inf")
        # p [MeV/c] / (c * 1e-6) / q = (p * 1e6 eV/c) / (q * e * c) = 1e6 * p / (q * 299792458)
        # Standard conversion: B*rho [T*m] = (p [MeV/c]) / (299.792458 * q)
        return self.momentum_mev_c / (299.792458 * self.charge_state_q)


@dataclass
class MultiChargeComponent:
    """An individual charge state within a multi-charge-state beam distribution."""
    species: IonSpecies
    fractional_weight: float
    centroid_offset_x_mm: float = 0.0
    centroid_offset_y_mm: float = 0.0


class MultiChargeBeam:
    """Represents a composite beam consisting of multiple simultaneous charge states."""

    def __init__(
        self,
        name: str,
        total_current_ma: float,
        components: list[MultiChargeComponent],
    ):
        self.name = name
        self.total_current_ma = total_current_ma
        self.components = components
        self._normalize_weights()

    def _normalize_weights(self) -> None:
        """Ensure sum of fractional weights equals 1.0."""
        total_w = sum(c.fractional_weight for c in self.components)
        if total_w > 0:
            for c in self.components:
                c.fractional_weight /= total_w

    @property
    def reference_species(self) -> IonSpecies:
        """Return the dominant or first charge state as reference."""
        if not self.components:
            raise ValueError("MultiChargeBeam has no components")
        return max(self.components, key=lambda c: c.fractional_weight).species

    @property
    def mean_charge_state(self) -> float:
        """Average charge state weighted by beam current."""
        return sum(c.species.charge_state_q * c.fractional_weight for c in self.components)

    @property
    def effective_rigidity_t_m(self) -> float:
        """Current-weighted mean magnetic rigidity."""
        return sum(c.species.magnetic_rigidity_t_m * c.fractional_weight for c in self.components)

    def compute_composite_envelope(
        self,
        dispersion_x_m: float = 0.0,
        baseline_sigma_x_mm: float = 1.5,
        baseline_sigma_y_mm: float = 1.5,
    ) -> tuple[float, float, float, float]:
        """Calculate effective multi-charge centroid and envelope with rigidity dispersion.

        Returns:
            (composite_cx_mm, composite_cy_mm, composite_sigma_x_mm, composite_sigma_y_mm)
        """
        ref_brho = self.reference_species.magnetic_rigidity_t_m

        cxs = []
        cys = []
        weights = []

        for c in self.components:
            brho = c.species.magnetic_rigidity_t_m
            # Rigidity mismatch delta = (Brho - Brho_ref) / Brho_ref
            delta_brho = (brho - ref_brho) / ref_brho if ref_brho > 0 else 0.0
            # Dispersive orbit shift: dx = D_x * delta * 1000 [mm]
            dx_disp = dispersion_x_m * delta_brho * 1000.0

            cxs.append(c.centroid_offset_x_mm + dx_disp)
            cys.append(c.centroid_offset_y_mm)
            weights.append(c.fractional_weight)

        w = np.array(weights)
        cx_arr = np.array(cxs)
        cy_arr = np.array(cys)

        mean_cx = float(np.sum(w * cx_arr))
        mean_cy = float(np.sum(w * cy_arr))

        # Composite variance: sigma_eff^2 = sigma_0^2 + sum(w * (cx_i - mean_cx)^2)
        var_x = (baseline_sigma_x_mm ** 2) + float(np.sum(w * ((cx_arr - mean_cx) ** 2)))
        var_y = (baseline_sigma_y_mm ** 2) + float(np.sum(w * ((cy_arr - mean_cy) ** 2)))

        return mean_cx, mean_cy, math.sqrt(var_x), math.sqrt(var_y)


# --- Helper Beam Factories for Major Heavy Ion Species ---

def create_uranium_multicharge_beam(
    energy_mev_u: float = 0.5,
    total_current_ma: float = 2.0,
    charge_weights: dict[int, float] | None = None,
) -> MultiChargeBeam:
    """Factory for Uranium-238 multi-charge state beam (e.g. U33+/U34+)."""
    weights = charge_weights or {33: 0.5, 34: 0.5}
    components = []
    for q, w in weights.items():
        sp = IonSpecies(
            name=f"U238_{q}+",
            mass_amu=238.0508,
            atomic_number_z=92,
            charge_state_q=q,
            kinetic_energy_mev_u=energy_mev_u,
        )
        components.append(MultiChargeComponent(species=sp, fractional_weight=w))
    return MultiChargeBeam("238U_MCS", total_current_ma=total_current_ma, components=components)


def create_xenon_multicharge_beam(
    energy_mev_u: float = 0.5,
    total_current_ma: float = 5.0,
    charge_weights: dict[int, float] | None = None,
) -> MultiChargeBeam:
    """Factory for Xenon-124 / 136 multi-charge state beam."""
    weights = charge_weights or {25: 0.2, 26: 0.6, 27: 0.2}
    components = []
    for q, w in weights.items():
        sp = IonSpecies(
            name=f"Xe124_{q}+",
            mass_amu=123.9059,
            atomic_number_z=54,
            charge_state_q=q,
            kinetic_energy_mev_u=energy_mev_u,
        )
        components.append(MultiChargeComponent(species=sp, fractional_weight=w))
    return MultiChargeBeam("124Xe_MCS", total_current_ma=total_current_ma, components=components)


def create_argon_beam(
    energy_mev_u: float = 0.5,
    total_current_ma: float = 8.0,
    charge_state_q: int = 11,
) -> MultiChargeBeam:
    """Factory for Argon-40 single or dominant charge state beam."""
    sp = IonSpecies(
        name=f"Ar40_{charge_state_q}+",
        mass_amu=39.9624,
        atomic_number_z=18,
        charge_state_q=charge_state_q,
        kinetic_energy_mev_u=energy_mev_u,
    )
    return MultiChargeBeam(
        "40Ar",
        total_current_ma=total_current_ma,
        components=[MultiChargeComponent(species=sp, fractional_weight=1.0)],
    )


def create_proton_beam(
    energy_mev_u: float = 3.0,
    total_current_ma: float = 10.0,
) -> MultiChargeBeam:
    """Factory for high-current Proton beam (H+)."""
    sp = IonSpecies(
        name="Proton_1+",
        mass_amu=1.007276,
        atomic_number_z=1,
        charge_state_q=1,
        kinetic_energy_mev_u=energy_mev_u,
    )
    return MultiChargeBeam(
        "Proton",
        total_current_ma=total_current_ma,
        components=[MultiChargeComponent(species=sp, fractional_weight=1.0)],
    )
