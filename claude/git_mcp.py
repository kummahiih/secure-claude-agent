"""
Git MCP stdio server for secure-claude.

Provides git tools (status, diff, add, commit, log) via MCP protocol.
Runs as a subprocess of Claude Code inside claude-server.

Security:
- Working directory structurally locked via GIT_DIR and GIT_WORK_TREE env vars
- core.hooksPath=/dev/null on every git call — structural hook prevention
- Must NOT call verify_isolation.py (Claude Code passes ANTHROPIC_API_KEY
  to child processes, which would false-positive)
"""

import asyncio
import os
import subprocess
import sys
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import Server

# Resolve git directory and worktree from environment.
# These are set in docker-compose.yml:
#   GIT_DIR=/gitdir
#   GIT_WORK_TREE=/workspace
GIT_DIR = os.environ.get("GIT_DIR")
GIT_WORK_TREE = os.environ.get("GIT_WORK_TREE")

if not GIT_DIR or not GIT_WORK_TREE:
    print(
        "FATAL: GIT_DIR and GIT_WORK_TREE must be set",
        file=sys.stderr,
    )
    sys.exit(1)

# Baseline commit for git_reset_soft floor enforcement.
# Must be set ONCE at container startup (in entrypoint.sh) and passed as
# GIT_BASELINE_COMMIT env var. This survives across Claude Code subprocess
# respawns — each query gets a fresh MCP server process, but the baseline
# stays fixed to what existed when the container started.
#
# If not set, falls back to capturing HEAD now (less safe — resets to
# whatever HEAD is at first tool invocation).
BASELINE_COMMIT: str | None = os.environ.get("GIT_BASELINE_COMMIT")

if BASELINE_COMMIT:
    print(f"Baseline commit (from env): {BASELINE_COMMIT}", file=sys.stderr)
else:
    # Fallback: capture now (only useful for testing, not production)
    try:
        _baseline_result = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            env={**os.environ, "GIT_DIR": GIT_DIR, "GIT_WORK_TREE": GIT_WORK_TREE},
        )
        if _baseline_result.returncode == 0:
            BASELINE_COMMIT = _baseline_result.stdout.strip()
            print(f"Baseline commit (captured): {BASELINE_COMMIT}", file=sys.stderr)
        else:
            print("No baseline commit (empty repo)", file=sys.stderr)
    except Exception as e:
        print(f"Warning: could not determine baseline commit: {e}", file=sys.stderr)


