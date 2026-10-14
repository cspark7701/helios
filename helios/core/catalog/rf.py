"""RF capability definitions for HELIOS."""

from helios.core.capabilities import Capability, CapabilityDomain, RiskLevel

RF_CAPABILITIES: list[Capability] = [
    Capability(
        name="rf_phase_amplitude_scan",
        description="Perform automated phase and amplitude scanning of accelerating cavities",
        domain=CapabilityDomain.RF,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.MEDIUM,
        keywords=["rf", "cavity", "phase", "amplitude", "tof", "buncher", "qwr", "hwr"],
        target_module="helios.tuning.analytic",
    ),
    Capability(
        name="sequence_rf_conditioning",
        description="Autonomous progressive RF power and pulse-width ramp sequencer with vacuum and multipacting interlocks",
        domain=CapabilityDomain.RF,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.MEDIUM,
        keywords=["rf conditioning", "multipacting", "pulse width", "vacuum interlock", "cavity processing"],
        target_module="helios.rf.conditioning",
    ),
    Capability(
        name="balance_srf_cryoplant_heat",
        description="Optimize superconducting cavity gradients against 2K cryoplant refrigeration capacity and thermal margins",
        domain=CapabilityDomain.RF,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["cryoplant", "bcs resistance", "heat load", "refrigeration", "2k bath", "q0", "jt valve"],
        target_module="helios.rf.cryoplant",
    ),
    Capability(
        name="evaluate_cavity_multipactor_and_dark_current",
        description="Model RF coaxial coupler multipactoring breakdown bands and Fowler-Nordheim dark current radiation",
        domain=CapabilityDomain.RF,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["multipactor", "sey", "dark current", "fowler-nordheim", "field emission", "bremsstrahlung", "coupler"],
        target_module="helios.rf.multipactor",
    ),
    Capability(
        name="compensate_srf_microphonics_piezo",
        description="Compensate SRF Lorentz Force Detuning and cryomodule microphonics using adaptive FxLMS piezo feedforward",
        domain=CapabilityDomain.RF,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["microphonics", "lfd", "lorentz force", "piezo", "fxlms", "feedforward", "srf detuning", "cavity vibration"],
        target_module="helios.rf.microphonics",
    ),
]
