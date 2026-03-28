"""
verify_isolation.py — Runtime isolation checks for secure-claude containers.

Call verify_all() at daemon startup. It fails hard (sys.exit(1)) if any
structural security invariant is violated.

IMPORTANT: This must only run at the entrypoint/daemon level, NEVER inside
MCP subprocess children (e.g., files_mcp.py). Claude Code passes
ANTHROPIC_API_KEY to its child processes, which would false-positive
the forbidden env var check.

Each container role has its own check profile:
- claude-server: must not see real API key, must not see parent repo artifacts
- proxy: must see real API key, must not see workspace or agent code
- mcp-server: must not see real API key, must not see parent repo artifacts

Usage in daemon startup (entrypoint.sh or top of server.py):
    from verify_isolation import verify_all
    verify_all(role="claude-server")

DO NOT call from: files_mcp.py, git_mcp.py, or any MCP stdio server.
"""

import os
import sys
import logging

logger = logging.getLogger("verify_isolation")


# --- Env var checks ---

# These env vars must NEVER appear in the container at entrypoint time.
# If they do, credential isolation has failed.
# Note: ANTHROPIC_API_KEY will later be injected into the Claude Code
# subprocess scope by server.py — but at entrypoint time it must not exist.
FORBIDDEN_ENV_VARS = {
    "claude-server": [
        "ANTHROPIC_API_KEY",  # Real key — only proxy should have this
    ],
    "mcp-server": [
        "ANTHROPIC_API_KEY",
    ],
    "plan-server": [
        "ANTHROPIC_API_KEY",
        "MCP_API_TOKEN",          # mcp-server token must not reach plan-server
        "TESTER_API_TOKEN",       # tester-server token must not reach plan-server
    ],
    "tester-server": [
        "ANTHROPIC_API_KEY",
        "MCP_API_TOKEN",          # mcp-server token must not reach tester-server
        "PLAN_API_TOKEN",         # plan-server token must not reach tester-server
    ],
    "proxy": [
        "MCP_API_TOKEN",          # Internal MCP auth, not for proxy
        "PLAN_API_TOKEN",         # Internal plan auth, not for proxy
        "TESTER_API_TOKEN",       # Internal tester auth, not for proxy
        "CLAUDE_API_TOKEN",       # Ingress auth, not for proxy
    ],
    "caddy": [
        "ANTHROPIC_API_KEY",      # Real key, not for caddy
        "DYNAMIC_AGENT_KEY",      # Agent-side token, not for caddy
        "MCP_API_TOKEN",          # Internal MCP auth, not for caddy
        "PLAN_API_TOKEN",         # Internal plan auth, not for caddy
        "TESTER_API_TOKEN",       # Internal tester auth, not for caddy
        "CLAUDE_API_TOKEN",       # Ingress auth handled via Caddyfile, not env
        "AGENT_API_TOKEN",        # Auth is handled by claude-server, not Caddy
    ],
}

# These env vars MUST be present for the container to function correctly.
REQUIRED_ENV_VARS = {
    "claude-server": [
        "DYNAMIC_AGENT_KEY",      # Ephemeral key, renamed to ANTHROPIC_API_KEY in subprocess
        "MCP_API_TOKEN",          # For authenticating to mcp-server
        "PLAN_API_TOKEN",         # For authenticating to plan-server
        "TESTER_API_TOKEN",       # For authenticating to tester-server
        "CLAUDE_API_TOKEN",       # For ingress auth via Caddy
        "ANTHROPIC_BASE_URL",     # Points to proxy:4000
    ],
    "mcp-server": [
        "MCP_API_TOKEN",
    ],
    "plan-server": [
        "PLAN_API_TOKEN",
    ],
    "tester-server": [
        "TESTER_API_TOKEN",
    ],
    "proxy": [
        "ANTHROPIC_API_KEY",      # Real key for upstream
        "DYNAMIC_AGENT_KEY",      # Virtual key validation
    ],
    "caddy": [
    ],
}


# --- Filesystem checks ---

# Files/dirs that must NOT exist in the container image or at runtime.
# Presence means secrets or parent repo artifacts leaked into the image.
FORBIDDEN_PATHS = {
    "claude-server": [
        "/app/.secrets.env",
        "/app/.cluster_tokens.env",
        "/app/docker-compose.yml",
        "/app/proxy_config.yaml",
        "/app/Caddyfile",
        "/workspace/.secrets.env",
        "/workspace/.cluster_tokens.env",
        "/workspace/docker-compose.yml",
        "/workspace/proxy_config.yaml",
        "/workspace/Caddyfile",
        "/workspace/Dockerfile.claude",
        "/workspace/Dockerfile.mcp",
        "/workspace/Dockerfile.proxy",
        "/workspace/Dockerfile.caddy",
        "/workspace/certs",
    ],
    "mcp-server": [
        "/workspace/.secrets.env",
        "/workspace/.cluster_tokens.env",
        "/workspace/docker-compose.yml",
        "/workspace/proxy_config.yaml",
        "/workspace/Dockerfile.claude",
        "/workspace/Dockerfile.mcp",
        "/workspace/Dockerfile.proxy",
        "/workspace/Dockerfile.caddy",
        "/workspace/certs",
    ],
    "proxy": [
        # Proxy must not have agent code or workspace
        "/app/server.py",
        "/app/files_mcp.py",
        "/workspace",
    ],
    "caddy": [
        # Caddy must not have agent code, proxy config, or workspace
        "/app",
        "/workspace",
    ],
}

