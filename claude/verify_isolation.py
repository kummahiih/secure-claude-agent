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
    "proxy": [
        # Proxy SHOULD have ANTHROPIC_API_KEY. No forbidden env vars.
    ],
}

# These env vars MUST be present for the container to function correctly.
REQUIRED_ENV_VARS = {
    "claude-server": [
        "DYNAMIC_AGENT_KEY",      # Ephemeral key, renamed to ANTHROPIC_API_KEY in subprocess
        "MCP_API_TOKEN",          # For authenticating to mcp-server
        "CLAUDE_API_TOKEN",       # For ingress auth via Caddy
        "ANTHROPIC_BASE_URL",     # Points to proxy:4000
    ],
    "mcp-server": [
        "MCP_API_TOKEN",
    ],
    "proxy": [
        "ANTHROPIC_API_KEY",
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
        # Proxy doesn't mount /workspace at all
    ],
}

# Files/dirs that MUST exist — sanity check that mounts and copies are correct.
REQUIRED_PATHS = {
    "claude-server": [
        "/app/server.py",
        "/app/files_mcp.py",
        "/app/verify_isolation.py",
        "/home/appuser/sandbox/.mcp.json",  # MCP config baked into image
    ],
    "mcp-server": [
        "/workspace",
    ],
    "proxy": [],
}

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
    return count


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <role>", file=sys.stderr)
        print(f"  Roles: {list(FORBIDDEN_ENV_VARS.keys())}", file=sys.stderr)
        sys.exit(1)
    verify_all(sys.argv[1])
