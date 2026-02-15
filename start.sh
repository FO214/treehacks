#!/usr/bin/env bash
# Start FastAPI server (fix + voice) on port 8000.
# Cloudflare tunnel → 8000

set -e
cd "$(dirname "$0")"

# Load .env
set -a
[ -f .env ] && source .env
set +a

# Use venv if it exists
if [ -f .venv/bin/activate ]; then
  source .venv/bin/activate
fi

echo "[start] Starting FastAPI (fix + voice) on :8000..."
# Unbuffered output so print() from server shows immediately
export PYTHONUNBUFFERED=1
exec uvicorn server.main:app --host 0.0.0.0 --port 8000
