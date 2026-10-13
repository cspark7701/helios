"""HELIOS Autonomous RF Conditioning and Superconducting Cavity Processing.

Implements:
1. Automated RF power and pulse-width conditioning ramp sequencer with vacuum interlocks.
2. Multipacting band detection, fast breakthroughs, and electron pick-up suppression.
3. Dual-actuator cavity resonance tracking (stepper motor + piezo) under microphonics.
"""

from dataclasses import dataclass
from enum import Enum
import logging
from typing import Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger(__name__)


class ConditioningState(str, Enum):
    IDLE = "IDLE"
    RAMPING = "RAMPING"
    DWELLING = "DWELLING"
    MULTIPACTING_DETECTED = "MULTIPACTING_DETECTED"
    FAST_JUMPING = "FAST_JUMPING"
    VACUUM_RECOVERY = "VACUUM_RECOVERY"
    COMPLETED = "COMPLETED"
    TRIPPED = "TRIPPED"


@dataclass
class RFConditioningStepResult:
    """Status update from a single conditioning control step."""
    power_kw: float
    pulse_width_us: float
    repetition_rate_hz: float
    vacuum_mbar: float
    electron_current_ua: float
    state: ConditioningState
    action_taken: str


@dataclass
class ResonanceTrackingResult:
    """Closed-loop resonance frequency tuner status."""
    phase_error_deg: float
    stepper_position_steps: int
    piezo_voltage_v: float
    frequency_detuning_hz: float
    quench_risk: bool


class AutonomousRFConditioner:
    """Manages progressive RF pulse power ramping with vacuum and multipacting safeguards."""

    def __init__(
        self,
        cavity_id: str,
        target_power_kw: float = 20.0,
        max_vacuum_mbar: float = 1e-7,
        recovery_vacuum_mbar: float = 5e-8,
        multipacting_threshold_ua: float = 0.5,
    ):
        self.cavity_id = cavity_id
        self.target_power_kw = target_power_kw
        self.max_vacuum_mbar = max_vacuum_mbar
        self.recovery_vacuum_mbar = recovery_vacuum_mbar
        self.multipacting_threshold_ua = multipacting_threshold_ua

        # Current setpoints
        self.current_power_kw = 0.1
        self.current_pulse_width_us = 50.0
        self.current_rep_rate_hz = 10.0
        self.state = ConditioningState.IDLE
        self.dwell_counter = 0

    def step(self, measured_vacuum_mbar: float, electron_pickup_ua: float) -> RFConditioningStepResult:
        """Execute one autonomous conditioning control iteration."""
        # 1. Vacuum interlock check
        if measured_vacuum_mbar > self.max_vacuum_mbar:
            self.state = ConditioningState.VACUUM_RECOVERY
            self.current_power_kw = max(0.1, self.current_power_kw * 0.7)
            action = f"Vacuum spike ({measured_vacuum_mbar:.2e} mbar) > threshold. Backed off power to {self.current_power_kw:.2f} kW."
            return RFConditioningStepResult(
                power_kw=self.current_power_kw,
                pulse_width_us=self.current_pulse_width_us,
                repetition_rate_hz=self.current_rep_rate_hz,
                vacuum_mbar=measured_vacuum_mbar,
                electron_current_ua=electron_pickup_ua,
                state=self.state,
                action_taken=action,
            )

        if self.state == ConditioningState.VACUUM_RECOVERY:
            if measured_vacuum_mbar < self.recovery_vacuum_mbar:
                self.state = ConditioningState.RAMPING
                action = f"Vacuum restored to {measured_vacuum_mbar:.2e} mbar. Resuming ramp."
            else:
                action = f"Dwelling in vacuum recovery ({measured_vacuum_mbar:.2e} mbar)."
                return RFConditioningStepResult(
                    power_kw=self.current_power_kw,
                    pulse_width_us=self.current_pulse_width_us,
                    repetition_rate_hz=self.current_rep_rate_hz,
                    vacuum_mbar=measured_vacuum_mbar,
                    electron_current_ua=electron_pickup_ua,
                    state=self.state,
                    action_taken=action,
                )

        # 2. Multipacting barrier detection
        if electron_pickup_ua > self.multipacting_threshold_ua:
            self.state = ConditioningState.FAST_JUMPING
            # Fast power jump (+25%) to traverse multipacting resonance zone quickly
            self.current_power_kw = min(self.target_power_kw, self.current_power_kw * 1.25)
            action = f"Multipacting detected ({electron_pickup_ua:.2f} uA). Fast power jump to {self.current_power_kw:.2f} kW to punch through barrier."
            return RFConditioningStepResult(
                power_kw=self.current_power_kw,
                pulse_width_us=self.current_pulse_width_us,
                repetition_rate_hz=self.current_rep_rate_hz,
                vacuum_mbar=measured_vacuum_mbar,
                electron_current_ua=electron_pickup_ua,
                state=self.state,
                action_taken=action,
            )

        # 3. Normal Power / Pulse Ramp
        if self.current_power_kw < self.target_power_kw:
            self.state = ConditioningState.RAMPING
            self.current_power_kw = min(self.target_power_kw, self.current_power_kw + 0.5)
            action = f"Incremented forward power to {self.current_power_kw:.2f} kW."
        elif self.current_pulse_width_us < 1000.0:
            self.state = ConditioningState.RAMPING
            self.current_pulse_width_us = min(1000.0, self.current_pulse_width_us + 50.0)
            action = f"Extended pulse width to {self.current_pulse_width_us:.1f} us at full power."
        else:
            self.state = ConditioningState.COMPLETED
            action = f"Cavity {self.cavity_id} reached full conditioned setpoint ({self.target_power_kw:.1f} kW, {self.current_pulse_width_us:.0f} us)."

        return RFConditioningStepResult(
            power_kw=self.current_power_kw,
            pulse_width_us=self.current_pulse_width_us,
            repetition_rate_hz=self.current_rep_rate_hz,
            vacuum_mbar=measured_vacuum_mbar,
            electron_current_ua=electron_pickup_ua,
            state=self.state,
            action_taken=action,
        )


