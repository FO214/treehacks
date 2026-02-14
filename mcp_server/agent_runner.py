"""
Modal sandbox + Claude Agent SDK: clone repo, run agent with fix instruction,
then commit changes to a new branch and open a GitHub PR.
"""
import json
import os
import re
import time
import urllib.request

import modal

# Default sample repo (user can override via tool arg)
DEFAULT_REPO_URL = "https://github.com/iankorovinsky/treehacks-agent-repo"

# Image: Python, git, Claude Agent SDK, non-root user for agent execution
IMAGE = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")
    .pip_install("claude-agent-sdk")
    .run_commands("useradd -m -s /bin/bash agent")
)

# Inline agent script run inside sandbox (workdir=/repo, AGENT_PROMPT in env).
# Drops root privileges before importing the SDK because claude-agent-sdk
# refuses --dangerously-skip-permissions when running as root.
AGENT_SCRIPT = """
import os, pwd, subprocess, sys

# ── Drop root privileges ──────────────────────────────────────────────
try:
    _u = pwd.getpwnam("agent")
    os.setgid(_u.pw_gid)
    os.initgroups("agent", _u.pw_gid)
    os.setuid(_u.pw_uid)
    os.environ["HOME"] = _u.pw_dir
except (KeyError, PermissionError):
    pass  # already non-root or user missing

print(f"[DEBUG] uid={os.getuid()} cwd={os.getcwd()} home={os.environ.get('HOME')}", flush=True)

import asyncio
from claude_agent_sdk import query, ClaudeAgentOptions

async def main():
    prompt = os.environ.get("AGENT_PROMPT", "List files in this repo.")
    opts = ClaudeAgentOptions(
        allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
        permission_mode="bypassPermissions",
    )
    out = []
    async for message in query(prompt=prompt, options=opts):
        # Log every message type for debugging
        mtype = type(message).__name__
        print(f"[DEBUG] message type={mtype} attrs={list(vars(message).keys())}", flush=True)
        if hasattr(message, "result") and message.result:
            out.append(str(message.result))

    # Check filesystem after agent finishes
    print("\\n[DEBUG] git status after agent:", flush=True)
    subprocess.run(["git", "status", "--short"], cwd="/repo")
    print("[DEBUG] git diff --stat:", flush=True)
    subprocess.run(["git", "diff", "--stat"], cwd="/repo")

    print("\\n--- AGENT RESULT ---\\n")
    print("\\n".join(out) if out else "No result output.")

asyncio.run(main())
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_github_owner_repo(repo_url: str) -> tuple[str, str]:
    """Extract (owner, repo) from a GitHub URL."""
    m = re.match(r"https?://github\.com/([^/]+)/([^/.]+)", repo_url)
    if not m:
        raise ValueError(f"Could not parse GitHub owner/repo from: {repo_url}")
    return m.group(1), m.group(2)


def _slugify(text: str, max_len: int = 40) -> str:
    """Turn a human sentence into a short branch-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-")


def _exec(sb, *args, **kwargs) -> tuple[str, str, int]:
    """Run a command in the sandbox; return (stdout, stderr, returncode)."""
    p = sb.exec(*args, **kwargs)
    p.wait()
    stdout = p.stdout.read() if hasattr(p, "stdout") else ""
    stderr = p.stderr.read() if hasattr(p, "stderr") else ""
    return stdout, stderr, p.returncode


