#!/usr/bin/env python3
"""Simple MCP client to test the server."""
import asyncio
import sys
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

SERVER_URL = "http://127.0.0.1:8765/mcp"


async def list_tools():
    """List all available tools."""
    async with streamablehttp_client(SERVER_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Available tools:")
            for tool in tools.tools:
                print(f"  - {tool.name}: {tool.description[:60]}...")


async def call_tool(tool_name: str, args: dict = None):
    """Call a specific tool."""
    async with streamablehttp_client(SERVER_URL) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print(f"Calling {tool_name}...")
            result = await session.call_tool(tool_name, args or {})
            for block in result.content:
                print(getattr(block, "text", block))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python test_client.py list                    # List all tools")
        print("  python test_client.py call <tool_name>        # Call a tool")
        print("  python test_client.py call run_fix --instruction 'Fix the bug'")
        print()
        print("Examples:")
        print("  python test_client.py call check_modal_status")
        print("  python test_client.py call test_local_server")
        print("  python test_client.py call get_project_info")
        sys.exit(1)

    command = sys.argv[1]

    if command == "list":
        asyncio.run(list_tools())
    elif command == "call":
        if len(sys.argv) < 3:
            print("Error: tool name required")
            sys.exit(1)
        tool_name = sys.argv[2]

        # Parse simple --key value args
        args = {}
        i = 3
        while i < len(sys.argv):
            if sys.argv[i].startswith("--"):
                key = sys.argv[i][2:]
                if i + 1 < len(sys.argv):
                    args[key] = sys.argv[i + 1]
                    i += 2
                else:
                    i += 1
            else:
                i += 1

        asyncio.run(call_tool(tool_name, args))
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
