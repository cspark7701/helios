"""HELIOS Magnet Power Supply Trip Recovery and Fallback Steering.

Isolates tripped magnetic elements, reconstructs the control response matrix,
and recalculates compensatory setpoints across remaining operational magnets.
"""

import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MagnetRecoveryResult:
    """Outcome of magnet power supply trip compensation."""
    tripped_pv: str
    active_compensators: list[str]
    corrective_setpoints: dict[str, float]
    predicted_residual_rms_mm: float
    success: bool


class MagnetPowerSupplyRecoverer:
    """Recalculates beam centering with reduced actuator set upon magnet trip."""

    def __init__(self, default_tolerance_mm: float = 0.20):
        self.default_tolerance_mm = default_tolerance_mm

    def recover_tripped_steerer(
        self,
        tripped_pv: str,
        all_steerers: list[str],
        bpm_readings_mm: dict[str, float],
        response_matrix: np.ndarray | None = None,
    ) -> MagnetRecoveryResult:
        """Re-steer orbit around a tripped steering magnet using remaining healthy steerers."""
        if tripped_pv not in all_steerers:
            raise ValueError(f"Tripped PV {tripped_pv} not in provided steerer list {all_steerers}")

        # Healthy steerers
        healthy_steerers = [pv for pv in all_steerers if pv != tripped_pv]
        num_healthy = len(healthy_steerers)
        num_bpms = len(bpm_readings_mm)

        y = np.array(list(bpm_readings_mm.values()))

        # Build or slice response matrix
        if response_matrix is not None and response_matrix.shape == (num_bpms, len(all_steerers)):
            tripped_idx = all_steerers.index(tripped_pv)
            healthy_indices = [i for i in range(len(all_steerers)) if i != tripped_idx]
            R_sub = response_matrix[:, healthy_indices]
        else:
            # Synthetic response matrix for fallback
            R_sub = np.ones((num_bpms, num_healthy)) * 0.4
            for i in range(min(num_bpms, num_healthy)):
                R_sub[i, i] = 1.2

        # SVD Pseudo-inverse solve: delta_u = - R_sub^+ * y
        U, S, Vt = np.linalg.svd(R_sub, full_matrices=False)
        S_inv = np.diag([1.0 / s if s > 1e-4 else 0.0 for s in S])
        delta_u = - (Vt.T @ S_inv @ U.T) @ y

        # Clip within physical power supply bounds
        delta_u = np.clip(delta_u, -3.0, 3.0)

        # Predicted residual: y_res = y + R_sub * delta_u
        y_residual = y + (R_sub @ delta_u)
        res_rms = float(np.sqrt(np.mean(y_residual ** 2)))

        corrective_dict = {tripped_pv: 0.0}  # Force tripped supply to 0
        for pv, kick in zip(healthy_steerers, delta_u):
            corrective_dict[pv] = float(kick)

        return MagnetRecoveryResult(
            tripped_pv=tripped_pv,
            active_compensators=healthy_steerers,
            corrective_setpoints=corrective_dict,
            predicted_residual_rms_mm=res_rms,
            success=res_rms <= self.default_tolerance_mm * 2.0,
        )
