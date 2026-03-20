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
    SYSTEM_PROMPT="test system prompt",
    PLAN_SYSTEM_PROMPT="test plan system prompt",
)
sys.modules["verify_isolation"] = MagicMock()

# Add the claude server directory to the path so we can import server.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cluster", "agent", "claude"))

from fastapi import HTTPException  # noqa: E402
from server import _check_upstream_auth_error  # noqa: E402


class TestCheckUpstreamAuthError:
    def test_auth_error_oauth_marker(self):
        """Raises HTTPException 502 when text contains 'OAuth token has expired'."""
        with pytest.raises(HTTPException) as exc_info:
            _check_upstream_auth_error(
                "Error: OAuth token has expired, please re-authenticate."
            )
        assert exc_info.value.status_code == 502

    def test_auth_error_authentication_error_marker(self):
        """Raises HTTPException 502 when text contains 'authentication_error'."""
        with pytest.raises(HTTPException) as exc_info:
            _check_upstream_auth_error(
                "Upstream returned authentication_error: invalid API key."
            )
        assert exc_info.value.status_code == 502

    def test_auth_error_no_marker(self):
        """Returns None and does not raise when text has no auth error markers."""
        result = _check_upstream_auth_error("Everything is working fine, no issues here.")
        assert result is None
