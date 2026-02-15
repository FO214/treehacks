# Cloudflare Tunnel Setup: treehacks.tzhu.dev

---

## Quick Path (tzhu.dev down temporarily)

1. **Cloudflare**: Add site `tzhu.dev` → Free plan → get nameservers
2. **Porkbun**: Switch tzhu.dev nameservers to Cloudflare's
3. **Run**: `./setup-tunnel.sh`
4. **Start backend**: `docker compose up`
5. **Test**: `https://treehacks.tzhu.dev`

Add your personal site DNS records in Cloudflare whenever you're ready.

---

## Full Path (keep personal site working)

### Part 1: Save Your Current DNS (Porkbun)

**Before changing anything**, record your existing DNS so your personal site keeps working.

1. Go to [porkbun.com](https://porkbun.com) and log in
2. **Domain Management** → click **tzhu.dev**
3. Open **DNS** or **DNS Records**
4. **Screenshot or copy every record** into a text file. You need:
   - Type (A, CNAME, MX, TXT, etc.)
   - Name (e.g. `@`, `www`, `mail`)
   - Value/Content
   - TTL (optional, Cloudflare will use its own)

---

## Part 2: Add Domain to Cloudflare

1. Go to [dash.cloudflare.com](https://dash.cloudflare.com)
2. Click **Add a site**
3. Enter `tzhu.dev` → **Add site**
4. Select **Free** plan → **Continue**
5. Cloudflare may show a scan of your current DNS. **Review it** – it might have imported some records
6. You’ll see two nameservers, e.g.:
   ```
   ada.ns.cloudflare.com
   bob.ns.cloudflare.com
   ```
   **Copy these** – you’ll need them for Porkbun

---

## Part 3: Add DNS Records in Cloudflare

1. In Cloudflare, go to **tzhu.dev** → **DNS** → **Records**
2. **Add every record** from your Porkbun list (Part 1)
3. For your personal website root (`tzhu.dev`):
   - If on **Vercel**: Add CNAME `@` → `cname.vercel-dns.com` (or your Vercel domain)
   - If on **Netlify**: Add CNAME `@` → `apex-loadbalancer.netlify.com`, CNAME `www` → `yoursite.netlify.com`
   - If on **custom server**: Add A record `@` → your server IP
   - If on **GitHub Pages**: Add the A records GitHub provides, CNAME `www` → `username.github.io`
4. Leave **Proxy status** as **Proxied** (orange cloud) unless you have a reason to use DNS only
5. **Do not add** `treehacks` yet – the tunnel script will create it

---

## Part 4: Switch Nameservers at Porkbun

1. Go back to [porkbun.com](https://porkbun.com) → **Domain Management** → **tzhu.dev**
2. Find **Nameservers** (or **DNS** → **Nameservers**)
3. Select **Custom nameservers** (or **Use custom nameservers**)
4. Delete the existing nameservers
5. Add Cloudflare’s two nameservers (from Part 2)
6. Save

**DNS can take 15 minutes to 48 hours to propagate.** Often 1–2 hours.

---

## Part 5: Verify Your Personal Site

1. Wait 15–30 minutes (or check propagation: `dig NS tzhu.dev`)
2. Visit `https://tzhu.dev` – your personal site should load
3. If it doesn’t, check Cloudflare DNS records match what you had in Porkbun

---

## Part 6: Run the Tunnel Script

1. Open Terminal
2. Go to the repo:
   ```bash
   cd /Users/theodore/treehacks
   ```
3. Run the script:
   ```bash
   ./setup-tunnel.sh
   ```
4. When prompted, **log in to Cloudflare** in the browser that opens
5. Select **tzhu.dev** when asked which domain to use
6. The script will:
   - Create the `treehacks` tunnel (if it doesn’t exist)
   - Write config for `treehacks.tzhu.dev` → `localhost:8000`
   - Add the DNS record for `treehacks.tzhu.dev`
7. When asked **Run tunnel now?**, type `y` and press Enter (or `n` to run later)

---

## Part 7: Start Your Backend

In a **separate terminal**:

```bash
cd /Users/theodore/treehacks
export MCP_HTTP_URL=http://mcp:8001/mcp
docker compose up --build
```

Your FastAPI server runs on port 8000.

---

## Part 8: Test the Tunnel

1. With both the tunnel and `docker compose` running:
2. Visit `https://treehacks.tzhu.dev`
3. You should see your FastAPI app (or its root response)

To test the fix endpoint:

```bash
curl -X POST https://treehacks.tzhu.dev/fix \
  -H "Content-Type: application/json" \
  -d '{"text_input": "List Python files in the repo"}'
```

---

## Quick Reference: Running Later

**Start backend:**
```bash
cd /Users/theodore/treehacks
export MCP_HTTP_URL=http://mcp:8001/mcp
docker compose up
```

**Start tunnel** (in another terminal):
```bash
cloudflared tunnel run treehacks
```

**Run tunnel as background service** (Mac):
```bash
sudo cloudflared service install
sudo launchctl start com.cloudflare.cloudflared
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `tzhu.dev` (personal site) broken | Re-add DNS records in Cloudflare to match Porkbun |
| `treehacks.tzhu.dev` not loading | Ensure tunnel is running and backend is on port 8000 |
| 502 Bad Gateway | Backend not running – start `docker compose up` |
| DNS not resolving | Wait for propagation; check `dig treehacks.tzhu.dev` |
