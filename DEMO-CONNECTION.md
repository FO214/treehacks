# Connection Demo: Vision Pro ↔ FastAPI

Step-by-step to get the demo block (red/green) working in the Vision Pro app.

---

## Option A: Cloudflare Tunnel (recommended)

### Step 1: Install deps

```bash
cd /Users/theodore/treehacks
python3 -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
npm install
```

### Step 2: Start the consolidated server (voice + demo + /fix on port 8000)

```bash
./start.sh
```

This starts the voice server on port 8000 (demo block, gesture-to-sound, /fix proxy). FastAPI runs on 8002 in the background for /fix.

### Step 3: Start the Cloudflare tunnel

In a **new terminal**:

```bash
cd /Users/theodore/treehacks
cloudflared tunnel run treehacks
```

(If not set up yet, run `./setup-tunnel.sh` first.)

### Step 4: Run on Vision Pro

1. Build and run on your Vision Pro (or simulator).
2. Tap **Toggle Immersive Space** to enter the immersive view.
3. A block should appear ~1m in front of you.
4. Every 2 seconds it should alternate **red** (0) and **green** (1).

`APIConfig.baseURL` is already set to `https://treehacks.tzhu.dev`.

---

## Option B: Docker + Cloudflare

### Step 1: Start the backend (requires Docker)

```bash
cd /Users/theodore/treehacks
export MCP_HTTP_URL=http://mcp:8001/mcp
docker compose up --build
```

### Step 2: Start the Cloudflare tunnel

In a **new terminal**:

```bash
cloudflared tunnel run treehacks
```

### Step 3: Run on Vision Pro

Same as Option A, Step 4.

---

## Option C: Local only (no tunnel)

Use when Vision Pro and Mac are on the same Wi‑Fi.

### Step 1: Start the backend (Python venv)

```bash
cd /Users/theodore/treehacks
source .venv/bin/activate
uvicorn server.main:app --host 0.0.0.0 --port 8000
```

### Step 2: Get your Mac's IP

```bash
ipconfig getifaddr en0
```

Example: `192.168.1.42`

### Step 3: Update APIConfig

```swift
static let baseURL = "http://192.168.1.42:8000"
```

Replace with your Mac's IP.

### Step 4: Run on Vision Pro

Same as Option A, Step 4. Vision Pro must be on the same Wi‑Fi as your Mac.

---

## Troubleshooting

| Problem | Fix |
|--------|-----|
| Block stays red | Backend not reachable. Check URL, tunnel, and firewall. |
| 502 Bad Gateway | Backend not running. Start `uvicorn server.main:app` or `docker compose up`. |
| Block never appears | Enter immersive space with the toggle button. |
| Local IP doesn't work | Ensure Vision Pro and Mac are on the same Wi‑Fi. |

### Test the API manually

```bash
curl https://treehacks.tzhu.dev/demo/value
# Should return: {"value":0} or {"value":1}
```