# Files/dirs that MUST exist — sanity check that mounts and copies are correct.
REQUIRED_PATHS = {
    "claude-server": [
        "/app/server.py",
        "/app/files_mcp.py",
        "/app/verify_isolation.py",
        "/app/prompts",                        # System prompts (root-owned, read-only)
        "/home/appuser/.claude/commands",       # Slash commands (root-owned, read-only)
        "/home/appuser/sandbox/.mcp.json",  # MCP config baked into image
    ],
    "mcp-server": [
        "/workspace",
    ],
    "proxy": [
        "/app/certs/proxy.crt",
        "/app/certs/proxy.key",
    ],
    "caddy": [
        "/etc/caddy/certs/caddy.crt",
        "/etc/caddy/certs/caddy.key",
        "/etc/caddy/certs/ca.crt",
    ],
    "plan-server": [
        "/app",
    ],
    "tester-server": [
        "/app",
    ],
}

# /workspace must contain ONLY these top-level entries in mcp-server.

# /workspace must contain ONLY these top-level entries in mcp-server.
# Anything else means parent repo content leaked through the mount.
# Note: claude-server doesn't mount /workspace, so this only applies to mcp-server.
WORKSPACE_ALLOWED_ENTRIES = {"claude", "fileserver", ".git", ".gitignore", "README.md", "LICENSE"}


# --- .env file scanner ---

def find_env_files(search_roots: list[str]) -> list[str]:
    """Walk search_roots and return paths to any .env files found."""
    found = []
    for root_dir in search_roots:
        if not os.path.isdir(root_dir):
            continue
        for dirpath, _dirnames, filenames in os.walk(root_dir):
            for f in filenames:
                if f.endswith(".env") or f == ".env":
                    found.append(os.path.join(dirpath, f))
    return found


# Directories to scan for .env files per role.
ENV_FILE_SCAN_DIRS = {
    "claude-server": ["/app", "/home/appuser"],
    "mcp-server": ["/workspace", "/app"],
    "proxy": ["/app"],
    "caddy": ["/etc/caddy"],
}


# --- Parent .git leak check ---

def check_git_no_parent_leak(workspace: str = "/workspace") -> list[str]:
    """
    Verify that .git inside /workspace does not reference the parent repo.

    In a proper submodule mount, .git should either be:
    - A directory (detached submodule clone), OR
    - A file pointing to a .git dir within the same mount

    It must NOT be a gitfile pointing outside /workspace (e.g., ../.git/modules/...).
    """
    errors = []
    git_path = os.path.join(workspace, ".git")

    if not os.path.exists(git_path):
        # No .git at all — might be fine depending on setup
        return errors

    if os.path.isfile(git_path):
        # It's a gitfile — read it and check the target
        try:
            content = open(git_path).read().strip()
            if content.startswith("gitdir:"):
                target = content.split("gitdir:", 1)[1].strip()
                # Resolve relative to workspace
                resolved = os.path.normpath(os.path.join(workspace, target))
                if not resolved.startswith(workspace):
                    errors.append(
                        f".git gitfile points outside workspace: {target} -> {resolved}"
                    )
        except OSError as e:
            errors.append(f"Cannot read .git file: {e}")

    return errors


# --- MCP config validation ---

def check_mcp_config(config_path: str) -> list[str]:
    """Verify MCP config file exists and has valid structure."""
    import json
    errors = []
    if not os.path.exists(config_path):
        errors.append(f"MCP config missing: {config_path}")
        return errors
    try:
        with open(config_path) as f:
            config = json.load(f)
        if "mcpServers" not in config:
            errors.append(f"MCP config missing 'mcpServers' key: {config_path}")
        elif "fileserver" not in config["mcpServers"]:
            errors.append(f"MCP config missing 'fileserver' entry: {config_path}")
    except (json.JSONDecodeError, OSError) as e:
        errors.append(f"MCP config invalid: {config_path}: {e}")
    return errors

PROMPT_DIRS_DEFAULT = ["/app/prompts", "/home/appuser/.claude/commands"]


