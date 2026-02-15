#!/usr/bin/env bash
# Cloudflare Tunnel setup for treehacks.tzhu.dev → localhost:8000
# Mac only. Run from repo root.

set -e

TUNNEL_NAME="treehacks"
DOMAIN="tzhu.dev"
SUBDOMAIN="treehacks"
LOCAL_PORT="${LOCAL_PORT:-8000}"
CONFIG_DIR="${HOME}/.cloudflared"
CONFIG_FILE="${CONFIG_DIR}/config.yml"

# Install cloudflared via Homebrew if missing (Mac)
if ! command -v cloudflared &>/dev/null; then
  if command -v brew &>/dev/null; then
    echo "Installing cloudflared via Homebrew..."
    brew install cloudflared
  else
    echo "cloudflared not found. Install with: brew install cloudflared"
    exit 1
  fi
fi

# Ensure config dir exists
mkdir -p "$CONFIG_DIR"

# Login only if no account cert (use your existing cert.pem if present)
if [[ ! -f "${CONFIG_DIR}/cert.pem" ]]; then
  echo "Ensuring Cloudflare login..."
  cloudflared tunnel login
else
  echo "Using existing cert at ${CONFIG_DIR}/cert.pem"
fi

# Get tunnel ID if it exists
TUNNEL_ID=$(cloudflared tunnel list 2>/dev/null | grep "$TUNNEL_NAME" | awk '{print $1}' | head -1)
CREDENTIALS_FILE="${CONFIG_DIR}/${TUNNEL_ID}.json"

# If tunnel exists but credentials JSON is missing, delete the orphan tunnel so we can create a new one
if [[ -n "$TUNNEL_ID" ]] && [[ ! -f "$CREDENTIALS_FILE" ]]; then
  echo "Tunnel $TUNNEL_NAME exists but credentials file is missing. Deleting orphan tunnel..."
  cloudflared tunnel delete "$TUNNEL_NAME" 2>/dev/null || true
  TUNNEL_ID=""
fi

# Create tunnel if it doesn't exist (or we just deleted an orphan)
if [[ -z "$TUNNEL_ID" ]]; then
  echo "Creating tunnel: $TUNNEL_NAME"
  cloudflared tunnel create "$TUNNEL_NAME"
  TUNNEL_ID=$(cloudflared tunnel list 2>/dev/null | grep "$TUNNEL_NAME" | awk '{print $1}' | head -1)
fi

if [[ -z "$TUNNEL_ID" ]]; then
  echo "Could not find tunnel ID for $TUNNEL_NAME. Run: cloudflared tunnel list"
  exit 1
fi

CREDENTIALS_FILE="${CONFIG_DIR}/${TUNNEL_ID}.json"
if [[ ! -f "$CREDENTIALS_FILE" ]]; then
  echo "Credentials file not found: $CREDENTIALS_FILE"
  exit 1
fi

# Write config
echo "Writing config to $CONFIG_FILE"
cat > "$CONFIG_FILE" << EOF
tunnel: $TUNNEL_ID
credentials-file: $CREDENTIALS_FILE

ingress:
  - hostname: ${SUBDOMAIN}.${DOMAIN}
    service: http://localhost:${LOCAL_PORT}
  - service: http_status:404
EOF

# Route DNS (create or update CNAME to this tunnel)
echo "Routing DNS: ${SUBDOMAIN}.${DOMAIN} -> tunnel"
if ! cloudflared tunnel route dns "$TUNNEL_NAME" "${SUBDOMAIN}.${DOMAIN}" 2>/dev/null; then
  echo "Note: DNS record already exists. Point ${SUBDOMAIN}.${DOMAIN} CNAME to: ${TUNNEL_ID}.cfargotunnel.com"
  echo "      Cloudflare Dashboard -> tzhu.dev -> DNS -> edit treehacks CNAME target to the above."
fi

echo ""
echo "Tunnel configured. Start your backend (e.g. docker compose up) on port $LOCAL_PORT, then run:"
echo "  cloudflared tunnel run $TUNNEL_NAME"
echo ""
echo "To run as a Mac background service: sudo cloudflared service install"
echo ""
echo "Run the tunnel now? (Ctrl+C to stop)"
read -r -p "Run tunnel now? [y/N] " response
if [[ "$response" =~ ^[yY] ]]; then
  cloudflared tunnel run "$TUNNEL_NAME"
fi
