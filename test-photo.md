# TreeHacks System Design

High-level architecture of the voice + fix-agent stack.

## Component overview

```mermaid
flowchart TB
    subgraph client [Client]
        VP[Vision Pro App]
    end

    subgraph server [FastAPI Server :8000]
        API[REST API]
        WSPoke["/ws/poke"]
        WSSpawn["/ws/spawn"]
        EventBus[event_bus]
        InternalEvent["POST /internal/event"]
        Voice[voice module]
    end

    subgraph mcp [MCP Server poke-mcp]
        FastMCP[FastMCP tools]
        RunFix[run_fix / run_fix_default_repo]
    end

    subgraph external [External Services]
        Modal[Modal]
        GitHub[GitHub]
        Poke[Poke API]
        ChatDB["chat.db"]
        OpenAI[OpenAI / Groq]
        Vercel[Vercel]
        Browserbase[Browserbase]
    end

    VP -->|"hand_open / hand_close"| WSPoke
    VP -->|"connect, receive events"| WSSpawn
    VP -.->|"optional POST /record-once"| API

    WSPoke --> Voice
    Voice -->|"transcript"| Poke
    Poke --> ChatDB
    Voice -->|"poll"| ChatDB
    Voice -->|"STT / TTS"| OpenAI

    API -->|"call_tool run_fix"| FastMCP
    RunFix --> Modal
    RunFix --> GitHub
    RunFix -->|"optional"| Vercel
    RunFix -->|"optional"| Browserbase

    RunFix -->|"POST events"| InternalEvent
    InternalEvent --> EventBus
    WSPoke --> EventBus
    WSSpawn --> EventBus
    EventBus -->|"broadcast"| VP
```

## Data flows

### 1. Voice (Vision Pro → server → Poke → talkback)

```mermaid
sequenceDiagram
    participant VP as Vision Pro
    participant WS as /ws/poke
    participant Voice as voice
    participant Poke as Poke API
    participant DB as chat.db
    participant TTS as TTS

    VP->>WS: hand_open
    WS->>Voice: start_recording()
    WS->>VP: broadcast listening

    VP->>WS: hand_close
    WS->>Voice: stop_and_process()
    Voice->>Voice: STT (OpenAI/Groq)
    Voice->>Poke: POST transcript
    Poke->>DB: (Poke writes reply)
    Voice->>DB: poll for inbound
    Voice->>TTS: speak inbound text
    WS->>VP: broadcast poke_speaking_start/stop
```

### 2. Fix agent (client → server → MCP → Modal → GitHub → Vision Pro)

```mermaid
sequenceDiagram
    participant Client as MCP Client
    participant Server as FastAPI
    participant MCP as poke-mcp
    participant Modal as Modal Sandbox
    participant GitHub as GitHub
    participant Webhook as /internal/event
    participant VP as Vision Pro

    Client->>Server: POST /fix (or direct MCP)
    Server->>MCP: call_tool run_fix
    MCP->>MCP: run_modal_agent (async/thread)

    MCP->>Modal: Sandbox.create
    MCP->>Modal: clone, branch, exec claude-agent-sdk
    MCP->>Webhook: POST create_agent_thinking
    MCP->>Webhook: POST agent_start_working
    Webhook->>VP: broadcast (via event_bus)

    Modal-->>MCP: agent done
    MCP->>GitHub: push, create PR
    opt smoke_test
        MCP->>Vercel: wait preview
        MCP->>Browserbase: run smoke test
    end
    MCP->>Webhook: POST agent_start_testing (vercel_link, browserbase_link)
    Webhook->>VP: broadcast
    VP->>VP: show webview (Browserbase/Vercel URL)

    MCP-->>Server: result
    Server-->>Client: PR URL + output
```

### 3. Event bus

- **Registered connections:** WebSockets that called `event_bus.register(ws)` — currently `/ws/poke` and `/ws/spawn`.
- **Producers:** `POST /internal/event` (from poke-mcp), and voice (e.g. `listening`, `poke_speaking_start`).
- **Consumers:** Vision Pro (and any other WS client). All registered clients receive every broadcast.

## Main directories

| Path | Role |
|------|------|
| `server/` | FastAPI app: /fix, /ws/poke, /ws/spawn, /internal/event, voice endpoints. event_bus, voice logic. |
| `poke-mcp/` | MCP server (FastMCP): run_fix, run_fix_default_repo, run_analysis, list_tools. Calls Modal, GitHub, posts to EVENT_WEBHOOK_URL. |
| `treehacks26/` | Vision Pro (Swift): connects to server baseURL, /ws/poke + /ws/spawn, renders agents + webviews. |
| `sound-effects/` | Audio files for recording start/stop and no-recording. |

## Key env (concise)

- **Server:** `MCP_HTTP_URL` (poke-mcp URL), voice: `OPENAI_API_KEY`, `POKE_API_KEY`, `POKE_HANDLE_ID`, `CHAT_DB_PATH`, `RECORD_MAX_SECONDS`, etc.
- **poke-mcp:** `ANTHROPIC_API_KEY`, `MODAL_*`, `GITHUB_TOKEN`, `EVENT_WEBHOOK_URL`, `RUN_FIX_IN_BACKGROUND`, `RUN_FIX_SMOKE_TEST`, `RUN_FIX_MAX_CONCURRENT`.
- **Vision Pro:** `APIConfig.baseURL` (e.g. tunnel to server).

## Run order (typical)

1. Start FastAPI: `./start.sh` (port 8000).
2. Start poke-mcp (e.g. `cd poke-mcp && ./start.sh`); set `EVENT_WEBHOOK_URL` to `http://localhost:8000/internal/event` if local.
3. Optional: Cloudflare (or other) tunnel to 8000; Vision Pro uses that as baseURL.
4. Vision Pro: connect to `baseURL/ws/poke` and `baseURL/ws/spawn` to use voice and agent UI.
