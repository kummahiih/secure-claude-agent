"""
test_log_mcp.py — Unit tests for log_mcp.py.

Covers:
  - list_tools returns 4 tools with correct names
  - _dispatch routes to correct endpoints
  - _dispatch passes auth headers
  - _dispatch handles 401 / 5xx responses
"""

import sys
import os
import types
import asyncio
import unittest
from unittest.mock import patch, MagicMock

# ---------------------------------------------------------------------------
# Path setup — allow "import log_mcp" from the parent directory
# ---------------------------------------------------------------------------
_HERE = os.path.dirname(__file__)
_PARENT = os.path.abspath(os.path.join(_HERE, ".."))
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

# ---------------------------------------------------------------------------
# Stub heavy / env-dependent modules before importing log_mcp
# ---------------------------------------------------------------------------

def _make_runenv_stub():
    mod = types.ModuleType("runenv")
    mod.LOG_SERVER_URL = "https://log-server:8443"
    mod.LOG_API_TOKEN = "testtoken"
    mod.MCP_SERVER_URL = ""
    mod.PLAN_SERVER_URL = ""
    mod.TESTER_SERVER_URL = ""
    mod.GIT_SERVER_URL = ""
    mod.MCP_API_TOKEN = None
    mod.PLAN_API_TOKEN = None
    mod.TESTER_API_TOKEN = None
    mod.GIT_API_TOKEN = None
    mod.CLAUDE_API_TOKEN = None
    mod.DYNAMIC_AGENT_KEY = None
    mod.ANTHROPIC_BASE_URL = None
    mod.SYSTEM_PROMPT = ""
    mod.PLAN_SYSTEM_PROMPT = ""
    return mod


def _make_setuplogging_stub():
    return types.ModuleType("setuplogging")


# Inject stubs before log_mcp is imported so module-level code resolves cleanly.
sys.modules.setdefault("setuplogging", _make_setuplogging_stub())
sys.modules["runenv"] = _make_runenv_stub()

