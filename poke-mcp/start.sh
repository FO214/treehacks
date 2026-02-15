#!/bin/bash
# Start the TreeHacks Fix Agent MCP Server

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

# Recreate venv if missing or broken (encodings error common with moved Python / 3.14)
if [ ! -f "$VENV_PYTHON" ] || ! "$VENV_PYTHON" -c "import encodings" 2>/dev/null; then
    echo "Creating or fixing virtual environment..."
    rm -rf .venv
    python3 -m venv .venv
    "$VENV_PYTHON" -m pip install -r requirements.txt -q
fi

# Check if Modal is installed
if ! "$VENV_PYTHON" -c "import modal" 2>/dev/null; then
    echo "Installing Modal..."
    "$VENV_PYTHON" -m pip install modal -q
fi

# Check for required environment variables
if [ ! -f ".env" ]; then
    echo "Warning: .env file not found. Make sure ANTHROPIC_API_KEY is set."
fi

echo "Starting MCP server on http://0.0.0.0:8765"
echo "Press Ctrl+C to stop"
echo ""

"$VENV_PYTHON" server.py
