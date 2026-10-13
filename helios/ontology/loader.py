"""HELIOS LinkML Ontology Loader, Validator, and Dynamic Model Ingestor.

Provides:
1. LinkML YAML schema parser and validation.
2. Bidirectional translation between LinkML models and native HELIOS
   LinacDevice, Lattice, and Element objects.
3. Fast JSON-Schema export for LLM function calling.
"""

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
import yaml

from linkml_runtime.utils.schemaview import SchemaView
from linkml.generators.jsonschemagen import JsonSchemaGenerator

from helios.interfaces.channel_map import ChannelLimits, DeviceType, LinacDevice
from helios.physics.lattice import Drift, Element, Lattice, Quadrupole as PhysicsQuad, RFCavity as PhysicsCavity

logger = logging.getLogger(__name__)

DEFAULT_SCHEMA_PATH = Path(__file__).parent / "helios_schema.yaml"


@dataclass
class LinkMLValidationResult:
    """Outcome of validating data against the LinkML accelerator schema."""
    is_valid: bool
    schema_name: str
    target_class: str
    errors: List[str] = field(default_factory=list)
    parsed_data: Optional[Dict[str, Any]] = None


class LinkMLOntologyManager:
    """Manages the canonical LinkML accelerator ontology and schema operations."""

    def __init__(self, schema_path: Optional[Union[str, Path]] = None):
        self.schema_path = Path(schema_path or DEFAULT_SCHEMA_PATH)
        if not self.schema_path.exists():
            raise FileNotFoundError(f"LinkML schema file not found at {self.schema_path}")
        self.schema_view = SchemaView(str(self.schema_path))

    def get_classes(self) -> List[str]:
        """Return list of all classes declared in the LinkML ontology."""
        return list(self.schema_view.all_classes().keys())

    def get_slots_for_class(self, class_name: str) -> List[str]:
        """Return all slot/field names associated with a class."""
        cls_def = self.schema_view.get_class(class_name)
        if not cls_def:
            raise KeyError(f"Class '{class_name}' does not exist in LinkML schema")
        return list(self.schema_view.class_slots(class_name))

    def generate_json_schema(self, target_class: Optional[str] = None) -> Dict[str, Any]:
        """Generate JSON-Schema specification for LLM tool calling and API endpoints."""
        generator = JsonSchemaGenerator(schema=str(self.schema_path))
        raw_json_schema = generator.serialize()
        schema_dict = json.loads(raw_json_schema)
        if target_class:
            return schema_dict.get("$defs", {}).get(target_class, schema_dict)
        return schema_dict

    def validate_dict(self, data: Dict[str, Any], target_class: str = "BeamlineElement") -> LinkMLValidationResult:
        """Validate input dictionary against class requirements in the LinkML schema."""
        errors: List[str] = []
        cls_def = self.schema_view.get_class(target_class)
        if not cls_def:
            return LinkMLValidationResult(
                is_valid=False,
                schema_name=self.schema_view.schema.name,
                target_class=target_class,
                errors=[f"Target class '{target_class}' not found in ontology"],
            )

        slots = self.schema_view.class_slots(target_class)
        for s_name in slots:
            slot_def = self.schema_view.get_slot(s_name)
            if slot_def and slot_def.required and s_name not in data:
                errors.append(f"Missing required slot '{s_name}' for class '{target_class}'")

        return LinkMLValidationResult(
            is_valid=(len(errors) == 0),
            schema_name=self.schema_view.schema.name,
            target_class=target_class,
            errors=errors,
            parsed_data=data if len(errors) == 0 else None,
        )

    def convert_linac_device_to_linkml(self, device: LinacDevice) -> Dict[str, Any]:
        """Translate a native HELIOS LinacDevice into a LinkML BeamlineElement record."""
        # Map device type to LinkML subclass
        class_mapping = {
            DeviceType.QUADRUPOLE: "Quadrupole",
            DeviceType.STEERER_H: "DipoleSteerer",
            DeviceType.STEERER_V: "DipoleSteerer",
            DeviceType.RF_CAVITY: "RFCavityElement",
            DeviceType.BPM: "BeamPositionMonitor",
            DeviceType.BLM: "BeamLossMonitor",
        }
        target_cls = class_mapping.get(device.device_type, "BeamlineElement")

        linkml_record: Dict[str, Any] = {
            "id": f"{device.section.upper()}:{device.name.upper()}",
            "name": device.name,
            "section": device.section.upper(),
            "z_position_m": device.z_position_m,
            "length_m": 0.2,  # Default typical device length
            "setpoint_pv": device.setpoint_pv,
            "readback_pv": device.readback_pv,
            "status_pv": device.status_pv,
            "description": f"{device.device_type.value} device in section {device.section}",
        }

        if device.device_type == DeviceType.QUADRUPOLE:
            grad = device.metadata.get("gradient_t_per_m", 15.0)
            linkml_record["magnetic_gradient_t_per_m"] = float(grad)
        elif device.device_type == DeviceType.RF_CAVITY:
            linkml_record["frequency_mhz"] = float(device.metadata.get("frequency_mhz", 162.5))
            linkml_record["voltage_kv"] = float(device.metadata.get("voltage_kv", 1200.0))
            linkml_record["phase_deg"] = float(device.metadata.get("phase_deg", -20.0))

        return linkml_record

    def convert_linkml_to_helios_element(self, linkml_record: Dict[str, Any]) -> Element:
        """Translate a validated LinkML record into a HELIOS physics simulation element."""
        name = linkml_record["name"]
        length = float(linkml_record.get("length_m", 0.2))

        if "magnetic_gradient_t_per_m" in linkml_record or "k1_m_minus2" in linkml_record:
            grad = float(linkml_record.get("magnetic_gradient_t_per_m", 0.0))
            if grad == 0.0 and "k1_m_minus2" in linkml_record:
                grad = float(linkml_record["k1_m_minus2"]) * 1.5
            return PhysicsQuad(name=name, length=length, gradient_t_m=grad)

        elif "voltage_kv" in linkml_record:
            voltage_mv = float(linkml_record["voltage_kv"]) * 1e-3
            phase_deg = float(linkml_record.get("phase_deg", -20.0))
            freq = float(linkml_record.get("frequency_mhz", 162.5))
            return PhysicsCavity(name=name, length=length, voltage_mv=voltage_mv, phase_deg=phase_deg, frequency_mhz=freq)

        else:
            return Drift(name=name, length=length)
