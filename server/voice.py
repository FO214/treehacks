"""
Voice server logic: recording, STT, Poke, chat.db polling, TTS, playback.
Ported from voice-server.mjs.
"""
import asyncio
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

import httpx

# Config from env
PROVIDER = (os.environ.get("PROVIDER") or "openai").lower()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
POKE_API_KEY = os.environ.get("POKE_API_KEY")
POKE_API = (os.environ.get("POKE_API") or "https://poke.com/api/v1").rstrip("/")

STT_MODEL = os.environ.get("STT_MODEL") or (
    "whisper-large-v3-turbo" if PROVIDER == "other" else "gpt-4o-mini-transcribe"
)
TTS_MODEL = os.environ.get("TTS_MODEL") or "gpt-4o-mini-tts"
TTS_VOICE = os.environ.get("TTS_VOICE") or ("Rachel" if PROVIDER == "other" else "alloy")
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_MODEL") or "eleven_turbo_v2_5"
TTS_SPEED = float(os.environ.get("TTS_SPEED") or os.environ.get("TTS_VOICE_SPEED") or "1.0")
TTS_RESPONSE_FORMAT = (os.environ.get("TTS_RESPONSE_FORMAT") or "").strip().lower()
TTS_BATCH_QUEUE = (os.environ.get("TTS_BATCH_QUEUE") or "true").lower() != "false"
TTS_BATCH_SEPARATOR = os.environ.get("TTS_BATCH_SEPARATOR") or " "
TALKBACK_ENABLED = (os.environ.get("TALKBACK_ENABLED") or "true").lower() != "false"
TTS_LOOP_AUTOSTART = (os.environ.get("TTS_LOOP_AUTOSTART") or "true").lower() != "false"
POKE_LOG_FILE = os.environ.get("POKE_LOG_FILE") or "poke-responses.log"
MIN_AUDIO_BYTES = int(os.environ.get("MIN_AUDIO_BYTES") or "8000")
CHAT_DB_PATH = os.environ.get("CHAT_DB_PATH") or str(
    Path.home() / "Library" / "Messages" / "chat.db"
)
POKE_HANDLE_ID = int(os.environ.get("POKE_HANDLE_ID") or "0")
CHAT_POLL_MS = int(os.environ.get("CHAT_POLL_MS") or "1000")
RESPONSE_TIMEOUT_MS = int(os.environ.get("RESPONSE_TIMEOUT_MS") or "120000")
TTS_LOOP_POLL_MS = int(os.environ.get("TTS_LOOP_POLL_MS") or "1000")

SILENCE_THRESHOLD = os.environ.get("SILENCE_THRESHOLD") or "5%"
SILENCE_START_DURATION = os.environ.get("SILENCE_START_DURATION") or "0.1"
SILENCE_STOP_DURATION = os.environ.get("SILENCE_STOP_DURATION") or "1.0"
RECORD_SAMPLE_RATE = os.environ.get("RECORD_SAMPLE_RATE") or ""
# Max recording duration (seconds) for speech-to-text; recording stops at silence or this limit
RECORD_MAX_SECONDS = int(os.environ.get("RECORD_MAX_SECONDS") or "15")

SOUND_EFFECTS_ENABLED = (os.environ.get("SOUND_EFFECTS_ENABLED") or "true").lower() != "false"
SOUND_EFFECTS_DIR = os.environ.get("SOUND_EFFECTS_DIR") or str(Path.cwd() / "sound-effects")
START_RECORDING_SOUND = os.environ.get("START_RECORDING_SOUND") or "start-recording.mp3"
STOP_RECORDING_SOUND = os.environ.get("STOP_RECORDING_SOUND") or "stop-recording.mp3"
NO_RECORDING_SOUND = os.environ.get("NO_RECORDING_SOUND") or "no-recording.mp3"

