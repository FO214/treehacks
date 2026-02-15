import "dotenv/config";

import fs from "node:fs";
import fsp from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import util from "node:util";

import express from "express";
import OpenAI from "openai";
import { Poke } from "poke";

const OPENAI_API_KEY = process.env.OPENAI_API_KEY;
const POKE_API_KEY = process.env.POKE_API_KEY;

if (!OPENAI_API_KEY) {
  throw new Error("OPENAI_API_KEY is required.");
}
if (!POKE_API_KEY) {
  throw new Error("POKE_API_KEY is required.");
}

const STT_MODEL = process.env.STT_MODEL || "gpt-4o-mini-transcribe";
const TTS_MODEL = process.env.TTS_MODEL || "gpt-4o-mini-tts";
const TTS_VOICE = process.env.TTS_VOICE || "alloy";
const TTS_SPEED = Number(process.env.TTS_SPEED || "1.0");
const TTS_RESPONSE_FORMAT_ENV = String(process.env.TTS_RESPONSE_FORMAT || "").trim().toLowerCase();
const TTS_BATCH_QUEUE = (process.env.TTS_BATCH_QUEUE || "true").toLowerCase() !== "false";
const TTS_BATCH_SEPARATOR = process.env.TTS_BATCH_SEPARATOR || " ";
const SOUND_EFFECTS_ENABLED = (process.env.SOUND_EFFECTS_ENABLED || "true").toLowerCase() !== "false";
const SOUND_EFFECTS_DIR = process.env.SOUND_EFFECTS_DIR || path.join(process.cwd(), "sound-effects");
const START_RECORDING_SOUND = process.env.START_RECORDING_SOUND || "start-recording.mp3";
const STOP_RECORDING_SOUND = process.env.STOP_RECORDING_SOUND || "stop-recording.mp3";
const NO_RECORDING_SOUND = process.env.NO_RECORDING_SOUND || "no-recording.mp3";
const MIN_AUDIO_BYTES = Number(process.env.MIN_AUDIO_BYTES || 8_000);
const SESSION_BOOT_MESSAGE = process.env.POKE_SESSION_BOOT_MESSAGE || "";
const RECORD_SAMPLE_RATE = process.env.RECORD_SAMPLE_RATE || "";
const SILENCE_THRESHOLD = process.env.SILENCE_THRESHOLD || "5%";
const SILENCE_START_DURATION = process.env.SILENCE_START_DURATION || "0.1";
const SILENCE_STOP_DURATION = process.env.SILENCE_STOP_DURATION || "1.0";
const TALKBACK_ENABLED = (process.env.TALKBACK_ENABLED || "true").toLowerCase() !== "false";
const TTS_LOOP_AUTOSTART = (process.env.TTS_LOOP_AUTOSTART || "true").toLowerCase() !== "false";
const POKE_LOG_FILE = process.env.POKE_LOG_FILE || "poke-responses.log";

const CHAT_DB_PATH = process.env.CHAT_DB_PATH || path.join(os.homedir(), "Library", "Messages", "chat.db");
const POKE_HANDLE_ID = Number(process.env.POKE_HANDLE_ID || "0");
const CHAT_POLL_MS = Number(process.env.CHAT_POLL_MS || "1000");
const RESPONSE_TIMEOUT_MS = Number(process.env.RESPONSE_TIMEOUT_MS || "120000");
const HTTP_PORT = Number(process.env.VOICE_HTTP_PORT || "8787");

const openai = new OpenAI({ apiKey: OPENAI_API_KEY });
const poke = new Poke({ apiKey: POKE_API_KEY });

function hasCommand(command) {
  const pathEnv = process.env.PATH || "";
  const dirs = pathEnv.split(path.delimiter);
  for (const dir of dirs) {
    if (!dir) continue;
    const full = path.join(dir, command);
    if (fs.existsSync(full)) {
      return true;
    }
  }
  return false;
}

