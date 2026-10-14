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
    target_module: str | None = Field(default=None, description="Module implementing or hosting this capability")
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
    from helios.core.catalog import ALL_DEFAULT_CAPABILITIES

    registry = CapabilityRegistry()
    for cap in ALL_DEFAULT_CAPABILITIES:
        registry.register(cap)
    return registry

