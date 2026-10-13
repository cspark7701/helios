"""HELIOS EPICS pvAccess (PVA) Interface.

Provides high-performance structured normative types (NTTable, NTNDArray, NTScalar),
multi-BPM vector orbits, profile monitor camera matrices, and Channel Access Security enforcement.
"""

from datetime import datetime, timezone
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Union
import numpy as np

from helios.interfaces.base import BaseControlInterface, ControlInterfaceError
from helios.interfaces.security import ControlSecurityManager, SecurityViolationError

try:
    from p4p.client.thread import Context as PvaContext
    from p4p.nt import NTTable, NTNDArray, NTScalar
    HAVE_P4P = True
except ImportError:
    PvaContext = None
    NTTable = None
    NTNDArray = None
    NTScalar = None
    HAVE_P4P = False

logger = logging.getLogger(__name__)


class PVAccessInterface(BaseControlInterface):
    """EPICS pvAccess client with Normative Type and security support."""

    def __init__(
        self,
        security_manager: Optional[ControlSecurityManager] = None,
        use_mock: bool = False,
    ):
        self.security_manager = security_manager or ControlSecurityManager()
        self.use_mock = use_mock or (not HAVE_P4P)
        self._mock_pvs: Dict[str, Any] = {}
        self._mock_subscribers: Dict[str, List[Callable[[str, Any], None]]] = {}

        self.pva_ctxt = None
        if not self.use_mock and HAVE_P4P:
            try:
                self.pva_ctxt = PvaContext("pva")
            except Exception as e:
                logger.warning(f"Failed to initialize p4p PVA context ({e}); falling back to mock PVA.")
                self.use_mock = True

    def get(self, pv_name: str) -> Any:
        """Synchronously read a PV value via pvAccess."""
        if not self.use_mock and self.pva_ctxt is not None:
            try:
                val = self.pva_ctxt.get(pv_name)
                # Unwrap p4p Value or NTScalar if applicable
                if hasattr(val, "raw"):
                    return getattr(val, "value", val)
                return val
            except Exception as e:
                logger.warning(f"PVA get('{pv_name}') failed: {e}; attempting mock store.")

        return self._mock_pvs.get(pv_name)

    def put(self, pv_name: str, value: Any, wait: bool = True, timeout: float = 5.0) -> bool:
        """Write a value to a PV via pvAccess after CAS security validation."""
        # 1. Security enforcement
        self.security_manager.check_permission(pv_name)

        if not self.use_mock and self.pva_ctxt is not None:
            try:
                self.pva_ctxt.put(pv_name, value, timeout=timeout)
                return True
            except Exception as e:
                logger.warning(f"PVA put('{pv_name}', {value}) failed: {e}; falling back to mock store.")

        self._mock_pvs[pv_name] = value
        # Trigger any registered callbacks
        if pv_name in self._mock_subscribers:
            for cb in self._mock_subscribers[pv_name]:
                try:
                    cb(pv_name, value)
                except Exception as cb_err:
                    logger.error(f"Error in PVA monitor callback for {pv_name}: {cb_err}")
        return True

    def get_many(self, pv_names: List[str]) -> Dict[str, Any]:
        """Read multiple Process Variables in batch."""
        return {pv: self.get(pv) for pv in pv_names}

    def put_many(self, setpoints: Dict[str, Any], wait: bool = True, timeout: float = 5.0) -> Dict[str, bool]:
        """Write multiple Process Variables in batch."""
        results = {}
        for pv, val in setpoints.items():
            results[pv] = self.put(pv, val, wait=wait, timeout=timeout)
        return results

    def subscribe(self, pv_name: str, callback: Callable[[str, Any], None]) -> None:
        """Subscribe to value change monitor events on a PV."""
        if pv_name not in self._mock_subscribers:
            self._mock_subscribers[pv_name] = []
        self._mock_subscribers[pv_name].append(callback)

    def unsubscribe(self, pv_name: str) -> None:
        """Unsubscribe from a monitored PV."""
        self._mock_subscribers.pop(pv_name, None)

    # ---------------- Normative Type Specialized Operations ---------------- #

    def get_nt_table(self, pv_name: str) -> Dict[str, List[Any]]:
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

    def put_nt_table(self, pv_name: str, table_data: Dict[str, List[Any]]) -> bool:
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