const RECORD_BIN = hasCommand("rec") ? "rec" : hasCommand("sox") ? "sox" : null;
const PLAY_BIN = hasCommand("afplay") ? "afplay" : hasCommand("ffplay") ? "ffplay" : null;
const TTS_RESPONSE_FORMAT =
  (TTS_RESPONSE_FORMAT_ENV === "wav" || TTS_RESPONSE_FORMAT_ENV === "pcm"
    ? TTS_RESPONSE_FORMAT_ENV
    : "") || (PLAY_BIN === "ffplay" ? "pcm" : "wav");

let stopRequested = false;
let isBusy = false;
let latestTranscript = null;
let lastSeenDate = "0";
let lastSeenRowId = "0";
let lastInboundMessage = null;
let pollTimer = null;
let pollBusy = false;
let ttsLoopTimer = null;
let ttsLoopRunning = false;
let ttsLoopBusy = false;

const inboundQueue = [];
const inboundWaiters = [];

function sqliteIntegerLiteral(value) {
  const normalized = String(value ?? "0").trim();
  return /^[0-9]+$/.test(normalized) ? normalized : "0";
}

function sanitizeTtsText(text) {
  return String(text || "")
    // Remove most emoji glyphs + joiners/variation selectors that keep emoji clusters.
    .replace(/\p{Extended_Pictographic}/gu, "")
    .replace(/[\u{1F1E6}-\u{1F1FF}\u200D\uFE0F]/gu, "")
    .replace(/\s+/g, " ")
    .trim();
}

process.on("SIGINT", () => {
  stopRequested = true;
  if (pollTimer) clearInterval(pollTimer);
  if (ttsLoopTimer) clearInterval(ttsLoopTimer);
  process.exit(0);
});
process.on("SIGTERM", () => {
  stopRequested = true;
  if (pollTimer) clearInterval(pollTimer);
  if (ttsLoopTimer) clearInterval(ttsLoopTimer);
  process.exit(0);
});

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function runCommand(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      stdio: options.stdio || "ignore",
      env: process.env,
    });

    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(`${command} exited with code ${code}`));
      }
    });
  });
}

function runCommandCapture(command, args) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      stdio: ["ignore", "pipe", "pipe"],
      env: process.env,
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });

    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0) {
        resolve({ stdout, stderr });
      } else {
        reject(new Error(`${command} exited with code ${code}: ${stderr || stdout}`));
      }
    });
  });
}

function tempAudioPath(prefix, extension = "wav") {
  return path.join(os.tmpdir(), `${prefix}-${randomUUID()}.${extension}`);
}

function safeStringify(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return util.inspect(value, { depth: null, colors: false });
  }
}

async function cleanup(...paths) {
  await Promise.all(paths.map((p) => fsp.unlink(p).catch(() => undefined)));
}

async function logPokeResponse(fullResponse) {
  const line = `[${new Date().toISOString()}]\n${safeStringify(fullResponse)}\n\n`;
  await fsp.appendFile(POKE_LOG_FILE, line, "utf8");
}

async function snapshotChatDb() {
  const id = randomUUID();
  const snapshot = path.join(os.tmpdir(), `chat-${id}.db`);
  const snapshotWal = `${snapshot}-wal`;
  const snapshotShm = `${snapshot}-shm`;

  try {
    await fsp.copyFile(CHAT_DB_PATH, snapshot);
  } catch (error) {
    if (error && (error.code === "EPERM" || error.code === "EACCES")) {
      throw new Error(
        `Cannot read ${CHAT_DB_PATH}. On macOS, grant Full Disk Access to the app running this process (Terminal/iTerm/VS Code and Node), then restart it.`,
      );
    }
    throw error;
  }

  const walSrc = `${CHAT_DB_PATH}-wal`;
  const shmSrc = `${CHAT_DB_PATH}-shm`;
  if (fs.existsSync(walSrc)) {
    await fsp.copyFile(walSrc, snapshotWal).catch(() => undefined);
  }
  if (fs.existsSync(shmSrc)) {
    await fsp.copyFile(shmSrc, snapshotShm).catch(() => undefined);
  }

  return {
    snapshot,
    async cleanupSnapshot() {
      await cleanup(snapshot, snapshotWal, snapshotShm);
    },
  };
}

