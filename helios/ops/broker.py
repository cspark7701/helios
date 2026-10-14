"""HELIOS Distributed Multi-Agent Message Broker and Event Bus.

Provides decoupled topic-based publish/subscribe communication enabling agents
(Orchestrator, Physics, Safety, Tuner, Diagnostics, Control) to coordinate
across multi-host control room environments.
"""

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class MessagePriority(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class EventMessage:
    """Structured message broadcast across agent event bus."""
    message_id: str
    topic: str
    sender_agent: str
    payload: dict[str, Any]
    priority: MessagePriority = MessagePriority.NORMAL
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_json(self) -> str:
        data = {
            "message_id": self.message_id,
            "topic": self.topic,
            "sender_agent": self.sender_agent,
            "payload": self.payload,
            "priority": self.priority.value,
            "timestamp": self.timestamp.isoformat(),
        }
        return json.dumps(data)


class BrokerBackendType(str, Enum):
    IN_PROCESS = "IN_PROCESS"
    REDIS = "REDIS"
    MQTT = "MQTT"


class DistributedEventBus:
    """Asynchronous and synchronous in-process / network event broker."""

    def __init__(self, backend: BrokerBackendType = BrokerBackendType.IN_PROCESS, redis_url: str | None = None):
        self.backend = backend
        self.redis_url = redis_url
        self._subscribers: dict[str, list[Callable[[EventMessage], None]]] = {}
        self._history: list[EventMessage] = []
        self._rpc_handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}

    def subscribe(self, topic_pattern: str, handler: Callable[[EventMessage], None]) -> None:
        """Register a handler callback for messages matching topic pattern."""
        if topic_pattern not in self._subscribers:
            self._subscribers[topic_pattern] = []
        self._subscribers[topic_pattern].append(handler)
        logger.debug(f"Subscribed handler to topic '{topic_pattern}'")

    def unsubscribe(self, topic_pattern: str, handler: Callable[[EventMessage], None]) -> None:
        """Unregister a handler callback."""
        if topic_pattern in self._subscribers:
            self._subscribers[topic_pattern] = [h for h in self._subscribers[topic_pattern] if h != handler]

    def publish(self, topic: str, sender_agent: str, payload: dict[str, Any]) -> EventMessage:
        """Publish a message to all subscribers matching topic."""
        msg = EventMessage(
            message_id=str(uuid.uuid4())[:8],
            topic=topic,
            sender_agent=sender_agent,
            payload=payload,
        )
        self._history.append(msg)

        # Dispatch to matching subscribers
        for pattern, handlers in self._subscribers.items():
            if self._topic_matches(pattern, topic):
                for h in handlers:
                    try:
                        h(msg)
                    except Exception as e:
                        logger.error(f"Error in event bus subscriber for '{topic}': {e}")
                        if topic.startswith("safety") or msg.priority == MessagePriority.CRITICAL:
                            raise RuntimeError(f"Critical safety event subscriber failed on topic '{topic}': {e}") from e

        return msg

    @staticmethod
    def _topic_matches(pattern: str, topic: str) -> bool:
        """Match hierarchical dot-separated topics with wildcard '*' support."""
        if pattern == "*" or pattern == topic:
            return True
        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            return topic.startswith(prefix)
        return False

    def get_history(self, topic_prefix: str | None = None) -> list[EventMessage]:
        """Return message log optionally filtered by topic prefix."""
        if not topic_prefix:
            return list(self._history)
        return [m for m in self._history if m.topic.startswith(topic_prefix)]

    def register_rpc_service(self, service_name: str, handler: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        """Register a remote callable procedure for distributed agent dispatch."""
        self._rpc_handlers[service_name] = handler
        logger.debug(f"Registered RPC service '{service_name}'")

    def call_rpc(self, service_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Synchronously execute a registered remote agent RPC handler."""
        if service_name not in self._rpc_handlers:
            raise KeyError(f"RPC service '{service_name}' is not registered on the event bus")
        return self._rpc_handlers[service_name](params)