import log_mcp  # noqa: E402 — intentional late import after sys.modules patching

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE = "https://log-server:8443"


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def _mock_resp(data=None, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = data or {}
    resp.text = ""
    return resp


# ---------------------------------------------------------------------------
# Tests: list_tools
# ---------------------------------------------------------------------------

class TestListTools(unittest.TestCase):

    def setUp(self):
        self._tools = _run(log_mcp.list_tools())

    def test_returns_four_tools(self):
        self.assertEqual(len(self._tools), 4)

    def test_tool_names(self):
        names = {t.name for t in self._tools}
        self.assertEqual(names, {
            "list_sessions",
            "get_session_summary",
            "query_logs",
            "get_token_breakdown",
        })

    def test_all_tools_have_input_schema(self):
        for tool in self._tools:
            self.assertIsNotNone(tool.inputSchema, f"{tool.name} missing inputSchema")

    def test_all_tools_have_description(self):
        for tool in self._tools:
            self.assertTrue(tool.description, f"{tool.name} missing description")


# ---------------------------------------------------------------------------
# Tests: _dispatch routing
# ---------------------------------------------------------------------------

class TestDispatchListSessions(unittest.TestCase):

    def test_uses_get_sessions_url(self):
        with patch("log_mcp.requests.get") as mock_get:
            mock_get.return_value = _mock_resp({"sessions": []})
            _run(log_mcp._dispatch("list_sessions", {}))
            url = mock_get.call_args[0][0]
            self.assertEqual(url, f"{BASE}/sessions")

    def test_passes_limit_param(self):
        with patch("log_mcp.requests.get") as mock_get:
            mock_get.return_value = _mock_resp({"sessions": []})
            _run(log_mcp._dispatch("list_sessions", {"limit": 5}))
            params = mock_get.call_args[1]["params"]
            self.assertEqual(params["limit"], 5)

    def test_passes_since_param(self):
        with patch("log_mcp.requests.get") as mock_get:
            mock_get.return_value = _mock_resp({"sessions": []})
            _run(log_mcp._dispatch("list_sessions", {"since": "2026-01-01T00:00:00Z"}))
            params = mock_get.call_args[1]["params"]
            self.assertEqual(params["since"], "2026-01-01T00:00:00Z")

    def test_sends_auth_header(self):
        with patch("log_mcp.requests.get") as mock_get:
            mock_get.return_value = _mock_resp({"sessions": []})
            _run(log_mcp._dispatch("list_sessions", {}))
            headers = mock_get.call_args[1]["headers"]
            self.assertEqual(headers["Authorization"], "Bearer testtoken")

    def test_returns_json_string(self):
        with patch("log_mcp.requests.get") as mock_get:
            mock_get.return_value = _mock_resp({"sessions": [{"session_id": "s1"}]})
            result = _run(log_mcp._dispatch("list_sessions", {}))
            self.assertIn("s1", result)


class TestDispatchGetSessionSummary(unittest.TestCase):

    def test_url_includes_session_id(self):
        with patch("log_mcp.requests.get") as mock_get:
            mock_get.return_value = _mock_resp({"session_id": "abc"})
            _run(log_mcp._dispatch("get_session_summary", {"session_id": "abc"}))
            url = mock_get.call_args[0][0]
            self.assertEqual(url, f"{BASE}/sessions/abc/summary")

    def test_sends_auth_header(self):
        with patch("log_mcp.requests.get") as mock_get:
            mock_get.return_value = _mock_resp({"session_id": "abc"})
            _run(log_mcp._dispatch("get_session_summary", {"session_id": "abc"}))
            headers = mock_get.call_args[1]["headers"]
            self.assertEqual(headers["Authorization"], "Bearer testtoken")


class TestDispatchQueryLogs(unittest.TestCase):

    def test_uses_post(self):
        with patch("log_mcp.requests.post") as mock_post:
            mock_post.return_value = _mock_resp({"events": []})
            _run(log_mcp._dispatch("query_logs", {"session_id": "abc"}))
            mock_post.assert_called_once()

    def test_url_includes_session_id(self):
        with patch("log_mcp.requests.post") as mock_post:
            mock_post.return_value = _mock_resp({"events": []})
            _run(log_mcp._dispatch("query_logs", {"session_id": "abc"}))
            url = mock_post.call_args[0][0]
            self.assertEqual(url, f"{BASE}/sessions/abc/query")

    def test_sends_event_type_in_body(self):
        with patch("log_mcp.requests.post") as mock_post:
            mock_post.return_value = _mock_resp({"events": []})
            _run(log_mcp._dispatch("query_logs", {
                "session_id": "abc", "event_type": "tool_call"
            }))
            body = mock_post.call_args[1]["json"]
            self.assertEqual(body["event_type"], "tool_call")

    def test_sends_auth_header(self):
        with patch("log_mcp.requests.post") as mock_post:
            mock_post.return_value = _mock_resp({"events": []})
            _run(log_mcp._dispatch("query_logs", {"session_id": "abc"}))
            headers = mock_post.call_args[1]["headers"]
            self.assertEqual(headers["Authorization"], "Bearer testtoken")


class TestDispatchGetTokenBreakdown(unittest.TestCase):

    def test_url_includes_session_id(self):
        with patch("log_mcp.requests.get") as mock_get:
            mock_get.return_value = _mock_resp({"token_breakdown": []})
            _run(log_mcp._dispatch("get_token_breakdown", {"session_id": "s1"}))
            url = mock_get.call_args[0][0]
            self.assertEqual(url, f"{BASE}/sessions/s1/tokens")

    def test_sends_auth_header(self):
        with patch("log_mcp.requests.get") as mock_get:
            mock_get.return_value = _mock_resp({"token_breakdown": []})
            _run(log_mcp._dispatch("get_token_breakdown", {"session_id": "s1"}))
            headers = mock_get.call_args[1]["headers"]
            self.assertEqual(headers["Authorization"], "Bearer testtoken")


# ---------------------------------------------------------------------------
# Tests: error handling in _dispatch
# ---------------------------------------------------------------------------

class TestDispatchErrorHandling(unittest.TestCase):

    def test_unknown_tool_raises_value_error(self):
        with self.assertRaises(ValueError):
            _run(log_mcp._dispatch("nonexistent_tool", {}))

    def test_list_sessions_401_raises_permission_error(self):
        with patch("log_mcp.requests.get") as mock_get:
            mock_get.return_value = _mock_resp(status=401)
            with self.assertRaises(PermissionError):
                _run(log_mcp._dispatch("list_sessions", {}))

    def test_list_sessions_500_raises_runtime_error(self):
        with patch("log_mcp.requests.get") as mock_get:
            mock_get.return_value = _mock_resp(status=500)
            with self.assertRaises(RuntimeError):
                _run(log_mcp._dispatch("list_sessions", {}))

    def test_get_session_summary_401_raises_permission_error(self):
        with patch("log_mcp.requests.get") as mock_get:
            mock_get.return_value = _mock_resp(status=401)
            with self.assertRaises(PermissionError):
                _run(log_mcp._dispatch("get_session_summary", {"session_id": "x"}))

    def test_query_logs_401_raises_permission_error(self):
        with patch("log_mcp.requests.post") as mock_post:
            mock_post.return_value = _mock_resp(status=401)
            with self.assertRaises(PermissionError):
                _run(log_mcp._dispatch("query_logs", {"session_id": "x"}))

    def test_get_token_breakdown_401_raises_permission_error(self):
        with patch("log_mcp.requests.get") as mock_get:
            mock_get.return_value = _mock_resp(status=401)
            with self.assertRaises(PermissionError):
                _run(log_mcp._dispatch("get_token_breakdown", {"session_id": "x"}))


if __name__ == "__main__":
    unittest.main()
