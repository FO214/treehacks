"""
TreeHacks Fix Agent MCP Server
Exposes the Modal + Claude Agent SDK functionality via FastMCP tools.

After the agent applies a fix, the server automatically creates a branch,
commits, pushes, and opens a GitHub pull request.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

# Load keys from poke-mcp/.env (ANTHROPIC_API_KEY, MODAL_*, GITHUB_TOKEN, etc.)
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(__file__), ".env")
    load_dotenv(_env_path)
except ImportError:
    pass

from fastmcp import FastMCP

# Get the directory containing this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

mcp = FastMCP("TreeHacks Fix Agent")

# Default repository for testing
DEFAULT_REPO_URL = "https://github.com/soooooooot/treehacks-agent-repo"

# System prompt: frames the task for fix/change flows (make the modification only,
# the server handles branching/committing/PR automatically).
FIX_SYSTEM_PROMPT = """You are a code assistant working in a cloned repository at /repo. Your task is to:
1. Make the modification or fix requested by the user.
2. Be precise and only change what is needed to fulfill the request.

IMPORTANT:
- ALWAYS use the Bash tool for ALL file operations (creating, editing, reading files).
  Use commands like: cat, echo with redirect, tee, sed, etc.
  Example: To create a file, use bash: cat << 'HEREDOC_EOF' > /repo/filename.ext
- Do NOT use the Write or Edit tools — they may not persist to disk in this environment.
- All file paths must be absolute, starting with /repo/
- Do NOT create branches, commit, or open PRs yourself — that is handled automatically after you finish."""


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
    stdout = p.stdout.read() if hasattr(p.stdout, "read") else ""
    stderr = p.stderr.read() if hasattr(p.stderr, "read") else ""
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
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }
    # Follow 307/308 redirects (urllib doesn't follow them for POST by default)
    for _ in range(3):
        req = urllib.request.Request(url, data=payload, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read())
            return result.get("html_url", "")
        except urllib.error.HTTPError as e:
            if e.code in (307, 308):
                url = e.headers.get("Location", url)
                continue
            raise


def _post_pr_comment(
    owner: str,
    repo: str,
    pr_number: int,
    body: str,
    token: str,
) -> None:
    """Post a comment on a GitHub pull request."""
    url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
    payload = json.dumps({"body": body}).encode()
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }
    for _ in range(3):
        req = urllib.request.Request(url, data=payload, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req) as resp:
                resp.read()
            return
        except urllib.error.HTTPError as e:
            if e.code in (307, 308):
                url = e.headers.get("Location", url)
                continue
            raise


def _extract_pr_number(pr_url: str) -> int | None:
    """Extract PR number from a GitHub PR URL like https://github.com/owner/repo/pull/123."""
    m = re.search(r"/pull/(\d+)", pr_url)
    return int(m.group(1)) if m else None


