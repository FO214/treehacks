"""
Event bus: broadcast JSON events to all connected WebSocket clients.

Usage:
    from server.event_bus import register, unregister, broadcast, broadcast_sync

    # In WS endpoint:
    register(websocket)
    ...
    unregister(websocket)

    # From async code:
    await broadcast({"type": "listening"})

    # From sync code / threads (voice.py, internal HTTP handler):
    broadcast_sync({"type": "poke_speaking_start", "text": "..."})
"""
import asyncio
import json
import threading
from typing import Any

from fastapi import WebSocket

# Connected WS clients
_clients: set[WebSocket] = set()
_lock = threading.Lock()

# Reference to the main event loop (set once at startup)
_loop: asyncio.AbstractEventLoop | None = None


def set_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Call once from the FastAPI lifespan to register the running event loop."""
    global _loop
    _loop = loop


def register(ws: WebSocket) -> None:
    with _lock:
        _clients.add(ws)


def unregister(ws: WebSocket) -> None:
    with _lock:
        _clients.discard(ws)


async def broadcast(event: dict[str, Any]) -> None:
    """Send *event* as JSON to every connected client. Silently drops failed sends."""
    payload = json.dumps(event)
    with _lock:
        clients = list(_clients)
    for ws in clients:
        try:
            await ws.send_text(payload)
        except Exception:
            # Client likely disconnected; will be cleaned up by its handler
            pass


def broadcast_sync(event: dict[str, Any]) -> None:
    """
    Fire-and-forget broadcast from synchronous / threaded code.
    Schedules the async broadcast on the main event loop.
    """
    if _loop is None or _loop.is_closed():
        return
    asyncio.run_coroutine_threadsafe(broadcast(event), _loop)
