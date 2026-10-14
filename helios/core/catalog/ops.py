"""Operations, Forensics and Ontology capability definitions for HELIOS."""

from helios.core.capabilities import Capability, CapabilityDomain, RiskLevel

OPS_CAPABILITIES: list[Capability] = [
    Capability(
        name="generate_shift_report",
        description="Compile and export linac commissioning shift logbook report in Markdown or LaTeX format",
        domain=CapabilityDomain.OPS,
        target_agent="HELIOS-Orchestrator",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["report", "shift", "logbook", "summary", "commissioning", "latex", "pdf", "export"],
        target_module="helios.ops.reporting",
    ),
    Capability(
        name="validate_linkml_schema",
        description="Validate accelerator device or lattice data against LinkML heavy-ion schema",
        domain=CapabilityDomain.ONTOLOGY,
        target_agent="HELIOS-Physics",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["linkml", "ontology", "validate schema", "w3c", "rdf", "schema"],
        target_module="helios.ontology.loader",
    ),
    Capability(
        name="query_beamline_topology",
        description="Traverse beamline knowledge graph to locate upstream/downstream neighbors and causal actuators",
        domain=CapabilityDomain.ONTOLOGY,
        target_agent="HELIOS-Orchestrator",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["topology", "knowledge graph", "neighbors", "upstream steerer", "causal", "graph"],
        target_module="helios.ontology.graph",
    ),
    Capability(
        name="generate_linac_shift_logbook_forensics",
        description="Synthesize automated linac shift handover reports and analyze 50ms pre-trip circular buffer forensics",
        domain=CapabilityDomain.OPS,
        target_agent="HELIOS-Orchestrator",
        risk_level=RiskLevel.READ_ONLY,
        keywords=["logbook", "e-log", "shift handover", "trip forensics", "circular buffer", "root cause", "uptime"],
        target_module="helios.ops.logbook",
    ),
]
