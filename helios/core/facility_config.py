"""HELIOS Centralized Facility and Channel Configuration.

Provides validated Pydantic FacilityConfig loading from YAML files,
centralizing PV names, steerers, BPMs, limits, units, and simulation roots.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from helios.interfaces.channel_map import ChannelLimits, ChannelManager, DeviceType, LinacDevice


class FacilityConfig(BaseModel):
    """Centralized machine and linac section configuration."""

    name: str = "HELIOS_MEBT"
    section: str = "MEBT"
    description: str = ""
    steerers: list[str] = Field(default_factory=list)
    bpms: list[str] = Field(default_factory=list)
    quadrupoles: list[str] = Field(default_factory=list)
    cavities: list[str] = Field(default_factory=list)
    panic_pvs: list[str] = Field(default_factory=list)
    devices: list[LinacDevice] = Field(default_factory=list)
    conversion_factor_a_per_mrad: float = 0.168
    current_increment_a: float = 0.05
    track_root: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | Path) -> FacilityConfig:
        """Load and validate facility configuration from a YAML file."""
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Facility config YAML not found: {p}")
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Handle raw devices dictionaries if present
        devices: list[LinacDevice] = []
        for d in data.get("devices", []):
            if isinstance(d, LinacDevice):
                devices.append(d)
            elif isinstance(d, dict):
                # Ensure device_type is Enum
                dtype = d.get("device_type")
                if isinstance(dtype, str):
                    d["device_type"] = DeviceType(dtype)
                limits_data = d.get("limits")
                if isinstance(limits_data, dict):
                    d["limits"] = ChannelLimits(**limits_data)
                devices.append(LinacDevice(**d))
        data["devices"] = devices
        return cls(**data)

    @classmethod
    def load_default(cls, section: str = "MEBT") -> FacilityConfig:
        """Load default configuration for the specified linac section."""
        # Check standard config directory candidates
        section_lower = section.lower()
        candidates = [
            Path(f"configs/facility_{section_lower}.yaml"),
            Path(f"configs/linac_{section_lower}_channels.yaml"),
            Path(__file__).parent.parent.parent / f"configs/facility_{section_lower}.yaml",
            Path(__file__).parent.parent.parent / f"configs/linac_{section_lower}_channels.yaml",
        ]
        for c in candidates:
            if c.is_file():
                try:
                    return cls.from_yaml(c)
                except Exception:
                    pass

        # Fallback default for MEBT if no YAML file found
        if section.upper() == "MEBT":
            return cls(
                name="HELIOS_MEBT_DEFAULT",
                section="MEBT",
                description="Default in-memory MEBT configuration",
                steerers=["MEBT:PSC:CH01:CurrentSet", "MEBT:PSC:CV01:CurrentSet"],
                bpms=["MEBT:DIAG:BPM01:X_POS", "MEBT:DIAG:BPM02:X_POS"],
                quadrupoles=["MEBT:PSC:QD01:CurrentSet", "MEBT:PSC:QF02:CurrentSet"],
                cavities=["MEBT:RF:CAV01:AmpSet"],
                panic_pvs=[
                    "MEBT:RF:CAV01:AmpSet",
                    "MEBT:PSC:CH01:CurrentSet",
                    "MEBT:PSC:CV01:CurrentSet",
                    "MEBT:PSC:QD01:CurrentSet",
                    "MEBT:PSC:QF02:CurrentSet",
                ],
            )
        return cls(name=f"HELIOS_{section.upper()}", section=section.upper())

    def to_channel_manager(self) -> ChannelManager:
        """Construct an indexed ChannelManager from this configuration."""
        manager = ChannelManager()
        for dev in self.devices:
            manager.register_device(dev)
        return manager
