# Treehacks

FastAPI server that takes a **text-input** (fix instruction), calls an **MCP server**, which scaffolds a **Modal sandbox** with the **Claude Agent SDK**, clones a sample repo, and runs the agent to implement the fix.

## Architecture

- **FastAPI** (`server/`): `POST /fix` with `{"text_input": "Fix the bug in auth.py", "repo_url": "https://..."}`. Calls the MCP server over stdio.
- **MCP server** (`mcp_server/`): Exposes tool `run_fix(instruction, repo_url)`. When invoked, creates a Modal sandbox, clones the repo, runs Claude Agent SDK with the instruction (Read/Edit/Bash/Glob/Grep), returns output.
- **Sample repo**: Default is `https://github.com/modal-labs/modal-examples`. You can add your own and pass `repo_url` in the request.

## Setup

1. **From repo root**, create a venv and install deps for both server and MCP:

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # or .venv\Scripts\activate on Windows
   pip install -r server/requirements.txt
   pip install -r mcp_server/requirements.txt
   ```

2. **Modal**: `pip install modal` and `modal token new` (or set `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`).

3. **Anthropic**: Create a Modal secret for the sandbox so the agent can call Claude:
   ```bash
   modal secret create anthropic-secret ANTHROPIC_API_KEY=sk-ant-...
   ```
   Or set `ANTHROPIC_API_KEY` in your env; the runner will pass it into the sandbox when no Modal secret exists.

4. **Run FastAPI** (from repo root so `python -m mcp_server.main` works):

   ```bash
   uvicorn server.main:app --reload
   ```

5. **Call the API**:

   ```bash
   curl -X POST http://127.0.0.1:8000/fix \
     -H "Content-Type: application/json" \
     -d '{"text_input": "List all Python files in this repo"}'
   ```

   With your own repo:

   ```bash
   curl -X POST http://127.0.0.1:8000/fix \
     -H "Content-Type: application/json" \
     -d '{"text_input": "Fix the login bug in auth.py", "repo_url": "https://github.com/you/your-sample-repo"}'
   ```

## Docker (server + MCP server)

This project can run the FastAPI server and the MCP server as separate services. The MCP server is exposed over Streamable HTTP at `/mcp` on port 8001.

1. Create an env file with your secrets (or export these in your shell):

   ```bash
   cat > .env <<'EOF'
   ANTHROPIC_API_KEY=sk-ant-...
   MODAL_TOKEN_ID=...
   MODAL_TOKEN_SECRET=...
   EOF
   ```

2. Build and run with Docker Compose (starts both `api` and `mcp`):

   ```bash
   docker compose up --build
   ```

3. Call the API (same as above):

   ```bash
   curl -X POST http://127.0.0.1:8000/fix \
     -H "Content-Type: application/json" \
     -d '{"text_input": "List all Python files in this repo"}'
   ```

Notes:
- The containers need outbound network access for `git clone` and the Modal sandbox.
- The MCP HTTP endpoint is `http://127.0.0.1:8001/mcp`.
- The FastAPI server uses `MCP_HTTP_URL` (default: `http://127.0.0.1:8001/mcp`) to reach the MCP server.

## Optional: your sample repo

Create a small repo with a deliberate bug (e.g. a broken test or a bug in one file). Push it to GitHub and pass its URL as `repo_url`. The agent will clone it in the sandbox and apply the fix from `text_input`.

## Poke MCP Integration

To integrate this MCP server with Poke (Streamable HTTP):

1. Go to `https://poke.com/settings/connections/integrations/new`.
2. Use the verified MCP server template for 1-click deploy: `https://github.com/InteractionCo/mcp-server-template`.
3. Configure your MCP connection in Poke after deployment.

If you want to run this repo directly instead of the template, point Poke to:
`http://<your-host>:8001/mcp` (this is served by `python -m mcp_server.http_server`).

To send messages to Poke programmatically:

Bash
```bash
API_KEY="your-api-key-here"
MESSAGE="Hello from HackMIT!"

response=$(curl 'https://poke.com/api/v1/inbound-sms/webhook' \
        -H "Authorization: Bearer $API_KEY" \
        -H "Content-Type: application/json" \
        -X POST \
        -d "{\"message\": \"$MESSAGE\"}")

echo $response
```

