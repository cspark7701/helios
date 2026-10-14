"""HELIOS EPICS pvAccess (PVA) Interface.

Provides high-performance structured normative types (NTTable, NTNDArray, NTScalar),
multi-BPM vector orbits, profile monitor camera matrices, and Channel Access Security enforcement.
"""

import logging
from collections.abc import Callable
from typing import Any

import numpy as np

from helios._optional import require
from helios.interfaces.base import (
    BaseControlInterface,
    ControlInterfaceError,
    InMemoryPVStore,
)
from helios.interfaces.security import ControlSecurityManager

try:
    from p4p.client.thread import Context as PvaContext
    from p4p.nt import NTNDArray, NTScalar, NTTable
except ImportError:
    PvaContext = None
    NTTable = None
    NTNDArray = None
    NTScalar = None

logger = logging.getLogger(__name__)


class PVAccessInterface(BaseControlInterface):
    """EPICS pvAccess client with Normative Type and security support."""

    def __init__(
        self,
        security_manager: ControlSecurityManager | None = None,
        use_mock: bool = False,
    ):
        self.security_manager = security_manager or ControlSecurityManager()
        self.use_mock = use_mock
        self._store: InMemoryPVStore | None = InMemoryPVStore() if use_mock else None
        self.pva_ctxt = None

        if not self.use_mock:
            try:
                require("p4p", extra="epics", feature="live EPICS pvAccess")
                from p4p.client.thread import Context as PvaContext
                self.pva_ctxt = PvaContext("pva")
            except Exception as e:
                raise ControlInterfaceError(f"Failed to initialize p4p PVA context: {e}") from e

    def get(self, pv_name: str) -> Any:
        """Synchronously read a PV value via pvAccess."""
        if self.use_mock:
            if self._store is None:
                raise ControlInterfaceError("Mock store not initialized")
            return self._store.get(pv_name)

        if self.pva_ctxt is None:
            raise ControlInterfaceError("PVA context is not initialized")
        try:
            val = self.pva_ctxt.get(pv_name)
            # Unwrap p4p Value or NTScalar if applicable
            if hasattr(val, "raw"):
                return getattr(val, "value", val)
            return val
        except Exception as e:
            logger.error(f"PVA get('{pv_name}') failed: {e}")
            raise ControlInterfaceError(f"PVA get failed for '{pv_name}': {e}") from e

    def put(self, pv_name: str, value: Any, wait: bool = True, timeout: float = 5.0) -> bool:
        """Write a value to a PV via pvAccess after CAS security validation."""
        # 1. Security enforcement
        self.security_manager.check_permission(pv_name)

        if self.use_mock:
            if self._store is None:
                raise ControlInterfaceError("Mock store not initialized")
            return self._store.put(pv_name, value)

        if self.pva_ctxt is None:
            raise ControlInterfaceError("PVA context is not initialized")
        try:
            self.pva_ctxt.put(pv_name, value, timeout=timeout)
            return True
        except Exception as e:
            logger.error(f"PVA put('{pv_name}', {value}) failed: {e}")
            raise ControlInterfaceError(f"PVA put failed for '{pv_name}': {e}") from e

    def subscribe(self, pv_name: str, callback: Callable[[str, Any], None]) -> None:
        """Subscribe to value change monitor events on a PV."""
        if self.use_mock:
            if self._store is None:
                raise ControlInterfaceError("Mock store not initialized")
            self._store.subscribe(pv_name, callback)
            return

        if self.pva_ctxt is None:
            raise ControlInterfaceError("PVA context is not initialized")

        def _handler(val):
            if hasattr(val, "raw"):
                val = getattr(val, "value", val)
            callback(pv_name, val)

        self.pva_ctxt.monitor(pv_name, _handler)

    def unsubscribe(self, pv_name: str) -> None:
        """Unsubscribe from a monitored PV."""
        if self.use_mock:
            if self._store is not None:
                self._store.unsubscribe(pv_name)
            return
        # Live PVA subscriptions are managed by context close/unsubscribe handle

    # ---------------- Normative Type Specialized Operations ---------------- #

    def get_nt_table(self, pv_name: str) -> dict[str, list[Any]]:
        """Retrieve structured NTTable (e.g., Linac Multi-BPM orbit table).

        Returns:
            Dict mapping column names to lists of values, e.g.:
            {'bpm': ['BPM1', 'BPM2'], 's_pos': [1.2, 3.4], 'x_mm': [0.1, -0.2]}
        """
        raw = self.get(pv_name)
        if isinstance(raw, dict) and "labels" in raw and "value" in raw:
            labels = raw["labels"]
            values = raw["value"]
            return {label: col_vals for label, col_vals in zip(labels, values)}
        elif isinstance(raw, dict):
            return raw
        # Default empty table
        return {}

    def put_nt_table(self, pv_name: str, table_data: dict[str, list[Any]]) -> bool:
        """Publish structured NTTable to a pvAccess channel."""
        self.security_manager.check_permission(pv_name)
        return self.put(pv_name, table_data)

    def get_nt_ndarray(self, pv_name: str) -> np.ndarray:
        """Retrieve structured NTNDArray (e.g. beam profile camera image matrix)."""
        raw = self.get(pv_name)
        if isinstance(raw, np.ndarray):
            return raw
        elif isinstance(raw, list):
            return np.array(raw)
        return np.zeros((1, 1), dtype=np.float32)

    def put_nt_ndarray(self, pv_name: str, array_data: np.ndarray) -> bool:
        """Publish structured NTNDArray to a pvAccess channel."""
        self.security_manager.check_permission(pv_name)
        return self.put(pv_name, array_data)
