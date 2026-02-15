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

# Login (opens browser)
echo "Ensuring Cloudflare login..."
cloudflared tunnel login

# Create tunnel if it doesn't exist
if ! cloudflared tunnel list 2>/dev/null | grep -q "$TUNNEL_NAME"; then
  echo "Creating tunnel: $TUNNEL_NAME"
  cloudflared tunnel create "$TUNNEL_NAME"
fi

# Get tunnel ID (first column of tunnel list output)
TUNNEL_ID=$(cloudflared tunnel list 2>/dev/null | grep "$TUNNEL_NAME" | awk '{print $1}' | head -1)
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

# Route DNS
echo "Routing DNS: ${SUBDOMAIN}.${DOMAIN} -> tunnel"
cloudflared tunnel route dns "$TUNNEL_NAME" "${SUBDOMAIN}.${DOMAIN}"

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
