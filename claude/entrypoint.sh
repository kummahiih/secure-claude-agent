#!/bin/bash
set -e

# MCP config is baked into the image at build time:
#   /home/appuser/sandbox/.mcp.json (read-only, 440)
# Passed to Claude Code via --mcp-config flag in server.py
# No runtime registration needed — no dependency on claude mcp add internals

# Run isolation checks before serving traffic
python /app/verify_isolation.py claude-server || exit 1

# Capture baseline commit ONCE at container startup.
# This is exported so all Claude Code subprocesses (and their MCP servers)
# inherit it. git_mcp.py uses this as the floor for git_reset_soft —
# the agent can only undo commits created after this point.
if [ -n "$GIT_DIR" ] && [ -n "$GIT_WORK_TREE" ]; then
    BASELINE=$(git -c core.hooksPath=/dev/null rev-parse HEAD 2>/dev/null || echo "")
    if [ -n "$BASELINE" ]; then
        export GIT_BASELINE_COMMIT="$BASELINE"
        echo "Baseline commit: $BASELINE"
    else
        echo "No baseline commit (empty repo)"
    fi
fi

exec python /app/server.py