async function queryChatDb(sql) {
  const { snapshot, cleanupSnapshot } = await snapshotChatDb();
  try {
    const { stdout } = await runCommandCapture("sqlite3", ["-json", snapshot, sql]);
    const trimmed = stdout.trim();
    if (!trimmed) return [];
    const parsed = JSON.parse(trimmed);
    return Array.isArray(parsed) ? parsed : [];
  } finally {
    await cleanupSnapshot();
  }
}

async function initCheckpointFromLatestMessage() {
  if (!POKE_HANDLE_ID) {
    console.warn("[chatdb] POKE_HANDLE_ID not set, poller disabled.");
    return;
  }

  const rows = await queryChatDb(`
SELECT CAST(message.ROWID AS TEXT) AS row_id, CAST(message.date AS TEXT) AS date
FROM message
WHERE message.handle_id = ${POKE_HANDLE_ID}
ORDER BY message.date DESC, message.ROWID DESC
LIMIT 1;
`);

  if (rows.length > 0) {
    lastSeenDate = String(rows[0].date || "0");
    lastSeenRowId = String(rows[0].row_id || "0");
  }

  console.log(`[chatdb] checkpoint date=${lastSeenDate} row_id=${lastSeenRowId}`);
}

function enqueueInboundMessage(msg) {
  lastInboundMessage = msg;
  if (inboundWaiters.length > 0) {
    const waiter = inboundWaiters.shift();
    waiter(msg);
    return;
  }
  inboundQueue.push(msg);
}

async function pollChatDbOnce() {
  if (!POKE_HANDLE_ID || stopRequested || pollBusy || ttsLoopBusy) return;
  pollBusy = true;

  try {
    const lastDateSql = sqliteIntegerLiteral(lastSeenDate);
    const lastRowIdSql = sqliteIntegerLiteral(lastSeenRowId);
    let enqueuedCount = 0;
    const rows = await queryChatDb(`
SELECT
  CAST(message.ROWID AS TEXT) AS row_id,
  CAST(message.date AS TEXT) AS date,
  message.is_from_me AS is_from_me,
  message.text AS text
FROM message
WHERE message.handle_id = ${POKE_HANDLE_ID}
AND (
  message.date > ${lastDateSql}
  OR (message.date = ${lastDateSql} AND message.ROWID > ${lastRowIdSql})
)
ORDER BY message.date ASC, message.ROWID ASC;
`);

    for (const row of rows) {
      const rowDate = String(row.date || "0");
      const rowId = String(row.row_id || "0");

      lastSeenDate = rowDate;
      lastSeenRowId = rowId;

      if (Number(row.is_from_me || 0) === 1) {
        continue;
      }

      const msg = {
        rowId,
        date: rowDate,
        text: row.text || "",
        receivedAt: new Date().toISOString(),
      };

      enqueueInboundMessage(msg);
      enqueuedCount += 1;
    }

    if (enqueuedCount > 0) {
      console.log(`[chatdb] queue (${inboundQueue.length}):`, inboundQueue.map(m => m.text));
    }
  } finally {
    pollBusy = false;
  }
}

function startChatDbPoller() {
  if (!POKE_HANDLE_ID) return;
  pollTimer = setInterval(async () => {
    try {
      await pollChatDbOnce();
    } catch (error) {
      console.error("[chatdb] poll error:", error?.message || error);
    }
  }, CHAT_POLL_MS);
}

const TTS_LOOP_POLL_MS = Number(process.env.TTS_LOOP_POLL_MS || "1000");

async function ttsLoopTick() {
  if (!ttsLoopRunning || stopRequested || ttsLoopBusy) return;

  ttsLoopBusy = true;
  try {
    while (inboundQueue.length > 0 && !isBusy && ttsLoopRunning && !stopRequested) {
      const textParts = [];
      while (inboundQueue.length > 0 && !isBusy && ttsLoopRunning && !stopRequested) {
        const msg = inboundQueue.shift();
        const cleaned = sanitizeTtsText(msg?.text || "");
        if (cleaned) textParts.push(cleaned);
        if (!TTS_BATCH_QUEUE) break;
      }

      const spokenText = textParts.join(TTS_BATCH_SEPARATOR).trim();
      if (!spokenText) {
        continue;
      }

      console.log(`[tts-loop] Speaking${textParts.length > 1 ? ` batch(${textParts.length})` : ""}: ${spokenText}`);
      try {
        await speakText(spokenText);
      } catch (error) {
        console.error("[tts-loop] TTS error:", error?.message || error);
      }
    }
  } finally {
    ttsLoopBusy = false;
  }
}

