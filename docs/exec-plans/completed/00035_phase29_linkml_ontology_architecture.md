# Execution Plan Change Record: Phase 29 LinkML Accelerator Modeling & Ontology Integration

- **Plan ID**: `00035`
- **Phase**: 29
- **Title**: LinkML Accelerator Modeling, W3C RDF/OWL Knowledge Graph & Topology Navigation
- **Status**: Completed
- **Timestamp**: 2026-10-13
- **Reference Standard**: [LinkML (Linked Open Data Modeling Language)](https://linkml.io/)

---

## 1. Executive Summary

Phase 29 introduces formal Linked Open Data modeling to HELIOS via **LinkML**, transforming the framework's internal schemas into an open, standardized accelerator physics ontology:
1. **Canonical LinkML Schema (`helios/ontology/helios_schema.yaml`)**:
   - Declares 11 core classes (`BeamlineElement`, `MagneticElement`, `Quadrupole`, `DipoleSteerer`, `RFCavityElement`, `BeamPositionMonitor`, `BeamLossMonitor`, `IonBeamState`, `LinacLatticeModel`, etc.).
   - Standard prefixes (`helios:`, `qudt:`, `linkml:`, `rdfs:`) and enums (`AcceleratorSectionEnum`, `DeviceTypeEnum`).
2. **LinkML Ontology Manager & Loader (`helios/ontology/loader.py`)**:
   - `LinkMLOntologyManager`: Ingests and inspects schemas via `SchemaView`.
   - Generates JSON-Schema for LLM tool calling.
   - Validates arbitrary dictionaries and performs bidirectional conversion between LinkML models, `LinacDevice`, and simulation `Element` instances (`Quadrupole`, `RFCavity`, `Drift`).
3. **W3C RDF / Turtle (TTL) Exporter (`helios/ontology/rdf_exporter.py`)**:
   - `RDFOntologyExporter`: Populates RDF knowledge graphs from linac configurations with typed entities, parameters, and upstream/downstream semantic topology links.
4. **Beamline Knowledge Graph (`helios/ontology/graph.py`)**:
   - `BeamlineKnowledgeGraph`: Traverses beamline ordering for spatial and causal reasoning (e.g., finding the nearest upstream steerers capable of correcting BPM offsets).
5. **Capabilities & CLI Integration**:
   - Registered `ONTOLOGY` domain in `helios/core/capabilities.py` with `validate_linkml_schema` and `query_beamline_topology`.

---

## 2. Test Verification

- **New Test Suite**: `tests/test_linkml_ontology.py` (6/6 passing).
- **Full Repository Suite**: **98/98 passing tests** across all 29 phases.
