#!/bin/bash
# Start the TreeHacks Fix Agent MCP Server

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

# Check if virtual environment exists
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Creating virtual environment with uv..."
    if command -v uv &> /dev/null; then
        uv venv .venv
        uv pip install -r requirements.txt -p "$VENV_PYTHON"
    else
        echo "Error: uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
fi

# Check if Modal is installed
if ! "$VENV_PYTHON" -c "import modal" 2>/dev/null; then
    echo "Installing Modal..."
    if command -v uv &> /dev/null; then
        uv pip install modal -p "$VENV_PYTHON"
    else
        echo "Error: uv not found"
        exit 1
    fi
fi

# Check for required environment variables
if [ ! -f ".env" ]; then
    echo "Warning: .env file not found. Make sure ANTHROPIC_API_KEY is set."
fi

echo "Starting MCP server on http://0.0.0.0:8765"
echo "Press Ctrl+C to stop"
echo ""

"$VENV_PYTHON" server.py
