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


class FixRequest(BaseModel):
    text_input: str
    repo_url: str | None = None  # optional; MCP server has default sample repo


class FixResponse(BaseModel):
    success: bool
    result: str
    error: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Register the running event loop so event_bus.broadcast_sync works from threads
    event_bus.set_loop(asyncio.get_running_loop())
    print("[startup] /ws/spawn is in DEBUG mode (agent cycle + jump_ping). Connect Vision Pro to see send logs.", flush=True)

    voice.voice_startup()
    if voice.TALKBACK_ENABLED and voice.TTS_LOOP_AUTOSTART:
        loop = asyncio.get_running_loop()
        voice.start_tts_loop(loop)
    yield
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
    await websocket.accept()
    event_bus.register(websocket)
    print("[ws/poke] client connected")
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
        print("[ws/poke] client disconnected")
    except Exception as e:
        print(f"[ws/poke] error: {e}")
    finally:
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
    Broadcasts them to all connected WS clients (both /ws/poke and /ws/spawn).
    Event types: create_agent_thinking, agent_start_working, agent_start_testing.
    """
    msg_type = body.get("type", "(no type)")
    print(f"[internal/event] ← received type={msg_type!r}, broadcasting…")
    await event_bus.broadcast(body)
    return {"ok": True}


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


async def _ws_send_agent_cycle(websocket: WebSocket) -> None:
    """Send agent lifecycle messages: create_agent_thinking → agent_start_working → agent_start_testing.
    Cycles through agents 1-9 for each phase.
    """
    print("[ws/spawn] agent_cycle loop started", flush=True)
    while True:
        # Phase 1: create_agent_thinking for each agent 1-9
        for agent_id in range(1, 10):
            msg = {
                "type": "create_agent_thinking",
                "agent_id": agent_id,
                "task_name": "placeholder task",
            }
            payload = _json.dumps(msg)
            print(f"[ws/spawn] → send: {payload[:80]}…", flush=True)
            await websocket.send_text(payload)
            await asyncio.sleep(0.5)
        # Phase 2: agent_start_working for each agent 1-9
        for agent_id in range(1, 10):
            msg = {"type": "agent_start_working", "agent_id": agent_id}
            payload = _json.dumps(msg)
            print(f"[ws/spawn] → send: {payload}", flush=True)
            await websocket.send_text(payload)
            await asyncio.sleep(0.5)
        # Phase 3: agent_start_testing for each agent 1-9
        for agent_id in range(1, 10):
            msg = {
                "type": "agent_start_testing",
                "agent_id": agent_id,
                "vercel_link": "https://google.com",
                "browserbase_link": "https://google.com",
            }
            payload = _json.dumps(msg)
            print(f"[ws/spawn] → send: {payload[:80]}…", flush=True)
            await websocket.send_text(payload)
            await asyncio.sleep(0.5)
        await asyncio.sleep(2.0)  # Pause before next cycle


@app.post("/palm-touched")
async def palm_touched(body: dict | None = None):
    """Receive jump_ping when user touches the palm tree. Body: {"type": "jump_ping"}."""
    print(f"[palm-touched] {body}", flush=True)
    return {"ok": True}


@app.websocket("/ws/spawn")
async def websocket_spawn(websocket: WebSocket):
    """Stream agent lifecycle messages to Vision Pro (jump_ping only on palm tree touch)."""
    await websocket.accept()
    print("[ws/spawn] client connected — starting debug cycle", flush=True)
    try:
        await _ws_send_agent_cycle(websocket)
    except Exception:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


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