def _run_git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command with structural safety flags.

    Every call gets:
    - core.hooksPath=/dev/null — prevents hook execution even if hooks exist in gitdir
    - GIT_DIR / GIT_WORK_TREE — locks operations to the mounted paths
    """
    cmd = [
        "git",
        "-c", "core.hooksPath=/dev/null",
        *args,
    ]
    env = {
        **os.environ,
        "GIT_DIR": GIT_DIR,
        "GIT_WORK_TREE": GIT_WORK_TREE,
    }
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30,
        check=check,
        env=env,
    )


def _ok(text: str) -> types.CallToolResult:
    """Return a successful tool result."""
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        isError=False,
    )


def _err(text: str) -> types.CallToolResult:
    """Return an error tool result."""
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)],
        isError=True,
    )


# --- Tool implementations ---


def git_status() -> types.CallToolResult:
    """Run git status."""
    try:
        result = _run_git("status", "--short", check=False)
        output = result.stdout.strip()
        if result.returncode != 0:
            return _err(f"git status failed: {result.stderr.strip()}")
        if not output:
            return _ok("Working tree clean — no changes.")
        return _ok(output)
    except subprocess.TimeoutExpired:
        return _err("git status timed out")
    except Exception as e:
        return _err(f"git status error: {e}")


def git_diff(staged: bool = False) -> types.CallToolResult:
    """Run git diff, optionally showing staged changes."""
    try:
        args = ["diff"]
        if staged:
            args.append("--cached")
        result = _run_git(*args, check=False)
        output = result.stdout.strip()
        if result.returncode != 0:
            return _err(f"git diff failed: {result.stderr.strip()}")
        if not output:
            label = "staged" if staged else "unstaged"
            return _ok(f"No {label} changes.")
        return _ok(output)
    except subprocess.TimeoutExpired:
        return _err("git diff timed out")
    except Exception as e:
        return _err(f"git diff error: {e}")


def git_add(paths: list[str]) -> types.CallToolResult:
    """Stage files for commit.

    Args:
        paths: List of file paths relative to the worktree root.
               Use ["."] to stage everything.
    """
    if not paths:
        return _err("No paths provided to git add")
    try:
        result = _run_git("add", "--", *paths, check=False)
        if result.returncode != 0:
            return _err(f"git add failed: {result.stderr.strip()}")
        return _ok(f"Staged: {', '.join(paths)}")
    except subprocess.TimeoutExpired:
        return _err("git add timed out")
    except Exception as e:
        return _err(f"git add error: {e}")


def git_commit(message: str) -> types.CallToolResult:
    """Create a commit with the given message.

    Args:
        message: Commit message (required, non-empty).
    """
    if not message or not message.strip():
        return _err("Commit message must not be empty")
    try:
        result = _run_git(
            "commit",
            "-m", message.strip(),
            "--no-verify",  # Belt-and-suspenders: skip hooks even if hooksPath fails
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            # "nothing to commit" is returncode 1 but not really an error
            if "nothing to commit" in stdout or "nothing to commit" in stderr:
                return _ok("Nothing to commit — working tree clean.")
            return _err(f"git commit failed: {stderr or stdout}")
        return _ok(result.stdout.strip())
    except subprocess.TimeoutExpired:
        return _err("git commit timed out")
    except Exception as e:
        return _err(f"git commit error: {e}")


def git_log(max_count: int = 10) -> types.CallToolResult:
    """Show recent commit log.

    Args:
        max_count: Number of commits to show (default 10, max 50).
    """
    max_count = min(max(1, max_count), 50)
    try:
        result = _run_git(
            "log",
            f"--max-count={max_count}",
            "--oneline",
            "--no-decorate",
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            # Empty repo has no commits
            if "does not have any commits" in stderr:
                return _ok("No commits yet.")
            return _err(f"git log failed: {stderr}")
        output = result.stdout.strip()
        if not output:
            return _ok("No commits yet.")
        return _ok(output)
    except subprocess.TimeoutExpired:
        return _err("git log timed out")
    except Exception as e:
        return _err(f"git log error: {e}")


def git_reset_soft(count: int = 1) -> types.CallToolResult:
    """Undo the last N commits, keeping changes staged.

    Enforces a baseline floor: cannot reset past the commit that existed
    when git_mcp.py started. The agent can only undo its own commits.

    Args:
        count: Number of commits to undo (default 1, max 5).
    """
    count = min(max(1, count), 5)

    if BASELINE_COMMIT is None:
        return _err("Cannot reset — no baseline commit (empty repo at startup)")

    try:
        # Resolve what HEAD~count points to
        target_result = _run_git(
            "rev-parse", f"HEAD~{count}",
            check=False,
        )
        if target_result.returncode != 0:
            return _err(
                f"Cannot reset {count} commits — not enough history. "
                f"{target_result.stderr.strip()}"
            )
        target_commit = target_result.stdout.strip()

        # Enforce baseline floor: allow resetting TO the baseline but not past it.
        # If target equals baseline, that's fine — we're undoing only agent commits.
        # If target is a strict ancestor of baseline, we'd be erasing pre-existing history.
        if target_commit != BASELINE_COMMIT:
            # Check if target is an ancestor of baseline (i.e., older than baseline)
            ancestor_check = _run_git(
                "merge-base", "--is-ancestor", target_commit, BASELINE_COMMIT,
                check=False,
            )
            if ancestor_check.returncode == 0:
                # target is strictly before baseline — block
                return _err(
                    f"Cannot reset {count} commits — would go past the baseline commit "
                    f"({BASELINE_COMMIT[:12]}). You can only undo commits created during "
                    f"this session."
                )

        # Safe to reset
        result = _run_git("reset", "--soft", f"HEAD~{count}", check=False)
        if result.returncode != 0:
            return _err(f"git reset failed: {result.stderr.strip()}")

        return _ok(
            f"Reset {count} commit(s). Changes are still staged. "
            f"HEAD is now at {target_commit[:12]}."
        )

    except subprocess.TimeoutExpired:
        return _err("git reset timed out")
    except Exception as e:
        return _err(f"git reset error: {e}")


# --- MCP server wiring ---

server = Server("git-mcp")

TOOLS = [
    types.Tool(
        name="git_status",
        description="Show working tree status (short format). Returns list of changed files with status codes.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    types.Tool(
        name="git_diff",
        description="Show file differences. By default shows unstaged changes. Set staged=true to see changes staged for commit.",
        inputSchema={
            "type": "object",
            "properties": {
                "staged": {
                    "type": "boolean",
                    "description": "If true, show staged (cached) changes instead of unstaged.",
                    "default": False,
                },
            },
        },
    ),
    types.Tool(
        name="git_add",
        description='Stage files for the next commit. Pass paths relative to workspace root. Use ["."] to stage all changes.',
        inputSchema={
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": 'File paths to stage, relative to workspace root. Use ["."] for all.',
                },
            },
            "required": ["paths"],
        },
    ),
    types.Tool(
        name="git_commit",
        description="Create a commit with staged changes. Requires a non-empty commit message.",
        inputSchema={
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Commit message.",
                },
            },
            "required": ["message"],
        },
    ),
    types.Tool(
        name="git_log",
        description="Show recent commits (oneline format). Returns up to max_count commits.",
        inputSchema={
            "type": "object",
            "properties": {
                "max_count": {
                    "type": "integer",
                    "description": "Number of commits to show (default 10, max 50).",
                    "default": 10,
                },
            },
        },
    ),
    types.Tool(
        name="git_reset_soft",
        description=(
            "Undo the last N commits, keeping all changes staged. "
            "Cannot reset past the baseline commit that existed at startup — "
            "only commits created during this session can be undone."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of commits to undo (default 1, max 5).",
                    "default": 1,
                },
            },
        },
    ),
]


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return TOOLS


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict[str, Any]
) -> types.CallToolResult:
    match name:
        case "git_status":
            return git_status()
        case "git_diff":
            return git_diff(staged=arguments.get("staged", False))
        case "git_add":
            return git_add(paths=arguments.get("paths", []))
        case "git_commit":
            return git_commit(message=arguments.get("message", ""))
        case "git_log":
            return git_log(max_count=arguments.get("max_count", 10))
        case "git_reset_soft":
            return git_reset_soft(count=arguments.get("count", 1))
        case _:
            return _err(f"Unknown tool: {name}")


async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())