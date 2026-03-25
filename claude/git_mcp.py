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


def parse_gitmodules(workspace: str = "/workspace") -> list[dict]:
    """Parse .gitmodules and return a list of submodule dicts.

    Args:
        workspace: Path to the workspace root (where .gitmodules lives).
                   Defaults to '/workspace' (the production mount point).

    Returns:
        List of dicts with 'name' and 'path' keys.  'path' is normalised
        with os.path.normpath.  Returns [] if .gitmodules is absent or
        cannot be read.
    """
    gitmodules_path = os.path.join(workspace, ".gitmodules")
    if not os.path.exists(gitmodules_path):
        return []

    submodules: list[dict] = []
    current_name: str | None = None
    current_path: str | None = None

    try:
        with open(gitmodules_path) as f:
            for raw_line in f:
                line = raw_line.strip()
                if line.startswith('[submodule "') and line.endswith('"]'):
                    # Flush previous entry
                    if current_name is not None and current_path is not None:
                        submodules.append(
                            {
                                "name": current_name,
                                "path": os.path.normpath(current_path),
                            }
                        )
                    current_name = line[len('[submodule "'):-2]
                    current_path = None
                elif "=" in line and current_name is not None:
                    key, _, value = line.partition("=")
                    if key.strip() == "path":
                        current_path = value.strip()
        # Flush last entry
        if current_name is not None and current_path is not None:
            submodules.append(
                {
                    "name": current_name,
                    "path": os.path.normpath(current_path),
                }
            )
    except OSError:
        return []

    return submodules


def git_env_for(
    file_path: str | None = None,
    submodule_path: str | None = None,
) -> tuple[dict, str, str]:
    """Return (env_vars, git_dir, work_tree) for the correct repo.

    Determines whether to use the root repo or a submodule repo based on
    the provided arguments.

    Priority:
    1. If ``submodule_path`` is given, use that submodule directly.
    2. Else if ``file_path`` is given, auto-detect the owning submodule
       by checking which submodule path is a prefix of ``file_path``.
    3. Otherwise, fall back to the root repo.

    Args:
        file_path: Path to a file relative to the workspace root.  Used to
                   auto-detect which submodule owns it.
        submodule_path: Explicit submodule path relative to the workspace
                        root (e.g. ``'cluster/agent'``).

    Returns:
        Tuple of ``(env_vars, git_dir, work_tree)`` where:
        - ``env_vars``  — copy of ``os.environ`` with ``GIT_DIR`` / ``GIT_WORK_TREE`` set
        - ``git_dir``   — absolute path to the ``.git`` directory
        - ``work_tree`` — absolute path to the working tree root
    """
    root_gitdir = GIT_DIR        # e.g. /gitdir
    root_worktree = GIT_WORK_TREE  # e.g. /workspace

    effective_submodule = submodule_path

    if effective_submodule is None and file_path is not None:
        submodules = parse_gitmodules(workspace=root_worktree)
        norm_file = os.path.normpath(file_path)
        for sub in submodules:
            sub_prefix = sub["path"]
            if norm_file == sub_prefix or norm_file.startswith(sub_prefix + os.sep):
                effective_submodule = sub["path"]
                break

    if effective_submodule is not None:
        git_dir = os.path.join(root_gitdir, "modules", effective_submodule)
        work_tree = os.path.join(root_worktree, effective_submodule)
    else:
        git_dir = root_gitdir
        work_tree = root_worktree

    env = {**os.environ, "GIT_DIR": git_dir, "GIT_WORK_TREE": work_tree}
    return env, git_dir, work_tree


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

# Per-submodule baseline commits, keyed by submodule path (relative to workspace).
# Populated at startup so git_reset_soft can enforce a floor for submodule resets.
SUBMODULE_BASELINE_COMMITS: dict[str, str] = {}

