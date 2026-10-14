"""HELIOS Accelerator Knowledge Graph & Beamline Topology Navigator.

Enables causal topological queries across the accelerator lattice:
- Upstream / downstream neighborhood searches (e.g. nearest steerers to a BPM).
- Path traversal for localized fault mitigation and orbit response tracing.
"""

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TopologyNeighbor:
    """Neighboring beamline element with distance and orientation."""
    element_id: str
    element_name: str
    element_type: str
    z_position_m: float
    distance_m: float
    is_upstream: bool


class BeamlineKnowledgeGraph:
    """Traverses linear accelerator topology graph for spatial reasoning."""

    def __init__(self, elements: list[dict[str, Any]] | None = None):
        self._elements: dict[str, dict[str, Any]] = {}
        self._ordered_ids: list[str] = []
        if elements:
            self.load_elements(elements)

    def load_elements(self, elements: list[dict[str, Any]]) -> None:
        """Ingest elements and sort by beamline position z."""
        sorted_elems = sorted(elements, key=lambda e: float(e.get("z_position_m", 0.0)))
        self._elements.clear()
        self._ordered_ids.clear()
        for e in sorted_elems:
            elem_id = e.get("id") or f"{e.get('section', 'LINAC')}:{e['name']}"
            e["id"] = elem_id
            self._elements[elem_id] = e
            self._ordered_ids.append(elem_id)

    def get_element(self, element_id: str) -> dict[str, Any] | None:
        """Fetch element by identifier."""
        return self._elements.get(element_id)

    def find_nearest_neighbors(
        self,
        target_id: str,
        target_type: str | None = None,
        max_neighbors: int = 2,
        upstream_only: bool = False,
        downstream_only: bool = False,
    ) -> list[TopologyNeighbor]:
        """Query nearest elements matching type filter along the beamline."""
        if target_id not in self._elements:
            raise KeyError(f"Target element '{target_id}' not found in knowledge graph")

        target = self._elements[target_id]
        target_z = float(target.get("z_position_m", 0.0))

        candidates: list[TopologyNeighbor] = []

        for eid, elem in self._elements.items():
            if eid == target_id:
                continue

            # Type filter
            elem_type = elem.get("device_type") or elem.get("type", "UNKNOWN")
            if target_type and target_type.lower() not in elem_type.lower():
                continue

            elem_z = float(elem.get("z_position_m", 0.0))
            dist = elem_z - target_z
            is_up = dist < 0

            if upstream_only and not is_up:
                continue
            if downstream_only and is_up:
                continue

            candidates.append(
                TopologyNeighbor(
                    element_id=eid,
                    element_name=elem.get("name", eid),
                    element_type=elem_type,
                    z_position_m=elem_z,
                    distance_m=abs(dist),
                    is_upstream=is_up,
                )
            )

        # Sort by shortest physical distance
        candidates.sort(key=lambda n: n.distance_m)
        return candidates[:max_neighbors]

    def find_affecting_steerers(self, bpm_id: str, max_steerers: int = 2) -> list[TopologyNeighbor]:
        """Find upstream steerers capable of correcting orbit at specified BPM."""
        return self.find_nearest_neighbors(
            target_id=bpm_id,
            target_type="STEERER",
            max_neighbors=max_steerers,
            upstream_only=True,
        )
