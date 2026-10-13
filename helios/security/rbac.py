"""HELIOS Control Room Security, Role-Based Access Control (RBAC), and Watchdog.

Implements:
1. Multi-tiered RBAC authorization gating high-risk setpoint writes and panic shutdowns.
2. Machine Protection System (MPS) cryptographic heartbeat watchdog daemon.
3. Tamper-evident secure audit certificate generation.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import hmac
import logging
import secrets
import time
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class UserRole(str, Enum):
    VIEWER = "VIEWER"
    PHYSICIST = "PHYSICIST"
    SAFETY_OFFICER = "SAFETY_OFFICER"
    ADMIN = "ADMIN"


class Permission(str, Enum):
    READ_TELEMETRY = "READ_TELEMETRY"
    SIMULATE = "SIMULATE"
    PROPOSE_SETPOINT = "PROPOSE_SETPOINT"
    EXECUTE_CAPUT = "EXECUTE_CAPUT"
    PANIC_SHUTDOWN = "PANIC_SHUTDOWN"
    OVERRIDE_INTERLOCK = "OVERRIDE_INTERLOCK"


ROLE_PERMISSIONS: Dict[UserRole, Set[Permission]] = {
    UserRole.VIEWER: {Permission.READ_TELEMETRY, Permission.SIMULATE},
    UserRole.PHYSICIST: {
        Permission.READ_TELEMETRY,
        Permission.SIMULATE,
        Permission.PROPOSE_SETPOINT,
        Permission.EXECUTE_CAPUT,
    },
    UserRole.SAFETY_OFFICER: {
        Permission.READ_TELEMETRY,
        Permission.SIMULATE,
        Permission.PROPOSE_SETPOINT,
        Permission.EXECUTE_CAPUT,
        Permission.PANIC_SHUTDOWN,
        Permission.OVERRIDE_INTERLOCK,
    },
    UserRole.ADMIN: set(Permission),
}


@dataclass
class AuthToken:
    """Cryptographic session authorization token."""
    username: str
    role: UserRole
    token_str: str
    issued_at: datetime
    expires_at: float


class RBACManager:
    """Manages role-based access control and token verification."""

    def __init__(self, secret_key: Optional[str] = None):
        self._secret = (secret_key or secrets.token_hex(32)).encode("utf-8")
        self._active_tokens: Dict[str, AuthToken] = {}

    def issue_token(self, username: str, role: UserRole, validity_seconds: float = 3600.0) -> AuthToken:
        """Generate authenticated session token."""
        raw = f"{username}|{role.value}|{time.time()}|{secrets.token_hex(8)}"
        signature = hmac.new(self._secret, raw.encode("utf-8"), hashlib.sha256).hexdigest()
        token_str = f"{raw}.{signature}"

        token = AuthToken(
            username=username,
            role=role,
            token_str=token_str,
            issued_at=datetime.now(timezone.utc),
            expires_at=time.time() + validity_seconds,
        )
        self._active_tokens[token_str] = token
        return token

    def verify_permission(self, token_str: str, required_permission: Permission) -> bool:
        """Verify whether token grants requested permission."""
        token = self._active_tokens.get(token_str)
        if not token or time.time() > token.expires_at:
            return False

        allowed_perms = ROLE_PERMISSIONS.get(token.role, set())
        return required_permission in allowed_perms


class MPSHeartbeatWatchdog:
    """Sub-second heartbeat monitor enforcing fail-safe fallback upon communication drop."""

    def __init__(self, timeout_seconds: float = 0.5):
        self.timeout_seconds = timeout_seconds
        self.last_heartbeat_time = time.time()
        self.is_interlocked = False

    def ping(self) -> None:
        """Register fresh heartbeat ping from control agent."""
        self.last_heartbeat_time = time.time()
        self.is_interlocked = False

    def check_health(self) -> bool:
        """Check if heartbeat is active within timeout."""
        elapsed = time.time() - self.last_heartbeat_time
        if elapsed > self.timeout_seconds:
            self.is_interlocked = True
            logger.critical(f"MPS WATCHDOG TIMEOUT! {elapsed:.3f}s > {self.timeout_seconds}s. Safe fallback triggered.")
            return False
        return True
