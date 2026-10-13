"""HELIOS Phase 44: Geodetic Survey & Mechanical Girder Alignment Integration.

Ingests 3D laser tracker coordinates (Leica / Hexagon AT403 survey systems) and calculates
optimal motorized girder mechanical adjustments (cams/jacks) to realign multi-magnet linac
girders and minimize required orbit corrector currents.
"""

from typing import Dict, List, Any, Optional, Tuple
import math
import numpy as np
from pydantic import BaseModel, Field


class MagnetFiducialMeasurement(BaseModel):
    """Laser tracker measured position and orientation of a linac magnet fiducial."""
    element_id: str
    girder_id: str
    s_longitudinal_m: float
    measured_x_mm: float
    measured_y_mm: float
    measured_z_mm: float
    pitch_mrad: float = 0.0
    yaw_mrad: float = 0.0
    roll_mrad: float = 0.0
    design_x_mm: float = 0.0
    design_y_mm: float = 0.0
    design_z_mm: float = 0.0


class GirderMoverAdjustment(BaseModel):
    """Motorized cam/jack displacements to realign a multi-magnet girder."""
    girder_id: str
    shift_dx_mm: float
    shift_dy_mm: float
    pitch_dtheta_mrad: float
    yaw_dpsi_mrad: float
    roll_dphi_mrad: float
    max_residual_error_mm: float
    rms_residual_error_mm: float
    projected_corrector_current_reduction_percent: float


class LaserTrackerSurveyAnalyzer:
    """Processes laser tracker geodetic data and computes girder realignment kinematics."""

    @staticmethod
    def evaluate_misalignments(
        measurements: List[MagnetFiducialMeasurement]
    ) -> Dict[str, Dict[str, float]]:
        """Calculate deviations relative to ideal theoretical linac beam axis."""
        deviations = {}
        for m in measurements:
            dx = m.measured_x_mm - m.design_x_mm
            dy = m.measured_y_mm - m.design_y_mm
            dz = m.measured_z_mm - m.design_z_mm
            deviations[m.element_id] = {
                "delta_x_mm": round(dx, 4),
                "delta_y_mm": round(dy, 4),
                "delta_z_mm": round(dz, 4),
                "pitch_mrad": round(m.pitch_mrad, 4),
                "yaw_mrad": round(m.yaw_mrad, 4),
                "roll_mrad": round(m.roll_mrad, 4),
            }
        return deviations

    def optimize_girder_realignment(
        self,
        girder_id: str,
        girder_elements: List[MagnetFiducialMeasurement]
    ) -> GirderMoverAdjustment:
        """Find rigid-body displacement (dx, dy, pitch, yaw) minimizing RMS element offsets."""
        if not girder_elements:
            raise ValueError("No elements provided for girder")

        s_coords = np.array([e.s_longitudinal_m for e in girder_elements])
        s_center = float(np.mean(s_coords))
        ds = s_coords - s_center

        dx_meas = np.array([e.measured_x_mm - e.design_x_mm for e in girder_elements])
        dy_meas = np.array([e.measured_y_mm - e.design_y_mm for e in girder_elements])

        # Rigid body model in horizontal: delta_x(s) ~ shift_x + yaw * ds
        # Fit shift_x and yaw via linear regression:
        # We want girder correction to cancel measurement: correction = -fit
        fit_x = np.polyfit(ds, dx_meas, 1)  # [slope (yaw), intercept (shift_x)]
        fit_y = np.polyfit(ds, dy_meas, 1)  # [slope (pitch), intercept (shift_y)]

        shift_dx = -float(fit_x[1])
        yaw_dpsi = -float(fit_x[0])  # rad -> mrad if ds in m and x in mm, 1 mm/m = 1 mrad
        shift_dy = -float(fit_y[1])
        pitch_dtheta = -float(fit_y[0])
        roll_dphi = -float(np.mean([e.roll_mrad for e in girder_elements]))

        # Residual deviations after rigid girder mover adjustment
        res_x = dx_meas + (shift_dx + yaw_dpsi * ds)
        res_y = dy_meas + (shift_dy + pitch_dtheta * ds)
        res_tot = np.sqrt(res_x ** 2 + res_y ** 2)

        rms_res = float(np.sqrt(np.mean(res_tot ** 2)))
        max_res = float(np.max(res_tot))

        # Initial offset before correction
        init_rms = float(np.sqrt(np.mean(dx_meas ** 2 + dy_meas ** 2)))
        reduction = max(0.0, min(100.0, (1.0 - rms_res / max(1e-6, init_rms)) * 100.0))

        return GirderMoverAdjustment(
            girder_id=girder_id,
            shift_dx_mm=round(shift_dx, 4),
            shift_dy_mm=round(shift_dy, 4),
            pitch_dtheta_mrad=round(pitch_dtheta, 4),
            yaw_dpsi_mrad=round(yaw_dpsi, 4),
            roll_dphi_mrad=round(roll_dphi, 4),
            max_residual_error_mm=round(max_res, 4),
            rms_residual_error_mm=round(rms_res, 4),
            projected_corrector_current_reduction_percent=round(reduction, 2)
        )