# ElevenLabs voice name -> ID
ELEVENLABS_VOICES = {
    "rachel": "21m00Tcm4TlvDq8ikWAM",
    "drew": "29vD33N1CtxCmqQRPOHJ",
    "clyde": "2EiwWnXFnvU5JabPnv8n",
    "domi": "AZnzlk1XvdvUeBnXmlld",
    "dave": "CYw3kZ02Hs0563khs1Fj",
    "fin": "D38z5RcWu1voky8WS1ja",
    "sarah": "EXAVITQu4vr4xnSDxMaL",
    "antoni": "ErXwobaYiN019PkySvjV",
    "thomas": "GBv7mTt0atIp3Br8iCZE",
    "charlie": "IKne3meq5aSn9XLyUdCD",
    "emily": "LcfcDJNUP1GQjkzn1xUU",
    "elli": "MF3mGyEYCl7XYWbV9V6O",
    "callum": "N2lVS1w4EtoT3dr4eOWO",
    "patrick": "ODq5zmih8GrVes37Dizd",
    "harry": "SOYHLrjzK2X1ezoPC6cr",
    "liam": "TX3LPaxmHKxFdv7VOQHJ",
    "josh": "TxGEqnHWrfWFTfGW9XjX",
    "arnold": "VR6AewLTigWG4xSOukaG",
    "charlotte": "XB0fDUnXU5powFXDhCwa",
    "matilda": "XrExE9yKIg1WjnnlVkGX",
    "james": "ZQe5CZNOzWyzPSCn5a3c",
    "jessica": "cgSgspJ2msm6clMCkdW9",
    "michael": "flq6f7yk4E4fJM5XTYuZ",
    "ethan": "g5CIjZEefAph4nQFvHAz",
    "chris": "iP95p4xoKVk53GoZ742B",
    "brian": "nPczCjzI2devNBz1zQrb",
    "daniel": "onwK4e9ZLuTAKqWW03F9",
    "lily": "pFZP5JQG7iQjIQuC4Bku",
    "bill": "pqHfZKP75CvOlQylNhV4",
    "george": "JBFqnCBsd6RMkjVDRZzb",
    "nicole": "piTKgcLEGmPE4e6mEKli",
    "adam": "pNInz6obpgDQGcFmaJgB",
}


def _has_command(cmd: str) -> bool:
    return shutil.which(cmd) is not None


RECORD_BIN = "rec" if _has_command("rec") else ("sox" if _has_command("sox") else None)
PLAY_BIN = "afplay" if _has_command("afplay") else ("ffplay" if _has_command("ffplay") else None)
TTS_FORMAT = (
    TTS_RESPONSE_FORMAT
    if TTS_RESPONSE_FORMAT in ("wav", "pcm")
    else ("pcm" if PLAY_BIN == "ffplay" else "wav")
)

# Shared state
_inbound_queue: list[dict] = []
_inbound_waiters: list[asyncio.Future] = []
_is_busy = False
_latest_transcript: str | None = None
_last_seen_date = "0"
_last_seen_row_id = "0"
_last_inbound_message: dict | None = None
_poll_busy = False
_tts_loop_running = False
_tts_loop_busy = False
_stop_requested = False
_poll_thread: threading.Thread | None = None
_tts_loop_task: asyncio.Task | None = None

# Explicit start/stop recording state (for WS hand_open / hand_close flow)
_recording_process: subprocess.Popen | None = None
_recording_audio_path: str | None = None


def _sqlite_int(val) -> str:
    s = str(val or "0").strip()
    return s if re.match(r"^\d+$", s) else "0"


def _sanitize_tts(text: str) -> str:
    if not text:
        return ""
    # Don't speak messages containing these domains
    for domain in ("view-email.cx", "authorize.cx"):
        if domain in text:
            text = text.replace(domain, "")
    # Remove emoji (common ranges)
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "]+",
        flags=re.UNICODE,
    )
    text = emoji_pattern.sub("", text)
    text = re.sub(r"[\u200D\uFE0F]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _temp_audio_path(prefix: str, ext: str = "wav") -> str:
    return str(Path(tempfile.gettempdir()) / f"{prefix}-{uuid.uuid4()}.{ext}")


def _run_cmd(cmd: list[str], inherit_stdio: bool = False) -> None:
    subprocess.run(
        cmd,
        check=True,
        capture_output=not inherit_stdio,
        env=os.environ,
    )


def _run_cmd_capture(cmd: list[str]) -> tuple[str, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, env=os.environ)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} exited {r.returncode}: {r.stderr or r.stdout}")
    return r.stdout, r.stderr


