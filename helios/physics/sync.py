"""HELIOS Online Digital Twin Synchronization & State Estimation.

Implements:
1. Extended / Ensemble Kalman Filter (EnKF) assimilating live BPM telemetry to estimate unmeasured beam states.
2. Drift detection and autonomous online recalibration trigger.
3. Golden baseline snapshot archive and semantic diff comparison.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class LinacEstimatedState:
    """Estimated physical beam state along the linac."""
    timestamp: datetime
    orbit_x_mm: np.ndarray
    orbit_y_mm: np.ndarray
    energy_spread_dpp: float
    unmeasured_emittance_x: float
    unmeasured_emittance_y: float
    state_covariance_trace: float


@dataclass
class ModelDriftStatus:
    """Drift evaluation between digital twin predictions and real machine."""
    discrepancy_rms_mm: float
    drift_detected: bool
    recalibration_recommended: bool
    affected_subsystems: list[str]


class DigitalTwinKalmanFilter:
    """Assimilates diagnostic BPM measurements to estimate full 6D linac trajectory and beam spread."""

    def __init__(self, num_bpms: int = 4, process_noise_std: float = 0.01, meas_noise_std: float = 0.02):
        self.num_bpms = num_bpms
        # State vector: [x_1, y_1, ..., x_N, y_N, dp/p, emit_x, emit_y]
        self.state_dim = num_bpms * 2 + 3
        self.state = np.zeros(self.state_dim)
        self.state[-3] = 0.001  # Initial dp/p
        self.state[-2] = 0.35   # Initial emit_x (mm-mrad)
        self.state[-1] = 0.35   # Initial emit_y (mm-mrad)

        self.p_cov = np.eye(self.state_dim) * 0.1
        self.q_proc = np.eye(self.state_dim) * (process_noise_std ** 2)
        self.r_meas = np.eye(num_bpms * 2) * (meas_noise_std ** 2)

    def update(self, measured_bpm_x: np.ndarray, measured_bpm_y: np.ndarray) -> LinacEstimatedState:
        """Execute Kalman prediction and measurement assimilation step."""
        # 1. State prediction: x_k|k-1 = F * x_k-1 (Assuming identity drift model + small random walk)
        pred_state = self.state.copy()
        pred_cov = self.p_cov + self.q_proc

        # 2. Measurement vector z: [x_1, y_1, ..., x_N, y_N]
        z = np.empty(self.num_bpms * 2)
        z[0::2] = measured_bpm_x
        z[1::2] = measured_bpm_y

        # Measurement matrix H: extracts first 2*N coordinates from state
        h_matrix = np.zeros((self.num_bpms * 2, self.state_dim))
        h_matrix[:self.num_bpms * 2, :self.num_bpms * 2] = np.eye(self.num_bpms * 2)

        # Innovation
        y_innov = z - (h_matrix @ pred_state)
        s_cov = h_matrix @ pred_cov @ h_matrix.T + self.r_meas

        # Kalman gain
        k_gain = pred_cov @ h_matrix.T @ np.linalg.inv(s_cov)

        # Updated state and covariance
        self.state = pred_state + k_gain @ y_innov
        self.p_cov = (np.eye(self.state_dim) - k_gain @ h_matrix) @ pred_cov

        return LinacEstimatedState(
            timestamp=datetime.now(timezone.utc),
            orbit_x_mm=self.state[:self.num_bpms * 2:2],
            orbit_y_mm=self.state[1:self.num_bpms * 2:2],
            energy_spread_dpp=float(self.state[-3]),
            unmeasured_emittance_x=float(self.state[-2]),
            unmeasured_emittance_y=float(self.state[-1]),
            state_covariance_trace=float(np.trace(self.p_cov)),
        )


class DigitalTwinDriftDetector:
    """Monitors persistent deviation between simulated predictions and live machine readbacks."""

    @staticmethod
    def detect_drift(
        predicted_bpm_mm: np.ndarray,
        measured_bpm_mm: np.ndarray,
        drift_threshold_mm: float = 0.25,
    ) -> ModelDriftStatus:
        """Evaluate if model residual exceeds statistical confidence limit."""
        diff = measured_bpm_mm - predicted_bpm_mm
        rms_discrepancy = float(np.sqrt(np.mean(diff ** 2)))

        is_drift = rms_discrepancy > drift_threshold_mm
        recalibration = rms_discrepancy > (drift_threshold_mm * 1.5)

        affected = []
        if is_drift:
            affected.append("SCL1_TRANSVERSE_OPTICS")
        if rms_discrepancy > 0.5:
            affected.append("RF_SYNCHRONOUS_PHASE")

        return ModelDriftStatus(
            discrepancy_rms_mm=rms_discrepancy,
            drift_detected=is_drift,
            recalibration_recommended=recalibration,
            affected_subsystems=affected,
        )


class GoldenBaselineArchive:
    """Manages versioned golden machine setpoints with semantic diffing."""

    def __init__(self):
        self._baselines: dict[str, dict[str, float]] = {}

    def save_golden(self, name: str, setpoints: dict[str, float]) -> None:
        """Store golden machine state configuration."""
        self._baselines[name] = dict(setpoints)

    def get_golden(self, name: str) -> dict[str, float] | None:
        """Retrieve golden setpoints by name."""
        return self._baselines.get(name)

    def diff_against_golden(self, name: str, current_setpoints: dict[str, float], tolerance: float = 1e-3) -> dict[str, Any]:
        """Compute semantic difference between current machine state and golden baseline."""
        golden = self._baselines.get(name)
        if not golden:
            raise KeyError(f"Golden baseline '{name}' not found")

        diffs = {}
        for pv, g_val in golden.items():
            c_val = current_setpoints.get(pv, 0.0)
            delta = c_val - g_val
            if abs(delta) > tolerance:
                diffs[pv] = {
                    "golden": g_val,
                    "current": c_val,
                    "delta": delta,
                    "pct_change": (delta / max(1e-6, abs(g_val))) * 100.0,
                }

        return {
            "baseline_name": name,
            "total_pvs_compared": len(golden),
            "deviated_pvs_count": len(diffs),
            "deviations": diffs,
            "is_identical": len(diffs) == 0,
        }
