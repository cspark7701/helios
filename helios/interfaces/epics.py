"""HELIOS EPICS Control System Driver and Mock Interface.

Provides real EPICS Channel Access connectivity via pyepics and an in-memory
MockControlInterface for simulation, continuous integration, and digital twin testing.
"""

import logging
import random
import time
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from helios.interfaces.base import (
    BaseControlInterface,
    ControlInterfaceError,
)

logger = logging.getLogger(__name__)


class MockControlInterface(BaseControlInterface):
    """In-memory mock control interface simulating EPICS PVs with realistic latency and feedback."""

    def __init__(self, response_lag_s: float = 0.01, readback_noise_std: float = 0.0):
        self.response_lag_s = response_lag_s
        self.readback_noise_std = readback_noise_std
        self._pvs: dict[str, Any] = {}
        self._subscribers: dict[str, list[Callable[[str, Any], None]]] = defaultdict(list)

    def set_initial_pv(self, pv_name: str, value: Any) -> None:
        """Pre-populate a PV value directly."""
        self._pvs[pv_name] = value

    def get(self, pv_name: str) -> Any:
        """Get PV value, adding simulated readback noise if configured."""
        val = self._pvs.get(pv_name)
        if val is not None and isinstance(val, (int, float)) and self.readback_noise_std > 0:
            val += random.gauss(0, self.readback_noise_std)
        return val

    def put(self, pv_name: str, value: Any, wait: bool = True, timeout: float = 5.0) -> bool:
        """Simulate putting a PV value and updating corresponding readback PV if mapped."""
        if self.response_lag_s > 0 and wait:
            time.sleep(self.response_lag_s)

        self._pvs[pv_name] = value

        # Automatically update common readback conventions
        # e.g. CurrentSet -> CurrentAct, Set -> Act, etc.
        if "Set" in pv_name:
            readback_name = pv_name.replace("Set", "Act")
            self._pvs[readback_name] = value
        elif "SP" in pv_name:
            readback_name = pv_name.replace("SP", "RB")
            self._pvs[readback_name] = value

        # Trigger callbacks
        for cb in self._subscribers.get(pv_name, []):
            try:
                cb(pv_name, value)
            except Exception as e:
                logger.error(f"Error in subscriber callback for {pv_name}: {e}")

        return True

    def subscribe(self, pv_name: str, callback: Callable[[str, Any], None]) -> None:
        self._subscribers[pv_name].append(callback)

    def unsubscribe(self, pv_name: str) -> None:
        if pv_name in self._subscribers:
            del self._subscribers[pv_name]


class EPICSInterface(BaseControlInterface):
    """Production EPICS Channel Access (CA) interface using pyepics."""

    def __init__(self, default_timeout: float = 5.0):
        self.default_timeout = default_timeout
        self._pv_cache: dict[str, Any] = {}
        self._check_epics_availability()

    def _check_epics_availability(self) -> None:
        try:
            import epics  # noqa: F401
            self._has_epics = True
        except ImportError:
            self._has_epics = False
            logger.warning("pyepics is not installed. Live EPICS operations will raise exceptions.")

    def _ensure_epics(self) -> None:
        if not self._has_epics:
            raise ControlInterfaceError("pyepics package is not installed. Use MockControlInterface or install pyepics.")

    def get(self, pv_name: str) -> Any:
        self._ensure_epics()
        import epics
        return epics.caget(pv_name, timeout=self.default_timeout)

    def put(self, pv_name: str, value: Any, wait: bool = True, timeout: float = 5.0) -> bool:
        self._ensure_epics()
        import epics
        status = epics.caput(pv_name, value, wait=wait, timeout=timeout)
        return status == 1

    def get_many(self, pv_names: list[str]) -> dict[str, Any]:
        self._ensure_epics()
        import epics
        values = epics.caget_many(pv_names, timeout=self.default_timeout)
        return dict(zip(pv_names, values))

    def subscribe(self, pv_name: str, callback: Callable[[str, Any], None]) -> None:
        self._ensure_epics()
        import epics

        def _handler(pvname=None, value=None, **kwargs):
            callback(pvname, value)

        pv = epics.PV(pv_name, callback=_handler)
        self._pv_cache[pv_name] = pv

    def unsubscribe(self, pv_name: str) -> None:
        if pv_name in self._pv_cache:
            pv = self._pv_cache.pop(pv_name)
            pv.clear_callbacks()
