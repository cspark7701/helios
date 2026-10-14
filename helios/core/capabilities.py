"""HELIOS Dynamic Capability Classification System.

Adopted directly from LBNL Osprey's dynamic capability dispatch architecture.
Filters and dispatches accelerator domain tools and agent capabilities
based on operator task intent, keeping LLM prompts lean and context-efficient.
"""

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """Risk rating for hardware actuation and simulation tools."""
    READ_ONLY = "READ_ONLY"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CapabilityDomain(str, Enum):
    """Accelerator subsystem domains."""
    ORBIT = "ORBIT"
    OPTICS = "OPTICS"
    RF = "RF"
    DIAGNOSTICS = "DIAGNOSTICS"
    SAFETY = "SAFETY"
    SIMULATION = "SIMULATION"
    EPICS = "EPICS"
    OPTIMIZATION = "OPTIMIZATION"
    OPS = "OPS"
    ONTOLOGY = "ONTOLOGY"
    CONTROL = "CONTROL"


class Capability(BaseModel):
    """Specification of an agent capability or tool."""
    name: str = Field(..., description="Unique capability or tool name")
    description: str = Field(..., description="Semantic description of what the tool accomplishes")
    domain: CapabilityDomain
    target_agent: str = Field(..., description="Agent responsible for executing this tool")
    risk_level: RiskLevel = RiskLevel.LOW
    keywords: list[str] = Field(default_factory=list, description="Keywords for intent matching")
    parameters_schema: dict[str, Any] = Field(default_factory=dict)
    handler: Any | None = Field(default=None, exclude=True, description="Callable execution handler")


class CapabilityRegistry:
    """Central registry and intent-driven dynamic classifier for agent capabilities."""

    def __init__(self):
        self._capabilities: dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        """Register a new capability in the system."""
        self._capabilities[capability.name] = capability

    def get(self, name: str) -> Capability | None:
        """Fetch a capability by exact name."""
        return self._capabilities.get(name)

    def list_all(self) -> list[Capability]:
        """List all registered capabilities."""
        return list(self._capabilities.values())

    def filter_by_domain(self, domain: CapabilityDomain) -> list[Capability]:
        """Return capabilities matching a specific subsystem domain."""
        return [c for c in self._capabilities.values() if c.domain == domain]

    def filter_by_agent(self, agent_role: str) -> list[Capability]:
        """Return capabilities assigned to a specific agent."""
        return [c for c in self._capabilities.values() if c.target_agent == agent_role]

    def classify_intent(self, prompt: str, max_tools: int = 10) -> list[Capability]:
        """Dynamic Capability Classification (Osprey Pattern).

        Analyzes the operator's natural language directive or task objective
        and returns a prioritized subset of capabilities relevant to the task.
        """
        prompt_lower = prompt.lower()
        tokens = set(re.findall(r"\b\w+\b", prompt_lower))

        scored: list[tuple[int, Capability]] = []

        for cap in self._capabilities.values():
            score = 0
            # Match domain name
            if cap.domain.value.lower() in prompt_lower:
                score += 5

            # Match capability keywords
            for kw in cap.keywords:
                kw_lower = kw.lower()
                if kw_lower in prompt_lower:
                    score += 3
                elif any(tok in kw_lower for tok in tokens):
                    score += 1

            # Match description tokens
            desc_tokens = set(re.findall(r"\b\w+\b", cap.description.lower()))
            overlap = tokens.intersection(desc_tokens)
            score += len(overlap)

            if score > 0:
                scored.append((score, cap))

        # Sort by relevance score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        selected = [cap for _, cap in scored[:max_tools]]

        # Always include core read-only diagnostics and safety if relevant
        if not any(c.domain == CapabilityDomain.SAFETY for c in selected):
            safety_defaults = [c for c in self.filter_by_domain(CapabilityDomain.SAFETY) if c.risk_level == RiskLevel.READ_ONLY]
            selected.extend(safety_defaults[:2])

        return selected


