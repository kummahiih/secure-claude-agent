#!/bin/bash
set -e

# MCP config is baked into the image at build time:
#   /home/appuser/sandbox/.mcp.json (read-only, 440)
# Passed to Claude Code via --mcp-config flag in server.py
# No runtime registration needed — no dependency on claude mcp add internals

# Run isolation checks before serving traffic
python /app/verify_isolation.py claude-server || exit 1

exec python /app/server.py