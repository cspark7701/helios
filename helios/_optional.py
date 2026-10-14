"""Unified optional dependency management for HELIOS.

Provides consistent, actionable error messages when optional extras are missing.
"""

import importlib
from types import ModuleType

EXTRAS: dict[str, list[str]] = {
    "epics": ["epics", "p4p"],
    "ml": ["torch"],
    "rl": ["gymnasium"],
    "dashboard": ["fastapi", "uvicorn", "requests"],
    "ontology": ["linkml", "linkml_runtime", "rdflib"],
}

MODULE_TO_EXTRA: dict[str, str] = {
    "torch": "ml",
    "gymnasium": "rl",
    "fastapi": "dashboard",
    "uvicorn": "dashboard",
    "p4p": "epics",
    "epics": "epics",
    "linkml": "ontology",
    "linkml_runtime": "ontology",
    "rdflib": "ontology",
}


class OptionalDependencyError(ImportError):
    """Raised when an optional dependency is required but not installed."""

    def __init__(self, package_name: str, extra: str | None = None, feature: str | None = None):
        self.package_name = package_name
        self.extra = extra or MODULE_TO_EXTRA.get(package_name, package_name)
        self.feature = feature
        feature_str = f" for {feature}" if feature else ""
        msg = (
            f"Optional dependency '{package_name}' is required{feature_str}. "
            f"Install it with: pip install 'helios-linac[{self.extra}]'"
        )
        super().__init__(msg)


def is_available(module_name: str) -> bool:
    """Check if an optional module can be imported without raising."""
    try:
        importlib.import_module(module_name)
        return True
    except (ImportError, Exception):
        return False


def require(module_name: str, extra: str | None = None, feature: str | None = None) -> ModuleType:
    """Import and return an optional module, raising OptionalDependencyError if unavailable."""
    try:
        return importlib.import_module(module_name)
    except ImportError as e:
        raise OptionalDependencyError(package_name=module_name, extra=extra, feature=feature) from e
