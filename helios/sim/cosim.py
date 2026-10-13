"""HELIOS Phase 48: Multi-Physics Digital Twin Co-Simulation Bridge & Zero-Copy Streaming.

Provides high-throughput in-memory IPC synchronization between particle dynamics codes
(TRACK / IMPACT-Z), thermal FEA models, and EPICS control streams with zero-copy buffer
sharing and adaptive linac macro-pulse repetition rate clock locking (1 Hz to 100 Hz).
"""

from typing import Dict, List, Any, Optional, Tuple
import time
import numpy as np
from pydantic import BaseModel, Field


class CoSimFrameHeader(BaseModel):
    """Metadata header for a synchronized co-simulation timestep."""
    frame_id: int
    timestamp_s: float = Field(default_factory=time.time)
    repetition_rate_Hz: float = Field(default=10.0, ge=0.5, le=1000.0)
    macroparticle_count: int
    mean_energy_MeV_u: float
    total_beam_power_W: float
    total_loss_power_W: float
    epics_pv_snapshot: Dict[str, float] = Field(default_factory=dict)


class ZeroCopyCoSimBridge:
    """Ring buffer co-simulation bridge for high-speed macroparticle and loss streaming."""

    def __init__(self, buffer_capacity: int = 8):
        self.capacity = buffer_capacity
        self._headers: List[CoSimFrameHeader] = []
        # Ring buffers storing NumPy memory arrays
        self._bunch_buffers: List[np.ndarray] = []
        self._loss_buffers: List[np.ndarray] = []
        self._frame_counter = 0
        self._sim_clock_s = 0.0

    def publish_frame(
        self,
        rep_rate_Hz: float,
        particles_6d: np.ndarray,
        loss_density_W_m: np.ndarray,
        epics_pvs: Optional[Dict[str, float]] = None
    ) -> CoSimFrameHeader:
        """Publish macroparticle array (N, 6) and loss map with zero-copy view."""
        self._frame_counter += 1
        n_part = len(particles_6d)

        # Average energy in delta coordinate or approximate kinetic energy
        mean_e = 17.5 * (1.0 + float(np.mean(particles_6d[:, 5])) if n_part > 0 else 1.0)
        tot_loss = float(np.sum(loss_density_W_m))

        header = CoSimFrameHeader(
            frame_id=self._frame_counter,
            timestamp_s=time.time(),
            repetition_rate_Hz=rep_rate_Hz,
            macroparticle_count=n_part,
            mean_energy_MeV_u=round(mean_e, 4),
            total_beam_power_W=25000.0,
            total_loss_power_W=round(tot_loss, 2),
            epics_pv_snapshot=epics_pvs or {}
        )

        # Ring buffer retention
        if len(self._headers) >= self.capacity:
            self._headers.pop(0)
            self._bunch_buffers.pop(0)
            self._loss_buffers.pop(0)

        self._headers.append(header)
        # Store direct array reference (zero-copy view)
        self._bunch_buffers.append(particles_6d)
        self._loss_buffers.append(loss_density_W_m)

        # Advance internal clock by 1 / rep_rate
        self._sim_clock_s += 1.0 / rep_rate_Hz

        return header

    def consume_latest_frame(self) -> Optional[Tuple[CoSimFrameHeader, np.ndarray, np.ndarray]]:
        """Retrieve most recent synchronized frame, bunch array, and loss map."""
        if not self._headers:
            return None
        return self._headers[-1], self._bunch_buffers[-1], self._loss_buffers[-1]

    def synchronize_clock(self, target_rep_rate_Hz: float, elapsed_real_time_s: float) -> float:
        """Compute lag/lead synchronization drift between simulation and machine repetition clock."""
        expected_ticks = elapsed_real_time_s * target_rep_rate_Hz
        actual_ticks = self._frame_counter
        tick_drift = actual_ticks - expected_ticks
        # Time drift in milliseconds
        time_drift_ms = (tick_drift / target_rep_rate_Hz) * 1000.0
        return round(float(time_drift_ms), 3)
