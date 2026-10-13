"""HELIOS Dynamic Capability Classification System.

Adopted directly from LBNL Osprey's dynamic capability dispatch architecture.
Filters and dispatches accelerator domain tools and agent capabilities
based on operator task intent, keeping LLM prompts lean and context-efficient.
"""

from enum import Enum
import re
from typing import Any, Callable, Dict, List, Optional, Set
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


class Capability(BaseModel):
    """Specification of an agent capability or tool."""
    name: str = Field(..., description="Unique capability or tool name")
    description: str = Field(..., description="Semantic description of what the tool accomplishes")
    domain: CapabilityDomain
    target_agent: str = Field(..., description="Agent responsible for executing this tool")
    risk_level: RiskLevel = RiskLevel.LOW
    keywords: List[str] = Field(default_factory=list, description="Keywords for intent matching")
    parameters_schema: Dict[str, Any] = Field(default_factory=dict)
    handler: Optional[Any] = Field(None, exclude=True, description="Callable execution handler")


class CapabilityRegistry:
    """Central registry and intent-driven dynamic classifier for agent capabilities."""

    def __init__(self):
        self._capabilities: Dict[str, Capability] = {}

    def register(self, capability: Capability) -> None:
        """Register a new capability in the system."""
        self._capabilities[capability.name] = capability

    def get(self, name: str) -> Optional[Capability]:
        """Fetch a capability by exact name."""
        return self._capabilities.get(name)

    def list_all(self) -> List[Capability]:
        """List all registered capabilities."""
        return list(self._capabilities.values())

    def filter_by_domain(self, domain: CapabilityDomain) -> List[Capability]:
        """Return capabilities matching a specific subsystem domain."""
        return [c for c in self._capabilities.values() if c.domain == domain]

    def filter_by_agent(self, agent_role: str) -> List[Capability]:
        """Return capabilities assigned to a specific agent."""
        return [c for c in self._capabilities.values() if c.target_agent == agent_role]

    def classify_intent(self, prompt: str, max_tools: int = 10) -> List[Capability]:
        """Dynamic Capability Classification (Osprey Pattern).

        Analyzes the operator's natural language directive or task objective
        and returns a prioritized subset of capabilities relevant to the task.
        """
        prompt_lower = prompt.lower()
        tokens = set(re.findall(r"\b\w+\b", prompt_lower))

        scored: List[tuple[int, Capability]] = []

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

    return registry
