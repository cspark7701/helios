"""HELIOS Machine Protection System (MPS) Latency Modeling and Fast Interlocks.

Models interlock response latency budgets (tau_detect + tau_propagate + tau_actuate <= tau_damage)
and verifies hardware protection readiness before authorizing beam actuation.
"""

import logging
from dataclasses import dataclass

from helios.core.schemas import ValidationCheck, ValidationResult

logger = logging.getLogger(__name__)


@dataclass
class MPSInterlockChannel:
    """Channel definition for a fast MPS sensor or interlock node."""
    channel_id: str
    description: str
    is_tripped: bool = False
    latency_us: float = 2.5     # Response time in microseconds
    hardware_ok: bool = True


@dataclass
class LatencyBudget:
    """Latency budget for machine protection response."""
    detection_time_us: float = 3.0
    propagation_time_us: float = 4.0
    actuation_time_us: float = 8.0
    beam_damage_threshold_us: float = 25.0  # Time before 1 MW/cm^2 heavy ion beam damages niobium wall

    @property
    def total_latency_us(self) -> float:
        return self.detection_time_us + self.propagation_time_us + self.actuation_time_us

    @property
    def margin_us(self) -> float:
        return self.beam_damage_threshold_us - self.total_latency_us

    @property
    def is_compliant(self) -> bool:
        return self.total_latency_us <= self.beam_damage_threshold_us


class MPSManager:
    """Supervises linac fast interlocks and verifies latency compliance."""

    def __init__(self, channels: list[MPSInterlockChannel] | None = None):
        self.channels: dict[str, MPSInterlockChannel] = {}
        defaults = channels or [
            MPSInterlockChannel("MPS:FAST:DIFF_BPM_LOSS", "Differential BPM fast loss detect", latency_us=2.0),
            MPSInterlockChannel("MPS:FAST:BLM_ION_CHAMBER", "Ionization chamber BLM radiation trip", latency_us=5.0),
            MPSInterlockChannel("MPS:FAST:VAC_VALVE_FAST", "Fast vacuum gate valve trip", latency_us=12.0),
            MPSInterlockChannel("MPS:FAST:RF_ARC_DETECT", "Optical arc detector in RF cavity coupler", latency_us=1.5),
        ]
        for ch in defaults:
            self.channels[ch.channel_id] = ch

    def set_interlock_status(self, channel_id: str, is_tripped: bool) -> None:
        """Update interlock state for testing or live simulation."""
        if channel_id in self.channels:
            self.channels[channel_id].is_tripped = is_tripped

    def verify_mps_readiness(self, latency_budget: LatencyBudget | None = None) -> ValidationResult:
        """Evaluate active interlocks and verify that protection latency budget is met."""
        budget = latency_budget or LatencyBudget()
        checks: list[ValidationCheck] = []
        errors: list[str] = []
        warnings: list[str] = []

        # 1. Latency budget compliance
        latency_ok = budget.is_compliant
        checks.append(ValidationCheck(
            check_name="MPS Fast Latency Budget Compliance",
            passed=latency_ok,
            measured_value=budget.total_latency_us,
            limit_value=budget.beam_damage_threshold_us,
            message=f"Total latency {budget.total_latency_us:.1f} us <= damage limit {budget.beam_damage_threshold_us:.1f} us (Margin: {budget.margin_us:.1f} us)",
        ))
        if not latency_ok:
            errors.append(
                f"MPS latency budget exceeded: {budget.total_latency_us:.1f} us > {budget.beam_damage_threshold_us:.1f} us"
            )

        # 2. Check each fast interlock channel
        for ch_id, ch in self.channels.items():
            ch_passed = not ch.is_tripped and ch.hardware_ok
            checks.append(ValidationCheck(
                check_name=f"MPS Node {ch_id}",
                passed=ch_passed,
                measured_value=1.0 if ch.is_tripped else 0.0,
                limit_value=0.0,
                message="INTERLOCK TRIPPED" if ch.is_tripped else "Normal",
            ))
            if ch.is_tripped:
                errors.append(f"Fast Interlock tripped on {ch_id}: {ch.description}")
            elif not ch.hardware_ok:
                errors.append(f"Hardware sensor fault on {ch_id}: {ch.description}")

        is_valid = len(errors) == 0

        return ValidationResult(
            is_valid=is_valid,
            validator_agent="HELIOS-Safety",
            checks=checks,
            errors=errors,
            warnings=warnings,
        )
