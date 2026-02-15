# Connection Demo: Vision Pro ↔ FastAPI

Step-by-step to get the demo block (red/green) working in the Vision Pro app.

---

## Option A: ngrok (fastest)

### Step 1: Start the backend

```bash
cd /Users/theodore/treehacks
export MCP_HTTP_URL=http://mcp:8001/mcp
docker compose up --build
```

Wait until you see `Uvicorn running on http://0.0.0.0:8000`.

### Step 2: Start ngrok

In a **new terminal**:

```bash
ngrok http 8000
```

Copy the **HTTPS** URL (e.g. `https://abc123.ngrok-free.app`).

### Step 3: Update APIConfig in Xcode

1. Open `treehacks26/treehacks26/APIConfig.swift`
2. Set `baseURL` to your ngrok URL:

```swift
static let baseURL = "https://YOUR-NGROK-URL.ngrok-free.app"
```

3. Save and build (⌘B).

### Step 4: Run on Vision Pro

1. Build and run on your Vision Pro (or simulator).
2. Tap **Toggle Immersive Space** to enter the immersive view.
3. A block should appear ~1m in front of you.
4. Every 2 seconds it should alternate **red** (0) and **green** (1).

---

## Option B: Cloudflare Tunnel

### Step 1: Start the backend

```bash
cd /Users/theodore/treehacks
export MCP_HTTP_URL=http://mcp:8001/mcp
docker compose up --build
```

### Step 2: Start the Cloudflare tunnel

In a **new terminal**:

```bash
cd /Users/theodore/treehacks
cloudflared tunnel run treehacks
```

(If not set up yet, run `./setup-tunnel.sh` first.)

### Step 3: Verify APIConfig

`APIConfig.baseURL` should be:

```swift
static let baseURL = "https://treehacks.tzhu.dev"
```

### Step 4: Run on Vision Pro

Same as Option A, Step 4.

---

## Option C: Local only (no tunnel)

Use when Vision Pro and Mac are on the same network.

### Step 1: Start the backend (no Docker)

```bash
cd /Users/theodore/treehacks
source .venv/bin/activate  # or create venv first
pip install -r server/requirements.txt -r mcp_server/requirements.txt
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

(Or use `docker compose up` and use your Mac’s local IP.)

### Step 2: Get your Mac’s IP

```bash
ipconfig getifaddr en0
```

Example: `192.168.1.42`

### Step 3: Update APIConfig

```swift
static let baseURL = "http://192.168.1.42:8000"
```

Replace with your Mac’s IP.

### Step 4: Run on Vision Pro

Same as Option A, Step 4. Vision Pro must be on the same Wi‑Fi as your Mac.

---

## Troubleshooting

| Problem | Fix |
|--------|-----|
| Block stays red | Backend not reachable. Check URL, tunnel, and firewall. |
| 502 Bad Gateway | Backend not running. Start `docker compose up` or uvicorn. |
| Block never appears | Enter immersive space with the toggle button. |
| ngrok returns HTML | `ngrok-skip-browser-warning` header is already added. |
| Local IP doesn’t work | Ensure Vision Pro and Mac are on the same Wi‑Fi. |

### Test the API manually

```bash
curl https://YOUR-URL/demo/value
# Should return: {"value":0} or {"value":1}
```