TypeScript
```ts
const API_KEY = 'your-api-key-here';
const MESSAGE = 'Hello from HackMIT!';

const response = await fetch('https://poke.com/api/v1/inbound-sms/webhook', {
    method: 'POST',
    headers: {
        'Authorization': `Bearer ${API_KEY}`,
        'Content-Type': 'application/json'
    },
    body: JSON.stringify({ message: MESSAGE })
});

const data = await response.json();
console.log(data);
```

Python
```py
import requests

API_KEY = 'your-api-key-here'
MESSAGE = 'Hello from HackMIT!'

response = requests.post(
    'https://poke.com/api/v1/inbound-sms/webhook',
    headers={
        'Authorization': f'Bearer {API_KEY}',
        'Content-Type': 'application/json'
    },
    json={'message': MESSAGE}
)

print(response.json())
```

### Voice service (chat.db poller + STT/TTS endpoints)

This repo includes a local voice service at `voice-server.mjs` that does:

1. Initialize a new `Poke` client on startup.
2. Read latest `message.date`/`ROWID` for `POKE_HANDLE_ID` as the startup checkpoint.
3. Poll `chat.db` every few seconds for new inbound messages from that handle.
4. Queue inbound messages in memory.
5. Expose endpoints to run one recording turn, STT, and TTS.

Run it from repo root:

```bash
npm install
npm run voice
```

For auto-restart on `.env` or `voice-server.mjs` changes during development:

```bash
npm run voice:dev
```

Required env vars:
- `POKE_API_KEY`
- `OPENAI_API_KEY`
- `POKE_HANDLE_ID` (Messages `handle_id` for Poke contact)

Optional env vars:
- `POKE_SESSION_BOOT_MESSAGE` (sent once to Poke on startup)
- `STT_MODEL` (default `gpt-4o-mini-transcribe`)
- `TTS_MODEL` (default `gpt-4o-mini-tts`)
- `TTS_VOICE` (default `alloy`)
- `TTS_SPEED` (default `1.0`)
- `TTS_RESPONSE_FORMAT` (`wav` or `pcm`; default auto: `pcm` with `ffplay`, else `wav`)
- `TTS_BATCH_QUEUE` (default `true`; when true, queued inbound messages are concatenated and spoken together)
- `TTS_BATCH_SEPARATOR` (default `" "`; separator used between concatenated queued messages)
- `SOUND_EFFECTS_ENABLED` (default `true`)
- `SOUND_EFFECTS_DIR` (default `./sound-effects`)
- `START_RECORDING_SOUND` (default `start-recording.mp3`)
- `STOP_RECORDING_SOUND` (default `stop-recording.mp3`)
- `NO_RECORDING_SOUND` (default `no-recording.mp3`)
- `MIN_AUDIO_BYTES` (default `8000`)
- `CHAT_DB_PATH` (default `~/Library/Messages/chat.db`)
- `CHAT_POLL_MS` (default `1000`)
- `RESPONSE_TIMEOUT_MS` (default `120000`)
- `VOICE_HTTP_PORT` (default `8787`)

Endpoints:
- `POST /record-once` (record -> STT -> send to Poke -> await next inbound chat.db message -> optional TTS talkback)
- `POST /stt` with `{ "audioPath": "/abs/path/to/file.wav" }`
- `POST /tts` with `{ "text": "hello" }`
- `GET /queue` and `POST /queue/speak-next`
- `GET /health`

Local system tools needed for audio I/O:
- `rec` (SoX) for recording with silence detection
- `afplay` (macOS) or `ffplay` for playback

## Project layout

```
treehacks/
├── server/           # FastAPI app
│   ├── main.py       # POST /fix → MCP client → run_fix
│   └── requirements.txt
├── mcp_server/       # MCP server (stdio)
│   ├── main.py       # FastMCP, run_fix tool
│   ├── agent_runner.py  # Modal sandbox + Claude Agent SDK
│   └── requirements.txt
└── README.md
```
