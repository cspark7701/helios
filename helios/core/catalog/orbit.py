"""Orbit and Optics capability definitions for HELIOS."""

from helios.core.capabilities import Capability, CapabilityDomain, RiskLevel

ORBIT_CAPABILITIES: list[Capability] = [
    Capability(
        name="calculate_orbit_correction",
        description="Compute dipole steerer current corrections using response matrix SVD inversion",
        domain=CapabilityDomain.ORBIT,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["orbit", "steerer", "svd", "trajectory", "correction", "flatten"],
        target_module="helios.tuning.analytic",
    ),
    Capability(
        name="run_beam_based_alignment",
        description="Execute quadrupole modulation (Delta K1) to resolve beam offset relative to magnetic center",
        domain=CapabilityDomain.ORBIT,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["bba", "beam-based alignment", "quadrupole center", "modulation", "k1", "offset"],
        target_module="helios.tuning.bba",
    ),
    Capability(
        name="run_dispersion_free_steering",
        description="Simultaneously minimize trajectory distortion and spurious dispersion using weighted SVD",
        domain=CapabilityDomain.ORBIT,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["dfs", "dispersion-free steering", "spurious dispersion", "orbit", "svd"],
        target_module="helios.tuning.bba",
    ),
    Capability(
        name="route_switchyard_target_vault",
        description="Plan and execute coordinated switchyard trajectory routing to target experiment vaults",
        domain=CapabilityDomain.ORBIT,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["switchyard", "target vault", "bending dipole", "hebt", "routing", "septum"],
        target_module="helios.tuning.switchyard",
    ),
    Capability(
        name="evaluate_hofmann_stability_and_rematch",
        description="Map linac phase advances onto Hofmann stability charts and calculate resonance-free lattice rematching",
        domain=CapabilityDomain.OPTICS,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["hofmann", "equipartitioning", "space charge", "tune depression", "emittance exchange", "phase advance"],
        target_module="helios.physics.equipartition",
    ),
    Capability(
        name="optimize_bunch_compressor_chicane",
        description="Calculate 4-dipole chicane R56 dispersion and optimize RF chirp voltage for heavy-ion bunch compression",
        domain=CapabilityDomain.OPTICS,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["bunch compressor", "chicane", "r56", "t566", "chirp", "longitudinal dispersion", "peak current"],
        target_module="helios.tuning.bunch_compressor",
    ),
]