function startTtsLoop() {
  if (ttsLoopRunning) return false;
  ttsLoopRunning = true;
  ttsLoopTimer = setInterval(ttsLoopTick, TTS_LOOP_POLL_MS);
  console.log("[tts-loop] Started");
  return true;
}

function stopTtsLoop() {
  if (!ttsLoopRunning) return false;
  ttsLoopRunning = false;
  ttsLoopBusy = false;
  if (ttsLoopTimer) {
    clearInterval(ttsLoopTimer);
    ttsLoopTimer = null;
  }
  console.log("[tts-loop] Stopped");
  return true;
}

function waitForInboundMessage(timeoutMs) {
  if (inboundQueue.length > 0) {
    return Promise.resolve(inboundQueue.shift());
  }

  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      const idx = inboundWaiters.indexOf(onMessage);
      if (idx >= 0) inboundWaiters.splice(idx, 1);
      reject(new Error("Timed out waiting for inbound Poke message from chat.db"));
    }, timeoutMs);

    const onMessage = (msg) => {
      clearTimeout(timeout);
      resolve(msg);
    };

    inboundWaiters.push(onMessage);
  });
}

async function recordUntilPause(outputPath) {
  if (!RECORD_BIN) {
    throw new Error("No recorder found. Install SoX (`brew install sox`) so `rec`/`sox` is available on PATH.");
  }

  const soxArgs = [
    "-q",
    "-c",
    "1",
    "-b",
    "16",
    outputPath,
    "silence",
    "1",
    SILENCE_START_DURATION,
    SILENCE_THRESHOLD,
    "1",
    SILENCE_STOP_DURATION,
    SILENCE_THRESHOLD,
  ];

  if (RECORD_SAMPLE_RATE) {
    soxArgs.splice(1, 0, "-r", RECORD_SAMPLE_RATE);
  }

  if (RECORD_BIN === "rec") {
    await runCommand("rec", soxArgs, { stdio: "inherit" });
    return;
  }

  await runCommand("sox", ["-d", ...soxArgs], { stdio: "inherit" });
}

async function transcribeAudio(audioPath) {
  const result = await openai.audio.transcriptions.create({
    file: fs.createReadStream(audioPath),
    model: STT_MODEL,
  });
  return (result.text || "").trim();
}

async function synthesizeSpeech(text, outputPath, responseFormat = "wav") {
  const speech = await openai.audio.speech.create({
    model: TTS_MODEL,
    voice: TTS_VOICE,
    input: text,
    speed: Number.isFinite(TTS_SPEED) && TTS_SPEED > 0 ? TTS_SPEED : 1.0,
    format: responseFormat,
  });
  const audioBuffer = Buffer.from(await speech.arrayBuffer());
  await fsp.writeFile(outputPath, audioBuffer);
}

async function playAudio(audioPath, responseFormat = "wav") {
  if (!PLAY_BIN) {
    throw new Error("No playback tool found. Use macOS `afplay` or install ffmpeg (`brew install ffmpeg`) for `ffplay`.");
  }
  if (PLAY_BIN === "afplay") {
    if (responseFormat !== "wav") {
      throw new Error("afplay only supports wav in this service. Set TTS_RESPONSE_FORMAT=wav or install ffplay.");
    }
    await runCommand("afplay", [audioPath], { stdio: "inherit" });
    return;
  }
  if (responseFormat === "pcm") {
    await runCommand(
      "ffplay",
      ["-f", "s16le", "-ar", "24000", "-ac", "1", "-nodisp", "-autoexit", "-loglevel", "error", audioPath],
      { stdio: "inherit" },
    );
    return;
  }
  await runCommand("ffplay", ["-nodisp", "-autoexit", "-loglevel", "error", audioPath], {
    stdio: "inherit",
  });
}

