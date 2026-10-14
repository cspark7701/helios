"""Core Protocols and Domain Contracts for HELIOS Digital Twin framework.

Facility-agnostic definitions governing twin domains, frozen surrogates,
and facility plugin contracts.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import numpy as np


@dataclass
class TwinDomain:
    """Operational and training domain bounds for a digital twin."""

    names: list[str]
    lower: dict[str, float]
    upper: dict[str, float]

    def out_of_domain(self, u: Mapping[str, float] | np.ndarray, margin: float = 0.0) -> list[str]:
        """Return control names that violate lower/upper domain bounds."""
        violations: list[str] = []
        if isinstance(u, np.ndarray):
            for i, name in enumerate(self.names):
                val = float(u[i])
                lo = self.lower.get(name, -np.inf) - margin
                hi = self.upper.get(name, np.inf) + margin
                if val < lo or val > hi:
                    violations.append(name)
        else:
            for name in self.names:
                if name in u:
                    val = float(u[name])
                    lo = self.lower.get(name, -np.inf) - margin
                    hi = self.upper.get(name, np.inf) + margin
                    if val < lo or val > hi:
                        violations.append(name)
        return violations

    def clamp(self, u: Mapping[str, float]) -> dict[str, float]:
        """Clamp setpoint values to strictly lie within lower and upper bounds."""
        clamped: dict[str, float] = {}
        for k, v in u.items():
            lo = self.lower.get(k, -np.inf)
            hi = self.upper.get(k, np.inf)
            clamped[k] = float(np.clip(v, lo, hi))
        return clamped

    def normalize(self, u: Mapping[str, float]) -> np.ndarray:
        """Normalize physical parameters into [-1, 1] range."""
        vals = []
        for name in self.names:
            v = float(u.get(name, 0.0))
            lo = self.lower.get(name, -1.0)
            hi = self.upper.get(name, 1.0)
            span = max(hi - lo, 1e-6)
            norm = 2.0 * (v - lo) / span - 1.0
            vals.append(float(np.clip(norm, -1.0, 1.0)))
        return np.array(vals, dtype=np.float32)

    def denormalize(self, arr: np.ndarray) -> dict[str, float]:
        """Denormalize [-1, 1] vector back to physical engineering units."""
        res: dict[str, float] = {}
        for i, name in enumerate(self.names):
            norm = float(arr[i])
            lo = self.lower.get(name, -1.0)
            hi = self.upper.get(name, 1.0)
            span = hi - lo
            res[name] = lo + 0.5 * (norm + 1.0) * span
        return res


@runtime_checkable
class FrozenSurrogateInterface(Protocol):
    """Protocol for machine-neutral inference models evaluated in-process."""

    def predict(self, controls: Mapping[str, float] | np.ndarray) -> Mapping[str, float] | np.ndarray:
        """Evaluate forward model from controls in physical engineering units."""
        ...

    def predict_tensor(self, x: Any) -> Any:
        """Differentiable forward tensor evaluation for autograd / Neural MPC."""
        ...


@dataclass
class FacilityTwin:
    """Self-contained container for an accelerator section digital twin."""

    facility: str
    section: str
    surrogate: Any
    control_names: list[str]
    control_units: dict[str, str] = field(default_factory=dict)
    diagnostic_names: list[str] = field(default_factory=list)
    domain: TwinDomain = field(default_factory=lambda: TwinDomain([], {}, {}))
    provenance: dict[str, str] = field(default_factory=dict)

    def predict(self, controls: Mapping[str, float]) -> dict[str, float]:
        """Execute forward surrogate inference."""
        res = self.surrogate.predict(controls)
        if isinstance(res, dict):
            return res
        if isinstance(res, np.ndarray):
            return {
                self.diagnostic_names[i]: float(res[i])
                for i in range(min(len(self.diagnostic_names), len(res)))
            }
        return {}


@runtime_checkable
class FacilityPlugin(Protocol):
    """Formal protocol implemented by facility plugins (e.g. raon_plugin)."""

    def available_sections(self) -> list[str]:
        """Return list of linac sections supported by this facility plugin."""
        ...

    def load_twin(self, section: str) -> FacilityTwin:
        """Load and return the FacilityTwin for the specified section."""
        ...

    def to_actuator_commands(self, section: str, controls: Mapping[str, float]) -> dict[str, Any]:
        """Convert physics controls to EPICS actuator setpoint commands."""
        ...

    def make_env(self, section: str, **kwargs: Any) -> Any:
        """Construct a Gymnasium training environment for the section."""
        ...
