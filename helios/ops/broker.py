"""HELIOS Distributed Multi-Agent Message Broker and Event Bus.

Provides decoupled topic-based publish/subscribe communication enabling agents
(Orchestrator, Physics, Safety, Tuner, Diagnostics, Control) to coordinate
across multi-host control room environments.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
from typing import Any, Callable, Dict, List, Optional, Set
import uuid

logger = logging.getLogger(__name__)


@dataclass
class EventMessage:
    """Structured message broadcast across agent event bus."""
    message_id: str
    topic: str
    sender_agent: str
    payload: Dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_json(self) -> str:
        data = {
            "message_id": self.message_id,
            "topic": self.topic,
            "sender_agent": self.sender_agent,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
        }
        return json.dumps(data)


class DistributedEventBus:
    """Asynchronous and synchronous in-process / network event broker."""

    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[EventMessage], None]]] = {}
        self._history: List[EventMessage] = []

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

    def publish(self, topic: str, sender_agent: str, payload: Dict[str, Any]) -> EventMessage:
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

    def get_history(self, topic_prefix: Optional[str] = None) -> List[EventMessage]:
        """Return message log optionally filtered by topic prefix."""
        if not topic_prefix:
            return list(self._history)
        return [m for m in self._history if m.topic.startswith(topic_prefix)]
