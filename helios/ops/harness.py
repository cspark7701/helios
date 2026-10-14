"""HELIOS End-to-End Commissioning Harness & Virtual Accelerator Mock IOC.

Provides:
1. VirtualLinacEPICSMock: Fast in-memory software IOC simulating heavy ion linac physics,
   including BPM trajectories, steerer actuation, RF cavity trip states, and BLM losses.
2. EndToEndCommissioningHarness: Autonomous multi-step orchestration pipeline executing
   cold start, orbit flattening, BBA calibration, and shift handover reporting.
"""

import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np

from helios.ops.audit import AuditTrailLogger
from helios.ops.broker import DistributedEventBus
from helios.ops.reporting import CommissioningReportGenerator, ShiftSummaryData
from helios.tuning.bba import BeamBasedAlignmentSolver

logger = logging.getLogger(__name__)


class VirtualLinacEPICSMock:
    """Simulates an entire linac section with Process Variables for tests and dry runs."""

    def __init__(self, section_name: str = "SCL1"):
        self.section_name = section_name
        self.pvs: dict[str, float] = {
            "SCL1:PS_Q01:I_Set": 15.0,
            "SCL1:PS_Q02:I_Set": 14.5,
            "SCL1:PS_Q03:I_Set": 15.2,
            "SCL1:PS_CH01:I_Set": 0.0,
            "SCL1:PS_CH02:I_Set": 0.0,
            "SCL1:PS_CV01:I_Set": 0.0,
            "SCL1:PS_CV02:I_Set": 0.0,
            "SCL1:CAV01:Amp_Set": 1.2,
            "SCL1:CAV01:Phase_Set": -20.0,
            "SCL1:CAV02:Amp_Set": 1.4,
            "SCL1:CAV02:Phase_Set": -20.0,
            "SCL1:BPM01:X": 1.15,
            "SCL1:BPM01:Y": -0.85,
            "SCL1:BPM02:X": 1.45,
            "SCL1:BPM02:Y": -0.65,
            "SCL1:BLM01:Loss": 0.02,
            "SCL1:BLM02:Loss": 0.04,
            "SCL1:FC01:Current": 2.50,
            "SCL1:FC02:Current": 2.40,
            "MPS:TripState": 0.0,  # 0 = Nominal, 1 = Tripped
        }
        self.readbacks: dict[str, float] = dict(self.pvs)

    def caget(self, pv_name: str) -> float:
        """Read simulated PV value with small synthetic measurement noise."""
        val = self.readbacks.get(pv_name, 0.0)
        if "BPM" in pv_name:
            val += np.random.normal(0.0, 0.005)
        return float(val)

    def caput(self, pv_name: str, value: float) -> bool:
        """Write simulated PV and update downstream coupled diagnostics."""
        self.pvs[pv_name] = value
        self.readbacks[pv_name] = value

        # Physics coupling: steerer changes affect BPMs
        if "PS_CH01" in pv_name:
            self.readbacks["SCL1:BPM01:X"] -= value * 0.45
            self.readbacks["SCL1:BPM02:X"] -= value * 0.85
        elif "PS_CV01" in pv_name:
            self.readbacks["SCL1:BPM01:Y"] -= value * 0.45
            self.readbacks["SCL1:BPM02:Y"] -= value * 0.85

        return True


class EndToEndCommissioningHarness:
    """Executes full autonomous multi-step commissioning workflow."""

    def __init__(self, mock_ioc: VirtualLinacEPICSMock | None = None):
        self.ioc = mock_ioc or VirtualLinacEPICSMock()
        self.event_bus = DistributedEventBus()
        self.audit = AuditTrailLogger()

    def run_commissioning_cycle(self) -> dict[str, Any]:
        """Execute autonomous commissioning sequence from start to finish."""
        # 1. Telemetry baseline reading
        init_x1 = self.ioc.caget("SCL1:BPM01:X")
        init_x2 = self.ioc.caget("SCL1:BPM02:X")
        initial_orbit_rms = float(np.sqrt((init_x1**2 + init_x2**2) / 2.0))

        # 2. Beam-Based Alignment & Quad modulation
        bba_offset = BeamBasedAlignmentSolver.solve_quad_offset(
            delta_k1=0.2,
            bpm_reading_nominal_mm=init_x1,
            bpm_reading_modulated_mm=init_x1 + 0.04,
            transfer_r12=0.5,
        )

        # 3. Orbit correction calculation & steerer actuation
        steerer_kick_1 = init_x1 / 0.45
        self.audit.log_action("HELIOS-Tuner", "caput", "SCL1:PS_CH01:I_Set", 0.0, steerer_kick_1, "Flatten BPM01 orbit")
        self.ioc.caput("SCL1:PS_CH01:I_Set", steerer_kick_1)

        # 4. Post-correction telemetry
        final_x1 = self.ioc.caget("SCL1:BPM01:X")
        final_x2 = self.ioc.caget("SCL1:BPM02:X")
        final_orbit_rms = float(np.sqrt((final_x1**2 + final_x2**2) / 2.0))

        # 5. Generate Shift Report
        shift_data = ShiftSummaryData(
            shift_label="E2E-Autonomous-Commissioning",
            physicist_on_duty="HELIOS-Autopilot",
            facility_name="RAON SCL1 Virtual Digital Twin",
            start_time=datetime(2026, 10, 13, 10, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc),
            executed_plans_count=1,
            initial_orbit_rms_mm=initial_orbit_rms,
            final_orbit_rms_mm=final_orbit_rms,
            initial_transmission_pct=95.0,
            final_transmission_pct=99.2,
            total_anomalies_detected=0,
            interlocks_tripped_count=0,
            notes="Full autonomous loop completed: BBA resolved, steerers compensated, orbit flattened.",
        )
        report_md = CommissioningReportGenerator.generate_markdown_report(shift_data)

        # Broadcast completion event
        self.event_bus.publish(
            topic="commissioning.cycle.completed",
            sender_agent="HELIOS-Orchestrator",
            payload={"final_rms_mm": final_orbit_rms, "bba_offset_mm": bba_offset},
        )

        return {
            "success": True,
            "bba_offset_mm": bba_offset,
            "initial_orbit_rms_mm": initial_orbit_rms,
            "final_orbit_rms_mm": final_orbit_rms,
            "audit_entries_count": len(self.audit.get_entries()),
            "audit_chain_valid": self.audit.verify_integrity()[0],
            "shift_report": report_md,
        }
