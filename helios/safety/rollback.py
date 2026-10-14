"""HELIOS Rollback Controller, Persistent Journal, and Emergency Panic Shutdown.

Maintains pre-actuation baseline setpoints, provides crash-resilient SQLite-persisted
checkpoints, and executes emergency machine shutdown protocols.
"""

import json
import logging
import sqlite3
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from helios.interfaces.base import BaseControlInterface

logger = logging.getLogger(__name__)


@dataclass
class RollbackCheckpoint:
    """Stored snapshot of machine setpoints for restoration."""
    checkpoint_id: str
    label: str
    timestamp: datetime
    setpoints: dict[str, float]


class PersistentRollbackJournal:
    """SQLite-backed persistent store for rollback checkpoints surviving process crashes."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    setpoints_json TEXT NOT NULL
                )
            """)
            conn.commit()

    def save_checkpoint(self, cp: RollbackCheckpoint) -> None:
        """Persist a checkpoint into the SQLite journal."""
        iso_ts = cp.timestamp.isoformat()
        sp_json = json.dumps(cp.setpoints)
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO checkpoints (checkpoint_id, label, timestamp, setpoints_json) VALUES (?, ?, ?, ?)",
                (cp.checkpoint_id, cp.label, iso_ts, sp_json),
            )
            conn.commit()

    def load_all_checkpoints(self) -> list[RollbackCheckpoint]:
        """Load all checkpoints ordered by timestamp ascending."""
        results = []
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT checkpoint_id, label, timestamp, setpoints_json FROM checkpoints ORDER BY timestamp ASC")
            for row in cursor.fetchall():
                cp_id, label, ts_str, sp_json = row
                ts = datetime.fromisoformat(ts_str)
                sps = json.loads(sp_json)
                results.append(RollbackCheckpoint(
                    checkpoint_id=cp_id,
                    label=label,
                    timestamp=ts,
                    setpoints={k: float(v) for k, v in sps.items()},
                ))
        return results

    def delete_checkpoint(self, checkpoint_id: str) -> None:
        """Remove a checkpoint from the journal."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("DELETE FROM checkpoints WHERE checkpoint_id = ?", (checkpoint_id,))
            conn.commit()


class RollbackController:
    """Manages baseline checkpoints, persistent journals, and emergency machine rollbacks."""

    def __init__(
        self,
        control_interface: BaseControlInterface,
        max_stack_size: int = 20,
        journal_path: Path | None = None,
    ):
        self.control = control_interface
        self.max_stack_size = max_stack_size
        self._stack: deque[RollbackCheckpoint] = deque(maxlen=max_stack_size)
        self.journal: PersistentRollbackJournal | None = None

        if journal_path:
            self.journal = PersistentRollbackJournal(journal_path)
            # Hydrate in-memory stack from disk
            persisted = self.journal.load_all_checkpoints()
            for cp in persisted:
                self._stack.append(cp)

    def create_checkpoint(self, label: str, setpoints: dict[str, float]) -> str:
        """Register a setpoint dictionary as a new rollback checkpoint."""
        cp_id = str(uuid.uuid4())[:8]
        cp = RollbackCheckpoint(
            checkpoint_id=cp_id,
            label=label,
            timestamp=datetime.now(timezone.utc),
            setpoints=dict(setpoints),
        )
        self._stack.append(cp)

        if self.journal:
            self.journal.save_checkpoint(cp)

        logger.info(f"Registered rollback checkpoint '{label}' (ID: {cp_id}) with {len(setpoints)} setpoints")
        return cp_id

    def capture_baseline_from_hardware(self, label: str, pvs: list[str]) -> str:
        """Query active hardware setpoints and save as baseline checkpoint."""
        current_vals = {}
        for pv in pvs:
            val = self.control.get(pv)
            if val is not None:
                current_vals[pv] = float(val)

        return self.create_checkpoint(label=label, setpoints=current_vals)

    def trigger_rollback(self, checkpoint_id: str | None = None) -> bool:
        """Restore machine to target or most recent checkpoint."""
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

    def panic_shutdown(self, pvs_to_zero: list[str] | None = None) -> bool:
        """EMERGENCY PANIC BUTTON: Instantly zero critical power and de-energize beamline."""
        if pvs_to_zero is not None:
            zero_targets = pvs_to_zero
        else:
            try:
                from helios.core.facility_config import FacilityConfig
                cfg = FacilityConfig.load_default("MEBT")
                zero_targets = cfg.panic_pvs if cfg.panic_pvs else [
                    "MEBT:CAV:01:AMP_SET",
                    "MEBT:CAV:02:AMP_SET",
                    "MEBT:DCH:01:I_SET",
                    "MEBT:DCV:01:I_SET",
                    "MEBT:DCH:02:I_SET",
                    "MEBT:DCV:02:I_SET",
                ]
            except Exception:
                zero_targets = [
                    "MEBT:CAV:01:AMP_SET",
                    "MEBT:CAV:02:AMP_SET",
                    "MEBT:DCH:01:I_SET",
                    "MEBT:DCV:01:I_SET",
                    "MEBT:DCH:02:I_SET",
                    "MEBT:DCV:02:I_SET",
                ]
        shutdown_setpoints = {pv: 0.0 for pv in zero_targets}
        logger.critical(f"EMERGENCY PANIC SHUTDOWN: Zeroing {len(shutdown_setpoints)} PVs immediately!")
        results = self.control.put_many(shutdown_setpoints, wait=True)
        return all(results.values())

    def list_checkpoints(self) -> list[RollbackCheckpoint]:
        """List all available checkpoints from newest to oldest."""
        return list(reversed(self._stack))
