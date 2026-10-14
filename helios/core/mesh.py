"""HELIOS Phase 38: Distributed Multi-Node Agent Mesh & Resilient Edge-Cloud Architecture.

Implements an asynchronous multi-node agent mesh for heavy-ion linacs, providing
dynamic peer discovery, heartbeat health monitoring, orchestrator failover election,
and disconnected edge autonomy with state synchronization.
"""

import time
import uuid
from collections.abc import Callable
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MeshNodeType(str, Enum):
    ORCHESTRATOR = "orchestrator"
    EDGE_IOC = "edge_ioc"
    PHYSICS_COMPUTE = "physics_compute"
    OPERATOR_CONSOLE = "operator_console"


class NodeStatus(str, Enum):
    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class AgentMeshNode(BaseModel):
    """Metadata for a registered mesh node."""
    node_id: str
    node_type: MeshNodeType
    address: str
    capabilities: list[str] = Field(default_factory=list)
    status: NodeStatus = NodeStatus.ONLINE
    last_heartbeat: float = Field(default_factory=time.time)
    priority_rank: int = Field(default=10)


class AgentMeshMessage(BaseModel):
    """Strongly-typed inter-agent message in the distributed mesh."""
    msg_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    sender_id: str
    target_id: str  # specific node_id or "*" for broadcast
    topic: str
    payload: dict[str, Any]
    timestamp: float = Field(default_factory=time.time)
    priority: int = Field(default=1, ge=1, le=5)


class DistributedAgentMesh:
    """Distributed communication and coordination mesh."""

    def __init__(self, heartbeat_timeout_s: float = 5.0):
        self.heartbeat_timeout_s = heartbeat_timeout_s
        self.nodes: dict[str, AgentMeshNode] = {}
        self.subscribers: dict[str, list[Callable[[AgentMeshMessage], None]]] = {}
        self.message_history: list[AgentMeshMessage] = []
        self.edge_offline_buffers: dict[str, list[AgentMeshMessage]] = {}
        self.active_orchestrator_id: str | None = None

    def register_node(self, node: AgentMeshNode) -> None:
        """Register a node in the mesh and update orchestrator election if needed."""
        self.nodes[node.node_id] = node
        if node.node_type == MeshNodeType.ORCHESTRATOR:
            if self.active_orchestrator_id is None or node.priority_rank > self.nodes[self.active_orchestrator_id].priority_rank:
                self.active_orchestrator_id = node.node_id

    def heartbeat(self, node_id: str) -> bool:
        """Record heartbeat from node."""
        if node_id in self.nodes:
            self.nodes[node_id].last_heartbeat = time.time()
            self.nodes[node_id].status = NodeStatus.ONLINE
            return True
        return False

    def subscribe(self, topic: str, callback: Callable[[AgentMeshMessage], None]) -> None:
        """Subscribe callback to a topic."""
        if topic not in self.subscribers:
            self.subscribers[topic] = []
        self.subscribers[topic].append(callback)

    def publish(self, message: AgentMeshMessage) -> int:
        """Publish a message to subscribers or direct target."""
        self.message_history.append(message)
        delivered_count = 0

        # Deliver to topic subscribers
        if message.topic in self.subscribers:
            for cb in self.subscribers[message.topic]:
                cb(message)
                delivered_count += 1

        return delivered_count

    def buffer_edge_offline_action(self, node_id: str, message: AgentMeshMessage) -> None:
        """Buffer actions taken locally by an edge IOC node during network disconnection."""
        if node_id not in self.edge_offline_buffers:
            self.edge_offline_buffers[node_id] = []
        self.edge_offline_buffers[node_id].append(message)

    def sync_reconnection(self, node_id: str) -> int:
        """Flush and synchronize offline buffered telemetry upon edge node reconnection."""
        self.heartbeat(node_id)
        buffered = self.edge_offline_buffers.pop(node_id, [])
        for msg in buffered:
            self.publish(msg)
        return len(buffered)

    def check_liveness_and_elect_orchestrator(self) -> str | None:
        """Check peer liveness and trigger failover election if active orchestrator has timed out."""
        now = time.time()
        for node_id, node in self.nodes.items():
            if now - node.last_heartbeat > self.heartbeat_timeout_s:
                node.status = NodeStatus.OFFLINE

        # Check if active orchestrator is alive
        if self.active_orchestrator_id:
            curr = self.nodes.get(self.active_orchestrator_id)
            if curr and curr.status == NodeStatus.OFFLINE:
                self.active_orchestrator_id = None

        # If no active orchestrator, elect highest-priority surviving candidate
        if self.active_orchestrator_id is None:
            candidates = [
                n for n in self.nodes.values()
                if n.node_type == MeshNodeType.ORCHESTRATOR and n.status == NodeStatus.ONLINE
            ]
            if candidates:
                candidates.sort(key=lambda x: x.priority_rank, reverse=True)
                self.active_orchestrator_id = candidates[0].node_id

        return self.active_orchestrator_id
