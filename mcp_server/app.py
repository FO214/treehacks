"""
Shared MCP app definition.
"""
import asyncio
import os
import sys

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from mcp_server.agent_runner import DEFAULT_REPO_URL, run_fix_sync

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

mcp = FastMCP(
    "treehacks-fix-agent",
    instructions="Run a fix instruction in a Modal sandbox with Claude Agent SDK, then open a GitHub PR with the changes.",
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool()
async def run_fix(instruction: str, repo_url: str = DEFAULT_REPO_URL) -> str:
    """Clone a GitHub repo into a Modal sandbox, run an AI agent to apply the requested fix,
    then push a branch and open a pull request with the changes.

    instruction: What to do (e.g. 'Fix the bug in auth.py' or 'Add a test for login').
    repo_url: GitHub HTTPS URL to clone. Defaults to the sample repo.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, run_fix_sync, instruction, repo_url)
