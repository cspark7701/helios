"""HELIOS Phase 37: Predictive Quench Interlock & Machine Protection (MPS).

Analyzes high-speed time-series telemetry from superconducting RF (SRF) cryomodules
and superconducting magnets (helium bath temperature, pressure, RF reflected power)
to forecast impending thermal quenches 100-500 ms before hardware trip.
"""

from enum import Enum

import numpy as np
from pydantic import BaseModel, Field


class QuenchRiskLevel(str, Enum):
    NOMINAL = "nominal"
    WARNING = "warning"
    CRITICAL_IMPENDING_QUENCH = "critical_impending_quench"


class CryomoduleTelemetry(BaseModel):
    """High-speed cryomodule telemetry sample."""
    timestamp_ms: float
    cavity_id: str
    helium_bath_temp_K: float = Field(..., ge=1.5, le=10.0)
    helium_pressure_mbar: float = Field(..., ge=20.0, le=50.0)
    forward_power_kW: float = Field(..., ge=0.0)
    reflected_power_kW: float = Field(..., ge=0.0)
    piezo_voltage_V: float = Field(default=50.0)


class QuenchPredictionResult(BaseModel):
    """Predictive quench assessment and proactive mitigation action."""
    cavity_id: str
    risk_level: QuenchRiskLevel
    quench_probability: float = Field(..., ge=0.0, le=1.0)
    estimated_time_to_quench_ms: float | None = None
    temperature_drift_rate_K_per_s: float
    reflected_power_ratio: float
    recommended_action: str


class PredictiveQuenchInterlock:
    """Detects pre-quench signatures using thermal rate and RF power reflection trends."""

    def __init__(
        self,
        nominal_temp_K: float = 2.05,
        max_allowed_temp_K: float = 2.20,
        temp_rate_threshold_K_per_s: float = 0.15,
        refl_power_ratio_threshold: float = 0.35
    ):
        self.nominal_temp_K = nominal_temp_K
        self.max_temp_K = max_allowed_temp_K
        self.rate_threshold = temp_rate_threshold_K_per_s
        self.refl_ratio_threshold = refl_power_ratio_threshold

    def evaluate_telemetry_window(
        self,
        telemetry_window: list[CryomoduleTelemetry]
    ) -> QuenchPredictionResult:
        """Analyze a sliding window of cryomodule telemetry samples (typically 50-200 ms)."""
        if not telemetry_window:
            raise ValueError("Telemetry window cannot be empty")

        cavity_id = telemetry_window[-1].cavity_id
        times_s = np.array([t.timestamp_ms for t in telemetry_window]) * 1e-3
        temps = np.array([t.helium_bath_temp_K for t in telemetry_window])
        fwd_p = np.array([t.forward_power_kW for t in telemetry_window])
        refl_p = np.array([t.reflected_power_kW for t in telemetry_window])

        latest = telemetry_window[-1]

        # Calculate reflected power ratio
        eps = 1e-6
        mean_fwd = max(float(np.mean(fwd_p)), eps)
        mean_refl = float(np.mean(refl_p))
        refl_ratio = mean_refl / mean_fwd

        # Calculate dT/dt slope using linear regression if enough samples
        if len(times_s) >= 2 and (times_s[-1] - times_s[0]) > 1e-6:
            dt = times_s[-1] - times_s[0]
            slope = (temps[-1] - temps[0]) / dt
        else:
            slope = 0.0

        # Assess risk
        temp_margin = self.max_temp_K - latest.helium_bath_temp_K
        
        prob = 0.0
        # Contribution from current temp
        if latest.helium_bath_temp_K > self.nominal_temp_K:
            prob += 0.3 * min(1.0, (latest.helium_bath_temp_K - self.nominal_temp_K) / (self.max_temp_K - self.nominal_temp_K))

        # Contribution from heating rate
        if slope > 0.0:
            prob += 0.4 * min(1.0, slope / self.rate_threshold)

        # Contribution from reflected power spike
        if refl_ratio > 0.1:
            prob += 0.3 * min(1.0, refl_ratio / self.refl_ratio_threshold)

        prob = min(1.0, max(0.0, prob))

        # Determine level and time to quench
        time_to_quench = None
        if slope > 1e-4 and temp_margin > 0:
            time_to_quench = round((temp_margin / slope) * 1000.0, 1)

        if prob >= 0.75 or (time_to_quench is not None and time_to_quench < 500.0):
            level = QuenchRiskLevel.CRITICAL_IMPENDING_QUENCH
            action = "PREEMPTIVE_BEAM_CUT_AND_RF_RAMPDOWN"
        elif prob >= 0.40 or slope > (self.rate_threshold * 0.5):
            level = QuenchRiskLevel.WARNING
            action = "THROTTLE_RF_POWER_AND_INCREASE_CRYO_JT_VALVE"
        else:
            level = QuenchRiskLevel.NOMINAL
            action = "CONTINUE_NORMAL_OPERATION"

        return QuenchPredictionResult(
            cavity_id=cavity_id,
            risk_level=level,
            quench_probability=round(prob, 3),
            estimated_time_to_quench_ms=time_to_quench,
            temperature_drift_rate_K_per_s=round(float(slope), 4),
            reflected_power_ratio=round(refl_ratio, 4),
            recommended_action=action
        )
