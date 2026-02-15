"""
MCP server (HTTP): exposes /mcp for Streamable HTTP transport.
Calls Modal sandbox + Claude Agent SDK to clone repo and apply fix.
Run from repo root: python -m mcp_server.main
"""
import os

from mcp_server.app import mcp

if __name__ == "__main__":
    mcp.settings.host = os.environ.get("HOST", "0.0.0.0")
    mcp.settings.port = int(os.environ.get("PORT", "8001"))
    mcp.settings.stateless_http = True
    mcp.run(transport="streamable-http")
