"""
TreeHacks Fix Agent MCP Server
Exposes the Modal + Claude Agent SDK functionality via FastMCP tools.
"""
import os
import subprocess
import sys

# Load keys from poke-mcp/.env (ANTHROPIC_API_KEY, MODAL_*, POKE_*, etc.)
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
DEFAULT_REPO_URL = "https://github.com/iankorovinsky/treehacks-agent-repo"

# System prompt: frames the task for fix/change flows (make modification, open PR, etc.)
FIX_SYSTEM_PROMPT = """You are a code assistant working in a cloned repository. Your task is to:
1. Make the modification or fix requested by the user.
2. After making changes, create a new branch, commit your changes, and open a pull request (e.g. via gh pr create if available, or describe the changes so a PR can be opened manually).
3. Be precise and only change what is needed to fulfill the request."""


def run_modal_agent(instruction: str, repo_url: str, system_prompt: str | None = None) -> str:
    """
    Run the Claude Code agent in a Modal sandbox.

    Each call creates a new sandbox, runs the agent, and terminates on completion/error.
    If system_prompt is provided, it is prepended to the user instruction.
    """
    try:
        import modal
    except ImportError:
        return "Error: Modal is not installed. Run: pip install modal"

    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        return "Error: ANTHROPIC_API_KEY not set in environment"

    # Look up or create the Modal app (works outside of `modal run`)
    app = modal.App.lookup("treehacks-fix-agent", create_if_missing=True)

    # Define the sandbox image with Claude Code CLI
    sandbox_image = (
        modal.Image.debian_slim(python_version="3.11")
        .apt_install("git", "curl", "ca-certificates")
        .run_commands(
            # Install Node.js 20
            "curl -fsSL https://deb.nodesource.com/setup_20.x | bash -",
            "apt-get install -y nodejs",
            # Install Claude Code CLI globally
            "npm install -g @anthropic-ai/claude-code",
        )
    )

    sb = None
    try:
        # Create sandbox
        sb = modal.Sandbox.create(
            app=app,
            image=sandbox_image,
            secrets=[modal.Secret.from_dict({"ANTHROPIC_API_KEY": anthropic_key})],
            timeout=600,
        )

        # Clone the repository
        clone_proc = sb.exec("git", "clone", repo_url, "/workspace/repo")
        clone_proc.wait()
        if clone_proc.returncode != 0:
            stderr = clone_proc.stderr.read()
            return f"Error cloning repo: {stderr}"

        # Run Claude Code agent with optional system prompt + user instruction
        # The agent has access to tools: Read, Write, Edit, Bash, Glob, Grep
        prompt = f"{system_prompt}\n\nUser request: {instruction}" if system_prompt else instruction
        agent_proc = sb.exec(
            "claude",
            "-p", prompt,
            "--output-format", "text",
            "--verbose",
            workdir="/workspace/repo"
        )
        agent_proc.wait()

        stdout = agent_proc.stdout.read()
        stderr = agent_proc.stderr.read()

        if agent_proc.returncode != 0:
            return f"Agent error (exit {agent_proc.returncode}):\n{stderr}\n\nOutput:\n{stdout}"

        return stdout if stdout else "Agent completed with no output"

    except Exception as e:
        return f"Error: {str(e)}"

    finally:
        # Always terminate the sandbox
        if sb:
            try:
                sb.terminate()
            except:
                pass


@mcp.tool()
def run_fix(instruction: str, repo_url: str = DEFAULT_REPO_URL) -> str:
    """
    Run a fix instruction in a Modal sandbox with Claude Agent SDK.

    This creates a sandboxed environment, clones the specified repository,
    and runs the Claude Agent SDK with your instruction to make changes.

    Args:
        instruction: What to fix or change (e.g., "Fix the bug in auth.py" or "Add a test for login")
        repo_url: Git repository URL to clone (defaults to treehacks-agent-repo)

    Returns:
        The output from the agent execution
    """
    try:
        result = run_modal_agent(
            instruction=instruction,
            repo_url=repo_url,
            system_prompt=FIX_SYSTEM_PROMPT,
        )
        return f"Fix completed!\n\n{result}"
    except Exception as e:
        return f"Error running fix: {str(e)}\n\nMake sure Modal is configured and ANTHROPIC_API_KEY is set."


@mcp.tool()
def run_fix_default_repo(instruction: str) -> str:
    """
    Quick fix on the default TreeHacks agent repository.

    Args:
        instruction: What to fix or change in the default repo

    Returns:
        The output from the agent execution
    """
    try:
        result = run_modal_agent(
            instruction=instruction,
            repo_url=DEFAULT_REPO_URL,
            system_prompt=FIX_SYSTEM_PROMPT,
        )
        return f"Fix completed on default repo!\n\n{result}"
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