def get_default_registry() -> CapabilityRegistry:
    """Instantiate and populate registry with standard Linac agent capabilities."""
    registry = CapabilityRegistry()

    # Diagnostics Agent Capabilities
    registry.register(Capability(
        name="read_bpm_orbit",
        description="Acquire horizontal and vertical beam orbit offsets from BPMs across a linac section",
        domain=CapabilityDomain.DIAGNOSTICS,
        target_agent="HELIOS-Diagnostics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["bpm", "orbit", "trajectory", "offset", "position", "mebt", "lebt", "scl"],
    ))
    registry.register(Capability(
        name="read_blm_losses",
        description="Read beam loss monitor signals and detect loss hotspots",
        domain=CapabilityDomain.DIAGNOSTICS,
        target_agent="HELIOS-Diagnostics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["blm", "loss", "spill", "radiation", "hotspot", "trip"],
    ))
    registry.register(Capability(
        name="read_transmission",
        description="Calculate beam transmission ratio between upstream and downstream Faraday cups or ACCTs",
        domain=CapabilityDomain.DIAGNOSTICS,
        target_agent="HELIOS-Diagnostics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["transmission", "current", "acct", "fc", "faraday", "intensity"],
    ))

    # Tuning Agent Capabilities
    registry.register(Capability(
        name="calculate_orbit_correction",
        description="Compute dipole steerer current corrections using response matrix SVD inversion",
        domain=CapabilityDomain.ORBIT,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["orbit", "steerer", "svd", "trajectory", "correction", "flatten"],
    ))
    registry.register(Capability(
        name="bayesian_quad_matching",
        description="Run multi-objective Bayesian optimization to match beam envelope with quadrupole magnets",
        domain=CapabilityDomain.OPTIMIZATION,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.MEDIUM,
        keywords=["match", "quadrupole", "envelope", "emittance", "bayesian", "optics"],
    ))
    registry.register(Capability(
        name="rf_phase_amplitude_scan",
        description="Perform automated phase and amplitude scanning of accelerating cavities",
        domain=CapabilityDomain.RF,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.MEDIUM,
        keywords=["rf", "cavity", "phase", "amplitude", "tof", "buncher", "qwr", "hwr"],
    ))

    # Physics Agent Capabilities
    registry.register(Capability(
        name="run_track_simulation",
        description="Run ANL TRACK heavy ion beam dynamics code via Wine to calculate ray tracing, multi-charge state beams, and envelopes",
        domain=CapabilityDomain.SIMULATION,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["track", "simulate", "envelope", "digital twin", "particles", "loss", "anl", "heavy ion"],
    ))
    registry.register(Capability(
        name="run_impactz_simulation",
        description="Run LBNL IMPACT-Z 3D space-charge particle-in-cell simulation via lume-impact",
        domain=CapabilityDomain.SIMULATION,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["impact", "impactz", "space charge", "pic", "lbnl", "lume-impact"],
    ))
    registry.register(Capability(
        name="run_surrogate_envelope",
        description="Evaluate fast neural network surrogate for instant beam size and loss prediction",
        domain=CapabilityDomain.SIMULATION,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["surrogate", "neural", "fast", "preflight", "prediction"],
    ))
    registry.register(Capability(
        name="evaluate_multi_charge_beam",
        description="Calculate magnetic rigidity, dispersion orbit shifts, and composite envelopes for multi-charge state beams (U, Xe, etc.)",
        domain=CapabilityDomain.SIMULATION,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["multi-charge", "mcs", "brho", "rigidity", "uranium", "species", "heavy ion"],
    ))
    registry.register(Capability(
        name="model_stripper_foil",
        description="Model charge stripping, mean charge distribution, energy loss dE/dx, and foil degradation lifetime",
        domain=CapabilityDomain.SIMULATION,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["stripper", "carbon foil", "charge state", "stripping", "lifetime", "scattering"],
    ))
    registry.register(Capability(
        name="tune_charge_separator",
        description="Autonomously tune magnetic chicane slit apertures to optimize charge purity and beam transmission",
        domain=CapabilityDomain.OPTIMIZATION,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["css", "charge separator", "slit", "chicane", "purity", "transmission"],
    ))
    registry.register(Capability(
        name="load_facility_lattice",
        description="Load verified pre-configured heavy-ion linac lattices for RAON, FRIB, or GSI/FAIR",
        domain=CapabilityDomain.SIMULATION,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["facility", "raon", "frib", "gsi", "fair", "scl1", "ls1", "lattice"],
    ))
    registry.register(Capability(
        name="export_lattice_format",
        description="Export or import accelerator lattices between HELIOS, CERN MAD-X, and APS Elegant LTE",
        domain=CapabilityDomain.SIMULATION,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["madx", "mad-x", "elegant", "lte", "convert", "export lattice"],
    ))
    registry.register(Capability(
        name="run_cross_code_benchmarks",
        description="Run comparative cross-code benchmarks evaluating TRACK, IMPACT-Z, and digital twin consistency",
        domain=CapabilityDomain.SIMULATION,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["benchmark", "cross-code", "comparison", "validation", "discrepancy"],
    ))
    registry.register(Capability(
        name="predict_virtual_profile",
        description="Non-interceptive virtual wire scanner reconstructing transverse beam sizes and emittance",
        domain=CapabilityDomain.DIAGNOSTICS,
        target_agent="HELIOS-Diagnostics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["virtual wire scanner", "profile", "emittance", "non-interceptive", "beam size"],
    ))
    registry.register(Capability(
        name="predict_virtual_loss_map",
        description="Predict radiation and halo beam scraping losses along vacuum chamber before beam injection",
        domain=CapabilityDomain.DIAGNOSTICS,
        target_agent="HELIOS-Diagnostics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["virtual blm", "halo", "scraping", "loss map", "radiation hotspot"],
    ))
    registry.register(Capability(
        name="calibrate_model_parameters",
        description="Calibrate surrogate and digital twin parameters against measured BPM orbit and beam sizes",
        domain=CapabilityDomain.OPTIMIZATION,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["calibrate", "fit", "quadrupole calibration", "online calibration", "twiss fit"],
    ))
    registry.register(Capability(
        name="run_rl_orbit_tuning",
        description="Execute continuous Reinforcement Learning (Actor-Critic) policy for dynamic trajectory and envelope control",
        domain=CapabilityDomain.OPTIMIZATION,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.MEDIUM,
        keywords=["rl", "reinforcement learning", "actor-critic", "ppo", "policy", "self-driving"],
    ))
    registry.register(Capability(
        name="run_neural_mpc_control",
        description="Execute Model-Predictive Control with neural surrogate for multi-step receding horizon trajectory planning",
        domain=CapabilityDomain.OPTIMIZATION,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.MEDIUM,
        keywords=["mpc", "model predictive control", "receding horizon", "drift compensation", "planning"],
    ))

    # Safety Agent Capabilities
    registry.register(Capability(
        name="check_setpoint_limits",
        description="Verify proposed magnet currents or RF parameters against hard safety limits and slew limits",
        domain=CapabilityDomain.SAFETY,
        target_agent="HELIOS-Safety",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["safety", "limit", "slew", "interlock", "verify", "mps"],
    ))
    registry.register(Capability(
        name="trigger_rollback",
        description="Immediately restore baseline PV setpoints in event of unexpected loss or machine trip",
        domain=CapabilityDomain.SAFETY,
        target_agent="HELIOS-Safety",
        risk_level=RiskLevel.CRITICAL,
        keywords=["rollback", "abort", "restore", "trip", "emergency"],
    ))
    registry.register(Capability(
        name="verify_srf_quench_margins",
        description="Verify cryogenic helium temperature, multipacting bands, and quench limits on SRF cavities",
        domain=CapabilityDomain.SAFETY,
        target_agent="HELIOS-Safety",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["srf", "quench", "cryo", "helium", "cavity protection", "multipacting"],
    ))
    registry.register(Capability(
        name="panic_shutdown_machine",
        description="Execute emergency one-click machine dump, zeroing critical RF and magnet setpoints",
        domain=CapabilityDomain.SAFETY,
        target_agent="HELIOS-Safety",
        risk_level=RiskLevel.CRITICAL,
        keywords=["panic", "shutdown", "dump", "kill beam", "emergency zero"],
    ))
    registry.register(Capability(
        name="autonomous_rf_cavity_rematch",
        description="Autonomously recalculate downstream cavity voltages and phases upon cavity trip to maintain energy gain",
        domain=CapabilityDomain.OPTIMIZATION,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.MEDIUM,
        keywords=["rematch", "cavity trip", "energy recovery", "rf failure", "self-healing"],
    ))
    registry.register(Capability(
        name="recover_tripped_magnet",
        description="Isolate tripped magnet power supply and recalculate compensatory orbit correction with remaining healthy steerers",
        domain=CapabilityDomain.OPTIMIZATION,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.MEDIUM,
        keywords=["magnet trip", "power supply fault", "fallback steer", "isolate"],
    ))
    registry.register(Capability(
        name="mitigate_beam_loss_hotspot",
        description="Pinpoint radiation loss hotspots from BLM telemetry and steer beam off vacuum chamber walls",
        domain=CapabilityDomain.DIAGNOSTICS,
        target_agent="HELIOS-Diagnostics",
        risk_level=RiskLevel.LOW,
        keywords=["loss hotspot", "scraping", "blm mitigation", "radiation relief"],
    ))

    # Control & Data Agent Capabilities
    registry.register(Capability(
        name="epics_caput_batch",
        description="Execute atomic batch EPICS caput with readback verification",
        domain=CapabilityDomain.EPICS,
        target_agent="HELIOS-Control",
        risk_level=RiskLevel.HIGH,
        keywords=["epics", "caput", "write", "actuate", "hardware", "pv"],
    ))
    registry.register(Capability(
        name="query_archiver_data",
        description="Query EPICS Archiver Appliance for historical PV time series and golden setpoints",
        domain=CapabilityDomain.DIAGNOSTICS,
        target_agent="HELIOS-Diagnostics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["archiver", "history", "golden", "baseline", "time-series", "drift"],
    ))
    registry.register(Capability(
        name="pva_get_table",
        description="Read structured pvAccess NTTable (e.g. multi-BPM orbit table or profile data)",
        domain=CapabilityDomain.EPICS,
        target_agent="HELIOS-Control",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["pva", "pvaccess", "nttable", "orbit table", "vector", "waveform"],
    ))

    # Operations & Reporting Capabilities
    registry.register(Capability(
        name="generate_shift_report",
        description="Compile and export linac commissioning shift logbook report in Markdown or LaTeX format",
        domain=CapabilityDomain.OPS,
        target_agent="HELIOS-Orchestrator",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["report", "shift", "logbook", "summary", "commissioning", "latex", "pdf", "export"],
    ))
    registry.register(Capability(
        name="verify_audit_log_integrity",
        description="Verify SHA-256 cryptographic hash-chain integrity of operational audit logs",
        domain=CapabilityDomain.SAFETY,
        target_agent="HELIOS-Safety",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["audit", "hash chain", "integrity", "tamper", "compliance", "sha256", "log"],
    ))

    # Advanced Beam & RF Control Capabilities (Phases 19 - 21)
    registry.register(Capability(
        name="run_beam_based_alignment",
        description="Execute quadrupole modulation (Delta K1) to resolve beam offset relative to magnetic center",
        domain=CapabilityDomain.ORBIT,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["bba", "beam-based alignment", "quadrupole center", "modulation", "k1", "offset"],
    ))
    registry.register(Capability(
        name="run_dispersion_free_steering",
        description="Simultaneously minimize trajectory distortion and spurious dispersion using weighted SVD",
        domain=CapabilityDomain.ORBIT,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["dfs", "dispersion-free steering", "spurious dispersion", "orbit", "svd"],
    ))
    registry.register(Capability(
        name="reconstruct_phase_space_ment",
        description="Reconstruct 2D transverse phase-space distribution from profile monitor projections using Maximum Entropy",
        domain=CapabilityDomain.DIAGNOSTICS,
        target_agent="HELIOS-Diagnostics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["ment", "tomography", "phase space", "maximum entropy", "emittance", "projection"],
    ))
    registry.register(Capability(
        name="sequence_rf_conditioning",
        description="Autonomous progressive RF power and pulse-width ramp sequencer with vacuum and multipacting interlocks",
        domain=CapabilityDomain.RF,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.MEDIUM,
        keywords=["rf conditioning", "multipacting", "pulse width", "vacuum interlock", "cavity processing"],
    ))

    # Production Scale Optimization & Digital Twin Capabilities (Phases 24 - 26)
    registry.register(Capability(
        name="run_parallel_parameter_sweep",
        description="Run multi-worker parallel simulation parameter sweeps and Uncertainty Quantification (UQ)",
        domain=CapabilityDomain.SIMULATION,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["parallel", "sweep", "ensemble", "uncertainty quantification", "uq", "confidence"],
    ))
    registry.register(Capability(
        name="assimilate_digital_twin_kalman",
        description="Continuous Ensemble Kalman Filter assimilating real-time BPM telemetry into digital twin state",
        domain=CapabilityDomain.SIMULATION,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["kalman", "enkf", "synchronize", "observer", "drift detection", "state estimation"],
    ))
    registry.register(Capability(
        name="optimize_pareto_front_nsga2",
        description="Multi-objective Pareto optimization (NSGA-II) balancing transmission, envelope scalloping, and energy spread",
        domain=CapabilityDomain.OPTIMIZATION,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["pareto", "nsga2", "multi-objective", "genetic", "trade-off", "optics"],
    ))

    # LinkML Ontology & Knowledge Graph Capabilities (Phase 29)
    registry.register(Capability(
        name="validate_linkml_schema",
        description="Validate accelerator device or lattice data against LinkML heavy-ion schema",
        domain=CapabilityDomain.ONTOLOGY,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["linkml", "ontology", "validate schema", "w3c", "rdf", "schema"],
    ))
    registry.register(Capability(
        name="query_beamline_topology",
        description="Traverse beamline knowledge graph to locate upstream/downstream neighbors and causal actuators",
        domain=CapabilityDomain.ONTOLOGY,
        target_agent="HELIOS-Orchestrator",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["topology", "knowledge graph", "neighbors", "upstream steerer", "causal", "graph"],
    ))

    # Advanced Physics, Switchyard & Resilience Capabilities (Phases 30 - 34)
    registry.register(Capability(
        name="track_symplectic_3d_fieldmap",
        description="Execute relativistic Boris symplectic particle tracking through 3D electromagnetic field maps",
        domain=CapabilityDomain.SIMULATION,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["field map", "3d", "boris", "symplectic", "pusher", "cst", "opera"],
    ))
    registry.register(Capability(
        name="evaluate_ibs_growth_rates",
        description="Calculate Intra-Beam Scattering (IBS) emittance diffusion and energy spread growth rates for heavy ions",
        domain=CapabilityDomain.SIMULATION,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["ibs", "intra-beam scattering", "emittance growth", "piwinski", "diffusion"],
    ))
    registry.register(Capability(
        name="route_switchyard_target_vault",
        description="Plan and execute coordinated switchyard trajectory routing to target experiment vaults",
        domain=CapabilityDomain.ORBIT,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["switchyard", "target vault", "bending dipole", "hebt", "routing", "septum"],
    ))
    registry.register(Capability(
        name="arbitrate_cotuning_conflicts",
        description="Resolve concurrent multi-agent Process Variable setpoint conflicts using cooperative game theory",
        domain=CapabilityDomain.OPTIMIZATION,
        target_agent="HELIOS-Orchestrator",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["game theory", "nash", "arbitration", "conflict resolution", "co-tuning"],
    ))

    # Differentiable Dynamics, ECR Tuning, Halo & Agent Mesh Capabilities (Phases 35 - 39)
    registry.register(Capability(
        name="solve_inverse_differentiable_lattice",
        description="Solve inverse lattice parameter reconstruction and calibration via PyTorch autograd backpropagation",
        domain=CapabilityDomain.SIMULATION,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["differentiable", "autodiff", "inverse solver", "gradient", "pytorch", "lattice calibration"],
    ))
    registry.register(Capability(
        name="optimize_ecr_plasma_and_switch",
        description="Optimize ECR ion source plasma parameters and calculate fast multi-species switching lattice scaling",
        domain=CapabilityDomain.OPTIMIZATION,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["ecr", "ion source", "plasma", "species switch", "charge state", "brho", "gas mixing"],
    ))
    registry.register(Capability(
        name="evaluate_halo_and_optimize_collimation",
        description="Compute Kurtosis and H-parameter beam halo metrics and set dynamic collimator jaw apertures",
        domain=CapabilityDomain.DIAGNOSTICS,
        target_agent="HELIOS-Diagnostics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["halo", "collimator", "kurtosis", "h-parameter", "jaw", "scraping", "transmission"],
    ))
    registry.register(Capability(
        name="predict_cryomodule_quench_risk",
        description="Forecast impending SRF cavity and magnet thermal quenches from high-speed cryomodule telemetry",
        domain=CapabilityDomain.SAFETY,
        target_agent="HELIOS-Safety",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["quench", "cryomodule", "srf", "temperature trend", "reflected power", "predictive mps"],
    ))
    registry.register(Capability(
        name="publish_mesh_telemetry_event",
        description="Publish and broadcast telemetry and control events across the distributed multi-node agent mesh",
        domain=CapabilityDomain.CONTROL,
        target_agent="HELIOS-Orchestrator",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["mesh", "distributed", "broker", "event", "failover", "edge sync"],
    ))

    # Advanced Heavy Ion Linac Systems Capabilities (Phases 40 - 44)
    registry.register(Capability(
        name="simulate_rfq_vane_modulation",
        description="Simulate cell-by-cell RFQ vane modulation, 3D electric field harmonics, and heavy ion bunching",
        domain=CapabilityDomain.SIMULATION,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["rfq", "vane modulation", "shaper", "gentle buncher", "bunching factor", "cell dynamics"],
    ))
    registry.register(Capability(
        name="evaluate_liquid_metal_stripper",
        description="Model high-power liquid lithium film and gas stripper hydrodynamics, thermal limits, and charge states",
        domain=CapabilityDomain.SIMULATION,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["liquid lithium", "stripper", "weber number", "vaporization", "charge exchange", "foil lifetime"],
    ))
    registry.register(Capability(
        name="balance_srf_cryoplant_heat",
        description="Optimize superconducting cavity gradients against 2K cryoplant refrigeration capacity and thermal margins",
        domain=CapabilityDomain.RF,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["cryoplant", "bcs resistance", "heat load", "refrigeration", "2k bath", "q0", "jt valve"],
    ))
    registry.register(Capability(
        name="compress_bunch_tensor_network",
        description="Perform low-rank Matrix Product State (MPS) / Tensor Train compression of 6D macroparticle density",
        domain=CapabilityDomain.SIMULATION,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["tensor train", "mps", "tensor network", "svd", "macroparticle compression", "pic memory"],
    ))
    registry.register(Capability(
        name="optimize_girder_laser_alignment",
        description="Calculate motorized girder mechanical adjustments from laser tracker survey data to minimize steerer currents",
        domain=CapabilityDomain.DIAGNOSTICS,
        target_agent="HELIOS-Diagnostics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["laser tracker", "survey", "girder mover", "fiducial", "mechanical alignment", "cams"],
    ))

    # High-Power Targets, Multipactor, and Radiological Safety Capabilities (Phases 45 - 49)
    registry.register(Capability(
        name="simulate_beam_dump_thermal_stress",
        description="Simulate heavy-ion Bragg peak energy deposition, hydrodynamic shock pressure, and CHF margins in beam dumps",
        domain=CapabilityDomain.SAFETY,
        target_agent="HELIOS-Safety",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["beam dump", "bragg peak", "thermal stress", "gruneisen", "chf", "hydrodynamic shock", "target"],
    ))
    registry.register(Capability(
        name="evaluate_cavity_multipactor_and_dark_current",
        description="Model RF coaxial coupler multipactoring breakdown bands and Fowler-Nordheim dark current radiation",
        domain=CapabilityDomain.RF,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["multipactor", "sey", "dark current", "fowler-nordheim", "field emission", "bremsstrahlung", "coupler"],
    ))
    registry.register(Capability(
        name="evaluate_hofmann_stability_and_rematch",
        description="Map linac phase advances onto Hofmann stability charts and calculate resonance-free lattice rematching",
        domain=CapabilityDomain.OPTICS,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["hofmann", "equipartitioning", "space charge", "tune depression", "emittance exchange", "phase advance"],
    ))
    registry.register(Capability(
        name="bridge_cosimulation_telemetry",
        description="Synchronize zero-copy in-memory multi-physics co-simulation buffers with live EPICS machine repetition clock",
        domain=CapabilityDomain.SIMULATION,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["co-simulation", "zero-copy", "streaming", "ipc", "rep-rate", "macro-pulse", "shared memory"],
    ))
    registry.register(Capability(
        name="calculate_radiological_activation_and_cooling",
        description="Compute residual isotope inventory, Bateman decay cooling curves, and tunnel access interlock tokens",
        domain=CapabilityDomain.SAFETY,
        target_agent="HELIOS-Safety",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["radiological", "activation", "decay", "cooling", "bateman", "gamma dose", "rpo clearance"],
    ))

    # Real-Time Controls, Fast MPS, Chicane Compression & Vacuum Capabilities (Phases 50 - 54)
    registry.register(Capability(
        name="compensate_srf_microphonics_piezo",
        description="Compensate SRF Lorentz Force Detuning and cryomodule microphonics using adaptive FxLMS piezo feedforward",
        domain=CapabilityDomain.RF,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["microphonics", "lfd", "lorentz force", "piezo", "fxlms", "feedforward", "srf detuning", "cavity vibration"],
    ))
    registry.register(Capability(
        name="monitor_fast_differential_beam_abort",
        description="Monitor sub-microsecond ACCT differential current loss and fast diamond BLMs to trigger dual-actuator beam abort",
        domain=CapabilityDomain.SAFETY,
        target_agent="HELIOS-Safety",
        risk_level=RiskLevel.CRITICAL,
        keywords=["fast mps", "differential current", "acct", "diamond blm", "sub-microsecond abort", "chopper", "beam punch-through"],
    ))
    registry.register(Capability(
        name="optimize_bunch_compressor_chicane",
        description="Calculate 4-dipole chicane R56 dispersion and optimize RF chirp voltage for heavy-ion bunch compression",
        domain=CapabilityDomain.OPTICS,
        target_agent="HELIOS-Tuner",
        risk_level=RiskLevel.LOW,
        keywords=["bunch compressor", "chicane", "r56", "t566", "chirp", "longitudinal dispersion", "peak current"],
    ))
    registry.register(Capability(
        name="model_linac_uhv_beam_gas_losses",
        description="Simulate UHV pressure profiles along linac warm/cryogenic sections and calculate heavy-ion stripping losses",
        domain=CapabilityDomain.SIMULATION,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["vacuum", "uhv", "pressure profile", "gas stripping", "charge exchange", "desorption", "cold-bore"],
    ))
    registry.register(Capability(
        name="generate_linac_shift_logbook_forensics",
        description="Synthesize automated linac shift handover reports and analyze 50ms pre-trip circular buffer forensics",
        domain=CapabilityDomain.OPS,
        target_agent="HELIOS-Orchestrator",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["logbook", "e-log", "shift handover", "trip forensics", "circular buffer", "root cause", "uptime"],
    ))

    return registry

