"""HELIOS Base Control System Interface and Slew-Rate Controller.

Defines the contract for control system drivers (EPICS CA/PVA and Mock),
incorporating atomic actuation, readback verification, and slew-rate limiting.
"""

import logging
import math
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class ControlInterfaceError(Exception):
    """Base exception for accelerator control system operations."""


class ReadbackTimeoutError(ControlInterfaceError):
    """Raised when PV readback does not converge within specified tolerance and timeout."""


class SlewRateLimiter:
    """Calculates ramped intermediate setpoints to enforce maximum rate-of-change."""

    @staticmethod
    def calculate_trajectory(
        current_val: float,
        target_val: float,
        max_slew_rate: float,
        step_interval_s: float = 0.1,
    ) -> list[float]:
        """Generate intermediate setpoints ensuring rate-of-change never exceeds max_slew_rate.

        Args:
            current_val: Starting value
            target_val: Final target value
            max_slew_rate: Maximum allowed change per second (|delta| / dt <= max_slew_rate)
            step_interval_s: Time step in seconds between setpoint updates

        Returns:
            List of intermediate float values terminating with target_val.
        """
        if max_slew_rate <= 0:
            return [target_val]

        delta = target_val - current_val
        if math.isclose(delta, 0.0, abs_tol=1e-7):
            return [target_val]

        max_step = max_slew_rate * step_interval_s
        num_steps = math.ceil(abs(delta) / max_step)

        if num_steps <= 1:
            return [target_val]

        trajectory = []
        sign = 1.0 if delta > 0 else -1.0
        for i in range(1, num_steps):
            trajectory.append(current_val + sign * i * max_step)
        trajectory.append(target_val)
        return trajectory


class MissingReadbackError(ControlInterfaceError):
    """Raised when a setpoint or diagnostic PV readback returns None or cannot be read."""


class InMemoryPVStore:
    """In-memory dictionary store for simulated PV read/write/subscribe operations."""

    def __init__(self, initial_pvs: dict[str, Any] | None = None):
        self._pvs: dict[str, Any] = dict(initial_pvs or {})
        self._subscribers: dict[str, list[Callable[[str, Any], None]]] = {}

    def get(self, pv_name: str) -> Any:
        return self._pvs.get(pv_name)

    def set(self, pv_name: str, value: Any) -> None:
        self._pvs[pv_name] = value

    def put(self, pv_name: str, value: Any) -> bool:
        self._pvs[pv_name] = value
        for cb in self._subscribers.get(pv_name, []):
            try:
                cb(pv_name, value)
            except Exception as e:
                logger.error(f"Error in subscriber callback for {pv_name}: {e}")
        return True

    def subscribe(self, pv_name: str, callback: Callable[[str, Any], None]) -> None:
        if pv_name not in self._subscribers:
            self._subscribers[pv_name] = []
        self._subscribers[pv_name].append(callback)

    def unsubscribe(self, pv_name: str) -> None:
        self._subscribers.pop(pv_name, None)

    def clear(self) -> None:
        self._pvs.clear()
        self._subscribers.clear()


class BaseControlInterface(ABC):
    """Abstract interface defining required control system interactions."""

    @abstractmethod
    def get(self, pv_name: str) -> Any:
        """Synchronously read a Process Variable value."""

    @abstractmethod
    def put(self, pv_name: str, value: Any, wait: bool = True, timeout: float = 5.0) -> bool:
        """Write a value to a Process Variable."""

    def get_many(self, pv_names: list[str]) -> dict[str, Any]:
        """Read multiple Process Variables in batch."""
        return {pv: self.get(pv) for pv in pv_names}

    def put_many(self, setpoints: dict[str, Any], wait: bool = True, timeout: float = 5.0) -> dict[str, bool]:
        """Write multiple Process Variables in batch."""
        return {pv: self.put(pv, val, wait=wait, timeout=timeout) for pv, val in setpoints.items()}

    @abstractmethod
    def subscribe(self, pv_name: str, callback: Callable[[str, Any], None]) -> None:
        """Subscribe to value change monitor events on a PV."""

    @abstractmethod
    def unsubscribe(self, pv_name: str) -> None:
        """Unsubscribe from a monitored PV."""

    def put_with_readback(
        self,
        setpoint_pv: str,
        readback_pv: str,
        target_val: float,
        tolerance: float = 0.01,
        timeout: float = 10.0,
        max_slew_rate: float | None = None,
        poll_interval: float = 0.05,
    ) -> bool:
        """Atomic write with optional slew-rate ramping and readback convergence verification.

        Args:
            setpoint_pv: PV to write setpoint to
            readback_pv: PV to monitor readback convergence
            target_val: Desired target setpoint
            tolerance: Maximum allowable difference |target - readback|
            timeout: Maximum wait time in seconds
            max_slew_rate: Max allowed delta per second (units/s)
            poll_interval: Sleep duration between readback checks

        Returns:
            True if readback converged within tolerance before timeout.

        Raises:
            MissingReadbackError: If current setpoint is None and ramping is required.
            ReadbackTimeoutError: If readback fails to converge before timeout expires.
        """
        start_time = time.monotonic()

        # Enforce slew-rate limiting if requested
        if max_slew_rate and max_slew_rate > 0:
            current_raw = self.get(setpoint_pv)
            if current_raw is None:
                raise MissingReadbackError(f"Cannot ramp setpoint for {setpoint_pv}: current value is None")
            current_val = float(current_raw)
            trajectory = SlewRateLimiter.calculate_trajectory(
                current_val=current_val,
                target_val=target_val,
                max_slew_rate=max_slew_rate,
                step_interval_s=poll_interval * 2,
            )
            for step_val in trajectory:
                self.put(setpoint_pv, step_val, wait=True, timeout=timeout)
                time.sleep(poll_interval * 2)
        else:
            self.put(setpoint_pv, target_val, wait=True, timeout=timeout)

        # Verify readback convergence
        while (time.monotonic() - start_time) < timeout:
            act_val = self.get(readback_pv)
            if act_val is not None:
                diff = abs(float(act_val) - target_val)
                if diff <= tolerance:
                    return True
            time.sleep(poll_interval)

        act_val = self.get(readback_pv)
        raise ReadbackTimeoutError(
            f"Readback for {setpoint_pv} -> {readback_pv} failed to converge to {target_val} "
            f"(actual: {act_val}, tolerance: {tolerance}) within {timeout}s timeout"
        )
