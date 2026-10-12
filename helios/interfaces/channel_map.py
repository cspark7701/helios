"""HELIOS Semantic Channel Mapping & Resolution System.

Follows LBNL Osprey's semantic channel mapping pattern. Bridges high-level
beam physics & agent concepts with low-level EPICS Process Variables (PVs).
"""

from enum import Enum
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import yaml


class DeviceType(str, Enum):
    """Heavy ion linac device types."""
    QUADRUPOLE = "QUADRUPOLE"
    SOLENOID = "SOLENOID"
    DIPOLE = "DIPOLE"
    STEERER_H = "STEERER_H"
    STEERER_V = "STEERER_V"
    RF_CAVITY = "RF_CAVITY"
    BPM = "BPM"
    BLM = "BLM"
    FARADAY_CUP = "FARADAY_CUP"
    WIRE_SCANNER = "WIRE_SCANNER"


class ChannelLimits(BaseModel):
    """Hard and soft operating limits for a channel."""
    min_val: float = Field(..., description="Absolute lower safety limit")
    max_val: float = Field(..., description="Absolute upper safety limit")
    warn_min: Optional[float] = None
    warn_max: Optional[float] = None
    max_slew_rate: Optional[float] = Field(None, description="Maximum change per second")
    units: str = Field("", description="Engineering units")


class LinacDevice(BaseModel):
    """A physical device in the heavy ion linac beamline."""
    section: str = Field(..., description="e.g. LEBT, RFQ, MEBT, SCL1, SCL2, HEBT")
    name: str = Field(..., description="Unique device name, e.g. QD01, CH01, CAV01")
    device_type: DeviceType
    z_position_m: float = Field(0.0, description="Beamline z position in meters")
    setpoint_pv: Optional[str] = None
    readback_pv: Optional[str] = None
    status_pv: Optional[str] = None
    limits: Optional[ChannelLimits] = None
    aliases: List[str] = Field(default_factory=list, description="Natural language aliases")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ChannelManager:
    """Manages channel registrations, YAML loading, and bidirectional semantic resolution."""

    def __init__(self):
        self._devices: Dict[str, LinacDevice] = {}  # key: f"{section}:{name}"
        self._pv_to_device: Dict[str, LinacDevice] = {}
        self._alias_map: Dict[str, str] = {}

    def register_device(self, device: LinacDevice) -> None:
        """Register a device and index its PVs and aliases."""
        key = f"{device.section.upper()}:{device.name.upper()}"
        self._devices[key] = device

        if device.setpoint_pv:
            self._pv_to_device[device.setpoint_pv] = device
        if device.readback_pv:
            self._pv_to_device[device.readback_pv] = device
        if device.status_pv:
            self._pv_to_device[device.status_pv] = device

        for alias in device.aliases:
            self._alias_map[alias.lower().strip()] = key

    def get_device(self, section: str, name: str) -> Optional[LinacDevice]:
        """Fetch device by section and name."""
        return self._devices.get(f"{section.upper()}:{name.upper()}")

    def resolve_pv_from_semantic(self, query: str, pv_type: str = "setpoint") -> Optional[str]:
        """Resolve a PV name from natural language query or semantic identifier.

        Examples:
        - "MEBT:QD01" -> setpoint PV of MEBT QD01
        - "MEBT Quadrupole 1 gradient" -> setpoint PV of MEBT QD01
        """
        query_clean = query.strip()

        # Direct key match
        if ":" in query_clean:
            parts = query_clean.split(":")
            dev = self.get_device(parts[0], parts[1])
            if dev:
                return self._get_pv_by_type(dev, pv_type)

        # Alias match
        key = self._alias_map.get(query_clean.lower())
        if key:
            dev = self._devices.get(key)
            if dev:
                return self._get_pv_by_type(dev, pv_type)

        # Keyword fuzzy search
        query_lower = query_clean.lower()
        for dev in self._devices.values():
            if dev.name.lower() in query_lower and dev.section.lower() in query_lower:
                return self._get_pv_by_type(dev, pv_type)

        return None

    def get_device_by_pv(self, pv_name: str) -> Optional[LinacDevice]:
        """Reverse lookup: find device by any associated PV."""
        return self._pv_to_device.get(pv_name)

    def filter_devices(
        self,
        section: Optional[str] = None,
        device_type: Optional[DeviceType] = None,
    ) -> List[LinacDevice]:
        """Filter devices by section and/or device type."""
        results = list(self._devices.values())
        if section:
            sec_upper = section.upper()
            results = [d for d in results if d.section.upper() == sec_upper]
        if device_type:
            results = [d for d in results if d.device_type == device_type]
        # Sort by beamline position z
        results.sort(key=lambda d: d.z_position_m)
        return results

    def _get_pv_by_type(self, dev: LinacDevice, pv_type: str) -> Optional[str]:
        if pv_type == "setpoint":
            return dev.setpoint_pv
        elif pv_type == "readback":
            return dev.readback_pv or dev.setpoint_pv
        elif pv_type == "status":
            return dev.status_pv
        return None

    @classmethod
    def from_yaml_file(cls, path: Path) -> "ChannelManager":
        """Load channel configuration from YAML file."""
        manager = cls()
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        for dev_data in data.get("devices", []):
            device = LinacDevice.model_validate(dev_data)
            manager.register_device(device)

        return manager


