"""HELIOS Accelerator Physics Elements and Transfer Matrices.

Provides beamline element representations and linear transfer matrices (R-matrices)
for particle tracking and beam envelope propagation.
"""

import math

import numpy as np
from pydantic import BaseModel, Field


class Element(BaseModel):
    """Abstract base class for beamline elements."""
    name: str
    length: float = Field(0.0, ge=0.0, description="Element length along beamline in meters")
    s_position: float = Field(0.0, description="Longitudinal position s in meters")

    def transfer_matrix_6x6(self, kinetic_energy_mev_u: float = 0.5, mass_amu: float = 1.0, charge_q: int = 1) -> np.ndarray:
        """Compute 6x6 linear transport matrix R. Defaults to identity."""
        return np.eye(6)


class Drift(Element):
    """Free drift space."""

    def transfer_matrix_6x6(self, kinetic_energy_mev_u: float = 0.5, mass_amu: float = 1.0, charge_q: int = 1) -> np.ndarray:
        R = np.eye(6)
        L = self.length
        R[0, 1] = L
        R[2, 3] = L
        R[4, 5] = L  # Longitudinal drift approximation
        return R


class Quadrupole(Element):
    """Magnetic quadrupole focusing element."""
    gradient_t_m: float = Field(0.0, description="Magnetic field gradient in T/m (positive focuses in X)")
    aperture_radius_m: float = Field(0.02, description="Bore radius in meters")

    def k1(self, kinetic_energy_mev_u: float = 0.5, mass_amu: float = 1.0, charge_q: int = 1) -> float:
        """Calculate geometric quadrupole strength k1 [m^-2]."""
        # Brho = p / q = sqrt(2 * m * E_k) / q (non-relativistic approximation for low energy linacs)
        # E_tot = m_0*c^2 + T
        m_kg = mass_amu * 1.66053906660e-27
        q_c = charge_q * 1.602176634e-19
        c = 299792458.0
        e_joules = kinetic_energy_mev_u * 1e6 * mass_amu * 1.602176634e-19
        gamma = 1.0 + e_joules / (m_kg * c**2)
        beta = math.sqrt(max(0.0, 1.0 - 1.0 / (gamma**2)))
        p_si = gamma * m_kg * beta * c
        brho = p_si / q_c
        return self.gradient_t_m / max(brho, 1e-9)

    def transfer_matrix_6x6(self, kinetic_energy_mev_u: float = 0.5, mass_amu: float = 1.0, charge_q: int = 1) -> np.ndarray:
        k = self.k1(kinetic_energy_mev_u, mass_amu, charge_q)
        L = self.length
        R = np.eye(6)

        if math.isclose(k, 0.0, abs_tol=1e-12) or math.isclose(L, 0.0, abs_tol=1e-12):
            R[0, 1] = L
            R[2, 3] = L
            return R

        if k > 0:
            # Focusing in X, defocusing in Y
            omega = math.sqrt(k)
            phi = omega * L
            cos_phi = math.cos(phi)
            sin_phi = math.sin(phi)
            cosh_phi = math.cosh(phi)
            sinh_phi = math.sinh(phi)

            # X plane (focusing)
            R[0, 0] = cos_phi
            R[0, 1] = sin_phi / omega
            R[1, 0] = -omega * sin_phi
            R[1, 1] = cos_phi

            # Y plane (defocusing)
            R[2, 2] = cosh_phi
            R[2, 3] = sinh_phi / omega
            R[3, 2] = omega * sinh_phi
            R[3, 3] = cosh_phi
        else:
            # Defocusing in X, focusing in Y
            omega = math.sqrt(abs(k))
            phi = omega * L
            cos_phi = math.cos(phi)
            sin_phi = math.sin(phi)
            cosh_phi = math.cosh(phi)
            sinh_phi = math.sinh(phi)

            # X plane (defocusing)
            R[0, 0] = cosh_phi
            R[0, 1] = sinh_phi / omega
            R[1, 0] = omega * sinh_phi
            R[1, 1] = cosh_phi

            # Y plane (focusing)
            R[2, 2] = cos_phi
            R[2, 3] = sin_phi / omega
            R[3, 2] = -omega * sin_phi
            R[3, 3] = cos_phi

        return R


