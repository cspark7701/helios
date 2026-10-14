"""HELIOS Diagnostics Archiver & Historical Telemetry Bridge.

Maintains historical in-memory and file-based telemetry logs for provenance,
post-mortem review, and trend analysis.
"""

import json
from collections import deque
from pathlib import Path

import numpy as np

from helios.core.schemas import TelemetrySnapshot


class TelemetryArchiver:
    """Stores and queries time-series telemetry snapshots."""

    def __init__(self, max_buffer_size: int = 1000):
        self.max_buffer_size = max_buffer_size
        self._history: deque[TelemetrySnapshot] = deque(maxlen=max_buffer_size)

    def record_snapshot(self, snapshot: TelemetrySnapshot) -> None:
        """Append a telemetry snapshot to history buffer."""
        self._history.append(snapshot)

    def get_latest(self) -> TelemetrySnapshot | None:
        """Fetch the most recent snapshot."""
        if not self._history:
            return None
        return self._history[-1]

    def get_recent(self, count: int = 10) -> list[TelemetrySnapshot]:
        """Fetch up to `count` recent snapshots."""
        return list(self._history)[-count:]

    def compute_trend_stats(self, channel_name: str, plane: str = "x") -> dict[str, float]:
        """Compute mean, std, and drift over recorded history for a BPM channel."""
        vals: list[float] = []
        for snap in self._history:
            if plane == "x" and channel_name in snap.bpm_x:
                vals.append(snap.bpm_x[channel_name])
            elif plane == "y" and channel_name in snap.bpm_y:
                vals.append(snap.bpm_y[channel_name])

        if not vals:
            return {"count": 0, "mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0}

        arr = np.array(vals)
        return {
            "count": len(vals),
            "mean": float(np.mean(arr)),
            "std": float(np.std(arr)),
            "min": float(np.min(arr)),
            "max": float(np.max(arr)),
        }

    def export_json(self, file_path: Path) -> None:
        """Export history to JSON for provenance records."""
        data = [json.loads(s.model_dump_json()) for s in self._history]
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
