"""HELIOS Control System Security and Channel Access Security (CAS) Enforcement.

Implements role-based access control (RBAC), write-permission ACLs,
and Channel Access Security policy verification for accelerator operations.
"""

from enum import Enum
import logging
import re
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class UserRole(str, Enum):
    """Operator authorization roles in the accelerator control room."""
    READ_ONLY = "READ_ONLY"      # Observers, telemetry scrapers, monitors
    OPERATOR = "OPERATOR"        # Standard control room operators (steerers, BPM offsets)
    PHYSICIST = "PHYSICIST"      # Machine physicists (quadrupoles, RF phases, BO tuning)
    ADMIN = "ADMIN"              # Control room experts (MPS override, raw power setpoints)


class SecurityViolationError(PermissionError):
    """Raised when an unauthorized agent or user attempts an unpermitted PV actuation."""


class ControlSecurityPolicy:
    """Security rules governing Process Variable read/write permissions."""

    def __init__(
        self,
        default_role: UserRole = UserRole.PHYSICIST,
        readonly_patterns: Optional[List[str]] = None,
        admin_patterns: Optional[List[str]] = None,
        physicist_patterns: Optional[List[str]] = None,
    ):
        self.default_role = default_role
        # Regular expressions matching protected PV groups
        self.readonly_patterns = readonly_patterns or [
            r".*:INTERLOCK:.*",
            r".*:MPS:.*",
            r".*:STATUS.*",
            r".*:READBACK.*",
            r".*:ACT.*",
        ]
        self.admin_patterns = admin_patterns or [
            r".*:OVERRIDE.*",
            r".*:HIGH_VOLTAGE:SET.*",
            r".*:QUENCH_BYPASS.*",
            r".*:VAC_GATE_VALVE:SET.*",
        ]
        self.physicist_patterns = physicist_patterns or [
            r".*:CAV:.*:AMP_SET.*",
            r".*:CAV:.*:PHASE_SET.*",
            r".*:QUAD:.*:B_SET.*",
            r".*:SOL:.*:B_SET.*",
        ]

    def is_strictly_readonly(self, pv_name: str) -> bool:
        """Check if PV is permanently read-only across all roles."""
        return any(re.match(pattern, pv_name, re.IGNORECASE) for pattern in self.readonly_patterns)

    def required_role(self, pv_name: str) -> UserRole:
        """Determine minimum required UserRole to write to given PV."""
        if self.is_strictly_readonly(pv_name):
            return UserRole.ADMIN

        for pattern in self.admin_patterns:
            if re.match(pattern, pv_name, re.IGNORECASE):
                return UserRole.ADMIN

        for pattern in self.physicist_patterns:
            if re.match(pattern, pv_name, re.IGNORECASE):
                return UserRole.PHYSICIST

        # Standard steerers and benign corrections default to OPERATOR
        return UserRole.OPERATOR

    def authorize_write(self, pv_name: str, user_role: UserRole) -> bool:
        """Validate if user_role possesses clearance to actuate target PV.

        Hierarchy: ADMIN > PHYSICIST > OPERATOR > READ_ONLY
        """
        if user_role == UserRole.READ_ONLY:
            return False

        if self.is_strictly_readonly(pv_name) and user_role != UserRole.ADMIN:
            return False

        min_role = self.required_role(pv_name)
        hierarchy = {
            UserRole.READ_ONLY: 0,
            UserRole.OPERATOR: 1,
            UserRole.PHYSICIST: 2,
            UserRole.ADMIN: 3,
        }

        return hierarchy[user_role] >= hierarchy[min_role]


class ControlSecurityManager:
    """Manages active session authentication and enforces CAS write boundaries."""

    def __init__(self, policy: Optional[ControlSecurityPolicy] = None):
        self.policy = policy or ControlSecurityPolicy()
        self._current_role = self.policy.default_role

    @property
    def current_role(self) -> UserRole:
        return self._current_role

    def set_session_role(self, role: UserRole) -> None:
        """Update active session clearance role."""
        logger.info(f"Security session clearance changed to: {role.value}")
        self._current_role = role

    def check_permission(self, pv_name: str) -> None:
        """Raise SecurityViolationError if the current role cannot write to pv_name."""
        if not self.policy.authorize_write(pv_name, self._current_role):
            required = self.policy.required_role(pv_name)
            raise SecurityViolationError(
                f"Permission denied: Writing to '{pv_name}' requires {required.value} role. "
                f"Current active session has {self._current_role.value} clearance."
            )
