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
from server import _check_upstream_errors, _redact_secrets, _expand_slash_command  # noqa: E402
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


class TestExpandSlashCommand:
    def test_non_slash_query_unchanged(self):
        """Queries not starting with '/' are returned unchanged."""
        assert _expand_slash_command("hello world") == "hello world"
        assert _expand_slash_command("") == ""

    def test_path_traversal_stripped_by_basename(self):
        """../../etc/passwd → basename → 'passwd'; no .md file exists, returns original."""
        query = "/../../etc/passwd"
        assert _expand_slash_command(query) == query

    def test_double_dot_name_rejected(self):
        """/.. → basename → '..' → caught by PATH_BLACKLIST, returns original."""
        query = "/.."
        assert _expand_slash_command(query) == query

    def test_deeply_nested_traversal_rejected_or_stripped(self):
        """Deeply nested traversal path is defanged: basename yields leaf component."""
        # /../../../../etc/shadow → basename → 'shadow'; no file, returns original
        query = "/../../../../etc/shadow"
        result = _expand_slash_command(query)
        # Either rejected or file not found — must not expand to unexpected content
        assert result == query

    def test_blacklisted_chars_rejected(self):
        """Names containing blacklisted shell metacharacters are rejected."""
        for char in [";", "|", "&", "$", "`", "!", "~", "\n", "\r", "\t"]:
            query = f"/cmd{char}inject"
            assert _expand_slash_command(query) == query, (
                f"Expected rejection for blacklisted char {char!r}"
            )

    def test_null_byte_in_name_rejected(self):
        """Names containing a null byte are rejected."""
        query = "/cmd\x00evil"
        assert _expand_slash_command(query) == query

    def test_empty_name_after_slash_rejected(self):
        """A lone '/' with whitespace only after it is handled gracefully."""
        assert _expand_slash_command("/ ") == "/ "

    def test_valid_command_not_found_returns_original(self):
        """A clean command name with no matching .md file returns the original query."""
        query = "/nonexistent-command-xyzzy"
        assert _expand_slash_command(query) == query

    def test_valid_command_expands_file_contents(self, tmp_path, monkeypatch):
        """A valid command name whose .md file exists returns the file contents."""
        monkeypatch.setattr(_server_module, "COMMANDS_DIR", str(tmp_path))
        (tmp_path / "my-cmd.md").write_text("do the thing")
        assert _expand_slash_command("/my-cmd") == "do the thing"

    def test_command_with_trailing_args_uses_first_token(self, tmp_path, monkeypatch):
        """Only the first token after '/' is used as the command name."""
        monkeypatch.setattr(_server_module, "COMMANDS_DIR", str(tmp_path))
        (tmp_path / "cmd.md").write_text("expanded content")
        assert _expand_slash_command("/cmd extra args here") == "expanded content"

    def test_basename_cannot_escape_commands_dir(self, tmp_path, monkeypatch):
        """Even if basename yields a valid filename, traversal outside COMMANDS_DIR is prevented."""
        monkeypatch.setattr(_server_module, "COMMANDS_DIR", str(tmp_path))
        # Create a file one level above COMMANDS_DIR with .md extension
        parent = tmp_path.parent
        (parent / "secret.md").write_text("secret content")
        # Query with traversal: basename strips the ../ so name becomes 'secret'
        # but the join will target tmp_path/secret.md, not parent/secret.md
        query = "/../secret"
        result = _expand_slash_command(query)
        # File does not exist at COMMANDS_DIR/secret.md → returns original
        assert result == query
