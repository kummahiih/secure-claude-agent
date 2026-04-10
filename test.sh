#!/bin/bash
set -euo pipefail

# Dummy tokens for unit tests — no real services are contacted
export MCP_API_TOKEN="${MCP_API_TOKEN:-dummy-mcp-token}"
export PLAN_API_TOKEN="${PLAN_API_TOKEN:-dummy-plan-token}"
export TESTER_API_TOKEN="${TESTER_API_TOKEN:-dummy-tester-token}"
export MCP_SERVER_URL="${MCP_SERVER_URL:-https://mcp-server:8443}"
export TESTER_SERVER_URL="${TESTER_SERVER_URL:-https://tester-server:8443}"
export PLAN_SERVER_URL="${PLAN_SERVER_URL:-https://plan-server:8443}"
export CLAUDE_API_TOKEN="${CLAUDE_API_TOKEN:-dummy-claude-token}"
export DYNAMIC_AGENT_KEY="${DYNAMIC_AGENT_KEY:-dummy-agent-key}"
export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-https://proxy:4000}"
export GIT_API_TOKEN="${GIT_API_TOKEN:-dummy-git-token}"
export GIT_SERVER_URL="${GIT_SERVER_URL:-https://git-server:8443}"
export LOG_API_TOKEN="${LOG_API_TOKEN:-dummy-log-token}"
export LOG_SERVER_URL="${LOG_SERVER_URL:-https://log-server:8443}"

echo "[unit] Running Go log-server tests..."
(cd ../log-server && GOTOOLCHAIN=local CGO_ENABLED=0 GOMAXPROCS=1 go test -p 1 -cpu 1 ./... -v 2>&1 | grep -E '(PASS|FAIL|ok|---)')

echo "[unit] Running Go fileserver tests..."
(cd fileserver && GOTOOLCHAIN=local CGO_ENABLED=0 GOMAXPROCS=1 go test -p 1 -cpu 1 mcp_test.go main.go -v)

echo "[unit] Running Go gitserver tests..."
(cd gitserver && GOTOOLCHAIN=local CGO_ENABLED=0 GOMAXPROCS=1 go test -p 1 -cpu 1 main_test.go main.go -v)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PROMPT_SYSTEM_DIR="${SCRIPT_DIR}/prompts/system"
export PROMPT_COMMANDS_DIR="${SCRIPT_DIR}/prompts/commands"

echo "[unit] Running Python MCP tests..."
(cd mcp && python -m pytest files_mcp_test.py git_mcp_test.py tester_mcp_test.py log_mcp_test.py log_emit_test.py -v --tb=short 2>&1 | grep -E '(PASSED|FAILED|ERROR|test_|===)')

echo "[unit] Running Python claude tests..."
(cd claude && python -m pytest claude_tests.py test_isolation.py test_server.py -v --tb=short 2>&1 | grep -E '(PASSED|FAILED|ERROR|test_|===)')