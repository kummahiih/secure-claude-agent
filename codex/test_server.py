import json
import os
import sys
import pytest
from unittest.mock import MagicMock, patch

# Mock out modules that require runtime environment / side-effects before importing server
sys.modules.setdefault("setuplogging", MagicMock())
sys.modules["runenv"] = MagicMock(
    CODEX_API_TOKEN="dummy-token",
    DYNAMIC_AGENT_KEY="dummy-key",
    OPENAI_BASE_URL="https://api.openai.com",
    MCP_API_TOKEN="dummy-mcp-token",
    PLAN_API_TOKEN="dummy-plan-token",
    PLAN_SERVER_URL="https://plan-server:8443",
    TESTER_API_TOKEN="dummy-tester-token",
    GIT_API_TOKEN="dummy-git-token",
    LOG_SERVER_URL="https://log-server:8443",
    LOG_API_TOKEN="dummy-log-token",
    SYSTEM_PROMPT="test system prompt",
    PLAN_SYSTEM_PROMPT="test plan system prompt",
    ADHOC_SYSTEM_PROMPT="test adhoc system prompt",
)
sys.modules["verify_isolation"] = MagicMock()

# server.py lives in the same directory as this test file
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import HTTPException  # noqa: E402
from server import _check_upstream_errors, _redact_secrets, _expand_slash_command  # noqa: E402
import server as _server_module  # noqa: E402


def _mock_popen(stdout="", stderr="", returncode=0):
    """Create a MagicMock that behaves like subprocess.Popen."""
    proc = MagicMock()
    proc.communicate.return_value = (stdout, stderr)
    proc.returncode = returncode
    proc.kill = MagicMock()
    return proc


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

    def test_git_api_token_is_redacted(self):
        """GIT_API_TOKEN value is in _SECRET_TOKENS and is redacted from output."""
        assert "dummy-git-token" in _server_module._SECRET_TOKENS
        result = _redact_secrets("leaked dummy-git-token here")
        assert "dummy-git-token" not in result
        assert "[REDACTED]" in result

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
        """../../etc/passwd -> basename -> 'passwd'; no .md file exists, returns original."""
        query = "/../../etc/passwd"
        assert _expand_slash_command(query) == query

    def test_double_dot_name_rejected(self):
        """/.. -> basename -> '..' -> caught by PATH_BLACKLIST, returns original."""
        query = "/.."
        assert _expand_slash_command(query) == query

    def test_deeply_nested_traversal_rejected_or_stripped(self):
        """Deeply nested traversal path is defanged: basename yields leaf component."""
        query = "/../../../../etc/shadow"
        result = _expand_slash_command(query)
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
        parent = tmp_path.parent
        (parent / "secret.md").write_text("secret content")
        query = "/../secret"
        result = _expand_slash_command(query)
        assert result == query


class TestQueryRequestValidation:
    def test_normal_query_and_model_accepted(self):
        from server import QueryRequest
        req = QueryRequest(query="hello", model="gpt-4o")
        assert req.query == "hello"
        assert req.model == "gpt-4o"

    def test_query_at_max_length_accepted(self):
        from pydantic import ValidationError
        from server import QueryRequest
        req = QueryRequest(query="a" * 100_000, model="m")
        assert len(req.query) == 100_000

    def test_query_over_max_length_rejected(self):
        from pydantic import ValidationError
        from server import QueryRequest
        with pytest.raises(ValidationError):
            QueryRequest(query="a" * 100_001, model="m")

    def test_model_at_max_length_accepted(self):
        from server import QueryRequest
        req = QueryRequest(query="q", model="m" * 200)
        assert len(req.model) == 200

    def test_model_over_max_length_rejected(self):
        from pydantic import ValidationError
        from server import QueryRequest
        with pytest.raises(ValidationError):
            QueryRequest(query="q", model="m" * 201)