for _sub in parse_gitmodules(workspace=GIT_WORK_TREE):
    try:
        _sub_env, _, _ = git_env_for(submodule_path=_sub["path"])
        _sub_result = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            env=_sub_env,
        )
        if _sub_result.returncode == 0:
            _sub_commit = _sub_result.stdout.strip()
            SUBMODULE_BASELINE_COMMITS[_sub["path"]] = _sub_commit
            print(
                f"Submodule baseline ({_sub['path']}): {_sub_commit}",
                file=sys.stderr,
            )
        else:
            print(
                f"Submodule {_sub['path']} has no commits yet — skipping baseline.",
                file=sys.stderr,
            )
    except Exception as _sub_e:
        print(
            f"Warning: could not determine baseline for submodule {_sub['path']}: {_sub_e}",
            file=sys.stderr,
        )


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


def _run_git_env(env: dict, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run a git command with the provided environment.

    Every call gets core.hooksPath=/dev/null.  The caller supplies the
    full environment (including GIT_DIR / GIT_WORK_TREE) via ``env``.
    """
    cmd = ["git", "-c", "core.hooksPath=/dev/null", *args]
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


def git_status(submodule_path: str | None = None) -> types.CallToolResult:
    """Run git status.

    Args:
        submodule_path: Optional submodule path relative to workspace root
                        (e.g. 'cluster/agent').  If omitted, operates on
                        the root repository.
    """
    try:
        env, _git_dir, _work_tree = git_env_for(submodule_path=submodule_path)
        result = _run_git_env(env, "status", "--short")
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


def git_diff(staged: bool = False, submodule_path: str | None = None) -> types.CallToolResult:
    """Run git diff, optionally showing staged changes.

    Args:
        staged: If True, show staged (cached) changes.
        submodule_path: Optional submodule path relative to workspace root.
                        If omitted, operates on the root repository.
    """
    try:
        env, _git_dir, _work_tree = git_env_for(submodule_path=submodule_path)
        args = ["diff"]
        if staged:
            args.append("--cached")
        result = _run_git_env(env, *args)
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

    All paths must belong to the same repository (root or a single
    submodule).  If they span multiple repositories, an error is returned
    and no files are staged.
    """
    if not paths:
        return _err("No paths provided to git add")
    try:
        # Determine the owning repo for every path and verify they are all
        # in the same repository.
        git_dirs: set[str] = set()
        envs: list[tuple[dict, str, str]] = []
        for p in paths:
            env, git_dir, work_tree = git_env_for(file_path=p)
            git_dirs.add(git_dir)
            envs.append((env, git_dir, work_tree))

        if len(git_dirs) > 1:
            return _err(
                "Error: git_add paths span multiple repositories; "
                "stage each submodule separately."
            )

        env, git_dir, work_tree = envs[0]

        # When operating on a submodule the user-supplied paths are relative
        # to the workspace root.  Convert them to absolute paths so git
        # resolves them correctly regardless of the process CWD.
        root = os.path.normpath(GIT_WORK_TREE)
        wt = os.path.normpath(work_tree)
        if wt != root:
            abs_paths: list[str] = []
            for p in paths:
                if p == ".":
                    abs_paths.append(wt)
                else:
                    abs_paths.append(os.path.normpath(os.path.join(root, p)))
            paths_to_stage = abs_paths
        else:
            paths_to_stage = paths

        result = _run_git_env(env, "add", "--", *paths_to_stage)
        if result.returncode != 0:
            return _err(f"git add failed: {result.stderr.strip()}")
        return _ok(f"Staged: {', '.join(paths)}")
    except subprocess.TimeoutExpired:
        return _err("git add timed out")
    except Exception as e:
        return _err(f"git add error: {e}")


def git_commit(message: str, submodule_path: str | None = None) -> types.CallToolResult:
    """Create a commit with the given message.

    Args:
        message: Commit message (required, non-empty).
        submodule_path: Optional submodule path relative to workspace root.
                        If omitted, commits to the root repository.
    """
    if not message or not message.strip():
        return _err("Commit message must not be empty")
    try:
        env, _git_dir, _work_tree = git_env_for(submodule_path=submodule_path)
        result = _run_git_env(
            env,
            "commit",
            "-m", message.strip(),
            "--no-verify",  # Belt-and-suspenders: skip hooks even if hooksPath fails
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


def git_log(max_count: int = 10, submodule_path: str | None = None) -> types.CallToolResult:
    """Show recent commit log.

    Args:
        max_count: Number of commits to show (default 10, max 50).
        submodule_path: Optional submodule path relative to workspace root.
                        If omitted, shows log for the root repository.
    """
    max_count = min(max(1, max_count), 50)
    try:
        env, _git_dir, _work_tree = git_env_for(submodule_path=submodule_path)
        result = _run_git_env(
            env,
            "log",
            f"--max-count={max_count}",
            "--oneline",
            "--no-decorate",
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


def git_reset_soft(count: int = 1, submodule_path: str | None = None) -> types.CallToolResult:
    """Undo the last N commits, keeping changes staged.

    Enforces a baseline floor: cannot reset past the commit that existed
    when git_mcp.py started. The agent can only undo its own commits.

    Args:
        count: Number of commits to undo (default 1, max 5).
        submodule_path: Optional submodule path relative to workspace root.
                        If omitted, resets the root repository.
    """
    count = min(max(1, count), 5)

    try:
        env, _git_dir, _work_tree = git_env_for(submodule_path=submodule_path)

        # Select the correct baseline for the target repository.
        if submodule_path is not None:
            effective_key = os.path.normpath(submodule_path)
            baseline = SUBMODULE_BASELINE_COMMITS.get(effective_key)
        else:
            baseline = BASELINE_COMMIT

        if baseline is None:
            return _err("Cannot reset — no baseline commit (empty repo at startup)")

        # Resolve what HEAD~count points to
        target_result = _run_git_env(env, "rev-parse", f"HEAD~{count}")
        if target_result.returncode != 0:
            return _err(
                f"Cannot reset {count} commits — not enough history. "
                f"{target_result.stderr.strip()}"
            )
        target_commit = target_result.stdout.strip()

        # Enforce baseline floor: allow resetting TO the baseline but not past it.
        # If target equals baseline, that's fine — we're undoing only agent commits.
        # If target is a strict ancestor of baseline, we'd be erasing pre-existing history.
        if target_commit != baseline:
            # Check if target is an ancestor of baseline (i.e., older than baseline)
            ancestor_check = _run_git_env(
                env, "merge-base", "--is-ancestor", target_commit, baseline
            )
            if ancestor_check.returncode == 0:
                # target is strictly before baseline — block
                return _err(
                    f"Cannot reset {count} commits — would go past the baseline commit "
                    f"({baseline[:12]}). You can only undo commits created during "
                    f"this session."
                )

        # Safe to reset
        result = _run_git_env(env, "reset", "--soft", f"HEAD~{count}")
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
            "properties": {
                "submodule_path": {
                    "type": "string",
                    "description": (
                        "Optional submodule path relative to workspace root "
                        "(e.g. 'cluster/agent'). If omitted, operates on the root repository."
                    ),
                },
            },
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
                "submodule_path": {
                    "type": "string",
                    "description": (
                        "Optional submodule path relative to workspace root "
                        "(e.g. 'cluster/agent'). If omitted, operates on the root repository."
                    ),
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
                "submodule_path": {
                    "type": "string",
                    "description": (
                        "Optional submodule path relative to workspace root "
                        "(e.g. 'cluster/agent'). If omitted, commits to the root repository."
                    ),
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
                "submodule_path": {
                    "type": "string",
                    "description": (
                        "Optional submodule path relative to workspace root "
                        "(e.g. 'cluster/agent'). If omitted, shows log for the root repository."
                    ),
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
                "submodule_path": {
                    "type": "string",
                    "description": (
                        "Optional submodule path relative to workspace root "
                        "(e.g. 'cluster/agent'). If omitted, resets the root repository."
                    ),
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
            return git_status(
                submodule_path=arguments.get("submodule_path"),
            )
        case "git_diff":
            return git_diff(
                staged=arguments.get("staged", False),
                submodule_path=arguments.get("submodule_path"),
            )
        case "git_add":
            return git_add(paths=arguments.get("paths", []))
        case "git_commit":
            return git_commit(
                message=arguments.get("message", ""),
                submodule_path=arguments.get("submodule_path"),
            )
        case "git_log":
            return git_log(
                max_count=arguments.get("max_count", 10),
                submodule_path=arguments.get("submodule_path"),
            )
        case "git_reset_soft":
            return git_reset_soft(
                count=arguments.get("count", 1),
                submodule_path=arguments.get("submodule_path"),
            )
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
