"""
Shared MCP app definition.
"""
import asyncio
import os
import sys

from mcp.server.fastmcp import FastMCP

from mcp_server.agent_runner import run_fix_sync

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

mcp = FastMCP(
    "treehacks-fix-agent",
    description="Run a fix instruction in a Modal sandbox with Claude Agent SDK (clone repo, then apply fix).",
)


@mcp.tool()
async def run_fix(instruction: str, repo_url: str = "https://github.com/modal-labs/modal-examples") -> str:
    """Scaffold a Modal sandbox with Claude Agent SDK, clone the given repo, and run the fix instruction.
    instruction: What to do (e.g. 'Fix the bug in auth.py' or 'Add a test for login').
    repo_url: Git URL to clone (default: modal-examples). Use your own sample repo when ready.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, run_fix_sync, instruction, repo_url)
