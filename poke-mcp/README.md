# TreeHacks Fix Agent - MCP Server

This is a FastMCP server that wraps the TreeHacks Fix Agent functionality, making it easy to trigger Modal + Claude Agent SDK operations via MCP protocol.

## 🚀 Quick Start

The server is already running on **http://0.0.0.0:8765/mcp**

## 🛠️ Available Tools

### Core Functionality
- **run_fix**: Execute fix instructions in a Modal sandbox
  - Args: `instruction` (required), `repo_url` (optional)
  - Example: `run_fix("Fix the bug in auth.py", "https://github.com/user/repo")`

- **run_fix_default_repo**: Quick fix on the default TreeHacks repository
  - Args: `instruction` (required)
  - Example: `run_fix_default_repo("Add tests for the login function")`

- **run_analysis**: Analyze code without making changes
  - Args: `instruction` (required), `repo_url` (optional)
  - Example: `run_analysis("List all API endpoints and their methods")`

### Testing & Debugging
- **run_test_fix**: Run a simple test to verify everything works
- **test_local_server**: Check if dependencies are installed correctly
- **check_modal_status**: Verify Modal CLI is configured

### Information
- **list_available_tools**: Show what tools the agent can use (Read, Write, Edit, Bash, Glob, Grep)
- **get_project_info**: Get detailed project documentation

## 📋 How It Works

1. **MCP Client** → Calls tool via HTTP/SSE
2. **FastMCP Server** (this) → Receives request
3. **Modal Sandbox** → Creates isolated environment
4. **Git Clone** → Downloads repository
5. **Claude Agent SDK** → Executes fix instruction
6. **Result** → Returns output to client

## 🔧 Requirements

- **Modal**: Authenticated with `modal token new`
- **Anthropic API Key**: Set as environment variable or Modal secret
- **Internet**: For cloning repositories

## 📦 Installation

Already installed! But if you need to reinstall:

```bash
cd /Users/iankorovinsky/Projects/treehacks/poke-mcp
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 🏃 Running

### Start the server:
```bash
cd /Users/iankorovinsky/Projects/treehacks/poke-mcp
./start.sh
```

Or manually:
```bash
cd /Users/iankorovinsky/Projects/treehacks/poke-mcp
source .venv/bin/activate
python server.py
```

### Stop the server:
```bash
pkill -f "poke-mcp/server.py"
```

### Check if running:
```bash
ps aux | grep "poke-mcp/server.py" | grep -v grep
```

## 🧪 Testing

### Test the endpoint:
```bash
curl -H "Accept: text/event-stream" http://0.0.0.0:8765/mcp
```

### Use the test tool:
Connect an MCP client and call `run_test_fix()` to verify the complete workflow.

## 📁 Project Structure

```
poke-mcp/
├── server.py          # FastMCP server implementation
├── requirements.txt   # Python dependencies
├── .venv/            # Virtual environment
└── README.md         # This file
```

## 🔗 Related Files

This server is self-contained and uses Modal + Claude Agent SDK directly:
- `server.py` - FastMCP server with Modal sandbox integration
- `.env` - Environment variables (API keys)
- `requirements.txt` - Python dependencies

## 💡 Example Usage

```python
# Using an MCP client:

# Fix a bug in a specific file
run_fix(
    instruction="Fix the authentication bug in src/auth.py",
    repo_url="https://github.com/yourorg/yourrepo"
)

# Analyze code structure
run_analysis(
    instruction="List all Python files and describe what each does"
)

# Quick test on default repo
run_fix_default_repo("Add error handling to the main function")
```

## 🐛 Troubleshooting

### Server won't start
- Check if port 8765 is already in use: `lsof -i :8765`
- Verify dependencies: Call `test_local_server()` tool

### Fix fails
- Verify Modal is configured: Call `check_modal_status()` tool
- Check ANTHROPIC_API_KEY is set in environment or Modal secrets
- Review Modal sandbox logs in the tool output

### Import errors
- Make sure the parent directory is in Python path (server.py handles this)
- Verify all dependencies in parent project are installed

## 📚 Documentation

For more information about the underlying components:
- [FastMCP](https://github.com/jlowin/fastmcp) - MCP server framework
- [Modal](https://modal.com) - Serverless container platform
- [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk) - AI agent framework

---

**Server Status**: 🟢 Running on http://0.0.0.0:8765/mcp
**Process ID**: Check with `ps aux | grep server.py`
