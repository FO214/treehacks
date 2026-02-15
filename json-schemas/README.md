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
| `diagram-request.json` | Request for repo → diagram generation |
| `diagram-response.json` | Diagram PNG + component positions for spatial display in Vision Pro |
| `agents.json` | List of agents and their status (coding, creating_pr, testing, etc.) |
| `agent-create-thinking.json` | Server → Vision Pro: Create agent in thinking state (agent_id 1-9, task_name) |
| `agent-start-working.json` | Server → Vision Pro: Agent starts working (agent_id 1-9) |
| `agent-start-testing.json` | Server → Vision Pro: Agent starts testing (agent_id, vercel_link, browserbase_link) |
| `demo-value.json` | Demo: value 0 or 1 for Vision Pro block color (GET /demo/value) |
