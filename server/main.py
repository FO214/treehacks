"""
FastAPI server: /fix, voice endpoints, demo. Single server on port 8000.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from repo root (parent of server/)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import asyncio
import json as _json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel

from . import voice
from . import event_bus

# ---------------------------------------------------------------------------
# Agent state store: last event payload per agent_id (1-9). Updated by /internal/event;
# status loop re-broadcasts each once per second so clients get a steady stream.
# ---------------------------------------------------------------------------
_agent_state_store: dict[int, dict[str, Any]] = {}

# Connection counts per endpoint (for debugging: is client on /ws/spawn or /ws/poke?)
_ws_spawn_connections = 0
_ws_poke_connections = 0

# ---------------------------------------------------------------------------
# Atomic agent ID counter (1-9, wrapping). Owned by the main server.
# ---------------------------------------------------------------------------
import threading

_agent_id_counter = 0
_agent_id_lock = threading.Lock()


def _next_agent_id() -> int:
    """Return the next agent ID (1-9, wrapping). First call after startup returns 1."""
    global _agent_id_counter
    with _agent_id_lock:
        _agent_id_counter = (_agent_id_counter % 9) + 1
        return _agent_id_counter


class FixRequest(BaseModel):
    text_input: str
    repo_url: str | None = None  # optional; MCP server has default sample repo


class FixResponse(BaseModel):
    success: bool
    result: str
    error: str | None = None


async def _agent_status_stream_loop() -> None:
    """Every 1 second, re-broadcast the last known state (same JSON) for each active agent."""
    while True:
        await asyncio.sleep(1.0)
        for agent_id, msg in list(_agent_state_store.items()):
            try:
                await event_bus.broadcast(msg)
            except Exception:
                pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Register the running event loop so event_bus.broadcast_sync works from threads
    event_bus.set_loop(asyncio.get_running_loop())
    print("[startup] /ws/spawn forwards real agent events from /internal/event only.", flush=True)

    voice.voice_startup()
    if voice.TALKBACK_ENABLED and voice.TTS_LOOP_AUTOSTART:
        loop = asyncio.get_running_loop()
        voice.start_tts_loop(loop)

    status_task = asyncio.create_task(_agent_status_stream_loop())
    try:
        yield
    finally:
        status_task.cancel()
        try:
            await status_task
        except asyncio.CancelledError:
            pass
    voice.stop_tts_loop()


@asynccontextmanager
async def get_mcp_session():
    """Connect to MCP server over HTTP and yield session."""
    mcp_url = os.environ.get("MCP_HTTP_URL", "http://127.0.0.1:8001/mcp")
    async with streamablehttp_client(mcp_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


async def call_run_fix(text_input: str, repo_url: str | None) -> str:
    """Call MCP tool run_fix and return result text."""
    args: dict[str, Any] = {"instruction": text_input}
    if repo_url:
        args["repo_url"] = repo_url
    async with get_mcp_session() as session:
        result = await session.call_tool("run_fix", arguments=args)
    if result.isError:
        first = result.content[0] if result.content else None
        msg = getattr(first, "text", None) or (first.get("text") if isinstance(first, dict) else None) if first else "Unknown MCP error"
        raise RuntimeError(msg)
    # Result is list of ContentBlock (object or dict)
    out_parts = []
    for block in result.content:
        text = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
        if text:
            out_parts.append(text)
    return "\n".join(out_parts) if out_parts else ""


app = FastAPI(
    title="TreeHacks API",
    description="Fix API + voice server (record, STT, Poke, TTS).",
    lifespan=lifespan,
)


@app.post("/fix", response_class=PlainTextResponse)
async def fix(request: FixRequest) -> str:
    """Run the fix instruction via MCP server (Modal sandbox + Claude Agent SDK)."""
    try:
        result = await call_run_fix(request.text_input, request.repo_url)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# WebSocket: /ws/poke — Vision Pro ↔ server voice event bridge
# ---------------------------------------------------------------------------

@app.websocket("/ws/poke")
async def websocket_poke(websocket: WebSocket):
    """
    Vision Pro connects here for voice flow.
    Receives hand_open / hand_close gestures;
    broadcasts listening, poke_speaking events back.
    """
    global _ws_poke_connections
    await websocket.accept()
    _ws_poke_connections += 1
    event_bus.register(websocket)
    print(f"[ws/poke] client connected (total poke: {_ws_poke_connections})", flush=True)
    try:
        while True:
            raw = await websocket.receive_text()
            print(f"[ws/poke] ← received: {raw[:120]}{'…' if len(raw) > 120 else ''}")
            try:
                msg = _json.loads(raw)
            except _json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")
            print(f"[ws/poke] ← parsed type={msg_type!r}")

            if msg_type == "hand_open":
                # Start recording from mic
                voice.start_recording()
                await event_bus.broadcast({"type": "listening"})

            elif msg_type == "hand_close":
                # Stop recording, transcribe, send to Poke, speak response
                async def _on_event(evt: dict):
                    await event_bus.broadcast(evt)

                await voice.stop_and_process(on_event=_on_event)

    except WebSocketDisconnect:
        print("[ws/poke] client disconnected", flush=True)
    except Exception as e:
        print(f"[ws/poke] error: {e}", flush=True)
    finally:
        _ws_poke_connections = max(0, _ws_poke_connections - 1)
        event_bus.unregister(websocket)
        try:
            await websocket.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# WebSocket: /ws/spawn — Vision Pro agent state stream
# (Debug handler below; for prod use event_bus, swap to register(websocket) + receive loop)
# ---------------------------------------------------------------------------

@app.post("/internal/event")
async def internal_event(body: dict):
    """
    Receives agent progress events from poke-mcp (cross-process webhook).
    Broadcasts them to all connected WS clients; stores last state per agent_id
    so the status stream can re-send the same message once per second per agent.
    Event types: create_agent_thinking, agent_start_working, agent_start_testing.
    """
    msg_type = body.get("type", "(no type)")
    agent_id = body.get("agent_id")
    if isinstance(agent_id, int) and 1 <= agent_id <= 9:
        _agent_state_store[agent_id] = dict(body)
    print(f"[internal/event] ← received type={msg_type!r}, broadcasting…")
    await event_bus.broadcast(body)
    return {"ok": True}


@app.post("/internal/next-agent-id")
async def next_agent_id():
    """
    Returns the next agent ID (1-9, wrapping).
    Called by poke-mcp to get a unique agent ID for each new job.
    """
    agent_id = _next_agent_id()
    print(f"[internal/next-agent-id] → returning agent_id={agent_id}")
    return {"agent_id": agent_id}


# ---------------------------------------------------------------------------
# Demo: Vision Pro block color (WebSocket rainbow)
# ---------------------------------------------------------------------------
import colorsys


async def _ws_send_rainbow(websocket: WebSocket) -> None:
    """Send rainbow colors in a loop."""
    hue = 0.0
    while True:
        r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        msg = {"r": int(r * 255), "g": int(g * 255), "b": int(b * 255)}
        await websocket.send_text(_json.dumps(msg))
        hue = (hue + 0.01) % 1.0
        await asyncio.sleep(0.05)


async def _ws_receive_loop(websocket: WebSocket) -> None:
    """Receive messages from client and print to console."""
    while True:
        data = await websocket.receive_text()
        print(f"[ws] client → server: {data}")


@app.websocket("/ws/demo")
async def websocket_demo(websocket: WebSocket):
    """Stream rainbow colors to clients; receive gesture/status messages from clients."""
    await websocket.accept()
    try:
        await asyncio.gather(
            _ws_send_rainbow(websocket),
            _ws_receive_loop(websocket),
        )
    except Exception:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.websocket("/ws/spawn")
async def websocket_spawn(websocket: WebSocket):
    """Vision Pro agent UI. Only real events from poke-mcp (POST /internal/event) are forwarded; no debug cycle."""
    global _ws_spawn_connections
    await websocket.accept()
    _ws_spawn_connections += 1
    event_bus.register(websocket)
    # Send snapshot of current agent states so client can spawn characters that already exist
    for _aid, stored in list(_agent_state_store.items()):
        try:
            await websocket.send_text(_json.dumps(stored))
        except Exception:
            break
    print(f"[ws/spawn] client connected (total spawn: {_ws_spawn_connections}), sent {len(_agent_state_store)} snapshot(s)", flush=True)
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        pass
    finally:
        _ws_spawn_connections = max(0, _ws_spawn_connections - 1)
        print("[ws/spawn] client disconnected", flush=True)
        event_bus.unregister(websocket)
        try:
            await websocket.close()
        except Exception:
            pass


@app.get("/debug/ws")
async def debug_ws():
    """Return how many clients are connected to each WebSocket path (to verify Vision Pro is on /ws/spawn)."""
    return {
        "ws_spawn": _ws_spawn_connections,
        "ws_poke": _ws_poke_connections,
        "event_bus_registered": event_bus.get_client_count(),
    }


# Voice endpoints
@app.get("/health")
async def health():
    return voice.get_health()


@app.post("/record-once")
async def record_once(body: dict | None = None):
    opts = body or {}
    try:
        result = await voice.run_record_turn_once(
            send_to_poke=opts.get("sendToPoke", True),
            talkback=opts.get("talkback", True),
            await_inbound=opts.get("awaitInbound", True),
            timeout_ms=opts.get("timeoutMs"),
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/stt")
async def stt(body: dict):
    audio_path = body.get("audioPath")
    if not audio_path:
        raise HTTPException(status_code=400, detail="audioPath is required")
    try:
        transcript = await voice.transcribe_file(audio_path)
        return {"ok": True, "transcript": transcript}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tts")
async def tts(body: dict):
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    try:
        await voice.speak_text_direct(text)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/queue")
async def queue():
    return voice.get_queue()


@app.post("/queue/speak-next")
async def queue_speak_next():
    msg = await voice.speak_next_from_queue()
    if msg is None:
        raise HTTPException(status_code=404, detail="queue empty")
    return {"ok": True, "message": msg}


@app.post("/tts/start-loop")
async def tts_start_loop():
    loop = asyncio.get_running_loop()
    voice.start_tts_loop(loop)
    return {"ok": True, "started": True, "running": voice._tts_loop_running}


@app.post("/tts/stop-loop")
async def tts_stop_loop():
    voice.stop_tts_loop()
    return {"ok": True, "stopped": True, "running": False}


@app.get("/tts/loop-status")
async def tts_loop_status():
    return {
        "ok": True,
        "running": voice._tts_loop_running,
        "busy": voice._tts_loop_busy,
        "isBusy": voice._is_busy,
        "queueSize": len(voice._inbound_queue),
    }