def _create_pr(
    owner: str,
    repo: str,
    branch: str,
    base: str,
    title: str,
    body: str,
    token: str,
) -> str:
    """Create a GitHub pull request via the REST API. Returns the PR URL."""
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    payload = json.dumps({
        "title": title,
        "head": branch,
        "base": base,
        "body": body,
    }).encode()
    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    return result.get("html_url", "")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_fix_sync(instruction: str, repo_url: str = DEFAULT_REPO_URL) -> str:
    """Create Modal sandbox, clone repo, run Claude Agent SDK, push branch & open PR."""

    github_token = os.environ.get("GITHUB_TOKEN", "")
    if not github_token:
        return "Error: GITHUB_TOKEN environment variable is required to push branches and create PRs."

    # Parse owner/repo for the GitHub API
    try:
        owner, repo_name = _parse_github_owner_repo(repo_url)
    except ValueError as e:
        return str(e)

    # Authenticated clone URL (allows push)
    auth_url = f"https://x-access-token:{github_token}@github.com/{owner}/{repo_name}.git"

    # Branch name from instruction + timestamp
    branch_name = f"soot-fix/{_slugify(instruction)}-{int(time.time())}"

    app = modal.App.lookup("treehacks-fix-agent", create_if_missing=True)

    with modal.enable_output():
        sb = modal.Sandbox.create(app=app, image=IMAGE, timeout=10 * 60)

    try:
        # ── 1. Clone repo (full clone so we can push) ──────────────────
        _, stderr, rc = _exec(sb, "git", "clone", auth_url, "/repo", timeout=120)
        if rc != 0:
            return f"Clone failed: {stderr}"

        # ── 2. Detect default branch name ──────────────────────────────
        base_branch_out, _, _ = _exec(
            sb, "git", "rev-parse", "--abbrev-ref", "HEAD", workdir="/repo",
        )
        base_branch = base_branch_out.strip() or "main"

        # ── 3. Configure git & create feature branch ───────────────────
        _exec(sb, "git", "config", "user.name", "Fix Agent", workdir="/repo")
        _exec(sb, "git", "config", "user.email", "agent@treehacks.dev", workdir="/repo")
        _exec(sb, "git", "checkout", "-b", branch_name, workdir="/repo")

        # ── 4. Run agent (drops root→agent inside the script) ────────────
        _exec(sb, "chown", "-R", "agent:agent", "/repo")

        prompt_secret = modal.Secret.from_dict({"AGENT_PROMPT": instruction})
        try:
            anthropic_secret = modal.Secret.from_name(
                "anthropic-secret", required_keys=["ANTHROPIC_API_KEY"],
            )
        except Exception:
            anthropic_secret = modal.Secret.from_dict(
                {"ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "")},
            )

        agent_p = sb.exec(
            "python", "-c", AGENT_SCRIPT,
            workdir="/repo",
            timeout=300,
            secrets=[prompt_secret, anthropic_secret],
        )
        agent_p.wait()
        agent_stdout = agent_p.stdout.read()
        agent_stderr = agent_p.stderr.read() if hasattr(agent_p, "stderr") else ""

        if agent_p.returncode != 0:
            return f"Agent exited {agent_p.returncode}\nstderr: {agent_stderr}\nstdout: {agent_stdout}"

        # ── 5. Check for changes ───────────────────────────────────────
        # After chown to agent, root needs safe.directory to use git here
        _exec(sb, "git", "config", "--global", "--add", "safe.directory", "/repo")
        diff_out, _, _ = _exec(sb, "git", "diff", "--stat", workdir="/repo")
        status_out, _, _ = _exec(sb, "git", "status", "--porcelain", workdir="/repo")

        if not diff_out.strip() and not status_out.strip():
            return f"Agent completed but made no file changes.\n\n{agent_stdout}"

        # ── 6. Stage, commit, push ─────────────────────────────────────
        _exec(sb, "git", "add", "-A", workdir="/repo")

        commit_msg = f"fix: {instruction[:72]}"
        _, stderr, rc = _exec(sb, "git", "commit", "-m", commit_msg, workdir="/repo")
        if rc != 0:
            return f"Commit failed: {stderr}\n\n{agent_stdout}"

        _, stderr, rc = _exec(
            sb, "git", "push", "origin", branch_name, workdir="/repo", timeout=120,
        )
        if rc != 0:
            return f"Push failed: {stderr}\n\n{agent_stdout}"

        # ── 7. Open pull request ───────────────────────────────────────
        pr_title = f"soot-fix: {instruction[:100]}"
        pr_body = (
            f"## Instructions\n\n"
            f"{instruction}\n\n"
            f"---\n\n"
            f"*Opened by [Soot](https://github.com/apps/soot-fix)*"
        )

        try:
            pr_url = _create_pr(
                owner, repo_name, branch_name, base_branch,
                pr_title, pr_body, github_token,
            )
        except Exception as e:
            return (
                f"Changes pushed to branch `{branch_name}` but PR creation failed: {e}\n\n"
                f"{agent_stdout}"
            )

        return f"PR created: {pr_url}\nBranch: {branch_name}\n\n{agent_stdout}"

    finally:
        sb.terminate()
