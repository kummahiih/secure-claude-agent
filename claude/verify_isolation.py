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