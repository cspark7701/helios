"""Pytest fixtures and configuration for HELIOS test suite."""

import numpy as np
import pytest


@pytest.fixture
def sample_lattice_dict():
    """Returns a basic dictionary representation of a linac lattice section."""
    return {
        "section": "MEBT",
        "elements": [
            {"name": "MEBT_QD01", "type": "Quadrupole", "s": 0.25, "gradient": 12.5},
            {"name": "MEBT_QF02", "type": "Quadrupole", "s": 0.55, "gradient": -11.8},
            {"name": "MEBT_BPM01", "type": "BPM", "s": 0.75},
            {"name": "MEBT_CAV01", "type": "RFCavity", "s": 1.20, "v0": 120.0, "phi0": -20.0},
        ],
    }
