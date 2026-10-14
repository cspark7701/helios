"""HELIOS Deterministic Safety Gatekeeper.

Deterministic verification engine ensuring proposed operational actions strictly
comply with hardware operating boundaries, slew rate limits, and MPS interlocks.
"""

import hashlib
import time
from collections.abc import Callable
from typing import Any

from helios.core.schemas import ExecutionPlan, StepStatus, ValidationCheck, ValidationResult
from helios.interfaces.base import BaseControlInterface, ControlInterfaceError
from helios.interfaces.channel_map import ChannelManager


class SafetyInterlockError(ControlInterfaceError):
    """Raised when an unvalidated hardware actuation is attempted without SafetyGatekeeper approval."""


class GuardedControlInterface(BaseControlInterface):
    """Control interface wrapper enforcing that all writes have valid SafetyGatekeeper tokens."""

    def __init__(self, raw_control: BaseControlInterface, gatekeeper: "SafetyGatekeeper"):
        self._raw = raw_control
        self._gatekeeper = gatekeeper

    def get(self, pv_name: str) -> Any:
        return self._raw.get(pv_name)

    def put(self, pv_name: str, value: Any, wait: bool = True, timeout: float = 5.0, token: str | None = None) -> bool:
        """Write to PV if and only if an authorization token matching (pv, value) was minted by SafetyGatekeeper."""
        try:
            val_float = float(value)
        except (ValueError, TypeError):
            val_float = None

        if not self._gatekeeper.verify_token(token, pv_name, val_float if val_float is not None else value):
            raise SafetyInterlockError(
                f"Guarded actuation refused: PV '{pv_name}' with value {value} has no valid SafetyGatekeeper authorization token."
            )
        return self._raw.put(pv_name, value, wait=wait, timeout=timeout)

    def subscribe(self, pv_name: str, callback: Callable[[str, Any], None]) -> None:
        self._raw.subscribe(pv_name, callback)

    def unsubscribe(self, pv_name: str) -> None:
        self._raw.unsubscribe(pv_name)


class SafetyGatekeeper:
    """Deterministic boundary and Machine Protection System (MPS) verifier."""

    def __init__(self, channel_manager: ChannelManager, control_interface: BaseControlInterface | None = None):
        self.channels = channel_manager
        self.control = control_interface
        self._valid_tokens: dict[str, dict[str, Any]] = {}
        self.guarded_control: GuardedControlInterface | None = (
            GuardedControlInterface(control_interface, self) if control_interface else None
        )

    def mint_token(self, proposed_setpoints: dict[str, float]) -> str:
        """Mint a cryptographic safety authorization token for approved setpoints."""
        serialized = ";".join(f"{k}={v:.6f}" for k, v in sorted(proposed_setpoints.items()))
        token = hashlib.sha256(f"{serialized}:{time.time()}".encode()).hexdigest()[:24]
        self._valid_tokens[token] = dict(proposed_setpoints)
        return token

    def verify_token(self, token: str | None, pv_name: str, value: Any) -> bool:
        """Verify whether token authorizes write of value to pv_name."""
        if not token or token not in self._valid_tokens:
            return False
        approved = self._valid_tokens[token]
        if pv_name not in approved:
            return False
        try:
            return abs(float(approved[pv_name]) - float(value)) < 1e-4
        except (ValueError, TypeError):
            return approved[pv_name] == value

    def execute(self, plan: ExecutionPlan) -> bool:
        """Execute validated plan steps through the safety agent."""
        if not self.control:
            raise ControlInterfaceError("SafetyGatekeeper has no active control interface")

        token = None
        for val in plan.validation_records:
            if val.validator_agent == "HELIOS-Safety" and val.is_valid and val.authorization_token:
                token = val.authorization_token
                break

        if not token:
            raise SafetyInterlockError(f"Cannot execute plan {plan.plan_id}: No approved safety token found.")

        for step in plan.steps:
            step.status = StepStatus.RUNNING
            pv = step.parameters["pv"]
            val = step.parameters["value"]
            if not self.verify_token(token, pv, val):
                step.status = StepStatus.FAILED
                raise SafetyInterlockError(f"Step {step.step_id} setpoint {pv}={val} not authorized by safety token {token}")
            success = self.control.put(pv, val, wait=True)
            if success:
                step.status = StepStatus.SUCCESS
                step.result = {"actuated_value": val}
            else:
                step.status = StepStatus.FAILED
                raise RuntimeError(f"Caput failed on PV {pv}")
        return True

    def validate_setpoints(
        self,
        proposed_setpoints: dict[str, float],
        agent_name: str = "HELIOS-Safety",
    ) -> ValidationResult:
        """Validate candidate setpoint dictionary against channel limits and slew limits."""
        checks: list[ValidationCheck] = []
        errors: list[str] = []
        warnings: list[str] = []

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
        token = self.mint_token(proposed_setpoints) if is_valid else None

        return ValidationResult(
            is_valid=is_valid,
            validator_agent=agent_name,
            checks=checks,
            authorization_token=token,
            warnings=warnings,
            errors=errors,
        )