class TestLogEmission:
    def test_emit_log_event_returns_early_when_no_url(self, monkeypatch):
        """_emit_log_event is a no-op when LOG_SERVER_URL is empty."""
        monkeypatch.setattr(_server_module, "LOG_SERVER_URL", "")
        with patch("server.requests.post") as mock_post:
            _server_module._emit_log_event({"event_type": "llm_call", "session_id": "s1"})
        mock_post.assert_not_called()

    def test_emit_log_event_returns_early_when_no_token(self, monkeypatch):
        """_emit_log_event is a no-op when LOG_API_TOKEN is empty."""
        monkeypatch.setattr(_server_module, "LOG_SERVER_URL", "https://log-server:8443")
        monkeypatch.setattr(_server_module, "LOG_API_TOKEN", "")
        with patch("server.requests.post") as mock_post:
            _server_module._emit_log_event({"event_type": "llm_call", "session_id": "s1"})
        mock_post.assert_not_called()

    def test_emit_log_event_post_failure_is_non_fatal(self, monkeypatch):
        """_emit_log_event logs a warning and does not raise when POST fails."""
        monkeypatch.setattr(_server_module, "LOG_SERVER_URL", "https://log-server:8443")
        monkeypatch.setattr(_server_module, "LOG_API_TOKEN", "dummy-log-token")
        with patch("server.requests.post", side_effect=Exception("connection refused")):
            _server_module._emit_log_event({"event_type": "llm_call", "session_id": "s1"})

    def test_emit_log_event_posts_with_auth_header(self, monkeypatch):
        """_emit_log_event sends Authorization: Bearer header with LOG_API_TOKEN."""
        monkeypatch.setattr(_server_module, "LOG_SERVER_URL", "https://log-server:8443")
        monkeypatch.setattr(_server_module, "LOG_API_TOKEN", "dummy-log-token")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("server.requests.post", return_value=mock_resp) as mock_post:
            _server_module._emit_log_event({"event_type": "llm_call", "session_id": "s1"})
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer dummy-log-token"


class TestParseCodexOutput:
    def test_returns_empty_usages_and_stripped_text(self):
        """_parse_codex_output returns ([], stripped_text)."""
        turn_usages, text = _server_module._parse_codex_output("  hello world  \n")
        assert turn_usages == []
        assert text == "hello world"

    def test_empty_stdout(self):
        """Empty stdout returns ([], '')."""
        turn_usages, text = _server_module._parse_codex_output("")
        assert turn_usages == []
        assert text == ""

    def test_multiline_output(self):
        """Multi-line output is stripped but otherwise preserved."""
        stdout = "  line one\nline two\n  "
        turn_usages, text = _server_module._parse_codex_output(stdout)
        assert turn_usages == []
        assert text == "line one\nline two"