async function playNotificationSound(fileName) {
  if (!SOUND_EFFECTS_ENABLED || !PLAY_BIN || !fileName) return;

  const soundPath = path.join(SOUND_EFFECTS_DIR, fileName);
  if (!fs.existsSync(soundPath)) return;

  try {
    if (PLAY_BIN === "afplay") {
      await runCommand("afplay", [soundPath], { stdio: "inherit" });
      return;
    }
    await runCommand("ffplay", ["-nodisp", "-autoexit", "-loglevel", "error", soundPath], { stdio: "inherit" });
  } catch (error) {
    console.warn(`[voice] notification sound failed (${fileName}):`, error?.message || error);
  }
}

async function speakText(text) {
  const extension = TTS_RESPONSE_FORMAT === "pcm" ? "pcm" : "wav";
  const outputPath = tempAudioPath("voice-out", extension);
  try {
    await synthesizeSpeech(text, outputPath, TTS_RESPONSE_FORMAT);
    await playAudio(outputPath, TTS_RESPONSE_FORMAT);
  } finally {
    await cleanup(outputPath);
  }
}

async function runRecordTurnOnce(options = {}) {
  if (inboundQueue.length > 0) {
    await playNotificationSound(NO_RECORDING_SOUND);
    return {
      ok: false,
      reason: "queue_pending",
      message: "Inbound queue has messages pending speech",
      queueSize: inboundQueue.length,
    };
  }
  if (ttsLoopBusy) {
    await playNotificationSound(NO_RECORDING_SOUND);
    return { ok: false, reason: "speaking", message: "Poke is busy speaking" };
  }
  if (isBusy) {
    await playNotificationSound(NO_RECORDING_SOUND);
    return { ok: false, reason: "busy", message: "Service is busy with another turn" };
  }

  const sendToPoke = options.sendToPoke !== false;
  const talkback = options.talkback !== false;
  const awaitInbound = options.awaitInbound !== false;
  const timeoutMs = Number(options.timeoutMs || RESPONSE_TIMEOUT_MS);

  const inputPath = tempAudioPath("voice-in", "wav");
  isBusy = true;

  try {
    console.log("[voice] Listening once... mic locked");
    await playNotificationSound(START_RECORDING_SOUND);
    await recordUntilPause(inputPath);
    await playNotificationSound(STOP_RECORDING_SOUND);

    const stats = await fsp.stat(inputPath);
    if (stats.size < MIN_AUDIO_BYTES) {
      await playNotificationSound(NO_RECORDING_SOUND);
      return { ok: false, reason: "audio_too_short" };
    }

    const transcript = await transcribeAudio(inputPath);
    latestTranscript = transcript;
    if (!transcript) {
      await playNotificationSound(NO_RECORDING_SOUND);
      return { ok: false, reason: "empty_transcript" };
    }

    console.log(`[you] ${transcript}`);

    let pokeAck = null;
    let inbound = null;

    if (sendToPoke) {
      console.log("[voice] Sending to Poke... mic locked");
      pokeAck = await poke.sendMessage(transcript);
      console.log("[poke:ack]", safeStringify(pokeAck));
      await logPokeResponse(pokeAck);

      if (awaitInbound && POKE_HANDLE_ID) {
        inbound = await waitForInboundMessage(timeoutMs);
        console.log("[poke:inbound]", safeStringify(inbound));

        if (talkback && TALKBACK_ENABLED && inbound.text) {
          console.log("[voice] Speaking inbound message... mic locked");
          await speakText(inbound.text);
        }
      }
    }

    return {
      ok: true,
      transcript,
      pokeAck,
      inbound,
    };
  } catch (error) {
    await playNotificationSound(NO_RECORDING_SOUND);
    throw error;
  } finally {
    await cleanup(inputPath);
    isBusy = false;
  }
}

