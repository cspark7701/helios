"""Telemetry assimilation and state synchronization for FacilityTwin."""

import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import numpy as np

from helios.physics.twin.protocol import FacilityTwin

logger = logging.getLogger(__name__)


class TwinStateSynchronizer:
    """Synchronizes live hardware telemetry with FacilityTwin state."""

    def __init__(self, twin: FacilityTwin):
        self.twin = twin
        self.last_sync_time: datetime | None = None
        self.telemetry_history: list[dict[str, Any]] = []
        self.estimated_twiss: dict[str, float] = {
            "alpha_x": 0.0,
            "beta_x_m": 1.25,
            "emittance_x_m_rad": 1.2e-6,
            "alpha_y": 0.0,
            "beta_y_m": 1.25,
            "emittance_y_m_rad": 1.2e-6,
        }

    def assimilate_telemetry(
        self,
        telemetry: Mapping[str, float],
        active_setpoints: Mapping[str, float],
    ) -> dict[str, Any]:
        """Assimilate live BPM/diagnostic measurements and update state."""
        self.last_sync_time = datetime.now(timezone.utc)

        # 1. Compute model-telemetry residual (innovation)
        model_prediction = self.twin.predict(active_setpoints)
        residuals: dict[str, float] = {}
        for diag in self.twin.diagnostic_names:
            measured = telemetry.get(diag)
            if measured is not None:
                predicted = model_prediction.get(diag, 0.0)
                residuals[diag] = float(measured - predicted)

        # 2. Estimate incoming beam centroid distortion
        res_vals = list(residuals.values())
        rms_residual = float(np.sqrt(np.mean(np.array(res_vals)**2))) if res_vals else 0.0

        # 3. Store snapshot
        record = {
            "timestamp": self.last_sync_time.isoformat(),
            "residuals": residuals,
            "rms_residual_mm": round(rms_residual, 4),
            "telemetry_count": len(telemetry),
        }
        self.telemetry_history.append(record)
        if len(self.telemetry_history) > 100:
            self.telemetry_history.pop(0)

        return record