def check_prompt_immutability(prompt_dirs: list[str] | None = None) -> list[str]:
    """
    Verify prompt files and their directories are read-only and root-owned.

    Both the system prompts dir and slash commands dir must be:
    - Owned by root (UID 0) — prevents appuser from deleting/creating entries
    - Not writable by owner — prevents modification even if ownership check
      is somehow bypassed

    This blocks the agent from modifying its own system prompts or injecting
    new slash commands at runtime.

    Args:
        prompt_dirs: Directories to check. Defaults to PROMPT_DIRS_DEFAULT
                     (Docker paths). Tests pass custom temp directories.
    """
    import stat

    if prompt_dirs is None:
        prompt_dirs = PROMPT_DIRS_DEFAULT

    errors = []

    for dirpath in prompt_dirs:
        if not os.path.isdir(dirpath):
            errors.append(f"Prompt directory missing: {dirpath}")
            continue

        # Check directory ownership and permissions
        st = os.stat(dirpath)
        if st.st_uid != 0:
            errors.append(f"Prompt directory not owned by root: {dirpath} (uid={st.st_uid})")
        if st.st_mode & stat.S_IWUSR:
            errors.append(f"Prompt directory is writable: {dirpath}")
        if st.st_mode & stat.S_IWGRP:
            errors.append(f"Prompt directory is group-writable: {dirpath}")
        if st.st_mode & stat.S_IWOTH:
            errors.append(f"Prompt directory is world-writable: {dirpath}")

        # Check each file inside
        for name in os.listdir(dirpath):
            fpath = os.path.join(dirpath, name)
            if not os.path.isfile(fpath):
                continue
            fst = os.stat(fpath)
            if fst.st_uid != 0:
                errors.append(f"Prompt file not owned by root: {fpath} (uid={fst.st_uid})")
            if fst.st_mode & stat.S_IWUSR:
                errors.append(f"Prompt file is writable: {fpath}")

    return errors

# --- Main verification ---

def verify_all(role: str) -> None:
    """
    Run all isolation checks for the given container role.
    Logs every violation, then exits non-zero if any were found.
    """
    if role not in FORBIDDEN_ENV_VARS:
        logger.error(f"Unknown role: {role!r}. Expected one of: {list(FORBIDDEN_ENV_VARS.keys())}")
        sys.exit(1)

    violations = []

    # 1. Forbidden env vars
    for var in FORBIDDEN_ENV_VARS.get(role, []):
        if var in os.environ:
            violations.append(f"FORBIDDEN env var present: {var}")

    # 2. Required env vars
    for var in REQUIRED_ENV_VARS.get(role, []):
        if var not in os.environ:
            violations.append(f"REQUIRED env var missing: {var}")

    # 3. Forbidden paths
    for path in FORBIDDEN_PATHS.get(role, []):
        if os.path.exists(path):
            violations.append(f"FORBIDDEN path exists: {path}")

    # 4. Required paths
    for path in REQUIRED_PATHS.get(role, []):
        if not os.path.exists(path):
            violations.append(f"REQUIRED path missing: {path}")

    # 5. .env file scan
    scan_dirs = ENV_FILE_SCAN_DIRS.get(role, [])
    env_files = find_env_files(scan_dirs)
    for ef in env_files:
        violations.append(f".env file found: {ef}")

    # 6. Workspace entry whitelist (mcp-server only — claude-server doesn't mount /workspace)
    if role == "mcp-server" and os.path.isdir("/workspace"):
        entries = set(os.listdir("/workspace"))
        unexpected = entries - WORKSPACE_ALLOWED_ENTRIES
        if unexpected:
            violations.append(
                f"/workspace contains unexpected entries: {sorted(unexpected)}"
            )

    # 7. .git parent leak check (mcp-server only)
    if role == "mcp-server":
        git_errors = check_git_no_parent_leak("/workspace")
        violations.extend(git_errors)

    # 8. MCP config validation (claude-server only)
    if role == "claude-server":
        mcp_errors = check_mcp_config("/home/appuser/sandbox/.mcp.json")
        violations.extend(mcp_errors)

    # 9. Prompt immutability (claude-server only)
    #    System prompts and slash commands must be root-owned and read-only
    #    to prevent the agent from modifying its own instructions at runtime.
    if role == "claude-server":
        prompt_errors = check_prompt_immutability()
        violations.extend(prompt_errors)

    # Report
    if violations:
        logger.error(f"=== ISOLATION CHECK FAILED for role={role} ===")
        for v in violations:
            logger.error(f"  ✗ {v}")
        logger.error(f"=== {len(violations)} violation(s) — refusing to start ===")
        sys.exit(1)
    else:
        logger.info(f"Isolation checks passed for role={role} ({_count_checks(role)} checks)")


def _count_checks(role: str) -> int:
    """Count total number of checks performed for a role."""
    count = 0
    count += len(FORBIDDEN_ENV_VARS.get(role, []))
    count += len(REQUIRED_ENV_VARS.get(role, []))
    count += len(FORBIDDEN_PATHS.get(role, []))
    count += len(REQUIRED_PATHS.get(role, []))
    count += 1  # .env file scan
    if role == "mcp-server":
        count += 1  # workspace entry whitelist
        count += 1  # .git leak check
    if role == "claude-server":
        count += 1  # MCP config validation
        count += 1  # Prompt immutability
    return count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <role>", file=sys.stderr)
        print(f"  Roles: {list(FORBIDDEN_ENV_VARS.keys())}", file=sys.stderr)
        sys.exit(1)
    verify_all(sys.argv[1])