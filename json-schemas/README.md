# JSON Schemas

Shared JSON schemas for communication between the **Vision Pro** app and the **server**.

Use these schemas to:
- Validate request/response payloads
- Generate type-safe models in Swift (Vision Pro) and Python (server)
- Keep both clients in sync

## Schemas

| File | Description |
|------|-------------|
| `fix-request.json` | Request body for `POST /fix` (fix instruction + optional repo URL) |
| `fix-response.json` | Response from fix endpoint |
| `agent-create-thinking.json` | Server → Vision Pro: Create agent in thinking state (agent_id 1-9, task_name) |
| `agent-start-working.json` | Server → Vision Pro: Agent starts working (agent_id 1-9) |
| `agent-start-testing.json` | Server → Vision Pro: Agent starts testing (agent_id, vercel_link, browserbase_link) |
| `jump-ping.json` | Server → Vision Pro: Signal to make the palm tree jump smoothly |
