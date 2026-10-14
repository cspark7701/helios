"""EPICS Control and Distributed Mesh capability definitions for HELIOS."""

from helios.core.capabilities import Capability, CapabilityDomain, RiskLevel

CONTROLS_CAPABILITIES: list[Capability] = [
    Capability(
        name="epics_caput_batch",
        description="Execute atomic batch EPICS caput with readback verification",
        domain=CapabilityDomain.EPICS,
        target_agent="HELIOS-Control",
        risk_level=RiskLevel.HIGH,
        keywords=["epics", "caput", "write", "actuate", "hardware", "pv"],
        target_module="helios.interfaces.epics",
    ),
    Capability(
        name="pva_get_table",
        description="Read structured pvAccess NTTable (e.g. multi-BPM orbit table or profile data)",
        domain=CapabilityDomain.EPICS,
        target_agent="HELIOS-Control",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["pva", "pvaccess", "nttable", "orbit table", "vector", "waveform"],
        target_module="helios.interfaces.pva",
    ),
    Capability(
        name="publish_mesh_telemetry_event",
        description="Publish and broadcast telemetry and control events across the distributed multi-node agent mesh",
        domain=CapabilityDomain.CONTROL,
        target_agent="HELIOS-Orchestrator",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["mesh", "distributed", "broker", "event", "failover", "edge sync"],
        target_module="helios.core.mesh",
    ),
]
