"""HELIOS Linac Lattice Model, Particle/Envelope Tracking, and Response Matrix Engine.

Provides multi-element linac lattice tracking, beam envelope evolution,
and orbit response matrix (ORM) generation for closed-loop steering.
"""

import math
from dataclasses import dataclass

import numpy as np

from helios.physics.elements import (
    DiagnosticElement,
    Drift,
    Element,
    Quadrupole,
    RFCavity,
    Steerer,
)


@dataclass
class TrajectoryPoint:
    """State of the beam centroid and envelope at a longitudinal position s."""
    element_name: str
    s_m: float
    x_mm: float
    xp_mrad: float
    y_mm: float
    yp_mrad: float
    sigma_x_mm: float
    sigma_y_mm: float
    loss_fraction: float = 0.0
    provenance: str = "analytic"


class Lattice:
    """Represents an accelerator lattice composed of sequential beamline elements."""

    def __init__(
        self,
        name: str,
        kinetic_energy_mev_u: float = 0.5,
        mass_amu: float = 1.0,
        charge_q: float = 1.0,
        elements: list[Element] | None = None,
    ):
        self.name = name
        self.kinetic_energy_mev_u = kinetic_energy_mev_u
        self.mass_amu = mass_amu
        self.charge_q = charge_q
        self.elements: list[Element] = []
        if elements:
            for elem in elements:
                self.add_element(elem)

    def add_element(self, element: Element) -> None:
        """Append an element and update its longitudinal s position."""
        current_s = self.total_length
        element.s_position = current_s
        self.elements.append(element)

    @property
    def total_length(self) -> float:
        """Total physical length of the lattice in meters."""
        return sum(e.length for e in self.elements)

    def get_element(self, name: str) -> Element | None:
        """Find element by name."""
        for e in self.elements:
            if e.name == name:
                return e
        return None

    @staticmethod
    def _init_envelope_state(
        initial_x_mm: float,
        initial_y_mm: float,
        initial_sigma_x_mm: float,
        initial_sigma_y_mm: float,
        emittance_x_mm_mrad: float,
        emittance_y_mm_mrad: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        x_vec = np.array([
            initial_x_mm * 1e-3, 0.0,
            initial_y_mm * 1e-3, 0.0,
            0.0, 0.0
        ], dtype=float)

        sig_x_m = initial_sigma_x_mm * 1e-3
        sig_y_m = initial_sigma_y_mm * 1e-3
        eps_x_m = emittance_x_mm_mrad * 1e-6
        eps_y_m = emittance_y_mm_mrad * 1e-6

        Sigma = np.zeros((6, 6), dtype=float)
        Sigma[0, 0] = sig_x_m**2
        Sigma[1, 1] = (eps_x_m / max(sig_x_m, 1e-9))**2
        Sigma[2, 2] = sig_y_m**2
        Sigma[3, 3] = (eps_y_m / max(sig_y_m, 1e-9))**2
        Sigma[4, 4] = 1e-6
        Sigma[5, 5] = 1e-6
        return x_vec, Sigma

    def _transport_element(
        self,
        elem: Element,
        x_vec: np.ndarray,
        Sigma: np.ndarray,
        cumulative_s: float,
        loss_accumulated: float,
    ) -> tuple[np.ndarray, np.ndarray, float, float, TrajectoryPoint]:
        R = elem.transfer_matrix_6x6(self.kinetic_energy_mev_u, self.mass_amu, self.charge_q)
        if isinstance(elem, Steerer):
            x_vec[1] += elem.kick_x_mrad * 1e-3
            x_vec[3] += elem.kick_y_mrad * 1e-3

        x_vec = R @ x_vec
        Sigma = R @ Sigma @ R.T
        cumulative_s += elem.length

        sig_x = math.sqrt(max(0.0, Sigma[0, 0])) * 1e3
        sig_y = math.sqrt(max(0.0, Sigma[2, 2])) * 1e3

        aperture_mm = elem.aperture_radius_m * 1e3 if isinstance(elem, Quadrupole) else 20.0
        envelope_edge_x = abs(x_vec[0] * 1e3) + 3.0 * sig_x
        envelope_edge_y = abs(x_vec[2] * 1e3) + 3.0 * sig_y
        max_edge = max(envelope_edge_x, envelope_edge_y)

        if max_edge > aperture_mm:
            excess = (max_edge - aperture_mm) / aperture_mm
            loss_accumulated += min(0.5, excess * 0.1)

        point = TrajectoryPoint(
            element_name=elem.name,
            s_m=cumulative_s,
            x_mm=x_vec[0] * 1e3,
            xp_mrad=x_vec[1] * 1e3,
            y_mm=x_vec[2] * 1e3,
            yp_mrad=x_vec[3] * 1e3,
            sigma_x_mm=sig_x,
            sigma_y_mm=sig_y,
            loss_fraction=min(1.0, loss_accumulated),
        )
        return x_vec, Sigma, cumulative_s, loss_accumulated, point

    def track_envelope(
        self,
        initial_sigma_x_mm: float = 2.0,
        initial_sigma_y_mm: float = 2.0,
        emittance_x_mm_mrad: float = 0.3,
        emittance_y_mm_mrad: float = 0.3,
        initial_x_mm: float = 0.0,
        initial_y_mm: float = 0.0,
    ) -> list[TrajectoryPoint]:
        """Track beam centroid and RMS envelope (sigma matrix) through the lattice."""
        x_vec, Sigma = self._init_envelope_state(
            initial_x_mm, initial_y_mm, initial_sigma_x_mm, initial_sigma_y_mm,
            emittance_x_mm_mrad, emittance_y_mm_mrad
        )

        trajectory: list[TrajectoryPoint] = [
            TrajectoryPoint(
                element_name="START",
                s_m=0.0,
                x_mm=x_vec[0] * 1e3,
                xp_mrad=x_vec[1] * 1e3,
                y_mm=x_vec[2] * 1e3,
                yp_mrad=x_vec[3] * 1e3,
                sigma_x_mm=math.sqrt(max(0.0, Sigma[0, 0])) * 1e3,
                sigma_y_mm=math.sqrt(max(0.0, Sigma[2, 2])) * 1e3,
            )
        ]
        cumulative_s = 0.0
        loss_accumulated = 0.0

        for elem in self.elements:
            x_vec, Sigma, cumulative_s, loss_accumulated, point = self._transport_element(
                elem, x_vec, Sigma, cumulative_s, loss_accumulated
            )
            trajectory.append(point)

        return trajectory

    def compute_orbit_response_matrix(
        self,
        steerer_names: list[str],
        bpm_names: list[str],
        kick_mrad: float = 0.5,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Compute horizontal and vertical Orbit Response Matrices (ORM) using perturbation tracking.

        Returns:
            (R_x, R_y): Matrices mapping steerer kicks (mrad) to BPM position changes (mm).
            Dimensions: (len(bpm_names), len(steerer_names))
        """
        n_bpms = len(bpm_names)
        n_steerers = len(steerer_names)

        Rx = np.zeros((n_bpms, n_steerers), dtype=float)
        Ry = np.zeros((n_bpms, n_steerers), dtype=float)

        # Baseline orbit at BPMs
        base_traj = self.track_envelope()
        bpm_s_map = {p.element_name: p for p in base_traj if p.element_name in bpm_names}

        for j, s_name in enumerate(steerer_names):
            steerer = self.get_element(s_name)
            if not isinstance(steerer, Steerer):
                continue

            orig_kx = steerer.kick_x_mrad
            orig_ky = steerer.kick_y_mrad

            # Horizontal perturbation
            steerer.kick_x_mrad = orig_kx + kick_mrad
            traj_x = self.track_envelope()
            steerer.kick_x_mrad = orig_kx  # restore

            # Vertical perturbation
            steerer.kick_y_mrad = orig_ky + kick_mrad
            traj_y = self.track_envelope()
            steerer.kick_y_mrad = orig_ky  # restore

            for i, b_name in enumerate(bpm_names):
                b_base = bpm_s_map.get(b_name)
                b_pert_x = next((p for p in traj_x if p.element_name == b_name), None)
                b_pert_y = next((p for p in traj_y if p.element_name == b_name), None)

                if b_base and b_pert_x:
                    Rx[i, j] = (b_pert_x.x_mm - b_base.x_mm) / kick_mrad
                if b_base and b_pert_y:
                    Ry[i, j] = (b_pert_y.y_mm - b_base.y_mm) / kick_mrad

        return Rx, Ry


def create_baseline_mebt_lattice() -> Lattice:
    """Create a calibrated MEBT lattice model for simulation and testing."""
    lat = Lattice(name="MEBT_BASELINE", kinetic_energy_mev_u=5.0, mass_amu=1.0, charge_q=1)

    lat.add_element(Drift(name="D01", length=0.15))
    lat.add_element(Steerer(name="MEBT_CH01", length=0.10, kick_x_mrad=0.0, kick_y_mrad=0.0))
    lat.add_element(Quadrupole(name="MEBT_QD01", length=0.20, gradient_t_m=-3.5, aperture_radius_m=0.02))
    lat.add_element(Drift(name="D02", length=0.15))
    lat.add_element(Quadrupole(name="MEBT_QF02", length=0.20, gradient_t_m=3.5, aperture_radius_m=0.02))
    lat.add_element(Drift(name="D03", length=0.20))
    lat.add_element(DiagnosticElement(name="MEBT_BPM01", length=0.05, diag_type="BPM"))
    lat.add_element(RFCavity(name="MEBT_CAV01", length=0.30, voltage_kv=120.0, phase_deg=-20.0))
    lat.add_element(Drift(name="D04", length=0.20))
    lat.add_element(DiagnosticElement(name="MEBT_BPM02", length=0.05, diag_type="BPM"))

    return lat
