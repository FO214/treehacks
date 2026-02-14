"""
FastAPI server: accepts text_input (fix instruction), calls MCP server tool run_fix.
"""
import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from mcp import ClientSession
from mcp.client.http import http_client
from pydantic import BaseModel


class FixRequest(BaseModel):
    text_input: str
    repo_url: str | None = None  # optional; MCP server has default sample repo


class FixResponse(BaseModel):
    success: bool
    result: str
    error: str | None = None


@asynccontextmanager
async def get_mcp_session():
    """Connect to MCP server over HTTP and yield session."""
    mcp_url = os.environ.get("MCP_HTTP_URL", "http://127.0.0.1:8001/mcp")
    async with http_client(mcp_url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


async def call_run_fix(text_input: str, repo_url: str | None) -> str:
    """Call MCP tool run_fix and return result text."""
    args: dict[str, Any] = {"instruction": text_input}
    if repo_url:
        args["repo_url"] = repo_url
    async with get_mcp_session() as session:
        result = await session.call_tool("run_fix", arguments=args)
    if result.isError:
        first = result.content[0] if result.content else None
        msg = getattr(first, "text", None) or (first.get("text") if isinstance(first, dict) else None) if first else "Unknown MCP error"
        raise RuntimeError(msg)
    # Result is list of ContentBlock (object or dict)
    out_parts = []
    for block in result.content:
        text = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
        if text:
            out_parts.append(text)
    return "\n".join(out_parts) if out_parts else ""


app = FastAPI(title="Fix API", description="Accepts fix instruction, calls MCP server (Modal + Claude Agent SDK).")


@app.post("/fix", response_class=PlainTextResponse)
async def fix(request: FixRequest) -> str:
    """Run the fix instruction via MCP server (Modal sandbox + Claude Agent SDK)."""
    try:
        result = await call_run_fix(request.text_input, request.repo_url)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
