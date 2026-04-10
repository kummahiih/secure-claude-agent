"""
Tests for git_mcp.py — REST client mode.

Mocks HTTP calls to git-server; no real git repo or network needed.
"""

import os
import pytest
from unittest.mock import patch, MagicMock

# Set required env vars before importing git_mcp / runenv
os.environ.setdefault("GIT_API_TOKEN", "dummy-git-token")
os.environ.setdefault("GIT_SERVER_URL", "https://git-server:8443")
# Disable log emission in all tests (avoids daemon-thread races with request mocks)
os.environ["LOG_SERVER_URL"] = ""

import git_mcp

_BASE = "https://git-server:8443"


@pytest.fixture(autouse=True)
def _silence_log_emit(monkeypatch):
    """Suppress _emit_log_event in all tests; TestGitOpLogEvents overrides with @patch."""
    monkeypatch.setattr(git_mcp, "_emit_log_event", lambda event: None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_resp(status_code: int = 200, json_data: dict = None, text: str = "") -> MagicMock:
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data if json_data is not None else {}
    m.text = text
    return m


def _ok_resp(output: str) -> MagicMock:
    return _mock_resp(200, {"output": output})


def _err_resp(status_code: int, error: str) -> MagicMock:
    return _mock_resp(status_code, {"error": error})


# ---------------------------------------------------------------------------
# git_status
# ---------------------------------------------------------------------------

class TestGitStatus:
    def test_clean_repo(self):
        with patch("requests.get", return_value=_ok_resp("Working tree clean — no changes.")) as mock_get:
            result = git_mcp.git_status()
        assert result.isError is False
        assert "clean" in result.content[0].text.lower()
        assert f"{_BASE}/status" in mock_get.call_args[0][0]

    def test_untracked_file(self):
        with patch("requests.get", return_value=_ok_resp("?? new_file.py")):
            result = git_mcp.git_status()
        assert result.isError is False
        assert "new_file.py" in result.content[0].text

    def test_modified_file(self):
        with patch("requests.get", return_value=_ok_resp(" M file.py")):
            result = git_mcp.git_status()
        assert result.isError is False
        assert "file.py" in result.content[0].text

    def test_submodule_path_sent(self):
        with patch("requests.get", return_value=_ok_resp("M foo.py")) as mock_get:
            git_mcp.git_status(submodule_path="cluster/agent")
        params = mock_get.call_args[1].get("params", {})
        assert params.get("submodule_path") == "cluster/agent"

    def test_no_submodule_path_not_sent(self):
        with patch("requests.get", return_value=_ok_resp("")) as mock_get:
            git_mcp.git_status()
        params = mock_get.call_args[1].get("params", {})
        assert "submodule_path" not in params

    def test_auth_header_sent(self):
        with patch("requests.get", return_value=_ok_resp("")) as mock_get:
            git_mcp.git_status()
        headers = mock_get.call_args[1].get("headers", {})
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")

    def test_unauthorized(self):
        with patch("requests.get", return_value=_err_resp(401, "Unauthorized")):
            result = git_mcp.git_status()
        assert result.isError is True
        assert "unauthorized" in result.content[0].text.lower()

    def test_server_error(self):
        with patch("requests.get", return_value=_err_resp(500, "internal error")):
            result = git_mcp.git_status()
        assert result.isError is True
        assert "internal error" in result.content[0].text

    def test_timeout(self):
        import requests as req_lib
        with patch("requests.get", side_effect=req_lib.exceptions.Timeout()):
            result = git_mcp.git_status()
        assert result.isError is True
        assert "timed out" in result.content[0].text.lower()

    def test_connection_error(self):
        import requests as req_lib
        with patch("requests.get", side_effect=req_lib.exceptions.ConnectionError()):
            result = git_mcp.git_status()
        assert result.isError is True


# ---------------------------------------------------------------------------
# git_diff
# ---------------------------------------------------------------------------

class TestGitDiff:
    def test_unstaged_diff(self):
        with patch("requests.get", return_value=_ok_resp("+line2")) as mock_get:
            result = git_mcp.git_diff()
        assert result.isError is False
        assert "+line2" in result.content[0].text
        params = mock_get.call_args[1].get("params", {})
        assert params.get("staged") == "false"

    def test_staged_diff(self):
        with patch("requests.get", return_value=_ok_resp("+v2")) as mock_get:
            result = git_mcp.git_diff(staged=True)
        assert result.isError is False
        assert "+v2" in result.content[0].text
        params = mock_get.call_args[1].get("params", {})
        assert params.get("staged") == "true"

    def test_no_unstaged_changes(self):
        with patch("requests.get", return_value=_ok_resp("No unstaged changes.")):
            result = git_mcp.git_diff()
        assert result.isError is False
        assert "no unstaged changes" in result.content[0].text.lower()

    def test_no_staged_changes(self):
        with patch("requests.get", return_value=_ok_resp("No staged changes.")):
            result = git_mcp.git_diff(staged=True)
        assert result.isError is False

    def test_submodule_path_sent(self):
        with patch("requests.get", return_value=_ok_resp("+x")) as mock_get:
            git_mcp.git_diff(submodule_path="cluster/agent")
        params = mock_get.call_args[1].get("params", {})
        assert params.get("submodule_path") == "cluster/agent"

    def test_correct_url(self):
        with patch("requests.get", return_value=_ok_resp("")) as mock_get:
            git_mcp.git_diff()
        assert f"{_BASE}/diff" in mock_get.call_args[0][0]

    def test_unauthorized(self):
        with patch("requests.get", return_value=_err_resp(401, "Unauthorized")):
            result = git_mcp.git_diff()
        assert result.isError is True
        assert "unauthorized" in result.content[0].text.lower()

    def test_timeout(self):
        import requests as req_lib
        with patch("requests.get", side_effect=req_lib.exceptions.Timeout()):
            result = git_mcp.git_diff()
        assert result.isError is True
        assert "timed out" in result.content[0].text.lower()


# ---------------------------------------------------------------------------
# git_add
# ---------------------------------------------------------------------------

class TestGitAdd:
    def test_add_file(self):
        with patch("requests.post", return_value=_ok_resp("Staged: new.py")) as mock_post:
            result = git_mcp.git_add(paths=["new.py"])
        assert result.isError is False
        assert "new.py" in result.content[0].text
        json_body = mock_post.call_args[1].get("json", {})
        assert json_body.get("paths") == ["new.py"]

    def test_add_all(self):
        with patch("requests.post", return_value=_ok_resp("Staged: .")) as mock_post:
            result = git_mcp.git_add(paths=["."])
        assert result.isError is False
        json_body = mock_post.call_args[1].get("json", {})
        assert json_body.get("paths") == ["."]

    def test_add_empty_paths(self):
        with patch("requests.post") as mock_post:
            result = git_mcp.git_add(paths=[])
        assert result.isError is True
        assert "no paths" in result.content[0].text.lower()
        mock_post.assert_not_called()

    def test_add_nonexistent_file(self):
        with patch("requests.post", return_value=_err_resp(422, "pathspec does not match any file")):
            result = git_mcp.git_add(paths=["does_not_exist.py"])
        assert result.isError is True

    def test_correct_url(self):
        with patch("requests.post", return_value=_ok_resp("Staged: x.py")) as mock_post:
            git_mcp.git_add(paths=["x.py"])
        assert f"{_BASE}/add" in mock_post.call_args[0][0]

    def test_auth_header_sent(self):
        with patch("requests.post", return_value=_ok_resp("Staged: x.py")) as mock_post:
            git_mcp.git_add(paths=["x.py"])
        headers = mock_post.call_args[1].get("headers", {})
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Bearer ")

    def test_multiple_paths(self):
        with patch("requests.post", return_value=_ok_resp("Staged: a.py, b.py")) as mock_post:
            result = git_mcp.git_add(paths=["a.py", "b.py"])
        assert result.isError is False
        json_body = mock_post.call_args[1].get("json", {})
        assert json_body.get("paths") == ["a.py", "b.py"]

    def test_unauthorized(self):
        with patch("requests.post", return_value=_err_resp(401, "Unauthorized")):
            result = git_mcp.git_add(paths=["f.py"])
        assert result.isError is True
        assert "unauthorized" in result.content[0].text.lower()

    def test_timeout(self):
        import requests as req_lib
        with patch("requests.post", side_effect=req_lib.exceptions.Timeout()):
            result = git_mcp.git_add(paths=["f.py"])
        assert result.isError is True
        assert "timed out" in result.content[0].text.lower()


# ---------------------------------------------------------------------------
# git_commit
# ---------------------------------------------------------------------------

class TestGitCommit:
    def test_commit(self):
        with patch("requests.post", return_value=_ok_resp("[main abc1234] test commit")) as mock_post:
            result = git_mcp.git_commit(message="test commit")
        assert result.isError is False
        assert "test commit" in result.content[0].text
        json_body = mock_post.call_args[1].get("json", {})
        assert json_body.get("message") == "test commit"

    def test_commit_empty_message(self):
        with patch("requests.post") as mock_post:
            result = git_mcp.git_commit(message="")
        assert result.isError is True
        assert "empty" in result.content[0].text.lower()
        mock_post.assert_not_called()

    def test_commit_whitespace_message(self):
        with patch("requests.post") as mock_post:
            result = git_mcp.git_commit(message="   ")
        assert result.isError is True
        mock_post.assert_not_called()

    def test_commit_nothing_staged(self):
        with patch("requests.post", return_value=_ok_resp("Nothing to commit — working tree clean.")):
            result = git_mcp.git_commit(message="empty commit")
        assert result.isError is False
        assert "nothing to commit" in result.content[0].text.lower()

    def test_message_stripped(self):
        with patch("requests.post", return_value=_ok_resp("[main abc] msg")) as mock_post:
            git_mcp.git_commit(message="  padded message  ")
        json_body = mock_post.call_args[1].get("json", {})
        assert json_body.get("message") == "padded message"

    def test_submodule_path_sent(self):
        with patch("requests.post", return_value=_ok_resp("[main abc] msg")) as mock_post:
            git_mcp.git_commit(message="msg", submodule_path="cluster/agent")
        json_body = mock_post.call_args[1].get("json", {})
        assert json_body.get("submodule_path") == "cluster/agent"

    def test_no_submodule_path_not_sent(self):
        with patch("requests.post", return_value=_ok_resp("[main abc] msg")) as mock_post:
            git_mcp.git_commit(message="msg")
        json_body = mock_post.call_args[1].get("json", {})
        assert "submodule_path" not in json_body

    def test_correct_url(self):
        with patch("requests.post", return_value=_ok_resp("[main abc] msg")) as mock_post:
            git_mcp.git_commit(message="msg")
        assert f"{_BASE}/commit" in mock_post.call_args[0][0]

    def test_unauthorized(self):
        with patch("requests.post", return_value=_err_resp(401, "Unauthorized")):
            result = git_mcp.git_commit(message="msg")
        assert result.isError is True
        assert "unauthorized" in result.content[0].text.lower()

    def test_timeout(self):
        import requests as req_lib
        with patch("requests.post", side_effect=req_lib.exceptions.Timeout()):
            result = git_mcp.git_commit(message="msg")
        assert result.isError is True
        assert "timed out" in result.content[0].text.lower()


# ---------------------------------------------------------------------------
# git_log
# ---------------------------------------------------------------------------

class TestGitLog:
    def test_no_commits(self):
        with patch("requests.get", return_value=_ok_resp("No commits yet.")):
            result = git_mcp.git_log()
        assert result.isError is False
        assert "no commits" in result.content[0].text.lower()

    def test_log_with_commits(self):
        with patch("requests.get", return_value=_ok_resp("abc1234 commit 2\ndef5678 commit 1")) as mock_get:
            result = git_mcp.git_log(max_count=2)
        assert result.isError is False
        text = result.content[0].text
        assert "commit 2" in text
        assert "commit 1" in text
        params = mock_get.call_args[1].get("params", {})
        assert params.get("max_count") == "2"

    def test_max_count_clamped_high(self):
        with patch("requests.get", return_value=_ok_resp("abc commit")) as mock_get:
            git_mcp.git_log(max_count=100)
        params = mock_get.call_args[1].get("params", {})
        assert int(params.get("max_count", 0)) <= 50

    def test_max_count_clamped_low(self):
        with patch("requests.get", return_value=_ok_resp("abc commit")) as mock_get:
            git_mcp.git_log(max_count=0)
        params = mock_get.call_args[1].get("params", {})
        assert int(params.get("max_count", 0)) >= 1

    def test_default_max_count(self):
        with patch("requests.get", return_value=_ok_resp("abc commit")) as mock_get:
            git_mcp.git_log()
        params = mock_get.call_args[1].get("params", {})
        assert params.get("max_count") == "10"

    def test_submodule_path_sent(self):
        with patch("requests.get", return_value=_ok_resp("abc msg")) as mock_get:
            git_mcp.git_log(submodule_path="cluster/agent")
        params = mock_get.call_args[1].get("params", {})
        assert params.get("submodule_path") == "cluster/agent"

    def test_correct_url(self):
        with patch("requests.get", return_value=_ok_resp("abc msg")) as mock_get:
            git_mcp.git_log()
        assert f"{_BASE}/log" in mock_get.call_args[0][0]

    def test_unauthorized(self):
        with patch("requests.get", return_value=_err_resp(401, "Unauthorized")):
            result = git_mcp.git_log()
        assert result.isError is True
        assert "unauthorized" in result.content[0].text.lower()

    def test_timeout(self):
        import requests as req_lib
        with patch("requests.get", side_effect=req_lib.exceptions.Timeout()):
            result = git_mcp.git_log()
        assert result.isError is True
        assert "timed out" in result.content[0].text.lower()


# ---------------------------------------------------------------------------
# git_reset_soft
# ---------------------------------------------------------------------------

class TestGitResetSoft:
    def test_reset_success(self):
        with patch("requests.post", return_value=_ok_resp("Reset 1 commit(s). Changes are still staged. HEAD is now at abc123456789.")) as mock_post:
            result = git_mcp.git_reset_soft(count=1)
        assert result.isError is False
        assert "Reset 1 commit" in result.content[0].text
        json_body = mock_post.call_args[1].get("json", {})
        assert json_body.get("count") == 1

    def test_reset_multiple(self):
        with patch("requests.post", return_value=_ok_resp("Reset 3 commit(s). Changes are still staged.")) as mock_post:
            result = git_mcp.git_reset_soft(count=3)
        assert result.isError is False
        json_body = mock_post.call_args[1].get("json", {})
        assert json_body.get("count") == 3

    def test_reset_blocked_past_baseline(self):
        with patch("requests.post", return_value=_err_resp(400, "Cannot reset — would go past baseline commit (abc123456789). You can only undo commits created during this session.")):
            result = git_mcp.git_reset_soft(count=1)
        assert result.isError is True
        assert "baseline" in result.content[0].text.lower()

    def test_reset_no_baseline(self):
        with patch("requests.post", return_value=_err_resp(400, "Cannot reset — no baseline commit (empty repo at startup)")):
            result = git_mcp.git_reset_soft(count=1)
        assert result.isError is True
        assert "no baseline" in result.content[0].text.lower()

    def test_count_clamped_high(self):
        with patch("requests.post", return_value=_ok_resp("Reset 5 commit(s).")) as mock_post:
            git_mcp.git_reset_soft(count=100)
        json_body = mock_post.call_args[1].get("json", {})
        assert json_body.get("count") <= 5

    def test_count_clamped_low(self):
        with patch("requests.post", return_value=_ok_resp("Reset 1 commit(s).")) as mock_post:
            git_mcp.git_reset_soft(count=0)
        json_body = mock_post.call_args[1].get("json", {})
        assert json_body.get("count") >= 1

    def test_submodule_path_sent(self):
        with patch("requests.post", return_value=_ok_resp("Reset 1 commit(s).")) as mock_post:
            git_mcp.git_reset_soft(count=1, submodule_path="cluster/agent")
        json_body = mock_post.call_args[1].get("json", {})
        assert json_body.get("submodule_path") == "cluster/agent"

    def test_no_submodule_path_not_sent(self):
        with patch("requests.post", return_value=_ok_resp("Reset 1 commit(s).")) as mock_post:
            git_mcp.git_reset_soft(count=1)
        json_body = mock_post.call_args[1].get("json", {})
        assert "submodule_path" not in json_body

    def test_correct_url(self):
        with patch("requests.post", return_value=_ok_resp("Reset 1 commit(s).")) as mock_post:
            git_mcp.git_reset_soft(count=1)
        assert f"{_BASE}/reset" in mock_post.call_args[0][0]

    def test_unauthorized(self):
        with patch("requests.post", return_value=_err_resp(401, "Unauthorized")):
            result = git_mcp.git_reset_soft(count=1)
        assert result.isError is True
        assert "unauthorized" in result.content[0].text.lower()

    def test_timeout(self):
        import requests as req_lib
        with patch("requests.post", side_effect=req_lib.exceptions.Timeout()):
            result = git_mcp.git_reset_soft(count=1)
        assert result.isError is True
        assert "timed out" in result.content[0].text.lower()


# ---------------------------------------------------------------------------
# Structural checks
# ---------------------------------------------------------------------------

class TestRestClientStructure:
    def test_no_subprocess_import(self):
        """git_mcp must not import subprocess in REST client mode."""
        assert "subprocess" not in vars(git_mcp), \
            "git_mcp imports subprocess — should not for REST client"

    def test_has_headers(self):
        """HEADERS constant must exist and include Authorization."""
        assert hasattr(git_mcp, "HEADERS")
        assert "Authorization" in git_mcp.HEADERS

    def test_has_verify(self):
        """VERIFY constant must point to CA cert."""
        assert hasattr(git_mcp, "VERIFY")
        assert git_mcp.VERIFY == "/app/certs/ca.crt"

    def test_git_server_url_set(self):
        """GIT_SERVER_URL must be importable from git_mcp."""
        assert hasattr(git_mcp, "GIT_SERVER_URL")
        assert git_mcp.GIT_SERVER_URL.startswith("https://")

    def test_tool_names_unchanged(self):
        """All 6 tool names must remain identical to the old interface."""
        names = {t.name for t in git_mcp.TOOLS}
        assert names == {"git_status", "git_diff", "git_add", "git_commit", "git_log", "git_reset_soft"}


# ---------------------------------------------------------------------------
# git_op log event emission
# ---------------------------------------------------------------------------

class TestGitOpLogEvents:
    @patch("git_mcp._emit_log_event")
    def test_git_status_emits_log_event(self, mock_emit):
        with patch("requests.get", return_value=_ok_resp("M foo.py")):
            result = git_mcp.git_status()
        assert result.isError is False
        mock_emit.assert_called_once()
        event = mock_emit.call_args[0][0]
        assert event["event_type"] == "git_op"
        assert event["operation"] == "git_status"
        assert "duration_ms" in event

    @patch("git_mcp._emit_log_event")
    def test_git_status_includes_submodule_path(self, mock_emit):
        with patch("requests.get", return_value=_ok_resp("")):
            git_mcp.git_status(submodule_path="cluster/agent")
        assert mock_emit.call_args[0][0]["submodule_path"] == "cluster/agent"

    @patch("git_mcp._emit_log_event")
    def test_git_status_no_submodule_in_event_when_absent(self, mock_emit):
        with patch("requests.get", return_value=_ok_resp("")):
            git_mcp.git_status()
        assert "submodule_path" not in mock_emit.call_args[0][0]

    @patch("git_mcp._emit_log_event")
    def test_git_status_does_not_emit_on_error(self, mock_emit):
        with patch("requests.get", return_value=_err_resp(500, "err")):
            git_mcp.git_status()
        mock_emit.assert_not_called()

    @patch("git_mcp._emit_log_event")
    def test_git_commit_emits_log_event(self, mock_emit):
        with patch("requests.post", return_value=_ok_resp("[main abc] msg")):
            result = git_mcp.git_commit(message="msg")
        assert result.isError is False
        mock_emit.assert_called_once()
        event = mock_emit.call_args[0][0]
        assert event["event_type"] == "git_op"
        assert event["operation"] == "git_commit"
        assert "duration_ms" in event

    @patch("git_mcp._emit_log_event")
    def test_git_commit_includes_submodule_path(self, mock_emit):
        with patch("requests.post", return_value=_ok_resp("[main abc] msg")):
            git_mcp.git_commit(message="msg", submodule_path="cluster/agent")
        assert mock_emit.call_args[0][0]["submodule_path"] == "cluster/agent"

    @patch("git_mcp._emit_log_event")
    def test_git_commit_does_not_emit_on_error(self, mock_emit):
        with patch("requests.post", return_value=_err_resp(401, "Unauthorized")):
            git_mcp.git_commit(message="msg")
        mock_emit.assert_not_called()

    @patch("git_mcp._emit_log_event")
    def test_git_add_emits_log_event(self, mock_emit):
        with patch("requests.post", return_value=_ok_resp("Staged: x.py")):
            git_mcp.git_add(paths=["x.py"])
        mock_emit.assert_called_once()
        event = mock_emit.call_args[0][0]
        assert event["event_type"] == "git_op"
        assert event["operation"] == "git_add"

    @patch("git_mcp._emit_log_event")
    def test_git_log_emits_log_event(self, mock_emit):
        with patch("requests.get", return_value=_ok_resp("abc commit")):
            git_mcp.git_log()
        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][0]["operation"] == "git_log"

    @patch("git_mcp._emit_log_event")
    def test_git_reset_soft_emits_log_event(self, mock_emit):
        with patch("requests.post", return_value=_ok_resp("Reset 1 commit(s).")):
            git_mcp.git_reset_soft(count=1)
        mock_emit.assert_called_once()
        assert mock_emit.call_args[0][0]["operation"] == "git_reset_soft"
