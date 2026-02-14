"""
Modal sandbox + Claude Agent SDK: clone repo, run agent with fix instruction.
Run from MCP server (sync); call via asyncio.to_thread from async tool.
"""
import os

import modal

# Default sample repo (user can override via tool arg)
DEFAULT_REPO_URL = "https://github.com/iankorovinsky/treehacks-agent-repo"

# Image: Python, git, Claude Agent SDK
IMAGE = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")
    .pip_install("claude-agent-sdk")
)

# Inline agent script run inside sandbox (workdir=/repo, AGENT_PROMPT in env)
AGENT_SCRIPT = """
import asyncio
import os
from claude_agent_sdk import query, ClaudeAgentOptions

async def main():
    prompt = os.environ.get("AGENT_PROMPT", "List files in this repo.")
    opts = ClaudeAgentOptions(
        allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        permission_mode="bypassPermissions",
    )
    out = []
    async for message in query(prompt=prompt, options=opts):
        if hasattr(message, "result") and message.result:
            out.append(str(message.result))
    print("\\n--- AGENT RESULT ---\\n")
    print("\\n".join(out) if out else "No result output.")

asyncio.run(main())
"""


def run_fix_sync(instruction: str, repo_url: str = DEFAULT_REPO_URL) -> str:
    """Create Modal sandbox, clone repo, run Claude Agent SDK with instruction. Returns combined stdout."""
    app = modal.App.lookup("treehacks-fix-agent", create_if_missing=True)

    with modal.enable_output():
        sb = modal.Sandbox.create(app=app, image=IMAGE, timeout=10 * 60)

    try:
        # Clone repo
        git_p = sb.exec("git", "clone", "--depth", "1", repo_url, "/repo", timeout=120)
        git_p.wait()
        if git_p.returncode != 0:
            err = git_p.stderr.read() if hasattr(git_p, "stderr") else "git clone failed"
            return f"Clone failed: {err}"

        # Run agent: instruction via env; Anthropic key from Modal secret (create with: modal secret create anthropic-secret ANTHROPIC_API_KEY=sk-...)
        prompt_secret = modal.Secret.from_dict({"AGENT_PROMPT": instruction})
        try:
            anthropic_secret = modal.Secret.from_name("anthropic-secret", required_keys=["ANTHROPIC_API_KEY"])
        except Exception:
            anthropic_secret = modal.Secret.from_dict({"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")})
        agent_p = sb.exec(
            "python", "-c", AGENT_SCRIPT,
            workdir="/repo",
            timeout=300,
            secrets=[prompt_secret, anthropic_secret],
        )
        agent_p.wait()
        stdout = agent_p.stdout.read()
        stderr = agent_p.stderr.read() if hasattr(agent_p, "stderr") else ""
        if agent_p.returncode != 0:
            return f"Agent exited {agent_p.returncode}\nstderr: {stderr}\nstdout: {stdout}"
        return stdout or "(no output)"
    finally:
        sb.terminate()
