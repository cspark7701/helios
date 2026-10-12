"""Tests for Semantic Channel Resolution and Device Mapping (Osprey pattern)."""

from pathlib import Path
import pytest

from helios.interfaces.channel_map import (
    ChannelManager,
    DeviceType,
    create_baseline_mebt_channel_manager,
)


def test_baseline_channel_manager():
    """Verify baseline channel manager registration and lookups."""
    manager = create_baseline_mebt_channel_manager()

    # Direct device lookup
    qd01 = manager.get_device("MEBT", "QD01")
    assert qd01 is not None
    assert qd01.device_type == DeviceType.QUADRUPOLE
    assert qd01.setpoint_pv == "MEBT:PSC:QD01:CurrentSet"

    # Semantic path resolution
    pv_set = manager.resolve_pv_from_semantic("MEBT:QD01", pv_type="setpoint")
    assert pv_set == "MEBT:PSC:QD01:CurrentSet"

    pv_act = manager.resolve_pv_from_semantic("MEBT:QD01", pv_type="readback")
    assert pv_act == "MEBT:PSC:QD01:CurrentAct"

    # Natural language alias resolution
    pv_alias = manager.resolve_pv_from_semantic("mebt first quadrupole")
    assert pv_alias == "MEBT:PSC:QD01:CurrentSet"

    pv_ch1 = manager.resolve_pv_from_semantic("mebt horizontal steerer 1")
    assert pv_ch1 == "MEBT:PSC:CH01:CurrentSet"

    # Reverse lookup by PV
    dev = manager.get_device_by_pv("MEBT:PSC:CH01:CurrentSet")
    assert dev is not None
    assert dev.name == "CH01"


def test_device_filtering():
    """Verify filtering by section and device type."""
    manager = create_baseline_mebt_channel_manager()

    quads = manager.filter_devices(section="MEBT", device_type=DeviceType.QUADRUPOLE)
    assert len(quads) == 2
    assert quads[0].name == "QD01"
    assert quads[1].name == "QF02"
    # Ensure ordered by beamline z
    assert quads[0].z_position_m < quads[1].z_position_m


def test_yaml_channel_loading():
    """Verify loading channels from YAML config."""
    yaml_path = Path("configs/linac_mebt_channels.yaml")
    assert yaml_path.exists()

    manager = ChannelManager.from_yaml_file(yaml_path)
    qd01 = manager.get_device("MEBT", "QD01")
    assert qd01 is not None
    assert qd01.limits.max_slew_rate == 5.0
    assert manager.resolve_pv_from_semantic("mebt quad 01") == "MEBT:PSC:QD01:CurrentSet"
