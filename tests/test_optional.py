"""Unit tests for helios._optional dependency handling."""

import pytest

from helios._optional import (
    EXTRAS,
    MODULE_TO_EXTRA,
    OptionalDependencyError,
    is_available,
    require,
)


def test_optional_available_module():
    """Verify require() imports existing standard modules."""
    sys_mod = require("sys")
    assert sys_mod.__name__ == "sys"
    assert is_available("sys") is True


def test_optional_missing_module_raises_error():
    """Verify require() raises OptionalDependencyError with actionable install guidance."""
    assert is_available("nonexistent_helios_package") is False

    with pytest.raises(OptionalDependencyError) as exc_info:
        require("nonexistent_helios_package", extra="custom_extra", feature="Custom Feature")

    err = exc_info.value
    assert err.package_name == "nonexistent_helios_package"
    assert err.extra == "custom_extra"
    assert err.feature == "Custom Feature"
    assert "pip install 'helios-linac[custom_extra]'" in str(err)
    assert "for Custom Feature" in str(err)


def test_module_to_extra_mappings():
    """Verify registered extra mappings match pyproject.toml."""
    assert MODULE_TO_EXTRA["torch"] == "ml"
    assert MODULE_TO_EXTRA["gymnasium"] == "rl"
    assert MODULE_TO_EXTRA["fastapi"] == "dashboard"
    assert MODULE_TO_EXTRA["p4p"] == "epics"
    assert "ml" in EXTRAS
    assert "rl" in EXTRAS
    assert "dashboard" in EXTRAS
    assert "all" in EXTRAS

