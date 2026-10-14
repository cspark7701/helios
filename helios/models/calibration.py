"""HELIOS Online Model Calibration Engine.

Calibrates digital twin and neural surrogate model parameters against live machine
telemetry (BPM orbits, beam sizes) using constrained least-squares / Bayesian optimization.
"""

import logging
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from helios.models.surrogate import NeuralLinacSurrogate

logger = logging.getLogger(__name__)


@dataclass
class CalibrationResult:
    """Outcome of online parameter calibration."""
    success: bool
    initial_rms_error_mm: float
    final_rms_error_mm: float
    calibrated_factors: dict[str, float]
    iterations: int
    message: str


class OnlineModelCalibrator:
    """Calibrates model parameters (effective quadrupole calibrations and initial Twiss)."""

    def __init__(self, surrogate: NeuralLinacSurrogate | None = None):
        self.surrogate = surrogate or NeuralLinacSurrogate()

    def calibrate_quadrupole_factors(
        self,
        measured_orbit_mm: dict[str, float],
        active_setpoints: dict[str, float],
        adjustable_quads: list[str] | None = None,
    ) -> CalibrationResult:
        """Calibrate effective quadrupole scaling factors against measured BPM orbit.

        Args:
            measured_orbit_mm: Dict of {'MEBT:BPM:01:X': 0.25, ...}
            active_setpoints: Current magnet and RF setpoints
            adjustable_quads: List of quadrupole PV names to calibrate
        """
        if adjustable_quads is not None:
            quads = adjustable_quads
        else:
            try:
                from helios.core.facility_config import FacilityConfig
                cfg = FacilityConfig.load_default("MEBT")
                quads = cfg.quadrupoles if cfg.quadrupoles else [
                    "MEBT:QUAD:01:B_SET",
                    "MEBT:QUAD:02:B_SET",
                    "MEBT:QUAD:03:B_SET",
                    "MEBT:QUAD:04:B_SET",
                ]
            except Exception:
                quads = [
                    "MEBT:QUAD:01:B_SET",
                    "MEBT:QUAD:02:B_SET",
                    "MEBT:QUAD:03:B_SET",
                    "MEBT:QUAD:04:B_SET",
                ]

        bpm_keys = list(measured_orbit_mm.keys())
        y_meas = np.array([measured_orbit_mm[k] for k in bpm_keys])

        # Baseline evaluation
        baseline_pred = self.surrogate.predict(active_setpoints)
        y_init = np.array(baseline_pred.centroid_x_mm[:len(y_meas)])
        initial_rms = float(np.sqrt(np.mean((y_meas - y_init) ** 2)))

        def loss_fn(factors: np.ndarray) -> float:
            test_setpoints = dict(active_setpoints)
            for q_name, factor in zip(quads, factors):
                test_setpoints[q_name] = active_setpoints.get(q_name, 1.0) * factor

            pred = self.surrogate.predict(test_setpoints)
            y_sim = np.array(pred.centroid_x_mm[:len(y_meas)])
            diff = y_meas - y_sim
            # Penalize deviation from nominal factor 1.0 (regularization)
            reg = 0.05 * np.sum((factors - 1.0) ** 2)
            return float(np.mean(diff ** 2) + reg)

        # Bounds: quad strength within +/- 15% of nominal calibration
        bounds = [(0.85, 1.15) for _ in quads]
        x0 = np.ones(len(quads))

        res = minimize(
            loss_fn,
            x0,
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 50, "ftol": 1e-5},
        )

        calibrated_dict = {q: float(factor) for q, factor in zip(quads, res.x)}

        # Evaluate final RMS
        final_setpoints = dict(active_setpoints)
        for q, factor in calibrated_dict.items():
            final_setpoints[q] = active_setpoints.get(q, 1.0) * factor
        final_pred = self.surrogate.predict(final_setpoints)
        y_final = np.array(final_pred.centroid_x_mm[:len(y_meas)])
        final_rms = float(np.sqrt(np.mean((y_meas - y_final) ** 2)))

        return CalibrationResult(
            success=res.success,
            initial_rms_error_mm=initial_rms,
            final_rms_error_mm=final_rms,
            calibrated_factors=calibrated_dict,
            iterations=int(res.nit),
            message=str(res.message),
        )
