#!/bin/bash
set -euo pipefail

echo "[unit] Running Go fileserver tests..."
(cd fileserver && go test mcp_test.go main.go -v 2>&1 | grep -E '(PASS|FAIL|---)')

echo "[unit] Running Python claude tests..."
(cd claude && python -m pytest claude_tests.py files_mcp_test.py test_isolation.py git_mcp_test.py tester_mcp_test.py -v --tb=short 2>&1 | grep -E '(PASSED|FAILED|ERROR|test_|===)')