async def _poke_send_message(text: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{POKE_API}/inbound/api-message",
            headers={
                "Authorization": f"Bearer {POKE_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"message": text},
        )
        if r.status_code == 401:
            raise RuntimeError("Poke: Invalid API key. Get one at https://poke.com/kitchen/api-keys")
        if r.status_code == 403:
            raise RuntimeError("Poke: API key lacks permission. Check scopes at https://poke.com/kitchen/api-keys")
        if r.status_code == 429:
            raise RuntimeError("Poke: Rate limited. Slow down and retry.")
        r.raise_for_status()
        return r.json()


def _log_poke_response(data: dict) -> None:
    try:
        line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}]\n{json.dumps(data, indent=2)}\n\n"
        with open(POKE_LOG_FILE, "a") as f:
            f.write(line)
    except Exception:
        pass


def _snapshot_chat_db() -> tuple[str, callable]:
    snap = Path(tempfile.gettempdir()) / f"chat-{uuid.uuid4()}.db"
    shutil.copy2(CHAT_DB_PATH, snap)
    wal = Path(f"{CHAT_DB_PATH}-wal")
    shm = Path(f"{CHAT_DB_PATH}-shm")
    if wal.exists():
        shutil.copy2(wal, f"{snap}-wal")
    if shm.exists():
        shutil.copy2(shm, f"{snap}-shm")

    def cleanup():
        for p in [snap, Path(f"{snap}-wal"), Path(f"{snap}-shm")]:
            if p.exists():
                p.unlink(missing_ok=True)

    return str(snap), cleanup


def _query_chat_db(sql: str) -> list[dict]:
    snap, cleanup = _snapshot_chat_db()
    try:
        conn = sqlite3.connect(snap)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    finally:
        cleanup()


def _enqueue_inbound(msg: dict) -> None:
    global _last_inbound_message
    _last_inbound_message = msg
    if _inbound_waiters:
        w = _inbound_waiters.pop(0)
        if not w.done():
            w.get_loop().call_soon_threadsafe(w.set_result, msg)
        return
    _inbound_queue.append(msg)


