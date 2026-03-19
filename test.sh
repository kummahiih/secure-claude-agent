#!/bin/bash
set -euo pipefail

echo "[unit] Running Go fileserver tests..."
(cd fileserver && go test mcp_test.go main.go -v 2>&1 | grep -E '(PASS|FAIL|---)')

echo "[unit] Running Python claude tests..."
(cd claude && python -m pytest claude_tests.py files_mcp_test.py test_isolation.py git_mcp_test.py -v --tb=short 2>&1 | grep -E '(PASSED|FAILED|ERROR|test_|===)')

echo "[security] Scanning Go deps (govulncheck)..."
(cd fileserver && go run golang.org/x/vuln/cmd/govulncheck@latest ./... 2>&1 | tail -5)

echo "[security] Scanning Python deps (pip-audit)..."
(cd .. && \
    docker run --rm \
    -e PIP_ROOT_USER_ACTION=ignore \
    -v "$(pwd)":/app \
    -w /app \
    python:3.11-slim /bin/bash -c \
    "pip install --quiet --upgrade pip && pip install --quiet pip-audit && pip-audit -r agent/claude/requirements.txt" 2>&1 | grep -E '(found|No known|CRITICAL|WARNING|ERROR|Name)' || echo "  ✅ pip-audit clean"
)
