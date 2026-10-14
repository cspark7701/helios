"""HELIOS Cryptographic Audit Trail and Regulatory Compliance Logging.

Maintains a tamper-evident, SHA-256 hash-chained ledger of all Process Variable
actuations, safety validations, and operator authorizations.
"""

import hashlib
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class AuditEntry:
    """Tamper-evident audit ledger record."""
    entry_id: int
    timestamp: datetime
    operator_id: str
    action: str
    pv_name: str
    previous_value: float
    new_value: float
    rationale: str
    prev_hash: str
    entry_hash: str

    def compute_hash(self) -> str:
        """Compute SHA-256 digest of record contents."""
        content = (
            f"{self.entry_id}|{self.timestamp.isoformat()}|{self.operator_id}|"
            f"{self.action}|{self.pv_name}|{self.previous_value:.6f}|"
            f"{self.new_value:.6f}|{self.rationale}|{self.prev_hash}"
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


class AuditTrailLogger:
    """Manages hash-chained audit logging ensuring regulatory compliance and non-repudiation."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path
        self._entries: list[AuditEntry] = []
        if self.db_path:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_sqlite()
            self._load_from_sqlite()

    def _init_sqlite(self) -> None:
        if not self.db_path:
            return
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_ledger (
                    entry_id INTEGER PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    operator_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    pv_name TEXT NOT NULL,
                    previous_value REAL NOT NULL,
                    new_value REAL NOT NULL,
                    rationale TEXT NOT NULL,
                    prev_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL
                )
            """)
            conn.commit()

    def _load_from_sqlite(self) -> None:
        if not self.db_path:
            return
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT entry_id, timestamp, operator_id, action, pv_name, previous_value, new_value, rationale, prev_hash, entry_hash FROM audit_ledger ORDER BY entry_id ASC")
            for row in cursor.fetchall():
                e = AuditEntry(
                    entry_id=row[0],
                    timestamp=datetime.fromisoformat(row[1]),
                    operator_id=row[2],
                    action=row[3],
                    pv_name=row[4],
                    previous_value=row[5],
                    new_value=row[6],
                    rationale=row[7],
                    prev_hash=row[8],
                    entry_hash=row[9],
                )
                self._entries.append(e)

    def log_action(
        self,
        operator_id: str,
        action: str,
        pv_name: str,
        previous_value: float,
        new_value: float,
        rationale: str = "",
    ) -> AuditEntry:
        """Append an actuation or state modification to the tamper-evident ledger."""
        next_id = len(self._entries) + 1
        prev_hash = self._entries[-1].entry_hash if self._entries else "0" * 64

        entry = AuditEntry(
            entry_id=next_id,
            timestamp=datetime.now(timezone.utc),
            operator_id=operator_id,
            action=action,
            pv_name=pv_name,
            previous_value=previous_value,
            new_value=new_value,
            rationale=rationale,
            prev_hash=prev_hash,
            entry_hash="",
        )
        entry.entry_hash = entry.compute_hash()
        self._entries.append(entry)

        if self.db_path:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    "INSERT INTO audit_ledger VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        entry.entry_id,
                        entry.timestamp.isoformat(),
                        entry.operator_id,
                        entry.action,
                        entry.pv_name,
                        entry.previous_value,
                        entry.new_value,
                        entry.rationale,
                        entry.prev_hash,
                        entry.entry_hash,
                    ),
                )
                conn.commit()

        logger.info(f"AUDIT LOG [{entry.entry_id}]: {operator_id} {action} {pv_name} -> {new_value:.4f}")
        return entry

    def verify_integrity(self) -> tuple[bool, str | None]:
        """Verify the complete hash chain from genesis to head."""
        if not self._entries:
            return True, None

        expected_prev_hash = "0" * 64
        for idx, entry in enumerate(self._entries):
            # Check link to previous
            if entry.prev_hash != expected_prev_hash:
                return False, f"Broken chain link at entry #{entry.entry_id}: expected {expected_prev_hash}, found {entry.prev_hash}"

            # Check self-consistency
            calc_hash = entry.compute_hash()
            if entry.entry_hash != calc_hash:
                return False, f"Tampered entry #{entry.entry_id}: recorded hash {entry.entry_hash} != computed {calc_hash}"

            expected_prev_hash = entry.entry_hash

        return True, None

    def get_entries(self) -> list[AuditEntry]:
        """Return full ledger history."""
        return list(self._entries)
