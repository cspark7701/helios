"""HELIOS Standard Linac Commissioning Workflows.

Implements high-level multi-step commissioning and tuning routines:
1. SVD Closed-Loop Orbit Flattening Workflow.
2. RF Cavity Phase and Amplitude Calibration Scan Workflow.
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from helios.core.schemas import (
    AutonomyLevel,
    ExecutionPlan,
    PlanStep,
    SetpointBatch,
    SetpointTarget,
)
from helios.interfaces.channel_map import ChannelManager
from helios.optimization.algorithms import SVDOrbitCorrection
from helios.physics.lattice import Lattice


class OrbitCorrectionWorkflow:
    """End-to-end trajectory alignment workflow using SVD response matrix inversion."""

    def __init__(self, lattice: Lattice, channel_manager: ChannelManager):
        self.lattice = lattice
        self.channels = channel_manager

    def build_orbit_correction_plan(
        self,
        plan_id: str,
        section: str,
        steerer_names: List[str],
        bpm_names: List[str],
        measured_bpm_x: Dict[str, float],
        measured_bpm_y: Dict[str, float],
        singular_cutoff: float = 0.05,
    ) -> Tuple[ExecutionPlan, Dict[str, float]]:
        """Synthesize a complete Plan-First ExecutionPlan for orbit flattening."""
        # Compute ORM
        Rx, Ry = self.lattice.compute_orbit_response_matrix(
            steerer_names=steerer_names,
            bpm_names=bpm_names,
        )

        # Extract vectors
        x_meas = np.array([measured_bpm_x.get(b, 0.0) for b in bpm_names])
        y_meas = np.array([measured_bpm_y.get(b, 0.0) for b in bpm_names])

        # Solve horizontal and vertical delta kicks
        delta_kx, stats_x = SVDOrbitCorrection.calculate_correction(Rx, x_meas, singular_value_cutoff=singular_cutoff)
        delta_ky, stats_y = SVDOrbitCorrection.calculate_correction(Ry, y_meas, singular_value_cutoff=singular_cutoff)

        proposed_setpoints: Dict[str, float] = {}
        plan_steps: List[PlanStep] = []

        # Convert kicks to current setpoints (using ~ 1 A per 2 mrad conversion factor for low energy steerer)
        for j, s_name in enumerate(steerer_names):
            dev = self.channels.get_device(section, s_name.replace(f"{section}_", ""))
            pv = dev.setpoint_pv if dev else f"{section}:PSC:{s_name}:CurrentSet"

            # Horizontal steerer
            curr_x = float(delta_kx[j] * 0.5)
            proposed_setpoints[pv] = curr_x

            # Step in execution plan
            plan_steps.append(PlanStep(
                step_id=f"step_steer_{j+1}",
                name=f"Trim Steerer {s_name}",
                target_agent="HELIOS-Control",
                action="epics_caput",
                parameters={"pv": pv, "value": curr_x, "tolerance": 0.02},
                required_capabilities=["epics_caput_batch"],
            ))

        plan = ExecutionPlan(
            plan_id=plan_id,
            title=f"{section} Orbit Trajectory Correction",
            objective=f"Reduce RMS orbit from {stats_x['initial_rms_mm']:.2f} mm to projected {stats_x['predicted_rms_mm']:.2f} mm",
            autonomy_level=AutonomyLevel.SUPERVISED,
            steps=plan_steps,
            provenance_metadata={
                "initial_rms_x_mm": stats_x["initial_rms_mm"],
                "predicted_rms_x_mm": stats_x["predicted_rms_mm"],
                "initial_rms_y_mm": stats_y["initial_rms_mm"],
                "predicted_rms_y_mm": stats_y["predicted_rms_mm"],
            },
        )

        return plan, proposed_setpoints


class RFPhaseScanWorkflow:
    """Automated RF cavity phase scan for finding synchronous phase."""

    @staticmethod
    def generate_phase_grid(start_deg: float = -180.0, stop_deg: float = 180.0, step_deg: float = 30.0) -> List[float]:
        """Generate list of discrete phase angles to scan."""
        return list(np.arange(start_deg, stop_deg + step_deg / 2, step_deg))

    @staticmethod
    def fit_synchronous_phase(phase_readings: Dict[float, float]) -> Tuple[float, float]:
        """Fit phase vs beam energy or transmission to locate maximum gain point.

        Returns:
            (best_phase_deg, max_metric)
        """
        if not phase_readings:
            return 0.0, 0.0
        best_phase = max(phase_readings, key=phase_readings.get)
        return float(best_phase), float(phase_readings[best_phase])