def create_baseline_mebt_channel_manager() -> ChannelManager:
    """Create a default channel manager preloaded with representative MEBT devices."""
    manager = ChannelManager()

    # Quadrupoles
    manager.register_device(LinacDevice(
        section="MEBT",
        name="QD01",
        device_type=DeviceType.QUADRUPOLE,
        z_position_m=0.25,
        setpoint_pv="MEBT:PSC:QD01:CurrentSet",
        readback_pv="MEBT:PSC:QD01:CurrentAct",
        status_pv="MEBT:PSC:QD01:Status",
        limits=ChannelLimits(min_val=-50.0, max_val=50.0, max_slew_rate=5.0, units="A"),
        aliases=["mebt quad 01", "mebt first quadrupole", "mebt qd1"],
    ))
    manager.register_device(LinacDevice(
        section="MEBT",
        name="QF02",
        device_type=DeviceType.QUADRUPOLE,
        z_position_m=0.60,
        setpoint_pv="MEBT:PSC:QF02:CurrentSet",
        readback_pv="MEBT:PSC:QF02:CurrentAct",
        status_pv="MEBT:PSC:QF02:Status",
        limits=ChannelLimits(min_val=-50.0, max_val=50.0, max_slew_rate=5.0, units="A"),
        aliases=["mebt quad 02", "mebt second quadrupole", "mebt qf2"],
    ))

    # Steerers
    manager.register_device(LinacDevice(
        section="MEBT",
        name="CH01",
        device_type=DeviceType.STEERER_H,
        z_position_m=0.35,
        setpoint_pv="MEBT:PSC:CH01:CurrentSet",
        readback_pv="MEBT:PSC:CH01:CurrentAct",
        limits=ChannelLimits(min_val=-10.0, max_val=10.0, max_slew_rate=2.0, units="A"),
        aliases=["mebt horizontal steerer 1", "mebt ch1"],
    ))
    manager.register_device(LinacDevice(
        section="MEBT",
        name="CV01",
        device_type=DeviceType.STEERER_V,
        z_position_m=0.35,
        setpoint_pv="MEBT:PSC:CV01:CurrentSet",
        readback_pv="MEBT:PSC:CV01:CurrentAct",
        limits=ChannelLimits(min_val=-10.0, max_val=10.0, max_slew_rate=2.0, units="A"),
        aliases=["mebt vertical steerer 1", "mebt cv1"],
    ))

    # Diagnostics
    manager.register_device(LinacDevice(
        section="MEBT",
        name="BPM01",
        device_type=DeviceType.BPM,
        z_position_m=0.80,
        readback_pv="MEBT:DIAG:BPM01:X_POS",
        metadata={"pv_y": "MEBT:DIAG:BPM01:Y_POS", "pv_phase": "MEBT:DIAG:BPM01:PHASE"},
        aliases=["mebt bpm 1", "first mebt bpm"],
    ))
    manager.register_device(LinacDevice(
        section="MEBT",
        name="BLM01",
        device_type=DeviceType.BLM,
        z_position_m=0.85,
        readback_pv="MEBT:DIAG:BLM01:DOSE",
        limits=ChannelLimits(min_val=0.0, max_val=100.0, units="uGy/s"),
        aliases=["mebt blm 1"],
    ))

    # RF Cavity (Buncher)
    manager.register_device(LinacDevice(
        section="MEBT",
        name="CAV01",
        device_type=DeviceType.RF_CAVITY,
        z_position_m=1.20,
        setpoint_pv="MEBT:RF:CAV01:AmpSet",
        readback_pv="MEBT:RF:CAV01:AmpAct",
        status_pv="MEBT:RF:CAV01:Interlock",
        limits=ChannelLimits(min_val=0.0, max_val=150.0, max_slew_rate=10.0, units="kV"),
        metadata={"phase_set_pv": "MEBT:RF:CAV01:PhaseSet", "phase_act_pv": "MEBT:RF:CAV01:PhaseAct"},
        aliases=["mebt buncher 1", "mebt rf cavity 1"],
    ))

    return manager
