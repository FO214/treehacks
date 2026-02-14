"""
MCP server (HTTP): exposes /mcp for Streamable HTTP transport.
Calls Modal sandbox + Claude Agent SDK to clone repo and apply fix.
Run from repo root: python -m mcp_server.main
"""
import os

from mcp_server.app import mcp

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8001"))
    mcp.run(transport="http", host=host, port=port, stateless_http=True)
