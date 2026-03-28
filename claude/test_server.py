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
from server import _check_upstream_errors, _redact_secrets  # noqa: E402
import server as _server_module  # noqa: E402


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


class TestRedactSecrets:
    def test_known_token_is_redacted(self):
        """A token present in _SECRET_TOKENS is replaced with [REDACTED]."""
        # Use a token that matches what test.sh exports (CLAUDE_API_TOKEN=dummy-claude-token)
        token = _server_module._SECRET_TOKENS[0] if _server_module._SECRET_TOKENS else None
        if token is None:
            pytest.skip("No secret tokens configured")
        result = _redact_secrets(f"Bearer {token} is the key")
        assert token not in result
        assert "[REDACTED]" in result

    def test_multiple_tokens_all_redacted(self):
        """All known tokens in the same string are redacted."""
        tokens = _server_module._SECRET_TOKENS[:2]
        if len(tokens) < 2:
            pytest.skip("Need at least 2 secret tokens configured")
        text = f"key={tokens[0]} token={tokens[1]}"
        result = _redact_secrets(text)
        assert tokens[0] not in result
        assert tokens[1] not in result
        assert result.count("[REDACTED]") == 2

    def test_non_string_returned_unchanged(self):
        """Non-string input is returned as-is without error."""
        assert _redact_secrets(None) is None
        assert _redact_secrets(42) == 42

    def test_text_without_secrets_unchanged(self):
        """Text with no secret tokens is returned unchanged."""
        text = "No secrets here, just ordinary log output."
        assert _redact_secrets(text) == text

    def test_no_secret_re_returns_text(self, monkeypatch):
        """When _SECRET_RE is None (no tokens configured), text is returned as-is."""
        monkeypatch.setattr(_server_module, "_SECRET_RE", None)
        text = "some text"
        assert _redact_secrets(text) == text
