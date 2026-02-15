#!/usr/bin/env bash
# Start FastAPI server (fix + voice) on port 8000.
# Cloudflare tunnel → 8000

set -e
cd "$(dirname "$0")"

# Load .env
set -a
[ -f .env ] && source .env
set +a

# Need Python >=3.10 for mcp and other deps (try PATH then Homebrew)
PYTHON_CMD=""
for p in python3.12 python3.11 python3.10 \
  /opt/homebrew/opt/python@3.12/bin/python3.12 \
  /opt/homebrew/opt/python@3.11/bin/python3.11 \
  /usr/local/opt/python@3.12/bin/python3.12 \
  /usr/local/opt/python@3.11/bin/python3.11; do
  if [ -x "$p" ] 2>/dev/null && "$p" -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
    PYTHON_CMD="$p"
    break
  fi
done
if [ -z "$PYTHON_CMD" ]; then
  if command -v python3 &>/dev/null && python3 -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
    PYTHON_CMD="python3"
  fi
fi
if [ -z "$PYTHON_CMD" ]; then
  echo "[start] ERROR: Python 3.10+ required for mcp. Install with: brew install python@3.12"
  echo "         Then run ./start.sh again."
  exit 1
fi

# Recreate venv if missing or broken (encodings error)
VENV_PYTHON=".venv/bin/python"
if [ ! -f "$VENV_PYTHON" ] || ! "$VENV_PYTHON" -c "import encodings" 2>/dev/null; then
  echo "[start] Creating or fixing virtual environment (using $PYTHON_CMD)..."
  rm -rf .venv
  "$PYTHON_CMD" -m venv .venv
  "$VENV_PYTHON" -m pip install --upgrade pip -q
  "$VENV_PYTHON" -m pip install -r server/requirements.txt -q
fi
if ! "$VENV_PYTHON" -c "import uvicorn" 2>/dev/null; then
  "$VENV_PYTHON" -m pip install --upgrade pip -q
  "$VENV_PYTHON" -m pip install -r server/requirements.txt -q
fi
source .venv/bin/activate

echo "[start] Starting FastAPI (fix + voice) on :8000..."
exec "$VENV_PYTHON" -m uvicorn server.main:app --host 0.0.0.0 --port 8000
