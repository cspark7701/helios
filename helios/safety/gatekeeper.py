"""HELIOS Deterministic Safety Gatekeeper.

Deterministic verification engine ensuring proposed operational actions strictly
comply with hardware operating boundaries, slew rate limits, and MPS interlocks.
"""

from typing import Dict, List, Optional
from helios.core.schemas import ValidationCheck, ValidationResult
from helios.interfaces.base import BaseControlInterface
from helios.interfaces.channel_map import ChannelManager


class SafetyGatekeeper:
    """Deterministic boundary and Machine Protection System (MPS) verifier."""

    def __init__(self, channel_manager: ChannelManager, control_interface: Optional[BaseControlInterface] = None):
        self.channels = channel_manager
        self.control = control_interface

    def validate_setpoints(
        self,
        proposed_setpoints: Dict[str, float],
        agent_name: str = "HELIOS-Safety",
    ) -> ValidationResult:
        """Validate candidate setpoint dictionary against channel limits and slew limits."""
        checks: List[ValidationCheck] = []
        errors: List[str] = []
        warnings: List[str] = []

        for pv_or_channel, target_val in proposed_setpoints.items():
            # Resolve device from PV or semantic name
            dev = self.channels.get_device_by_pv(pv_or_channel)
            if not dev and ":" in pv_or_channel:
                parts = pv_or_channel.split(":")
                dev = self.channels.get_device(parts[0], parts[1])

            if not dev or not dev.limits:
                # If no explicit limit defined, flag warning
                warnings.append(f"No explicit limits defined for channel {pv_or_channel}")
                continue

            limits = dev.limits

            # Check 1: Hard Upper and Lower Limits
            within_hard = limits.min_val <= target_val <= limits.max_val
            checks.append(ValidationCheck(
                check_name=f"{dev.name} Hard Limit Range",
                passed=within_hard,
                measured_value=target_val,
                limit_value=limits.max_val,
                message=f"{target_val} {limits.units} vs [{limits.min_val}, {limits.max_val}] {limits.units}",
            ))
            if not within_hard:
                errors.append(
                    f"Channel {pv_or_channel} ({dev.name}) requested setpoint {target_val} {limits.units} "
                    f"exceeds hard limits [{limits.min_val}, {limits.max_val}] {limits.units}"
                )

            # Check 2: Soft Warning Limits
            if limits.warn_min is not None and target_val < limits.warn_min:
                warnings.append(f"Channel {pv_or_channel} below warning limit {limits.warn_min} {limits.units}")
            if limits.warn_max is not None and target_val > limits.warn_max:
                warnings.append(f"Channel {pv_or_channel} exceeds warning limit {limits.warn_max} {limits.units}")

            # Check 3: Slew rate check against current value if control interface is active
            if self.control and limits.max_slew_rate:
                current_val = self.control.get(dev.setpoint_pv or pv_or_channel)
                if current_val is not None:
                    delta = abs(float(current_val) - target_val)
                    # Slew check for single-step change
                    if delta > limits.max_slew_rate * 5.0:  # step jump limit
                        warnings.append(
                            f"Large single jump on {dev.name} ({delta:.2f} > 5s rate {limits.max_slew_rate*5.0:.2f}). "
                            "Ramped slew-limiting will be enforced during write."
                        )

        # Check 4: Interlocks if control interface is available
        if self.control:
            # Query MPS status PV if present
            mps_ok = self.control.get("MPS:GLOBAL:INTERLOCK_OK")
            if mps_ok is not None and int(mps_ok) == 0:
                checks.append(ValidationCheck(
                    check_name="Machine Protection System (MPS)",
                    passed=False,
                    message="Global MPS Interlock is NOT cleared",
                ))
                errors.append("MPS Interlock active: Live actuation prohibited!")

        is_valid = len(errors) == 0

        return ValidationResult(
            is_valid=is_valid,
            validator_agent=agent_name,
            checks=checks,
            warnings=warnings,
            errors=errors,
        )