async function startup() {
  console.log("[voice] Service starting.");
  console.log("[voice] Poke client initialized.");
  console.log(`[voice] Recorder: ${RECORD_BIN || "not found"}`);
  console.log(`[voice] Player: ${PLAY_BIN || "not found"}`);
  console.log(`[voice] TTS response format: ${TTS_RESPONSE_FORMAT}`);
  console.log(`[voice] TTS queue batching: ${TTS_BATCH_QUEUE ? "enabled" : "disabled"}`);
  console.log(`[voice] Talkback: ${TALKBACK_ENABLED ? "enabled" : "disabled"}`);
  console.log(`[voice] Poke log file: ${POKE_LOG_FILE}`);
  console.log(`[chatdb] path: ${CHAT_DB_PATH}`);
  console.log(`[chatdb] handle_id: ${POKE_HANDLE_ID || "not set"}`);
  console.log(`[chatdb] poll interval: ${CHAT_POLL_MS}ms`);
  if (SESSION_BOOT_MESSAGE) {
    await poke.sendMessage(SESSION_BOOT_MESSAGE);
    console.log("[voice] Sent session boot message to Poke.");
  }
}

function startHttpServer() {
  const app = express();
  app.use(express.json({ limit: "1mb" }));

  app.get("/health", (req, res) => {
    res.status(200).json({
      ok: true,
      busy: isBusy,
      queueSize: inboundQueue.length,
      lastSeenDate,
      lastSeenRowId,
      latestTranscript,
      lastInboundMessage,
    });
  });

  app.post("/record-once", async (req, res, next) => {
    try {
      const result = await runRecordTurnOnce(req.body || {});
      res.status(200).json(result);
    } catch (error) {
      next(error);
    }
  });

  app.post("/stt", async (req, res, next) => {
    try {
      const audioPath = req.body?.audioPath;
      if (!audioPath) {
        res.status(400).json({ ok: false, error: "audioPath is required" });
        return;
      }
      const transcript = await transcribeAudio(audioPath);
      latestTranscript = transcript;
      res.status(200).json({ ok: true, transcript });
    } catch (error) {
      next(error);
    }
  });

  app.post("/tts", async (req, res, next) => {
    try {
      const text = (req.body?.text || "").trim();
      if (!text) {
        res.status(400).json({ ok: false, error: "text is required" });
        return;
      }
      await speakText(text);
      res.status(200).json({ ok: true });
    } catch (error) {
      next(error);
    }
  });

  app.get("/queue", (req, res) => {
    res.status(200).json({
      ok: true,
      queueSize: inboundQueue.length,
      messages: inboundQueue,
    });
  });

  app.post("/queue/speak-next", async (req, res, next) => {
    try {
      const msg = inboundQueue.shift();
      if (!msg) {
        res.status(404).json({ ok: false, error: "queue empty" });
        return;
      }
      if (msg.text) {
        await speakText(msg.text);
      }
      res.status(200).json({ ok: true, message: msg });
    } catch (error) {
      next(error);
    }
  });

  app.post("/tts/start-loop", (req, res) => {
    const started = startTtsLoop();
    res.status(200).json({ ok: true, started, running: ttsLoopRunning });
  });

  app.post("/tts/stop-loop", (req, res) => {
    const stopped = stopTtsLoop();
    res.status(200).json({ ok: true, stopped, running: ttsLoopRunning });
  });

  app.get("/tts/loop-status", (req, res) => {
    res.status(200).json({
      ok: true,
      running: ttsLoopRunning,
      busy: ttsLoopBusy,
      isBusy,
      queueSize: inboundQueue.length,
    });
  });

  app.use((req, res) => {
    res.status(404).json({ ok: false, error: "not found" });
  });

  app.use((error, req, res, next) => {
    res.status(500).json({ ok: false, error: error?.message || String(error) });
  });

  app.listen(HTTP_PORT, () => {
    console.log(`[http] listening on :${HTTP_PORT}`);
    console.log("[http] endpoints: POST /record-once, POST /stt, POST /tts, GET /queue, GET /health, POST /tts/start-loop, POST /tts/stop-loop, GET /tts/loop-status");
  });
}

async function main() {
  await startup();
  await initCheckpointFromLatestMessage();
  startChatDbPoller();
  if (TALKBACK_ENABLED && TTS_LOOP_AUTOSTART) {
    startTtsLoop();
  }
  await sleep(50);
  startHttpServer();
}

main().catch((error) => {
  console.error("[voice] fatal error:", error?.message || error);
  process.exit(1);
});