def _poll_chat_db_once() -> None:
    global _poll_busy, _last_seen_date, _last_seen_row_id
    if not POKE_HANDLE_ID or _stop_requested or _poll_busy or _tts_loop_busy:
        return
    _poll_busy = True
    try:
        last_date = _sqlite_int(_last_seen_date)
        last_row = _sqlite_int(_last_seen_row_id)
        rows = _query_chat_db(f"""
SELECT
  CAST(message.ROWID AS TEXT) AS row_id,
  CAST(message.date AS TEXT) AS date,
  message.is_from_me AS is_from_me,
  message.text AS text
FROM message
WHERE message.handle_id = {POKE_HANDLE_ID}
AND (
  message.date > {last_date}
  OR (message.date = {last_date} AND message.ROWID > {last_row})
)
ORDER BY message.date ASC, message.ROWID ASC
""")
        for row in rows:
            _last_seen_date = str(row.get("date") or "0")
            _last_seen_row_id = str(row.get("row_id") or "0")
            if int(row.get("is_from_me") or 0) == 1:
                continue
            _enqueue_inbound({
                "rowId": _last_seen_row_id,
                "date": _last_seen_date,
                "text": row.get("text") or "",
                "receivedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
    finally:
        _poll_busy = False


def _poll_loop() -> None:
    while not _stop_requested:
        try:
            _poll_chat_db_once()
        except Exception as e:
            print(f"[chatdb] poll error: {e}")
        time.sleep(CHAT_POLL_MS / 1000.0)


def _init_checkpoint() -> None:
    global _last_seen_date, _last_seen_row_id
    if not POKE_HANDLE_ID:
        return
    try:
        rows = _query_chat_db(f"""
SELECT CAST(message.ROWID AS TEXT) AS row_id, CAST(message.date AS TEXT) AS date
FROM message
WHERE message.handle_id = {POKE_HANDLE_ID}
ORDER BY message.date DESC, message.ROWID DESC
LIMIT 1
""")
        if rows:
            _last_seen_date = str(rows[0].get("date") or "0")
            _last_seen_row_id = str(rows[0].get("row_id") or "0")
        print(f"[chatdb] checkpoint date={_last_seen_date} row_id={_last_seen_row_id}")
    except (PermissionError, OSError) as e:
        print(f"[chatdb] Cannot read chat.db (grant Full Disk Access): {e}")


async def _wait_for_inbound(timeout_ms: int) -> dict | None:
    if _inbound_queue:
        return _inbound_queue.pop(0)
    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    _inbound_waiters.append(fut)
    try:
        return await asyncio.wait_for(
            asyncio.shield(fut),
            timeout=timeout_ms / 1000.0,
        )
    except asyncio.TimeoutError:
        if fut in _inbound_waiters:
            _inbound_waiters.remove(fut)
        raise RuntimeError("Timed out waiting for inbound Poke message from chat.db")


def _record_until_pause(output_path: str) -> None:
    if not RECORD_BIN:
        raise RuntimeError("No recorder. Install SoX: brew install sox")
    args = ["-q", "-c", "1", "-b", "16", output_path, "silence", "1",
            SILENCE_START_DURATION, SILENCE_THRESHOLD, "1",
            SILENCE_STOP_DURATION, SILENCE_THRESHOLD]
    if RECORD_SAMPLE_RATE:
        args = ["-r", RECORD_SAMPLE_RATE] + args
    cmd = (["rec"] if RECORD_BIN == "rec" else ["sox", "-d"]) + args
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        proc.wait(timeout=RECORD_MAX_SECONDS)
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.wait(timeout=2)


def _transcribe_audio(audio_path: str) -> str:
    from openai import OpenAI
    from groq import Groq

    with open(audio_path, "rb") as f:
        if PROVIDER == "other" and GROQ_API_KEY:
            client = Groq(api_key=GROQ_API_KEY)
            result = client.audio.transcriptions.create(file=f, model=STT_MODEL)
        else:
            client = OpenAI(api_key=OPENAI_API_KEY)
            result = client.audio.transcriptions.create(file=f, model=STT_MODEL)
        return (result.text or "").strip()


def _synthesize_speech(text: str, output_path: str, fmt: str = "wav") -> None:
    from openai import OpenAI

    if PROVIDER == "other" and ELEVENLABS_API_KEY:
        voice_id = ELEVENLABS_VOICES.get(TTS_VOICE.lower(), TTS_VOICE)
        payload = {
            "text": text,
            "model_id": ELEVENLABS_MODEL,
            "output_format": "mp3_44100_128",
            "voice_settings": {"speed": TTS_SPEED},
        }
        with httpx.Client() as client:
            r = client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": ELEVENLABS_API_KEY,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            r.raise_for_status()
            Path(output_path).write_bytes(r.content)
        return

    client = OpenAI(api_key=OPENAI_API_KEY)
    speech = client.audio.speech.create(
        model=TTS_MODEL,
        voice=TTS_VOICE,
        input=text,
        speed=TTS_SPEED,
        format=fmt,
    )
    Path(output_path).write_bytes(speech.content)


def _play_audio(audio_path: str, fmt: str = "wav") -> None:
    if not PLAY_BIN:
        raise RuntimeError("No playback. Use afplay (macOS) or ffplay (brew install ffmpeg)")
    if PLAY_BIN == "afplay":
        if fmt not in ("wav", "mp3"):
            raise RuntimeError("afplay needs wav/mp3. Set TTS_RESPONSE_FORMAT=wav or use ffplay")
        _run_cmd(["afplay", audio_path], inherit_stdio=True)
        return
    if fmt == "pcm":
        _run_cmd(["ffplay", "-f", "s16le", "-ar", "24000", "-ac", "1",
                  "-nodisp", "-autoexit", "-loglevel", "error", audio_path], inherit_stdio=True)
    else:
        _run_cmd(["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", audio_path], inherit_stdio=True)


def _play_notification_sound(filename: str) -> None:
    if not SOUND_EFFECTS_ENABLED or not PLAY_BIN or not filename:
        return
    path = Path(SOUND_EFFECTS_DIR) / filename
    if not path.exists():
        return
    try:
        _run_cmd([PLAY_BIN, str(path)], inherit_stdio=True)
    except Exception as e:
        print(f"[voice] notification sound failed ({filename}): {e}")


def _speak_text(text: str) -> None:
    text = _sanitize_tts(text or "")
    if not text:
        return
    fmt = "mp3" if PROVIDER == "other" else TTS_FORMAT
    ext = "mp3" if fmt == "mp3" else ("pcm" if fmt == "pcm" else "wav")
    out = _temp_audio_path("voice-out", ext)
    try:
        _synthesize_speech(text, out, fmt)
        _play_audio(out, fmt)
    finally:
        if Path(out).exists():
            Path(out).unlink(missing_ok=True)


async def _tts_loop_tick() -> None:
    global _tts_loop_busy
    if not _tts_loop_running or _stop_requested or _tts_loop_busy:
        return
    _tts_loop_busy = True
    try:
        while _inbound_queue and not _is_busy and _tts_loop_running and not _stop_requested:
            parts = []
            while _inbound_queue and not _is_busy and _tts_loop_running and not _stop_requested:
                msg = _inbound_queue.pop(0)
                cleaned = _sanitize_tts(msg.get("text") or "")
                if cleaned:
                    parts.append(cleaned)
                if not TTS_BATCH_QUEUE:
                    break
            spoken = TTS_BATCH_SEPARATOR.join(parts).strip()
            if not spoken:
                continue
            print(f"[tts-loop] Speaking: {spoken}")
            try:
                await asyncio.to_thread(_speak_text, spoken)
            except Exception as e:
                print(f"[tts-loop] TTS error: {e}")
    finally:
        _tts_loop_busy = False


async def _tts_loop() -> None:
    while _tts_loop_running and not _stop_requested:
        await _tts_loop_tick()
        await asyncio.sleep(TTS_LOOP_POLL_MS / 1000.0)


def start_chat_poller() -> None:
    global _poll_thread
    if not POKE_HANDLE_ID or _poll_thread:
        return
    try:
        _query_chat_db("SELECT 1")
    except (PermissionError, OSError):
        print("[chatdb] Skipping poller (no chat.db access)")
        return
    _poll_thread = threading.Thread(target=_poll_loop, daemon=True)
    _poll_thread.start()
    print("[chatdb] poller started")


def start_tts_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _tts_loop_running, _tts_loop_task
    if _tts_loop_running:
        return
    _tts_loop_running = True
    _tts_loop_task = loop.create_task(_tts_loop())
    print("[tts-loop] Started")


def stop_tts_loop() -> None:
    global _tts_loop_running, _tts_loop_task
    if not _tts_loop_running:
        return
    _tts_loop_running = False
    if _tts_loop_task and not _tts_loop_task.done():
        _tts_loop_task.cancel()
    _tts_loop_task = None
    print("[tts-loop] Stopped")


async def run_record_turn_once(
    send_to_poke: bool = True,
    talkback: bool = True,
    await_inbound: bool = True,
    timeout_ms: int | None = None,
) -> dict:
    global _is_busy, _latest_transcript
    timeout_ms = timeout_ms or RESPONSE_TIMEOUT_MS

    if _inbound_queue:
        _play_notification_sound(NO_RECORDING_SOUND)
        return {
            "ok": False,
            "reason": "queue_pending",
            "message": "Inbound queue has messages pending speech",
            "queueSize": len(_inbound_queue),
        }
    if _tts_loop_busy:
        _play_notification_sound(NO_RECORDING_SOUND)
        return {"ok": False, "reason": "speaking", "message": "Poke is busy speaking"}
    if _is_busy:
        _play_notification_sound(NO_RECORDING_SOUND)
        return {"ok": False, "reason": "busy", "message": "Service is busy with another turn"}

    input_path = _temp_audio_path("voice-in", "wav")
    _is_busy = True
    try:
        print("[voice] Listening once... mic locked")
        _play_notification_sound(START_RECORDING_SOUND)
        await asyncio.to_thread(_record_until_pause, input_path)
        _play_notification_sound(STOP_RECORDING_SOUND)

        size = Path(input_path).stat().st_size
        if size < MIN_AUDIO_BYTES:
            _play_notification_sound(NO_RECORDING_SOUND)
            return {"ok": False, "reason": "audio_too_short"}

        transcript = await asyncio.to_thread(_transcribe_audio, input_path)
        _latest_transcript = transcript
        if not transcript:
            _play_notification_sound(NO_RECORDING_SOUND)
            return {"ok": False, "reason": "empty_transcript"}

        print(f"[you] {transcript}")

        poke_ack = None
        inbound = None

        if send_to_poke:
            print("[voice] Sending to Poke... mic locked")
            poke_ack = await _poke_send_message(transcript)
            print(f"[poke:ack] {json.dumps(poke_ack)}")
            _log_poke_response(poke_ack)

            if await_inbound and POKE_HANDLE_ID:
                inbound = await _wait_for_inbound(timeout_ms)
                print(f"[poke:inbound] {json.dumps(inbound)}")

                if talkback and TALKBACK_ENABLED and inbound.get("text"):
                    print("[voice] Speaking inbound message... mic locked")
                    await asyncio.to_thread(_speak_text, inbound["text"])

        return {"ok": True, "transcript": transcript, "pokeAck": poke_ack, "inbound": inbound}
    except Exception as e:
        _play_notification_sound(NO_RECORDING_SOUND)
        raise
    finally:
        if Path(input_path).exists():
            Path(input_path).unlink(missing_ok=True)
        _is_busy = False


def get_health() -> dict:
    return {
        "ok": True,
        "busy": _is_busy,
        "queueSize": len(_inbound_queue),
        "lastSeenDate": _last_seen_date,
        "lastSeenRowId": _last_seen_row_id,
        "latestTranscript": _latest_transcript,
        "lastInboundMessage": _last_inbound_message,
    }


def get_queue() -> dict:
    return {"ok": True, "queueSize": len(_inbound_queue), "messages": list(_inbound_queue)}


async def speak_next_from_queue() -> dict | None:
    if not _inbound_queue:
        return None
    msg = _inbound_queue.pop(0)
    if msg.get("text"):
        await asyncio.to_thread(_speak_text, msg["text"])
    return msg


async def speak_text_direct(text: str) -> None:
    await asyncio.to_thread(_speak_text, text)


async def transcribe_file(audio_path: str) -> str:
    return await asyncio.to_thread(_transcribe_audio, audio_path)


def voice_startup() -> None:
    print("[voice] Service starting.")
    print(f"[voice] Provider: {PROVIDER}")
    print(f"[voice] Recorder: {RECORD_BIN or 'not found'}")
    print(f"[voice] Player: {PLAY_BIN or 'not found'}")
    print(f"[voice] Talkback: {TALKBACK_ENABLED}")
    print(f"[chatdb] path: {CHAT_DB_PATH}")
    print(f"[chatdb] handle_id: {POKE_HANDLE_ID or 'not set'}")
    _init_checkpoint()
    start_chat_poller()
    if TALKBACK_ENABLED and TTS_LOOP_AUTOSTART:
        pass  # TTS loop started in lifespan


# ---------------------------------------------------------------------------
# Explicit start / stop recording (WebSocket hand_open / hand_close flow)
# ---------------------------------------------------------------------------

def start_recording() -> None:
    """
    Begin recording from the mic (SoX) without silence detection.
    Returns immediately; the process runs in the background until
    stop_recording() is called.
    """
    global _recording_process, _recording_audio_path

    # If already recording, ignore
    if _recording_process is not None:
        print("[voice] start_recording: already recording, ignoring")
        return

    if not RECORD_BIN:
        print("[voice] start_recording: no recorder (install SoX)")
        return

    _recording_audio_path = _temp_audio_path("voice-ws", "wav")
    _play_notification_sound(START_RECORDING_SOUND)

    # Record continuously (no silence detection) — mono 16-bit WAV
    args: list[str] = []
    if RECORD_SAMPLE_RATE:
        args += ["-r", RECORD_SAMPLE_RATE]
    args += ["-q", "-c", "1", "-b", "16", _recording_audio_path]

    if RECORD_BIN == "rec":
        cmd = ["rec"] + args
    else:
        cmd = ["sox", "-d"] + args

    print(f"[voice] start_recording: {' '.join(cmd)}")
    _recording_process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=os.environ,
    )


def stop_recording() -> str | None:
    """
    Stop the recording started by start_recording().
    Returns the path to the recorded WAV file, or None if nothing was recording.
    """
    global _recording_process, _recording_audio_path

    if _recording_process is None:
        print("[voice] stop_recording: not recording")
        return None

    # Send SIGINT so SoX finalises the WAV header properly
    import signal
    try:
        _recording_process.send_signal(signal.SIGINT)
        _recording_process.wait(timeout=5)
    except Exception:
        _recording_process.kill()
        _recording_process.wait(timeout=3)

    _play_notification_sound(STOP_RECORDING_SOUND)

    audio_path = _recording_audio_path
    _recording_process = None
    _recording_audio_path = None

    print(f"[voice] stop_recording: saved to {audio_path}")
    return audio_path


async def stop_and_process(
    on_event=None,
    send_to_poke: bool = True,
    talkback: bool = True,
    await_inbound: bool = True,
    timeout_ms: int | None = None,
) -> dict:
    """
    Stop recording, transcribe, send to Poke, wait for response, speak it.

    *on_event* is an async callable that receives event dicts to broadcast
    over the WebSocket (e.g. poke_speaking_start / poke_speaking_stop).
    """
    global _is_busy, _latest_transcript
    timeout_ms = timeout_ms or RESPONSE_TIMEOUT_MS

    audio_path = stop_recording()
    if audio_path is None:
        return {"ok": False, "reason": "not_recording"}

    _is_busy = True
    try:
        # Check audio size
        size = Path(audio_path).stat().st_size if Path(audio_path).exists() else 0
        if size < MIN_AUDIO_BYTES:
            _play_notification_sound(NO_RECORDING_SOUND)
            return {"ok": False, "reason": "audio_too_short"}

        # Transcribe
        transcript = await asyncio.to_thread(_transcribe_audio, audio_path)
        _latest_transcript = transcript
        if not transcript:
            _play_notification_sound(NO_RECORDING_SOUND)
            return {"ok": False, "reason": "empty_transcript"}

        print(f"[you] {transcript}")

        poke_ack = None
        inbound = None

        if send_to_poke:
            print("[voice] Sending to Poke...")
            poke_ack = await _poke_send_message(transcript)
            print(f"[poke:ack] {json.dumps(poke_ack)}")
            _log_poke_response(poke_ack)

            if await_inbound and POKE_HANDLE_ID:
                inbound = await _wait_for_inbound(timeout_ms)
                inbound_text = (inbound or {}).get("text", "")
                print(f"[poke:inbound] {json.dumps(inbound)}")

                if talkback and TALKBACK_ENABLED and inbound_text:
                    # Emit poke_speaking_start
                    if on_event:
                        await on_event({"type": "poke_speaking_start", "text": inbound_text})

                    print(f"[voice] Speaking: {inbound_text}")
                    await asyncio.to_thread(_speak_text, inbound_text)

                    # Emit poke_speaking_stop
                    if on_event:
                        await on_event({"type": "poke_speaking_stop"})

        return {"ok": True, "transcript": transcript, "pokeAck": poke_ack, "inbound": inbound}

    except Exception as e:
        _play_notification_sound(NO_RECORDING_SOUND)
        print(f"[voice] stop_and_process error: {e}")
        raise
    finally:
        if audio_path and Path(audio_path).exists():
            Path(audio_path).unlink(missing_ok=True)
        _is_busy = False
