"""Unit tests for analytic orbit correction tuning module."""

import pytest

from helios.tuning.analytic import (
    LEBT_RX,
    LEBT_RY,
    LEBT_STATION_DATA,
    LEBT_STEERER_NAMES,
    execute_analytic_orbit_correction,
)


def test_lebt_constants():
    """Verify standard LEBT station data and response matrices."""
    assert len(LEBT_STATION_DATA) == 6
    assert len(LEBT_STEERER_NAMES) == 5
    assert LEBT_RX.shape == (6, 5)
    assert LEBT_RY.shape == (6, 5)


def test_execute_analytic_orbit_correction_lebt():
    """Verify rapid analytic orbit correction on LEBT."""
    res = execute_analytic_orbit_correction(
        section="LEBT",
        conversion_factor_a_per_mrad=0.168,
        current_increment_a=0.05,
    )

    assert res["section"] == "LEBT"
    assert res["engine"] == "analytic"
    assert res["initial_rms_x_mm"] > 0.0
    assert res["corrected_rms_x_mm"] < res["initial_rms_x_mm"]
    assert res["improvement_pct"] > 0.0
    assert len(res["steerers"]) == 5
    assert len(res["monitors"]) == 6


def test_execute_analytic_orbit_correction_mebt():
    """Verify rapid analytic orbit correction on synthetic MEBT section."""
    res = execute_analytic_orbit_correction(
        section="MEBT",
        conversion_factor_a_per_mrad=0.168,
        current_increment_a=0.05,
    )

    assert res["section"] == "MEBT"
    assert res["engine"] == "analytic"
    assert "corrected_rms_x_mm" in res
    assert len(res["steerers"]) == 4
    assert len(res["monitors"]) == 8