class TestLogLlmTurns:
    def test_emits_per_turn_events(self, monkeypatch):
        """_log_llm_turns emits one event per turn with correct turn_number."""
        captured = []
        monkeypatch.setattr(_server_module, "_emit_log_event", captured.append)

        turn_usages = [
            {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
            {"input_tokens": 20, "output_tokens": 8, "cache_read_input_tokens": 1, "cache_creation_input_tokens": 0},
            {"input_tokens": 30, "output_tokens": 12, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 2},
        ]
        _server_module._log_llm_turns("sess-t1", "gpt-4o", turn_usages, 9000)

        import time; time.sleep(0.05)
        assert len(captured) == 3
        assert captured[0]["turn_number"] == 1
        assert captured[1]["turn_number"] == 2
        assert captured[2]["turn_number"] == 3
        assert captured[0]["event_type"] == "llm_call"
        assert captured[0]["model"] == "gpt-4o"
        assert captured[0]["session_id"] == "sess-t1"
        # duration_ms only on last turn
        assert captured[0]["duration_ms"] == 0
        assert captured[1]["duration_ms"] == 0
        assert captured[2]["duration_ms"] == 9000

    def test_includes_cache_creation_tokens(self, monkeypatch):
        """_log_llm_turns includes cache_creation_tokens in emitted events."""
        captured = []
        monkeypatch.setattr(_server_module, "_emit_log_event", captured.append)

        turn_usages = [
            {"input_tokens": 5, "output_tokens": 3, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 42},
        ]
        _server_module._log_llm_turns("sess-cc", "gpt-4o", turn_usages, 100)

        import time; time.sleep(0.05)
        assert len(captured) == 1
        assert captured[0]["cache_creation_tokens"] == 42

    def test_empty_turn_usages_emits_nothing(self, monkeypatch):
        """No events emitted when turn_usages is empty."""
        captured = []
        monkeypatch.setattr(_server_module, "_emit_log_event", captured.append)
        _server_module._log_llm_turns("sess-empty", "gpt-4o", [], 100)
        import time; time.sleep(0.05)
        assert captured == []


class TestAdhocMode:
    """Tests for the plan-check branching in the /ask endpoint."""

    def _auth_headers(self):
        return {"Authorization": f"Bearer {_server_module.CODEX_API_TOKEN}"}

    def test_no_plan_skips_loop(self):
        """404 from plan-server -> single subagent invocation with ADHOC_SYSTEM_PROMPT."""
        from fastapi.testclient import TestClient

        client = TestClient(_server_module.app)

        mock_plan_resp = MagicMock()
        mock_plan_resp.status_code = 404

        mock_proc = _mock_popen(stdout="ad-hoc answer", returncode=0)

        with patch("server.requests.get", return_value=mock_plan_resp), \
             patch("server.subprocess.Popen", return_value=mock_proc) as mock_popen:
            response = client.post("/ask", headers=self._auth_headers(),
                                   json={"model": "gpt-4o", "query": "hello"})

        assert response.status_code == 200
        assert response.json()["response"] == "ad-hoc answer"
        assert mock_popen.call_count == 1
        cmd = mock_popen.call_args[0][0]
        idx = cmd.index("--instructions")
        assert cmd[idx + 1] == _server_module.ADHOC_SYSTEM_PROMPT

    def test_active_plan_uses_loop(self):
        """200 with task from plan-server -> loop with SYSTEM_PROMPT, multiple invocations."""
        from fastapi.testclient import TestClient

        client = TestClient(_server_module.app)

        mock_plan_resp = MagicMock()
        mock_plan_resp.status_code = 200
        mock_plan_resp.json.return_value = {"task": {"id": "t1", "name": "Do work"}}

        mock_task = _mock_popen(stdout="task done", returncode=0)
        mock_done = _mock_popen(stdout="DONE", returncode=0)

        with patch("server.requests.get", return_value=mock_plan_resp), \
             patch("server.subprocess.Popen", side_effect=[mock_task, mock_done]) as mock_popen:
            response = client.post("/ask", headers=self._auth_headers(),
                                   json={"model": "gpt-4o", "query": "run plan"})

        assert response.status_code == 200
        assert "task done" in response.json()["response"]
        assert mock_popen.call_count == 2
        cmd = mock_popen.call_args_list[0][0][0]
        idx = cmd.index("--instructions")
        assert cmd[idx + 1] == _server_module.SYSTEM_PROMPT

    def test_plan_check_failure_falls_back_to_adhoc(self):
        """Connection error to plan-server -> codex _has_active_plan_task returns False -> ad-hoc."""
        from fastapi.testclient import TestClient

        client = TestClient(_server_module.app)

        mock_proc = _mock_popen(stdout="fallback answer", returncode=0)

        with patch("server.requests.get", side_effect=ConnectionError("plan-server down")), \
             patch("server.subprocess.Popen", return_value=mock_proc) as mock_popen:
            response = client.post("/ask", headers=self._auth_headers(),
                                   json={"model": "gpt-4o", "query": "hello"})

        assert response.status_code == 200
        assert response.json()["response"] == "fallback answer"
        assert mock_popen.call_count == 1
        cmd = mock_popen.call_args[0][0]
        idx = cmd.index("--instructions")
        assert cmd[idx + 1] == _server_module.ADHOC_SYSTEM_PROMPT


class TestIntraLoopPlanCheck:
    """Tests for the intra-loop plan check added after each subagent iteration."""

    def _auth_headers(self):
        return {"Authorization": f"Bearer {_server_module.CODEX_API_TOKEN}"}

    def test_loop_stops_when_plan_empty_after_task(self):
        """After one task completes, 404 from plan-server breaks loop without spawning DONE subagent."""
        from fastapi.testclient import TestClient

        client = TestClient(_server_module.app)

        plan_with_task = MagicMock()
        plan_with_task.status_code = 200
        plan_with_task.json.return_value = {"task": {"id": "t1", "name": "Do work"}}

        plan_empty = MagicMock()
        plan_empty.status_code = 404

        mock_task = _mock_popen(stdout="task done", returncode=0)

        with patch("server.requests.get", side_effect=[plan_with_task, plan_empty]), \
             patch("server.subprocess.Popen", return_value=mock_task) as mock_popen:
            response = client.post("/ask", headers=self._auth_headers(),
                                   json={"model": "gpt-4o", "query": "run plan"})

        assert response.status_code == 200
        assert "task done" in response.json()["response"]
        assert mock_popen.call_count == 1

    def test_loop_continues_when_plan_has_next_task(self):
        """When plan-server always has tasks, loop continues until subagent returns DONE."""
        from fastapi.testclient import TestClient

        client = TestClient(_server_module.app)

        mock_plan_resp = MagicMock()
        mock_plan_resp.status_code = 200
        mock_plan_resp.json.return_value = {"task": {"id": "t1", "name": "Do work"}}

        mock_t1 = _mock_popen(stdout="task1 done", returncode=0)
        mock_t2 = _mock_popen(stdout="task2 done", returncode=0)
        mock_done = _mock_popen(stdout="DONE", returncode=0)

        with patch("server.requests.get", return_value=mock_plan_resp), \
             patch("server.subprocess.Popen", side_effect=[mock_t1, mock_t2, mock_done]) as mock_popen:
            response = client.post("/ask", headers=self._auth_headers(),
                                   json={"model": "gpt-4o", "query": "run plan"})

        assert response.status_code == 200
        body = response.json()["response"]
        assert "task1 done" in body
        assert "task2 done" in body
        assert mock_popen.call_count == 3


class TestConcurrencyCap:
    """Tests for RR-8: concurrency cap on /ask and /plan endpoints."""

    def _auth_headers(self):
        return {"Authorization": f"Bearer {_server_module.CODEX_API_TOKEN}"}

    def test_ask_rejects_when_semaphore_locked(self):
        """Second /ask request gets 429 when semaphore is already held."""
        from fastapi.testclient import TestClient
        import asyncio

        client = TestClient(_server_module.app)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(_server_module._ENDPOINT_SEMAPHORE.acquire())
        try:
            response = client.post("/ask", headers=self._auth_headers(),
                                   json={"model": "gpt-4o", "query": "hello"})
            assert response.status_code == 429
            assert "already in progress" in response.json()["detail"]
        finally:
            _server_module._ENDPOINT_SEMAPHORE.release()
            loop.close()

    def test_plan_rejects_when_semaphore_locked(self):
        """Second /plan request gets 429 when semaphore is already held."""
        from fastapi.testclient import TestClient
        import asyncio

        client = TestClient(_server_module.app)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(_server_module._ENDPOINT_SEMAPHORE.acquire())
        try:
            response = client.post("/plan", headers=self._auth_headers(),
                                   json={"model": "gpt-4o", "query": "plan something"})
            assert response.status_code == 429
            assert "already in progress" in response.json()["detail"]
        finally:
            _server_module._ENDPOINT_SEMAPHORE.release()
            loop.close()

    def test_semaphore_released_after_ask(self):
        """Semaphore is released after /ask completes, allowing subsequent requests."""
        from fastapi.testclient import TestClient

        client = TestClient(_server_module.app)

        mock_plan_resp = MagicMock()
        mock_plan_resp.status_code = 404

        mock_proc = _mock_popen(stdout="response", returncode=0)

        with patch("server.requests.get", return_value=mock_plan_resp), \
             patch("server.subprocess.Popen", return_value=mock_proc):
            resp1 = client.post("/ask", headers=self._auth_headers(),
                                json={"model": "gpt-4o", "query": "hello"})
            assert resp1.status_code == 200

            resp2 = client.post("/ask", headers=self._auth_headers(),
                                json={"model": "gpt-4o", "query": "hello again"})
            assert resp2.status_code == 200

    def test_semaphore_released_on_error(self):
        """Semaphore is released even when the subagent raises an exception."""
        from fastapi.testclient import TestClient

        client = TestClient(_server_module.app)

        mock_plan_resp = MagicMock()
        mock_plan_resp.status_code = 404

        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = RuntimeError("boom")

        with patch("server.requests.get", return_value=mock_plan_resp), \
             patch("server.subprocess.Popen", return_value=mock_proc):
            resp1 = client.post("/ask", headers=self._auth_headers(),
                                json={"model": "gpt-4o", "query": "hello"})

        assert not _server_module._ENDPOINT_SEMAPHORE.locked()
