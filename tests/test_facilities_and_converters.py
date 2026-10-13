"""Unit tests for Multi-Facility Lattices, Converters, and Physics Benchmarks (Phase 17)."""

import pytest

from helios.physics.benchmarks import CrossCodeBenchmarkRunner
from helios.physics.converters import LatticeConverter
from helios.physics.facilities import (
    create_frib_ls1_lattice,
    create_gsi_fair_lattice,
    create_raon_scl1_lattice,
)
from helios.physics.lattice import create_baseline_mebt_lattice


def test_facility_lattice_instantiations():
    """Verify standard lattice definitions for RAON, FRIB, and GSI/FAIR."""
    # 1. RAON SCL1
    raon = create_raon_scl1_lattice()
    assert raon.name == "RAON_SCL1_BASELINE"
    assert len(raon.elements) > 20
    assert any("QWR" in elem.name for elem in raon.elements)
    assert any("HWR" in elem.name for elem in raon.elements)

    # 2. FRIB LS1
    frib = create_frib_ls1_lattice()
    assert frib.name == "FRIB_LS1_BASELINE"
    assert len(frib.elements) > 20
    assert any("SOL" in elem.name for elem in frib.elements)

    # 3. GSI FAIR
    gsi = create_gsi_fair_lattice()
    assert gsi.name == "GSI_FAIR_UNILAC"
    assert len(gsi.elements) > 15


def test_lattice_format_converters_madx_and_elegant():
    """Verify bi-directional conversion between HELIOS, MAD-X, and Elegant formats."""
    lat = create_baseline_mebt_lattice()

    # 1. Export to MAD-X
    madx_str = LatticeConverter.export_to_madx(lat)
    assert "DRIFT" in madx_str
    assert "QUADRUPOLE" in madx_str
    assert "LINE=" in madx_str

    # 2. Export to Elegant
    lte_str = LatticeConverter.export_to_elegant(lat)
    assert "EDRIFT" in lte_str
    assert "KQUAD" in lte_str
    assert "LINE=" in lte_str

    # 3. Round-trip Import from MAD-X
    imported_lat = LatticeConverter.import_from_madx(madx_str, lattice_name="ROUNDTRIP_MEBT")
    assert imported_lat.name == "ROUNDTRIP_MEBT"
    assert len(imported_lat.elements) == len(lat.elements)
    assert imported_lat.elements[0].length == lat.elements[0].length


def test_cross_code_benchmarks_runner():
    """Verify CrossCodeBenchmarkRunner comparative evaluation."""
    runner = CrossCodeBenchmarkRunner()
    lat = create_baseline_mebt_lattice()

    report = runner.run_benchmark(lat)

    assert report.lattice_name == lat.name
    assert "AnalyticDigitalTwin" in report.benchmarks
    assert "ANL_TRACK" in report.benchmarks
    assert "LBNL_IMPACT_Z" in report.benchmarks
    assert report.fastest_code is not None
    assert report.envelope_discrepancy_pct >= 0.0
    assert isinstance(report.consistency_passed, bool)
