"""WebSocket telemetry streaming route for HELIOS dashboard."""

import asyncio
import json
import logging
from datetime import datetime, timezone

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws/telemetry")
async def websocket_telemetry(websocket: WebSocket) -> None:
    """Stream real-time telemetry updates to connected operator consoles."""
    await websocket.accept()
    connected_clients: list[WebSocket] = getattr(websocket.app.state, "connected_clients", [])
    connected_clients.append(websocket)
    try:
        while True:
            payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "transmission_pct": 99.4 + 0.1 * np.random.randn(),
                "orbit_rms_mm": 0.1135 + 0.005 * np.random.randn(),
            }
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)
