import os
import sys
import pytest
from unittest.mock import MagicMock

# Mock out modules that require runtime environment / side-effects before importing server
sys.modules.setdefault("setuplogging", MagicMock())
sys.modules["runenv"] = MagicMock(
    CLAUDE_API_TOKEN="dummy-token",
    DYNAMIC_AGENT_KEY="dummy-key",
    ANTHROPIC_BASE_URL="https://api.anthropic.com",
    MCP_API_TOKEN="dummy-mcp-token",
    PLAN_API_TOKEN="dummy-plan-token",
    TESTER_API_TOKEN="dummy-tester-token",
    SYSTEM_PROMPT="test system prompt",
    PLAN_SYSTEM_PROMPT="test plan system prompt",
)
sys.modules["verify_isolation"] = MagicMock()

# server.py lives in the same directory as this test file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import HTTPException  # noqa: E402
from server import _check_upstream_errors  # noqa: E402


class TestCheckUpstreamAuthError:
    def test_auth_error_oauth_marker(self):
        """Raises HTTPException 502 when text contains 'OAuth token has expired'."""
        with pytest.raises(HTTPException) as exc_info:
            _check_upstream_errors(
                "Error: OAuth token has expired, please re-authenticate."
            )
        assert exc_info.value.status_code == 502

    def test_auth_error_authentication_error_marker(self):
        """Raises HTTPException 502 when text contains 'authentication_error'."""
        with pytest.raises(HTTPException) as exc_info:
            _check_upstream_errors(
                "Upstream returned authentication_error: invalid API key."
            )
        assert exc_info.value.status_code == 502

    def test_auth_error_no_marker(self):
        """Returns None and does not raise when text has no auth error markers."""
        result = _check_upstream_errors("Everything is working fine, no issues here.")
        assert result is None
