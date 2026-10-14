"""HELIOS Phase 39: Multi-Modal Operator Voice & Intent Parsing.

Parses natural language and voice directives from control room physicists into
structured, verifiable execution plans conforming to the Plan-First Osprey architecture.
"""

import re
from typing import Any

from pydantic import BaseModel, Field


class OperatorIntent(BaseModel):
    """Structured operational intent parsed from operator command."""
    raw_utterance: str
    action_type: str  # orbit_correction, species_switch, cavity_tune, collimator_adjust, quench_check, transmission_opt
    target_subsystem: str  # LEBT, RFQ, MEBT, SCL1, SCL2, HEBT, SWITCHYARD, ALL
    target_devices: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(..., ge=0.0, le=1.0)
    requires_human_confirmation: bool = True
    synthesized_plan_summary: str


class OperatorIntentParser:
    """Domain-specific natural language parser for heavy-ion linac control rooms."""

    ACTION_PATTERNS = [
        (r"(orbit|trajectory|steer|flatten|align)", "orbit_correction"),
        (r"(species|switch|change ion|uranium|argon|xenon|oxygen)", "species_switch"),
        (r"(cavity|phase|amplitude|rf|tune cavity)", "cavity_tune"),
        (r"(collimat|halo|scraper|jaw)", "collimator_adjust"),
        (r"(quench|cryo|bath|temperature|thermal)", "quench_check"),
        (r"(transmiss|loss|tune linac|maximize)", "transmission_opt"),
    ]

    SUBSYSTEM_PATTERNS = [
        (r"\b(lebt)\b", "LEBT"),
        (r"\b(rfq)\b", "RFQ"),
        (r"\b(mebt)\b", "MEBT"),
        (r"\b(scl1|scl-1)\b", "SCL1"),
        (r"\b(scl2|scl-2)\b", "SCL2"),
        (r"\b(hebt)\b", "HEBT"),
        (r"\b(switchyard|vault)\b", "SWITCHYARD"),
    ]

    def parse_command(self, utterance: str) -> OperatorIntent:
        """Parse free-form operator text into structured intent."""
        text = utterance.lower().strip()

        # Determine action
        action_type = "unknown_action"
        for pattern, action in self.ACTION_PATTERNS:
            if re.search(pattern, text):
                action_type = action
                break

        # Determine subsystem
        subsystem = "ALL"
        for pattern, sub in self.SUBSYSTEM_PATTERNS:
            if re.search(pattern, text):
                subsystem = sub
                break

        # Extract specific devices or target values
        devices = []
        dev_matches = re.findall(r"\b(sol[0-9]+|quad[0-9]+|cav[0-9]+|bpm[0-9]+|str[0-9]+)\b", text)
        if dev_matches:
            devices = [d.upper() for d in dev_matches]

        params = {}
        # Check target species
        if "uranium" in text or "u238" in text:
            params["target_species"] = "U238"
        elif "xenon" in text or "xe124" in text:
            params["target_species"] = "Xe124"
        elif "argon" in text or "ar40" in text:
            params["target_species"] = "Ar40"
        elif "oxygen" in text or "o16" in text:
            params["target_species"] = "O16"

        # Check numeric values
        num_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(deg|deg\.|kv|mv|ma|ua|mm|%)", text)
        if num_match:
            params["target_value"] = float(num_match.group(1))
            params["unit"] = num_match.group(2)

        confidence = 0.95 if action_type != "unknown_action" else 0.35

        summary = (
            f"Execute {action_type.replace('_', ' ')} in section {subsystem} "
            f"targeting {devices if devices else 'all section elements'} "
            f"with parameters: {params}"
        )

        return OperatorIntent(
            raw_utterance=utterance,
            action_type=action_type,
            target_subsystem=subsystem,
            target_devices=devices,
            parameters=params,
            confidence=confidence,
            requires_human_confirmation=True,
            synthesized_plan_summary=summary
        )
