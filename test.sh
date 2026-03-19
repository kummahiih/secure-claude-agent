#!/bin/bash
set -euo pipefail

# Dummy tokens for unit tests — no real services are contacted
export MCP_API_TOKEN="${MCP_API_TOKEN:-dummy-mcp-token}"
export MCP_SERVER_URL="${MCP_SERVER_URL:-https://mcp-server:8443}"
export TESTER_SERVER_URL="${TESTER_SERVER_URL:-https://tester-server:8443}"
export PLAN_SERVER_URL="${PLAN_SERVER_URL:-https://plan-server:8443}"
export CLAUDE_API_TOKEN="${CLAUDE_API_TOKEN:-dummy-claude-token}"
export DYNAMIC_AGENT_KEY="${DYNAMIC_AGENT_KEY:-dummy-agent-key}"
export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-https://proxy:4000}"

echo "[unit] Running Go fileserver tests..."
(cd fileserver && go test mcp_test.go main.go -v 2>&1 | grep -E '(PASS|FAIL|---)')

echo "[unit] Running Python claude tests..."
(cd claude && python -m pytest claude_tests.py files_mcp_test.py test_isolation.py git_mcp_test.py tester_mcp_test.py -v --tb=short 2>&1 | grep -E '(PASSED|FAILED|ERROR|test_|===)')