class CavityResonanceTracker:
    """Dual-actuator (slow coarse stepper motor + fast fine piezoelectric) resonance controller."""

    def __init__(
        self,
        cavity_id: str,
        stepper_sensitivity_hz_per_step: float = 1.5,
        piezo_sensitivity_hz_per_v: float = 12.0,
        max_piezo_voltage_v: float = 100.0,
    ):
        self.cavity_id = cavity_id
        self.stepper_sensitivity = stepper_sensitivity_hz_per_step
        self.piezo_sensitivity = piezo_sensitivity_hz_per_v
        self.max_piezo_voltage = max_piezo_voltage_v

        self.current_stepper_pos = 0
        self.current_piezo_v = 50.0  # Center biased

    def track(self, phase_error_deg: float) -> ResonanceTrackingResult:
        """Compensate phase error / detuning using fast piezo and coarse stepper motor."""
        # Sensitivity: ~ 2.0 Hz per degree of phase error
        detuning_hz = phase_error_deg * 2.0

        # Fine piezo correction
        delta_piezo_v = detuning_hz / self.piezo_sensitivity
        new_piezo_v = np.clip(self.current_piezo_v + delta_piezo_v, 0.0, self.max_piezo_voltage)

        # If piezo nears saturation limits (< 15V or > 85V), offload to stepper
        if new_piezo_v < 15.0 or new_piezo_v > 85.0:
            excess_v = new_piezo_v - 50.0
            stepper_steps = int(np.round((excess_v * self.piezo_sensitivity) / self.stepper_sensitivity))
            self.current_stepper_pos += stepper_steps
            new_piezo_v = 50.0  # Reset piezo to center bias

        self.current_piezo_v = float(new_piezo_v)
        quench_risk = bool(abs(detuning_hz) > 250.0)

        return ResonanceTrackingResult(
            phase_error_deg=phase_error_deg,
            stepper_position_steps=self.current_stepper_pos,
            piezo_voltage_v=self.current_piezo_v,
            frequency_detuning_hz=detuning_hz,
            quench_risk=quench_risk,
        )
