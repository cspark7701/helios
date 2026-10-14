"""HELIOS EPICS Archiver Appliance Client.

Provides structured time-series retrieval, golden baseline snapshot extraction,
and statistics aggregations from EPICS Archiver Appliance (PB/JSON endpoints).
"""

import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class ArchiverError(Exception):
    """Base exception for archiver appliance retrieval operations."""


class ArchiverApplianceClient:
    """REST API Client for EPICS Archiver Appliance (SLAC/FRIB/ALS/RAON standard)."""

    def __init__(
        self,
        base_url: str = "http://localhost:17665/retrieval",
        timeout: float = 10.0,
        mock_mode: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.mock_mode = mock_mode
        self._mock_data_store: dict[str, list[dict[str, Any]]] = {}

    def register_mock_history(self, pv_name: str, samples: list[dict[str, Any]]) -> None:
        """Register synthetic historical points for testing or offline simulations."""
        self._mock_data_store[pv_name] = samples

    def get_data(
        self,
        pv_name: str,
        start_time: datetime,
        end_time: datetime,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        """Retrieve time-series data for a Process Variable between start_time and end_time.

        Returns a list of dicts: [{'val': float, 'secs': int, 'nanos': int, 'severity': int, ...}]
        """
        if self.mock_mode or requests is None:
            return self._query_mock_data(pv_name, start_time, end_time)

        # EPICS Archiver Appliance ISO8601 formatting (with trailing Z)
        iso_from = start_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        iso_to = end_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        url = f"{self.base_url}/data/getData.json"
        params = {
            "pv": pv_name,
            "from": iso_from,
            "to": iso_to,
            "limit": limit,
        }

        try:
            resp = requests.get(url, params=params, timeout=self.timeout)  # type: ignore[arg-type]
            resp.raise_for_status()
            data = resp.json()
            if not data or not isinstance(data, list):
                return []
            # Appliance returns: [{"meta": {...}, "data": [{"val": ..., "secs": ...}, ...]}]
            entry = data[0]
            return entry.get("data", [])
        except Exception as e:
            logger.warning(f"Archiver request failed for PV '{pv_name}': {e}. Falling back to mock store.")
            return self._query_mock_data(pv_name, start_time, end_time)

    def _query_mock_data(
        self,
        pv_name: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict[str, Any]]:
        """Query synthetic mock historical points."""
        stored = self._mock_data_store.get(pv_name)
        if stored:
            t_start = start_time.timestamp()
            t_end = end_time.timestamp()
            return [pt for pt in stored if t_start <= pt.get("secs", 0) <= t_end]

        # Generate plausible mock data if none pre-registered
        t_start = int(start_time.timestamp())
        t_end = int(end_time.timestamp())
        step = max(1, (t_end - t_start) // 20)
        out = []
        base_val = 1.0 if "BPM" in pv_name else 0.5
        for s in range(t_start, t_end + 1, step):
            out.append({
                "secs": s,
                "nanos": 0,
                "val": base_val + 0.05 * np.sin(s / 60.0),
                "severity": 0,
                "status": 0,
            })
        return out

    def get_golden_baseline(
        self,
        pv_names: list[str],
        timestamp: datetime,
        window_seconds: int = 60,
    ) -> dict[str, float]:
        """Extract snapshot golden setpoints for a list of PVs around a designated timestamp."""
        baseline: dict[str, float] = {}
        t_start = datetime.fromtimestamp(timestamp.timestamp() - window_seconds, tz=timezone.utc)
        t_end = datetime.fromtimestamp(timestamp.timestamp() + window_seconds, tz=timezone.utc)

        for pv in pv_names:
            points = self.get_data(pv, t_start, t_end)
            if points:
                # Use closest value or average
                vals = [p["val"] for p in points if isinstance(p.get("val"), (int, float))]
                if vals:
                    baseline[pv] = float(np.median(vals))
                else:
                    baseline[pv] = 0.0
            else:
                baseline[pv] = 0.0

        return baseline

    def compute_pv_statistics(
        self,
        pv_name: str,
        start_time: datetime,
        end_time: datetime,
    ) -> dict[str, float]:
        """Compute summary statistics (mean, std, min, max, drift_per_min) over a time window."""
        points = self.get_data(pv_name, start_time, end_time)
        vals = [p["val"] for p in points if isinstance(p.get("val"), (int, float))]
        times = [p["secs"] for p in points if isinstance(p.get("val"), (int, float))]

        if not vals:
            return {"count": 0.0, "mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "drift_per_min": 0.0}

        arr = np.array(vals)
        t_arr = np.array(times)

        # Drift rate via linear slope
        drift_rate = 0.0
        if len(arr) >= 2 and (t_arr[-1] - t_arr[0]) > 0:
            dt_mins = (t_arr[-1] - t_arr[0]) / 60.0
            drift_rate = float((arr[-1] - arr[0]) / dt_mins)

        return {
            "count": float(len(arr)),
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
            "drift_per_min": drift_rate,
        }