def _wait_for_vercel_preview(
    owner: str,
    repo: str,
    pr_number: int,
    token: str,
    timeout: int = 300,
) -> str | None:
    """
    Poll PR comments for the Vercel bot's preview URL.
    Returns the preview URL when found, or None on timeout.
    """
    comments_url = f"https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }

    print(f"[soot] Waiting for Vercel preview deploy (polling PR #{pr_number} comments)...", flush=True)
    start = time.time()

    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(comments_url, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    comments = json.loads(resp.read())
            except urllib.error.HTTPError as e:
                if e.code in (307, 308):
                    redirect_url = e.headers.get("Location", comments_url)
                    req = urllib.request.Request(redirect_url, headers=headers)
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        comments = json.loads(resp.read())
                else:
                    raise

            for comment in comments:
                body = comment.get("body", "")
                user = comment.get("user", {}).get("login", "")
                # Vercel bot comments with preview URLs
                if "vercel" in user.lower() or "vercel" in body.lower():
                    # Only proceed if the deployment is actually ready (not still building)
                    if "ready" not in body.lower():
                        elapsed = int(time.time() - start)
                        print(f"[soot] Vercel comment found but still building ({elapsed}s)...", flush=True)
                        continue
                    # Extract preview URL — Vercel uses *.vercel.app links
                    url_match = re.search(r"https://[a-zA-Z0-9\-]+\.vercel\.app", body)
                    if url_match:
                        preview_url = url_match.group(0)
                        elapsed = int(time.time() - start)
                        print(f"[soot] Vercel preview ready ({elapsed}s): {preview_url}", flush=True)
                        return preview_url
        except Exception as e:
            elapsed = int(time.time() - start)
            print(f"[soot] Polling error ({elapsed}s): {e}", flush=True)

        elapsed = int(time.time() - start)
        print(f"[soot] No Vercel comment yet ({elapsed}s)...", flush=True)
        time.sleep(10)

    print(f"[soot] Timed out waiting for Vercel preview ({timeout}s)", flush=True)
    return None


def _run_browser_smoke_test(
    tunnel_url: str,
    pr_url: str,
    owner: str,
    repo_name: str,
    github_token: str,
) -> str:
    """
    Run a Browserbase smoke test against a live tunnel URL and post results as a PR comment.

    Returns a short summary string for inclusion in the tool output.
    """
    from browserbase import Browserbase
    from playwright.sync_api import sync_playwright

    bb_api_key = os.environ.get("BROWSERBASE_API_KEY", "")
    bb_project_id = os.environ.get("BROWSERBASE_PROJECT_ID", "")
    if not bb_api_key or not bb_project_id:
        return "Smoke test skipped: BROWSERBASE_API_KEY or BROWSERBASE_PROJECT_ID not set."

    pr_number = _extract_pr_number(pr_url)
    if not pr_number:
        return f"Smoke test skipped: could not parse PR number from {pr_url}"

    bb = Browserbase(api_key=bb_api_key)
    session = bb.sessions.create(project_id=bb_project_id)
    replay_url = f"https://browserbase.com/sessions/{session.id}"

    console_messages: list[str] = []
    console_errors: list[str] = []
    status = "Passed"
    details: dict[str, str] = {}

    pw = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.connect_over_cdp(session.connect_url)
        context = browser.contexts[0]
        page = context.pages[0]

        # Capture console output
        def _on_console(msg):
            text = f"[{msg.type}] {msg.text}"
            console_messages.append(text)
            if msg.type in ("error", "warning"):
                console_errors.append(text)

        page.on("console", _on_console)

        # Navigate to the app
        start_time = time.time()
        try:
            response = page.goto(tunnel_url, wait_until="networkidle", timeout=30000)
            load_time = round(time.time() - start_time, 1)
            details["Page loaded"] = "yes"
            details["Load time"] = f"{load_time}s"
            details["Page title"] = page.title() or "(empty)"

            if response and response.status >= 500:
                status = "Failed"
                details["HTTP status"] = str(response.status)
            elif response:
                details["HTTP status"] = str(response.status)
        except Exception as nav_err:
            load_time = round(time.time() - start_time, 1)
            status = "Failed"
            details["Page loaded"] = "no"
            details["Load time"] = f"{load_time}s"
            details["Error"] = str(nav_err)[:200]

        if console_errors:
            status = "Failed"
            details["Console errors"] = str(len(console_errors))
        else:
            details["Console errors"] = "none"

        # Give the page a moment to settle, then close
        page.wait_for_timeout(2000)
        page.close()
        browser.close()

    except Exception as e:
        status = "Failed"
        details["Browser error"] = str(e)[:300]
    finally:
        if pw:
            pw.stop()

    # Build the PR comment
    detail_lines = "\n".join(f"- {k}: {v}" for k, v in details.items())
    console_section = ""
    if console_errors:
        truncated = console_errors[:10]
        console_section = "\n### Console Output\n```\n" + "\n".join(truncated) + "\n```"
        if len(console_errors) > 10:
            console_section += f"\n... and {len(console_errors) - 10} more"

    comment_body = (
        f"## Smoke Test Results\n\n"
        f"**Status:** {status}\n"
        f"**Replay:** [Watch browser test recording]({replay_url})\n\n"
        f"### Details\n{detail_lines}"
        f"{console_section}\n\n"
        f"---\n*Tested by [Soot](https://github.com/apps/soot-fix)*"
    )

    try:
        _post_pr_comment(owner, repo_name, pr_number, comment_body, github_token)
        print(f"[soot] Smoke test comment posted on PR #{pr_number}.", flush=True)
    except Exception as e:
        print(f"[soot] Failed to post smoke test comment: {e}", flush=True)

    return f"Smoke test {status}. Replay: {replay_url}"


# ---------------------------------------------------------------------------
# Modal image + inline agent script (claude-agent-sdk, NOT Claude Code CLI)
# ---------------------------------------------------------------------------

# Sandbox image: Python 3.12, Node.js 20, git, claude-agent-sdk, non-root user
_SANDBOX_IMAGE = None  # built lazily after `import modal`


def _get_sandbox_image():
    """Build (and cache) the Modal sandbox image."""
    global _SANDBOX_IMAGE
    if _SANDBOX_IMAGE is None:
        import modal
        _SANDBOX_IMAGE = (
            modal.Image.debian_slim(python_version="3.12")
            .apt_install("git", "curl", "ca-certificates")
            .run_commands(
                # Install Node.js 20 (needed for npm start / Next.js / etc.)
                "curl -fsSL https://deb.nodesource.com/setup_20.x | bash -",
                "apt-get install -y nodejs",
            )
            .pip_install("claude-agent-sdk")
            .run_commands("useradd -m -s /bin/bash agent")
        )
    return _SANDBOX_IMAGE


# Inline agent script executed inside the sandbox.
# Drops root → agent user (claude-agent-sdk refuses root), then runs the prompt.
AGENT_SCRIPT = r"""
import os, pwd, subprocess, sys, json

# ── Drop root privileges ──────────────────────────────────────────────
try:
    _u = pwd.getpwnam("agent")
    os.setgid(_u.pw_gid)
    os.initgroups("agent", _u.pw_gid)
    os.setuid(_u.pw_uid)
    # Point HOME at /repo so claude-agent-sdk resolves paths inside the repo
    os.environ["HOME"] = "/repo"
except (KeyError, PermissionError):
    pass  # already non-root or user missing

# Make doubly sure cwd is /repo
os.chdir("/repo")

print(f"[agent] uid={os.getuid()} cwd={os.getcwd()} home={os.environ.get('HOME')}", flush=True)

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
        mtype = type(message).__name__
        # Verbose: dump every field of every message
        msg_data = {}
        for k in vars(message):
            v = getattr(message, k)
            try:
                json.dumps(v)
                msg_data[k] = v
            except (TypeError, ValueError):
                msg_data[k] = repr(v)[:300]
        print(f"[agent] {mtype}: {json.dumps(msg_data, default=str)[:500]}", flush=True)
        if hasattr(message, "result") and message.result:
            out.append(str(message.result))

    # ── Debugging: see what actually exists on disk ────────────────────
    print("\n[agent] ls -la /repo/:", flush=True)
    subprocess.run(["ls", "-la", "/repo/"])
    print("\n[agent] git status after agent:", flush=True)
    subprocess.run(["git", "status", "--short"], cwd="/repo")
    print("[agent] git diff --stat:", flush=True)
    subprocess.run(["git", "diff", "--stat"], cwd="/repo")

    print("\n--- AGENT RESULT ---\n")
    print("\n".join(out) if out else "No result output.")

asyncio.run(main())
"""


def run_modal_agent(
    instruction: str,
    repo_url: str,
    system_prompt: str | None = None,
    smoke_test: bool = False,
) -> str:
    """
    Run claude-agent-sdk in a Modal sandbox, then push a branch and open a PR.

    Flow:
      1. Clone repo (authenticated so we can push)
      2. Create a feature branch
      3. Run claude-agent-sdk with the user instruction (drops root → agent)
      4. Stage + commit + push any changes the agent made
      5. Open a GitHub pull request via the API
      6. (Optional) Wait for Vercel preview deploy, then run Browserbase smoke test
    """
    try:
        import modal
    except ImportError:
        return "Error: Modal is not installed. Run: pip install modal"

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        return "Error: ANTHROPIC_API_KEY not set in environment"

    github_token = os.environ.get("GITHUB_TOKEN", "")
    if not github_token:
        return "Error: GITHUB_TOKEN environment variable is required to push branches and create PRs."

    # Parse owner/repo for GitHub API + authenticated clone
    try:
        owner, repo_name = _parse_github_owner_repo(repo_url)
    except ValueError as e:
        return str(e)

    auth_url = f"https://x-access-token:{github_token}@github.com/{owner}/{repo_name}.git"
    branch_name = f"soot-fix/{_slugify(instruction)}-{int(time.time())}"

    app = modal.App.lookup("treehacks-fix-agent", create_if_missing=True)
    sandbox_image = _get_sandbox_image()

    sb = None
    try:
        # ── Create sandbox ────────────────────────────────────────────
        print("[soot] Creating Modal sandbox...", flush=True)
        sandbox_kwargs: dict = dict(app=app, image=sandbox_image, timeout=10 * 60)
        with modal.enable_output():
            sb = modal.Sandbox.create(**sandbox_kwargs)
        print("[soot] Sandbox created.", flush=True)

        # ── 1. Clone repo (authenticated URL so we can push later) ────
        print(f"[soot] Cloning {owner}/{repo_name}...", flush=True)
        _, stderr, rc = _exec(sb, "git", "clone", auth_url, "/repo", timeout=120)
        if rc != 0:
            return f"Clone failed: {stderr}"
        print("[soot] Clone complete.", flush=True)

        # ── 2. Detect default branch & create feature branch ─────────
        base_branch_out, _, _ = _exec(
            sb, "git", "rev-parse", "--abbrev-ref", "HEAD", workdir="/repo",
        )
        base_branch = base_branch_out.strip() or "main"

        _exec(sb, "git", "config", "user.name", "Soot Fix Agent", workdir="/repo")
        _exec(sb, "git", "config", "user.email", "agent@treehacks.dev", workdir="/repo")
        _exec(sb, "git", "checkout", "-b", branch_name, workdir="/repo")
        print(f"[soot] Created branch: {branch_name} (base: {base_branch})", flush=True)

        # ── 3. Run agent (drops root → agent inside the script) ──────
        _exec(sb, "chown", "-R", "agent:agent", "/repo")

        # Build the full prompt (prepend system prompt if provided)
        full_prompt = f"{system_prompt}\n\nUser request: {instruction}" if system_prompt else instruction

        prompt_secret = modal.Secret.from_dict({"AGENT_PROMPT": full_prompt})
        try:
            anthropic_secret = modal.Secret.from_name(
                "anthropic-secret", required_keys=["ANTHROPIC_API_KEY"],
            )
        except Exception:
            anthropic_secret = modal.Secret.from_dict(
                {"ANTHROPIC_API_KEY": anthropic_key},
            )

        print("[soot] Running claude-agent-sdk...", flush=True)
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
        print("[soot] Agent finished.", flush=True)

        # ── 4. Check for changes ─────────────────────────────────────
        # After chown to agent, root needs safe.directory to use git
        _exec(sb, "git", "config", "--global", "--add", "safe.directory", "/repo")

        # Clean up SDK metadata so it doesn't pollute the commit
        _exec(sb, "rm", "-rf", "/repo/.claude", "/repo/.claude.json", "/repo/.npm")
        # Also remove any backup files
        _exec(sb, "bash", "-c", "rm -f /repo/.claude.json.backup.*")

        diff_out, _, _ = _exec(sb, "git", "diff", "--stat", workdir="/repo")
        status_out, _, _ = _exec(sb, "git", "status", "--porcelain", workdir="/repo")

        if not diff_out.strip() and not status_out.strip():
            return f"Agent completed but made no file changes.\n\n{agent_stdout}"

        # ── 5. Stage, commit, push ───────────────────────────────────
        _exec(sb, "git", "add", "-A", workdir="/repo")

        commit_msg = f"fix: {instruction[:72]}"
        _, stderr, rc = _exec(sb, "git", "commit", "-m", commit_msg, workdir="/repo")
        if rc != 0:
            return f"Commit failed: {stderr}\n\n{agent_stdout}"

        print(f"[soot] Pushing branch {branch_name}...", flush=True)
        _, stderr, rc = _exec(
            sb, "git", "push", "origin", branch_name, workdir="/repo", timeout=120,
        )
        if rc != 0:
            return f"Push failed: {stderr}\n\n{agent_stdout}"
        print("[soot] Push complete.", flush=True)

        # ── 6. Open pull request ─────────────────────────────────────
        pr_title = f"soot-fix: {instruction[:100]}"
        pr_body = (
            f"## Instructions\n\n"
            f"{instruction}\n\n"
            f"---\n\n"
            f"*Opened by [Soot](https://github.com/apps/soot-fix)*"
        )

        print(f"[soot] Opening PR on {owner}/{repo_name}...", flush=True)
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

        print(f"[soot] PR created: {pr_url}", flush=True)

        # ── 7. (Optional) Smoke test via Browserbase + Vercel preview ──
        smoke_result = ""
        if smoke_test:
            try:
                # Wait for Vercel bot to comment with the preview URL
                pr_number = _extract_pr_number(pr_url)
                preview_url = _wait_for_vercel_preview(
                    owner, repo_name, pr_number, github_token, timeout=300,
                )

                if preview_url:
                    print(f"[soot] Running Browserbase smoke test against {preview_url}...", flush=True)
                    # Run Playwright in a separate thread — its sync API
                    # crashes if called from inside an asyncio event loop
                    # (the MCP server is async).
                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        smoke_result = pool.submit(
                            _run_browser_smoke_test,
                            tunnel_url=preview_url,
                            pr_url=pr_url,
                            owner=owner,
                            repo_name=repo_name,
                            github_token=github_token,
                        ).result()
                    print(f"[soot] {smoke_result}", flush=True)
                else:
                    smoke_result = "Smoke test skipped: Vercel preview deploy did not complete within 5 minutes."
                    print(f"[soot] {smoke_result}", flush=True)

            except Exception as e:
                smoke_result = f"Smoke test error: {e}"
                print(f"[soot] {smoke_result}", flush=True)

        result_parts = [f"PR created: {pr_url}", f"Branch: {branch_name}"]
        if smoke_result:
            result_parts.append(f"Smoke test: {smoke_result}")
        result_parts.append("")
        result_parts.append(agent_stdout)
        return "\n".join(result_parts)

    except Exception as e:
        return f"Error: {str(e)}"

    finally:
        if sb:
            try:
                sb.terminate()
            except:
                pass


@mcp.tool()
def run_fix(
    instruction: str,
    repo_url: str = DEFAULT_REPO_URL,
    smoke_test: bool = False,
) -> str:
    """
    Run a fix instruction in a Modal sandbox with Claude Agent SDK, then push a branch and open a PR.

    This creates a sandboxed environment, clones the specified repository,
    runs the Claude Agent SDK with your instruction, and automatically
    commits, pushes, and opens a GitHub pull request with the changes.

    Optionally waits for Vercel preview deploy, then runs a Browserbase smoke test.

    Args:
        instruction: What to fix or change (e.g., "Fix the bug in auth.py" or "Add a test for login")
        repo_url: GitHub HTTPS URL to clone (defaults to treehacks-agent-repo)
        smoke_test: If true, wait for Vercel preview deploy and run a browser smoke test via Browserbase

    Returns:
        The PR URL, agent output, and optional smoke test results
    """
    try:
        result = run_modal_agent(
            instruction=instruction,
            repo_url=repo_url,
            system_prompt=FIX_SYSTEM_PROMPT,
            smoke_test=smoke_test,
        )
        return result
    except Exception as e:
        return f"Error running fix: {str(e)}\n\nMake sure Modal is configured, ANTHROPIC_API_KEY and GITHUB_TOKEN are set."


@mcp.tool()
def run_fix_default_repo(instruction: str, smoke_test: bool = False) -> str:
    """
    Quick fix on the default TreeHacks agent repository, with automatic PR.

    Args:
        instruction: What to fix or change in the default repo
        smoke_test: If true, start the app after PR and run a browser smoke test via Browserbase

    Returns:
        The PR URL, agent output, and optional smoke test results
    """
    try:
        result = run_modal_agent(
            instruction=instruction,
            repo_url=DEFAULT_REPO_URL,
            system_prompt=FIX_SYSTEM_PROMPT,
            smoke_test=smoke_test,
        )
        return result
    except Exception as e:
        return f"Error running fix: {str(e)}"


@mcp.tool()
def run_analysis(instruction: str, repo_url: str = DEFAULT_REPO_URL) -> str:
    """
    Analyze code without making changes.

    This is useful for understanding code structure, finding bugs, or getting insights
    before making actual changes.

    Args:
        instruction: What to analyze (e.g., "Analyze the auth flow" or "List all API endpoints")
        repo_url: Git repository URL to clone and analyze

    Returns:
        The analysis results from the agent
    """
    try:
        analysis_instruction = f"ANALYSIS ONLY (do not modify files): {instruction}"
        result = run_modal_agent(instruction=analysis_instruction, repo_url=repo_url)
        return f"Analysis completed!\n\n{result}"
    except Exception as e:
        return f"Error running analysis: {str(e)}"


@mcp.tool()
def test_local_server() -> str:
    """
    Test if the local MCP server is running correctly.

    Returns:
        Status information about the server setup
    """
    venv_python = os.path.join(SCRIPT_DIR, ".venv", "bin", "python")
    try:
        result = subprocess.run(
            [venv_python, "-c", "import fastmcp; import modal; import dotenv; print('All dependencies OK')"],
            capture_output=True,
            text=True,
            cwd=SCRIPT_DIR,
            timeout=10
        )
        if result.returncode == 0:
            return f"Server dependencies are installed correctly!\n{result.stdout}"
        else:
            return f"Dependency check failed:\n{result.stderr}"
    except Exception as e:
        return f"Error checking dependencies: {str(e)}"


@mcp.tool()
def check_modal_status() -> str:
    """
    Check if Modal is properly configured.

    Returns:
        Modal configuration status
    """
    modal_cli = os.path.join(SCRIPT_DIR, ".venv", "bin", "modal")
    try:
        result = subprocess.run(
            [modal_cli, "token", "info"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return f"Modal is configured!\n{result.stdout}"
        else:
            return f"Modal not configured. Run '.venv/bin/modal token new' to authenticate.\n{result.stderr}"
    except FileNotFoundError:
        return f"Modal CLI not found at {modal_cli}. Run: uv pip install modal -p .venv/bin/python"
    except Exception as e:
        return f"Error checking Modal: {str(e)}"


@mcp.tool()
def list_available_tools() -> str:
    """
    List the tools available to the Claude Agent SDK in the sandbox.

    Returns:
        List of available tools and their purposes
    """
    tools = {
        "Read": "Read files from the repository",
        "Write": "Create new files or overwrite existing ones",
        "Edit": "Make precise edits to existing files",
        "Bash": "Execute shell commands in the sandbox",
        "Glob": "Find files matching patterns",
        "Grep": "Search for text patterns in files"
    }

    output = ["Available Agent Tools:", "=" * 50]
    for tool, description in tools.items():
        output.append(f"\n• {tool}")
        output.append(f"  {description}")

    return "\n".join(output)


@mcp.tool()
def get_project_info() -> str:
    """
    Get information about the TreeHacks Fix Agent project.

    Returns:
        Project description and usage information
    """
    info = """
TreeHacks Fix Agent - MCP Server
=================================

This MCP server wraps the TreeHacks Fix Agent, which combines:
• Modal (serverless containers) for sandboxed execution
• Claude Agent SDK for AI-powered code fixes
• Git for repository management

Key Features:
- Clone any Git repository into a sandboxed environment
- Run AI-powered fix instructions with Claude Agent SDK
- Safe execution without affecting your local files
- Automatic cleanup after execution

Usage:
1. Use run_fix() with an instruction and repo URL
2. The agent will clone the repo, apply fixes, and return results
3. All changes happen in the sandbox (not your local machine)

Requirements:
- Modal account and authentication (modal token new)
- ANTHROPIC_API_KEY environment variable or Modal secret
- Internet connection for cloning repositories

Example Instructions:
- "Fix the authentication bug in auth.py"
- "Add error handling to the API endpoints"
- "Write unit tests for the user service"
- "Refactor the database connection code"
"""
    return info


@mcp.tool()
def run_test_fix() -> str:
    """
    Run a simple test fix on the default repository to verify everything works.

    Returns:
        Test execution results
    """
    test_instruction = "List all Python files in the repository and describe what each one does."
    try:
        result = run_modal_agent(instruction=test_instruction, repo_url=DEFAULT_REPO_URL)
        return f"Test fix completed successfully!\n\nInstruction: {test_instruction}\n\nResult:\n{result}"
    except Exception as e:
        return f"Test fix failed: {str(e)}\n\nThis might indicate Modal or API key issues."


if __name__ == "__main__":
    print("Starting TreeHacks Fix Agent MCP Server on http://0.0.0.0:8765")
    print("Available tools:")
    print("   - run_fix: Execute fix instructions in sandbox")
    print("   - run_fix_default_repo: Quick fix on default repo")
    print("   - run_analysis: Analyze code without changes")
    print("   - test_local_server: Check dependencies")
    print("   - check_modal_status: Verify Modal configuration")
    print("   - list_available_tools: Show agent capabilities")
    print("   - get_project_info: Project documentation")
    print("   - run_test_fix: Test the complete workflow")
    print()
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8765)
