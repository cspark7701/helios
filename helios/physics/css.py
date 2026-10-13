"""HELIOS Charge State Separator (CSS) and Achromatic Selector.

Models magnetic dispersion chicanes, charge state spatial separation,
and autonomous slit tuning for charge purity optimization and loss prevention.
"""

from dataclasses import dataclass
import logging
import math
from typing import Dict, List, Optional, Tuple
import numpy as np

from helios.physics.species import MultiChargeBeam, MultiChargeComponent

logger = logging.getLogger(__name__)


@dataclass
class CSSTransmissionReport:
    """Outcome of beam transmission through charge separator slits."""
    selected_charge_state: int
    target_transmission_pct: float
    total_transmitted_current_ma: float
    charge_purity_pct: float
    component_transmissions: Dict[int, float]
    slit_gap_mm: float
    slit_center_mm: float
    dipole_field_t: float


class ChargeStateSeparator:
    """Achromatic magnetic chicane with adjustable momentum/rigidity selection slits."""

    def __init__(
        self,
        dispersion_x_m: float = 1.25,        # Horizontal dispersion at slit plane (m)
        bend_radius_m: float = 1.80,         # Dipole bending radius (m)
        nominal_dipole_field_t: float = 1.15,
        default_slit_gap_mm: float = 8.0,
    ):
        self.dispersion_x_m = dispersion_x_m
        self.bend_radius_m = bend_radius_m
        self.dipole_field_t = nominal_dipole_field_t
        self.slit_gap_mm = default_slit_gap_mm
        self.slit_center_mm = 0.0

    def calculate_charge_positions_mm(self, beam: MultiChargeBeam) -> Dict[int, float]:
        """Compute horizontal coordinate x (mm) of each charge state at slit plane."""
        ref_brho = beam.reference_species.magnetic_rigidity_t_m
        positions: Dict[int, float] = {}

        for comp in beam.components:
            q = comp.species.charge_state_q
            brho = comp.species.magnetic_rigidity_t_m
            # delta = (Brho - Brho_ref) / Brho_ref
            delta_brho = (brho - ref_brho) / ref_brho if ref_brho > 0 else 0.0
            # x [mm] = D_x * delta * 1000
            x_mm = self.dispersion_x_m * delta_brho * 1000.0
            positions[q] = float(x_mm)

        return positions

    def evaluate_transmission(
        self,
        beam: MultiChargeBeam,
        slit_center_mm: Optional[float] = None,
        slit_gap_mm: Optional[float] = None,
        target_charge_q: Optional[int] = None,
    ) -> CSSTransmissionReport:
        """Evaluate charge selection transmission and purity."""
        gap = slit_gap_mm if slit_gap_mm is not None else self.slit_gap_mm
        center = slit_center_mm if slit_center_mm is not None else self.slit_center_mm
        target_q = target_charge_q or beam.reference_species.charge_state_q

        x_min = center - (gap / 2.0)
        x_max = center + (gap / 2.0)

        positions = self.calculate_charge_positions_mm(beam)

        transmitted_currents = {}
        component_trans = {}

        for comp in beam.components:
            q = comp.species.charge_state_q
            x_pos = positions.get(q, 0.0)
            sig_x = 1.2  # mm RMS beam size at slit plane

            # Fraction passing slit bounds [x_min, x_max] for normal distribution N(x_pos, sig_x)
            from scipy.special import erf
            f_pass = 0.5 * (erf((x_max - x_pos) / (math.sqrt(2) * sig_x)) - erf((x_min - x_pos) / (math.sqrt(2) * sig_x)))
            f_pass = max(0.0, min(1.0, float(f_pass)))

            component_trans[q] = f_pass * 100.0
            transmitted_currents[q] = f_pass * comp.fractional_weight * beam.total_current_ma

        total_trans_current = sum(transmitted_currents.values())
        target_trans_current = transmitted_currents.get(target_q, 0.0)

        purity = (target_trans_current / total_trans_current * 100.0) if total_trans_current > 0 else 0.0
        target_pct = component_trans.get(target_q, 0.0)

        return CSSTransmissionReport(
            selected_charge_state=target_q,
            target_transmission_pct=target_pct,
            total_transmitted_current_ma=total_trans_current,
            charge_purity_pct=purity,
            component_transmissions=component_trans,
            slit_gap_mm=gap,
            slit_center_mm=center,
            dipole_field_t=self.dipole_field_t,
        )

    def tune_slits_for_optimal_purity(
        self,
        beam: MultiChargeBeam,
        target_charge_q: int,
        min_transmission_pct: float = 95.0,
    ) -> CSSTransmissionReport:
        """Autonomously tune slit center and gap to maximize purity while meeting transmission constraint."""
        positions = self.calculate_charge_positions_mm(beam)
        target_x = positions.get(target_charge_q, 0.0)

        # Center slits exactly on target charge centroid
        self.slit_center_mm = target_x

        # Scan gap between 4 mm and 15 mm to maximize purity while keeping transmission >= min_transmission_pct
        best_gap = self.slit_gap_mm
        best_report = None
        best_purity = -1.0

        for gap in np.linspace(4.0, 16.0, 25):
            rep = self.evaluate_transmission(beam, slit_center_mm=target_x, slit_gap_mm=float(gap), target_charge_q=target_charge_q)
            if rep.target_transmission_pct >= min_transmission_pct:
                if rep.charge_purity_pct > best_purity:
                    best_purity = rep.charge_purity_pct
                    best_gap = float(gap)
                    best_report = rep

        if best_report is None:
            # Fallback to nominal gap
            best_report = self.evaluate_transmission(beam, slit_center_mm=target_x, slit_gap_mm=self.slit_gap_mm, target_charge_q=target_charge_q)

        self.slit_gap_mm = best_gap
        return best_report
