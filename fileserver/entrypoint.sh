#!/bin/sh
set -e
# mcp-server isolation checks
for var in ANTHROPIC_API_KEY CLAUDE_API_TOKEN DYNAMIC_AGENT_KEY; do
  eval val=\$$var 2>/dev/null || val=""
  if [ -n "$val" ]; then
    echo "FATAL: $var present in mcp-server" >&2; exit 1
  fi
done
if [ -z "$MCP_API_TOKEN" ]; then
  echo "FATAL: MCP_API_TOKEN missing" >&2; exit 1
fi
if find /workspace -name '*.env' 2>/dev/null | grep -q .; then
  echo "FATAL: .env file found in /workspace" >&2; exit 1
fi
exec /app/mcp-server "$@"