class Steerer(Element):
    """Dipole steering corrector (horizontal and vertical kicks)."""
    kick_x_mrad: float = Field(0.0, description="Horizontal kick angle in mrad")
    kick_y_mrad: float = Field(0.0, description="Vertical kick angle in mrad")
    current_x_a: float = Field(0.0, description="Horizontal power supply current in Amperes")
    current_y_a: float = Field(0.0, description="Vertical power supply current in Amperes")
    conversion_factor_a_per_mrad: float = Field(0.168, description="Transfer factor converting kick angle (mrad) to current (A)")
    current_increment_a: float = Field(0.05, description="Power supply minimum current step / quantization resolution in Amperes")

    @classmethod
    def kick_to_current(
        cls,
        kick_mrad: float,
        conversion_factor_a_per_mrad: float = 0.168,
        increment_a: float = 0.05,
    ) -> float:
        """Convert angular deflection kick (mrad) to power supply current (A) with DAC quantization."""
        raw_current = kick_mrad * conversion_factor_a_per_mrad
        if increment_a > 0.0:
            return round(round(raw_current / increment_a) * increment_a, 6)
        return raw_current

    @classmethod
    def current_to_kick(
        cls,
        current_a: float,
        conversion_factor_a_per_mrad: float = 0.168,
    ) -> float:
        """Convert power supply current (A) back to effective deflection kick (mrad)."""
        if abs(conversion_factor_a_per_mrad) < 1e-9:
            return 0.0
        return current_a / conversion_factor_a_per_mrad

    def set_currents(self, current_x: float, current_y: float) -> None:
        """Set steerer currents and update effective kick angles according to conversion calibration."""
        if self.current_increment_a > 0.0:
            self.current_x_a = round(round(current_x / self.current_increment_a) * self.current_increment_a, 6)
            self.current_y_a = round(round(current_y / self.current_increment_a) * self.current_increment_a, 6)
        else:
            self.current_x_a = current_x
            self.current_y_a = current_y

        self.kick_x_mrad = self.current_to_kick(self.current_x_a, self.conversion_factor_a_per_mrad)
        self.kick_y_mrad = self.current_to_kick(self.current_y_a, self.conversion_factor_a_per_mrad)

    def set_kicks(self, kick_x_mrad: float, kick_y_mrad: float) -> None:
        """Set kicks, quantizing them to achievable power supply current DAC setpoints."""
        self.current_x_a = self.kick_to_current(kick_x_mrad, self.conversion_factor_a_per_mrad, self.current_increment_a)
        self.current_y_a = self.kick_to_current(kick_y_mrad, self.conversion_factor_a_per_mrad, self.current_increment_a)
        self.kick_x_mrad = self.current_to_kick(self.current_x_a, self.conversion_factor_a_per_mrad)
        self.kick_y_mrad = self.current_to_kick(self.current_y_a, self.conversion_factor_a_per_mrad)

    def transfer_matrix_6x6(self, kinetic_energy_mev_u: float = 0.5, mass_amu: float = 1.0, charge_q: int = 1) -> np.ndarray:
        R = np.eye(6)
        R[0, 1] = self.length
        R[2, 3] = self.length
        return R


class RFCavity(Element):
    """Accelerating or bunching RF cavity."""
    voltage_kv: float = Field(0.0, description="Peak cavity voltage in kV")
    phase_deg: float = Field(0.0, description="Synchronous RF phase in degrees")
    frequency_mhz: float = Field(81.25, description="RF operating frequency in MHz")

    def transfer_matrix_6x6(self, kinetic_energy_mev_u: float = 0.5, mass_amu: float = 1.0, charge_q: int = 1) -> np.ndarray:
        # Thin lens approximation with longitudinal focusing and RF defocusing
        R = np.eye(6)
        L = self.length
        R[0, 1] = L
        R[2, 3] = L
        # Longitudinal focusing matrix element R_65: d(delta_p/p) / d(z)
        if self.voltage_kv > 0 and kinetic_energy_mev_u > 0:
            phi_rad = math.radians(self.phase_deg)
            _omega_rf = 2 * math.pi * self.frequency_mhz * 1e6
            # Thin kick approximation
            R[5, 4] = - (self.voltage_kv * 1e3 * math.sin(phi_rad)) / (kinetic_energy_mev_u * 1e6)
        return R


class DiagnosticElement(Element):
    """Beam diagnostic instrument (BPM, BLM, Wire Scanner, Faraday Cup)."""
    diag_type: str = Field("BPM", description="BPM, BLM, WIRE, FC")

    def transfer_matrix_6x6(self, kinetic_energy_mev_u: float = 0.5, mass_amu: float = 1.0, charge_q: int = 1) -> np.ndarray:
        R = np.eye(6)
        R[0, 1] = self.length
        R[2, 3] = self.length
        return R
