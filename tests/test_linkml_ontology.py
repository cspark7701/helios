"""Unit tests for HELIOS LinkML Accelerator Ontology & Knowledge Graph (Phase 29).

Validates:
1. LinkML schema parsing and SchemaView inspection.
2. LinkML data dictionary validation and required slot checking.
3. Bidirectional translation between LinacDevice, LinkML records, and Lattice physics elements.
4. JSON-Schema generation for LLM tool calling.
5. W3C Turtle (TTL) and RDF Knowledge Graph serialization.
6. BeamlineKnowledgeGraph upstream/downstream topological neighborhood queries.
"""

from pathlib import Path
import pytest
import rdflib

from helios.interfaces.channel_map import DeviceType, LinacDevice
from helios.ontology.loader import LinkMLOntologyManager
from helios.ontology.rdf_exporter import RDFOntologyExporter
from helios.ontology.graph import BeamlineKnowledgeGraph
from helios.physics.lattice import Quadrupole as PhysicsQuad, RFCavity as PhysicsCavity


def test_linkml_schema_view_and_slots():
    mgr = LinkMLOntologyManager()
    classes = mgr.get_classes()
    assert "BeamlineElement" in classes
    assert "Quadrupole" in classes
    assert "RFCavityElement" in classes
    assert "BeamPositionMonitor" in classes
    assert "LinacLatticeModel" in classes

    quad_slots = mgr.get_slots_for_class("Quadrupole")
    assert "magnetic_gradient_t_per_m" in quad_slots
    assert "z_position_m" in quad_slots
    assert "section" in quad_slots


def test_linkml_validation():
    mgr = LinkMLOntologyManager()

    # Valid Quadrupole record
    valid_data = {
        "id": "MEBT:QD01",
        "name": "QD01",
        "section": "MEBT",
        "z_position_m": 1.25,
        "length_m": 0.22,
        "magnetic_gradient_t_per_m": 16.5,
    }
    res = mgr.validate_dict(valid_data, target_class="Quadrupole")
    assert res.is_valid is True
    assert len(res.errors) == 0

    # Invalid record missing required z_position_m
    invalid_data = {
        "id": "MEBT:QD01",
        "name": "QD01",
        "section": "MEBT",
    }
    res_invalid = mgr.validate_dict(invalid_data, target_class="Quadrupole")
    assert res_invalid.is_valid is False
    assert any("z_position_m" in err for err in res_invalid.errors)


def test_json_schema_generation():
    mgr = LinkMLOntologyManager()
    json_schema = mgr.generate_json_schema()
    assert "$schema" in json_schema or "$defs" in json_schema or "title" in json_schema


def test_bidirectional_conversion_and_physics_element():
    mgr = LinkMLOntologyManager()

    # Native LinacDevice -> LinkML record
    dev = LinacDevice(
        section="MEBT",
        name="QD01",
        device_type=DeviceType.QUADRUPOLE,
        z_position_m=1.45,
        setpoint_pv="MEBT:PS_QD01:I_Set",
        metadata={"gradient_t_per_m": 18.2},
    )
    linkml_dict = mgr.convert_linac_device_to_linkml(dev)
    assert linkml_dict["id"] == "MEBT:QD01"
    assert linkml_dict["magnetic_gradient_t_per_m"] == 18.2

    # LinkML record -> Physics Element
    elem = mgr.convert_linkml_to_helios_element(linkml_dict)
    assert isinstance(elem, PhysicsQuad)
    assert elem.name == "QD01"
    assert elem.gradient_t_m == 18.2
    assert elem.k1() > 0.0


def test_rdf_turtle_exporter():
    exporter = RDFOntologyExporter()
    elements = [
        {
            "id": "MEBT:CH01",
            "name": "CH01",
            "section": "MEBT",
            "device_type": "STEERER_H",
            "z_position_m": 0.8,
            "length_m": 0.15,
            "setpoint_pv": "MEBT:PS_CH01:I_Set",
        },
        {
            "id": "MEBT:QD01",
            "name": "QD01",
            "section": "MEBT",
            "device_type": "QUADRUPOLE",
            "z_position_m": 1.2,
            "length_m": 0.2,
            "magnetic_gradient_t_per_m": 15.0,
        },
        {
            "id": "MEBT:BPM01",
            "name": "BPM01",
            "section": "MEBT",
            "device_type": "BPM",
            "z_position_m": 1.8,
            "length_m": 0.1,
            "reading_x_mm": 0.35,
        },
    ]

    graph = exporter.export_elements_to_graph(elements, lattice_name="MEBT_Lattice")
    assert len(graph) > 10

    turtle_str = exporter.serialize_turtle()
    assert "https://w3id.org/helios/ontology/" in turtle_str
    assert "MEBT:BPM01" in turtle_str
    assert "Quadrupole" in turtle_str


def test_beamline_knowledge_graph_topology():
    elements = [
        {"id": "MEBT:CH01", "name": "CH01", "device_type": "STEERER_H", "z_position_m": 0.5},
        {"id": "MEBT:QD01", "name": "QD01", "device_type": "QUADRUPOLE", "z_position_m": 1.0},
        {"id": "MEBT:CH02", "name": "CH02", "device_type": "STEERER_H", "z_position_m": 1.5},
        {"id": "MEBT:BPM01", "name": "BPM01", "device_type": "BPM", "z_position_m": 2.0},
        {"id": "MEBT:QD02", "name": "QD02", "device_type": "QUADRUPOLE", "z_position_m": 2.5},
    ]

    bkg = BeamlineKnowledgeGraph(elements)

    # Find upstream steerers capable of correcting BPM01 (at z=2.0)
    affecting = bkg.find_affecting_steerers("MEBT:BPM01", max_steerers=2)
    assert len(affecting) == 2
    # Nearest upstream steerer is CH02 (z=1.5, dist=0.5m)
    assert affecting[0].element_name == "CH02"
    assert affecting[0].is_upstream is True
    # Second upstream steerer is CH01 (z=0.5, dist=1.5m)
    assert affecting[1].element_name == "CH01"
    assert affecting[1].is_upstream is True
