"""HELIOS Rollback Controller and Checkpoint Stack.

Maintains pre-actuation baseline setpoints and executes atomic rollback
in the event of unexpected beam losses, trips, or operator aborts.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Dict, List, Optional
import uuid

from helios.interfaces.base import BaseControlInterface

logger = logging.getLogger(__name__)


@dataclass
class RollbackCheckpoint:
    """Stored snapshot of machine setpoints for restoration."""
    checkpoint_id: str
    label: str
    timestamp: datetime
    setpoints: Dict[str, float]


class RollbackController:
    """Manages baseline checkpoints and executes hardware rollbacks."""

    def __init__(self, control_interface: BaseControlInterface, max_stack_size: int = 20):
        self.control = control_interface
        self.max_stack_size = max_stack_size
        self._stack: deque[RollbackCheckpoint] = deque(maxlen=max_stack_size)

    def create_checkpoint(self, label: str, setpoints: Dict[str, float]) -> str:
        """Register a setpoint dictionary as a new rollback checkpoint."""
        cp_id = str(uuid.uuid4())[:8]
        cp = RollbackCheckpoint(
            checkpoint_id=cp_id,
            label=label,
            timestamp=datetime.now(timezone.utc),
            setpoints=dict(setpoints),
        )
        self._stack.append(cp)
        logger.info(f"Registered rollback checkpoint '{label}' (ID: {cp_id}) with {len(setpoints)} setpoints")
        return cp_id

    def capture_baseline_from_hardware(self, label: str, pvs: List[str]) -> str:
        """Query active hardware setpoints and save as baseline checkpoint."""
        current_vals = {}
        for pv in pvs:
            val = self.control.get(pv)
            if val is not None:
                current_vals[pv] = float(val)

        return self.create_checkpoint(label=label, setpoints=current_vals)

    def trigger_rollback(self, checkpoint_id: Optional[str] = None) -> bool:
        """Restore machine to target or most recent checkpoint.

        Returns:
            True if rollback succeeded.
        """
        if not self._stack:
            logger.warning("Rollback triggered but checkpoint stack is empty!")
            return False

        target_cp = None
        if checkpoint_id:
            for cp in reversed(self._stack):
                if cp.checkpoint_id == checkpoint_id:
                    target_cp = cp
                    break
        else:
            target_cp = self._stack[-1]

        if not target_cp:
            logger.error(f"Checkpoint ID {checkpoint_id} not found in rollback stack!")
            return False

        logger.warning(f"ROLLBACK ACTIVATED: Restoring checkpoint '{target_cp.label}' ({len(target_cp.setpoints)} PVs)")
        results = self.control.put_many(target_cp.setpoints, wait=True)
        return all(results.values())

    def list_checkpoints(self) -> List[RollbackCheckpoint]:
        """List all available checkpoints from newest to oldest."""
        return list(reversed(self._stack))
