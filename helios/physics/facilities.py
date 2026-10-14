"""HELIOS Pre-Configured Facility Lattice Digital Twins.

Provides verified heavy-ion linac lattice models for:
1. RAON (Korea) - SCL1 (QWR & HWR) and SCL2 (SSR1 & SSR2)
2. FRIB (MSU, USA) - Linac Segment 1 (LS1 QWR modules)
3. GSI / FAIR (Germany) - UNILAC High-Charge State Linac
"""

from helios.physics.elements import (
    DiagnosticElement,
    Drift,
    Quadrupole,
    RFCavity,
    Steerer,
)
from helios.physics.lattice import Lattice


def create_raon_scl1_lattice() -> Lattice:
    """Create RAON Superconducting Linac 1 (SCL1) model.

    Features Quarter-Wave Resonators (QWR) and Half-Wave Resonators (HWR)
    with superconducting focusing doublets/solenoids (0.5 to 18.5 MeV/u for 238U).
    """
    elements = []

    # QWR Section: 4 periods
    for i in range(1, 5):
        elements.append(Drift(name=f"RAON:SCL1:DRFT_{i}A", length=0.25))
        elements.append(RFCavity(name=f"RAON:SCL1:QWR_{i:02d}", length=0.35, voltage_kv=950.0, phase_deg=-20.0, frequency_mhz=81.25))
        elements.append(Drift(name=f"RAON:SCL1:DRFT_{i}B", length=0.20))
        elements.append(Steerer(name=f"RAON:SCL1:STR_{i:02d}", length=0.10, kick_x_mrad=0.0, kick_y_mrad=0.0))
        elements.append(Quadrupole(name=f"RAON:SCL1:QD_{i:02d}", length=0.20, gradient_t_m=8.5, aperture_radius_m=0.020))
        elements.append(DiagnosticElement(name=f"RAON:SCL1:BPM_{i:02d}", length=0.10, diag_type="BPM"))

    # HWR Section: 4 periods
    for i in range(1, 5):
        elements.append(Drift(name=f"RAON:SCL1:HWR_DRFT_{i}A", length=0.30))
        elements.append(RFCavity(name=f"RAON:SCL1:HWR_{i:02d}", length=0.45, voltage_kv=1450.0, phase_deg=-20.0, frequency_mhz=162.5))
        elements.append(Drift(name=f"RAON:SCL1:HWR_DRFT_{i}B", length=0.25))
        elements.append(Quadrupole(name=f"RAON:SCL1:QF_{i:02d}", length=0.22, gradient_t_m=-9.2, aperture_radius_m=0.025))
        elements.append(DiagnosticElement(name=f"RAON:SCL1:HWR_BPM_{i:02d}", length=0.10, diag_type="BPM"))
        elements.append(DiagnosticElement(name=f"RAON:SCL1:HWR_BLM_{i:02d}", length=0.05, diag_type="BLM"))

    return Lattice(
        name="RAON_SCL1_BASELINE",
        elements=elements,
        kinetic_energy_mev_u=0.50,
        mass_amu=238.05,
        charge_q=33.0,
    )


def create_frib_ls1_lattice() -> Lattice:
    """Create FRIB Linac Segment 1 (LS1) model.

    Features beta=0.041 and beta=0.085 QWR cryomodules interspersed with 9-Tesla superconducting solenoids.
    """
    elements = []

    # 4 LS1 Cryomodule periods
    for cm in range(1, 5):
        elements.append(Drift(name=f"FRIB:LS1:CM{cm}:DRFT_IN", length=0.30))
        elements.append(Quadrupole(name=f"FRIB:LS1:CM{cm}:SOL", length=0.40, gradient_t_m=12.0, aperture_radius_m=0.020))
        elements.append(Drift(name=f"FRIB:LS1:CM{cm}:DRFT_MID", length=0.15))
        elements.append(RFCavity(name=f"FRIB:LS1:CM{cm}:CAV1", length=0.28, voltage_kv=850.0, phase_deg=-25.0, frequency_mhz=80.5))
        elements.append(Drift(name=f"FRIB:LS1:CM{cm}:DRFT_SEP", length=0.10))
        elements.append(RFCavity(name=f"FRIB:LS1:CM{cm}:CAV2", length=0.28, voltage_kv=850.0, phase_deg=-25.0, frequency_mhz=80.5))
        elements.append(Steerer(name=f"FRIB:LS1:CM{cm}:CORR", length=0.10, kick_x_mrad=0.0, kick_y_mrad=0.0))
        elements.append(DiagnosticElement(name=f"FRIB:LS1:CM{cm}:BPM", length=0.10, diag_type="BPM"))
        elements.append(DiagnosticElement(name=f"FRIB:LS1:CM{cm}:BLM", length=0.05, diag_type="BLM"))

    return Lattice(
        name="FRIB_LS1_BASELINE",
        elements=elements,
        kinetic_energy_mev_u=0.50,
        mass_amu=238.05,
        charge_q=33.0,
    )


def create_gsi_fair_lattice() -> Lattice:
    """Create GSI/FAIR UNILAC High-Charge State Injector model."""
    elements = []

    for i in range(1, 6):
        elements.append(Drift(name=f"GSI:HLI:DRFT_{i}A", length=0.35))
        elements.append(Quadrupole(name=f"GSI:HLI:QD_{i}", length=0.25, gradient_t_m=7.5, aperture_radius_m=0.025))
        elements.append(Drift(name=f"GSI:HLI:DRFT_{i}B", length=0.20))
        elements.append(RFCavity(name=f"GSI:HLI:IH_CAV_{i}", length=0.60, voltage_kv=1100.0, phase_deg=-15.0, frequency_mhz=108.4))
        elements.append(Quadrupole(name=f"GSI:HLI:QF_{i}", length=0.25, gradient_t_m=-7.5, aperture_radius_m=0.025))
        elements.append(Steerer(name=f"GSI:HLI:STEER_{i}", length=0.10, kick_x_mrad=0.0, kick_y_mrad=0.0))
        elements.append(DiagnosticElement(name=f"GSI:HLI:BPM_{i}", length=0.10, diag_type="BPM"))

    return Lattice(
        name="GSI_FAIR_UNILAC",
        elements=elements,
        kinetic_energy_mev_u=1.40,
        mass_amu=238.05,
        charge_q=28.0,
    )
