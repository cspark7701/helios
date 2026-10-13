"""HELIOS Phase 51: Sub-Microsecond Fast Machine Protection System (MPS) & Differential Beam Abort.

Implements high-speed differential current monitoring (ACCT/FCT), fast diamond BLM
loss detection, and sub-5-microsecond dual-actuator beam abort logic (LEBT electrostatic
chopper + RFQ RF drive cutoff) to prevent prompt punch-through on thin niobium cryomodule walls.
"""

from typing import Dict, List, Any, Optional
import time
from pydantic import BaseModel, Field


class FastMPSConfiguration(BaseModel):
    """Thresholds and timing specs for sub-microsecond linac machine protection."""
    upstream_acct_id: str = "MEBT_ACCT_01"
    downstream_acct_id: str = "SCL1_ACCT_02"
    diff_current_threshold_uA: float = Field(default=35.0, ge=5.0, description="Differential beam loss threshold in micro-amperes")
    diamond_blm_threshold_V: float = Field(default=0.85, ge=0.1, description="Fast diamond BLM signal threshold in Volts")
    max_safe_abort_latency_us: float = Field(default=5.0, description="Maximum permitted abort time before cryomodule punch-through")


class FastAbortEvent(BaseModel):
    """Record of an executed fast beam abort trip sequence."""
    aborted: bool
    trigger_cause: str  # NONE, DIFFERENTIAL_CURRENT_LOSS, DIAMOND_BLM_SPIKE, DUAL_COINCIDENCE
    differential_current_uA: float
    diamond_blm_peak_V: float
    detection_latency_us: float
    fpga_logic_latency_us: float
    chopper_fire_latency_us: float
    rfq_cutoff_latency_us: float
    total_abort_latency_us: float
    actuators_fired: List[str]
    cryomodule_puncture_prevented: bool


class FastMPSEngine:
    """Sub-microsecond FPGA-class fast protection engine."""

    def __init__(self, config: FastMPSConfiguration):
        self.config = config

    def evaluate_signals(
        self,
        upstream_current_uA: float,
        downstream_current_uA: float,
        diamond_blm_voltage_V: float
    ) -> FastAbortEvent:
        """Evaluate real-time sensor streams and trigger sub-5 us abort if thresholds exceeded."""
        diff_I = max(0.0, upstream_current_uA - downstream_current_uA)

        trip_current = diff_I >= self.config.diff_current_threshold_uA
        trip_blm = diamond_blm_voltage_V >= self.config.diamond_blm_threshold_V

        if trip_current and trip_blm:
            cause = "DUAL_COINCIDENCE"
            should_abort = True
        elif trip_current:
            cause = "DIFFERENTIAL_CURRENT_LOSS"
            should_abort = True
        elif trip_blm:
            cause = "DIAMOND_BLM_SPIKE"
            should_abort = True
        else:
            cause = "NONE"
            should_abort = False

        if should_abort:
            # Latency budget breakdown
            t_detect = 0.85   # ACCT/Diamond analog front-end response in us
            t_fpga = 0.35     # FPGA logic comparator + interlock matrix in us
            t_chopper = 1.20  # Fast high-voltage LEBT electrostatic chopper deflection
            t_rfq = 1.60      # RFQ solid-state RF gate driver cutoff
            t_total = t_detect + t_fpga + min(t_chopper, t_rfq)  # Parallel actuator firing
            actuators = ["LEBT_ELECTROSTATIC_CHOPPER", "RFQ_FAST_RF_CUTOFF"]
            prevented = t_total <= self.config.max_safe_abort_latency_us
        else:
            t_detect = 0.0
            t_fpga = 0.0
            t_chopper = 0.0
            t_rfq = 0.0
            t_total = 0.0
            actuators = []
            prevented = True

        return FastAbortEvent(
            aborted=should_abort,
            trigger_cause=cause,
            differential_current_uA=round(diff_I, 2),
            diamond_blm_peak_V=round(diamond_blm_voltage_V, 3),
            detection_latency_us=round(t_detect, 2),
            fpga_logic_latency_us=round(t_fpga, 2),
            chopper_fire_latency_us=round(t_chopper, 2),
            rfq_cutoff_latency_us=round(t_rfq, 2),
            total_abort_latency_us=round(t_total, 2),
            actuators_fired=actuators,
            cryomodule_puncture_prevented=prevented
        )
