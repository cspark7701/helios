"""HELIOS W3C RDF, OWL, and Turtle (TTL) Ontology Exporter.

Serializes LinkML-governed linac configurations, beamline topologies,
and device states into standard Semantic Web Knowledge Graph representations.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import rdflib
from rdflib import BNode, Graph, Literal, Namespace, RDF, RDFS, URIRef
from rdflib.namespace import XSD

logger = logging = __import__("logging").getLogger(__name__)

HELIOS_NS = Namespace("https://w3id.org/helios/ontology/")
QUDT_NS = Namespace("http://qudt.org/schema/qudt/")
UNIT_NS = Namespace("http://qudt.org/vocab/unit/")


class RDFOntologyExporter:
    """Exports accelerator configurations and digital twins to W3C RDF / OWL / Turtle formats."""

    def __init__(self):
        self.graph = Graph()
        self.graph.bind("helios", HELIOS_NS)
        self.graph.bind("qudt", QUDT_NS)
        self.graph.bind("unit", UNIT_NS)
        self.graph.bind("rdfs", RDFS)

    def export_elements_to_graph(self, elements: List[Dict[str, Any]], lattice_name: str = "HELIOS_Linac") -> Graph:
        """Populate RDF knowledge graph with beamline elements and topology connections."""
        lattice_uri = URIRef(f"https://w3id.org/helios/lattice/{lattice_name}")
        self.graph.add((lattice_uri, RDF.type, HELIOS_NS.LinacLatticeModel))
        self.graph.add((lattice_uri, RDFS.label, Literal(lattice_name, datatype=XSD.string)))

        prev_element_uri: Optional[URIRef] = None

        for elem in elements:
            elem_id = elem.get("id") or f"{elem.get('section', 'LINAC')}:{elem['name']}"
            elem_uri = URIRef(f"https://w3id.org/helios/device/{elem_id}")

            # Assign class type
            if "magnetic_gradient_t_per_m" in elem or "k1_m_minus2" in elem:
                self.graph.add((elem_uri, RDF.type, HELIOS_NS.Quadrupole))
                if "magnetic_gradient_t_per_m" in elem:
                    self.graph.add((elem_uri, HELIOS_NS.magnetic_gradient_t_per_m, Literal(elem["magnetic_gradient_t_per_m"], datatype=XSD.float)))
            elif "voltage_kv" in elem:
                self.graph.add((elem_uri, RDF.type, HELIOS_NS.RFCavityElement))
                self.graph.add((elem_uri, HELIOS_NS.voltage_kv, Literal(elem["voltage_kv"], datatype=XSD.float)))
                self.graph.add((elem_uri, HELIOS_NS.phase_deg, Literal(elem.get("phase_deg", -20.0), datatype=XSD.float)))
            elif "reading_x_mm" in elem:
                self.graph.add((elem_uri, RDF.type, HELIOS_NS.BeamPositionMonitor))
            elif "loss_rate_gy_per_s" in elem:
                self.graph.add((elem_uri, RDF.type, HELIOS_NS.BeamLossMonitor))
            else:
                self.graph.add((elem_uri, RDF.type, HELIOS_NS.BeamlineElement))

            # Standard slots
            self.graph.add((elem_uri, RDFS.label, Literal(elem["name"], datatype=XSD.string)))
            self.graph.add((elem_uri, HELIOS_NS.section, Literal(elem.get("section", "LINAC"), datatype=XSD.string)))
            self.graph.add((elem_uri, HELIOS_NS.z_position_m, Literal(float(elem.get("z_position_m", 0.0)), datatype=XSD.float)))
            self.graph.add((elem_uri, HELIOS_NS.length_m, Literal(float(elem.get("length_m", 0.2)), datatype=XSD.float)))

            if elem.get("setpoint_pv"):
                self.graph.add((elem_uri, HELIOS_NS.setpoint_pv, Literal(elem["setpoint_pv"], datatype=XSD.string)))
            if elem.get("readback_pv"):
                self.graph.add((elem_uri, HELIOS_NS.readback_pv, Literal(elem["readback_pv"], datatype=XSD.string)))

            # Link to lattice
            self.graph.add((lattice_uri, HELIOS_NS.elements, elem_uri))

            # Topology connection: upstream / downstream chaining
            if prev_element_uri is not None:
                self.graph.add((prev_element_uri, HELIOS_NS.downstream_element_id, elem_uri))
                self.graph.add((elem_uri, HELIOS_NS.upstream_element_id, prev_element_uri))

            prev_element_uri = elem_uri

        return self.graph

    def serialize_turtle(self) -> str:
        """Serialize knowledge graph in W3C Turtle format."""
        return self.graph.serialize(format="turtle")

    def serialize_owl_xml(self) -> str:
        """Serialize knowledge graph in W3C XML/RDF format."""
        return self.graph.serialize(format="xml")
