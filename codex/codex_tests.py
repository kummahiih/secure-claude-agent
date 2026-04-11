import os
import sys
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


from runenv import CODEX_API_TOKEN, DYNAMIC_AGENT_KEY, MCP_API_TOKEN, SYSTEM_PROMPT, ADHOC_SYSTEM_PROMPT


# Ensure the local directory is in the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from server import app

client = TestClient(app)


def _mock_popen(stdout="", stderr="", returncode=0):
    """Create a MagicMock that behaves like subprocess.Popen."""
    proc = MagicMock()
    proc.communicate.return_value = (stdout, stderr)
    proc.returncode = returncode
    proc.kill = MagicMock()
    return proc


# --- Auth Tests ---

def test_fastapi_endpoint_unauthorized():
    # 1. Test missing token entirely
    response = client.post("/ask", json={"model": "gpt-4o", "query": "What is the status?"})
    assert response.status_code == 401

    # 2. Test invalid token
    headers = {"Authorization": "Bearer completely-wrong-token"}
    response = client.post("/ask", headers=headers, json={"model": "gpt-4o", "query": "What is the status?"})
    assert response.status_code == 401


def test_fastapi_endpoint_authorized_success():
    headers = {"Authorization": f"Bearer {os.environ['CODEX_API_TOKEN']}"}
    mock_task = _mock_popen(stdout="Here is the status.", returncode=0)
    mock_done = _mock_popen(stdout="DONE", returncode=0)

    expected_cmd = [
        "codex", "--quiet",
        "--model", "gpt-4o",
        "--instructions", SYSTEM_PROMPT,
        "What is the status?",
    ]
    expected_kwargs = dict(
        cwd="/home/appuser/sandbox",
        stdout=-1,  # subprocess.PIPE
        stderr=-1,  # subprocess.PIPE
        text=True,
        env={
            **os.environ,
            "HOME": "/home/appuser",
            "OPENAI_API_KEY": DYNAMIC_AGENT_KEY or "",
        }
    )

    mock_has_task = MagicMock()
    mock_has_task.status_code = 200
    mock_has_task.json.return_value = {"task": {"id": "t1", "name": "Do something"}}

    with patch("server.requests.get", return_value=mock_has_task), \
         patch("server.subprocess.Popen", side_effect=[mock_task, mock_done]) as mock_popen:
        response = client.post("/ask", headers=headers, json={"model": "gpt-4o", "query": "What is the status?"})
        assert response.status_code == 200
        json_response = response.json()
        assert json_response["response"] == "Here is the status."
        assert mock_popen.call_count == 2
        actual_args, actual_kwargs = mock_popen.call_args_list[0]
        assert actual_args == (expected_cmd,)
        assert actual_kwargs == expected_kwargs


def test_fastapi_endpoint_authorized_codex_error():
    headers = {"Authorization": f"Bearer {os.environ['CODEX_API_TOKEN']}"}
    mock_proc = _mock_popen(stderr="codex: error: subprocess failed", returncode=1)

    with patch("server.subprocess.Popen", return_value=mock_proc):
        response = client.post("/ask", headers=headers, json={"model": "gpt-4o", "query": "What is the status?"})
        assert response.status_code == 200
        json_response = response.json()
        assert "error" in json_response
        assert "subprocess failed" in json_response["error"]


def test_fastapi_endpoint_disallowed_model():
    headers = {"Authorization": f"Bearer {os.environ['CODEX_API_TOKEN']}"}
    response = client.post("/ask", headers=headers, json={"model": "bad-model", "query": "What is the status?"})
    assert response.status_code == 400
    assert "bad-model" in response.json()["detail"]


def test_fastapi_endpoint_timeout():
    import subprocess
    headers = {"Authorization": f"Bearer {os.environ['CODEX_API_TOKEN']}"}

    mock_proc = MagicMock()
    mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="codex", timeout=600)
    mock_proc.kill = MagicMock()
    # After kill, communicate returns empty
    def _communicate_after_kill(*a, **kw):
        return ("", "")
    # Use a list to track calls: first call raises, subsequent calls return empty
    call_count = [0]
    def _communicate_side_effect(*a, **kw):
        call_count[0] += 1
        if call_count[0] == 1:
            raise subprocess.TimeoutExpired(cmd="codex", timeout=600)
        return ("", "")
    mock_proc.communicate.side_effect = _communicate_side_effect

    with patch("server.subprocess.Popen", return_value=mock_proc):
        response = client.post("/ask", headers=headers, json={"model": "gpt-4o", "query": "Hang forever"})
        assert response.status_code == 200
        json_response = response.json()
        assert "error" in json_response
        assert "timed out" in json_response["error"]


def test_fastapi_endpoint_unexpected_exception():
    headers = {"Authorization": f"Bearer {os.environ['CODEX_API_TOKEN']}"}

    mock_proc = MagicMock()
    mock_proc.communicate.side_effect = Exception("Unexpected failure")

    with patch("server.subprocess.Popen", return_value=mock_proc):
        response = client.post("/ask", headers=headers, json={"model": "gpt-4o", "query": "Crash this"})
        assert response.status_code == 200
        json_response = response.json()
        assert "error" in json_response
        assert "Unexpected failure" in json_response["error"]


# --- Health Check ---

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

# --- End-to-End Mock Tests ---

def test_plan_loop_success():
    headers = {"Authorization": f"Bearer {os.environ['CODEX_API_TOKEN']}"}
    mock_proc = _mock_popen(
        stdout=(
            "Calling plan_current... task t1 returned.\n"
            "Working on task...\n"
            "Calling run_tests... status: pass.\n"
            "Calling git_commit... committed.\n"
            "Calling plan_complete... done."
        ),
        returncode=0,
    )

    mock_has_task = MagicMock()
    mock_has_task.status_code = 200
    mock_has_task.json.return_value = {"task": {"id": "t1", "name": "Do work"}}

    with patch("server.requests.get", return_value=mock_has_task), \
         patch("server.subprocess.Popen", return_value=mock_proc) as mock_popen:
        response = client.post("/ask", headers=headers, json={"model": "gpt-4o", "query": "Run the plan loop"})
        assert response.status_code == 200
        json_response = response.json()
        assert "error" not in json_response
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert "--instructions" in cmd
        idx = cmd.index("--instructions")
        assert cmd[idx + 1] == SYSTEM_PROMPT


def test_plan_loop_block_after_retries():
    headers = {"Authorization": f"Bearer {os.environ['CODEX_API_TOKEN']}"}
    mock_proc = _mock_popen(
        stdout=(
            "Calling plan_current... task t2 returned.\n"
            "Attempt 1: run_tests failed.\n"
            "Attempt 2: run_tests failed.\n"
            "Attempt 3: run_tests failed.\n"
            "Calling plan_block... blocked due to repeated test failures."
        ),
        returncode=0,
    )

    mock_has_task = MagicMock()
    mock_has_task.status_code = 200
    mock_has_task.json.return_value = {"task": {"id": "t2", "name": "Failing task"}}

    with patch("server.requests.get", return_value=mock_has_task), \
         patch("server.subprocess.Popen", return_value=mock_proc) as mock_popen:
        response = client.post("/ask", headers=headers, json={"model": "gpt-4o", "query": "Run the plan loop with failures"})
        assert response.status_code == 200
        json_response = response.json()
        assert "error" not in json_response
        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert "--instructions" in cmd
        idx = cmd.index("--instructions")
        assert cmd[idx + 1] == SYSTEM_PROMPT


class TestModelAllowlist:
    def test_ask_rejects_unknown_model(self):
        headers = {"Authorization": f"Bearer {os.environ['CODEX_API_TOKEN']}"}
        response = client.post("/ask", headers=headers, json={"model": "claude-sonnet-4-6", "query": "hello"})
        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"]

    def test_plan_rejects_unknown_model(self):
        headers = {"Authorization": f"Bearer {os.environ['CODEX_API_TOKEN']}"}
        response = client.post("/plan", headers=headers, json={"model": "claude-sonnet-4-6", "query": "hello"})
        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"]

    def test_ask_accepts_allowed_model(self):
        headers = {"Authorization": f"Bearer {os.environ['CODEX_API_TOKEN']}"}
        mock_proc = _mock_popen(stdout="ok", returncode=0)
        with patch("server.subprocess.Popen", return_value=mock_proc):
            response = client.post("/ask", headers=headers, json={"model": "gpt-4o", "query": "hello"})
        assert response.status_code == 200

    def test_ask_rejects_empty_model(self):
        headers = {"Authorization": f"Bearer {os.environ['CODEX_API_TOKEN']}"}
        response = client.post("/ask", headers=headers, json={"model": "", "query": "hello"})
        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"]

    def test_model_validation_is_exact_match(self):
        headers = {"Authorization": f"Bearer {os.environ['CODEX_API_TOKEN']}"}
        response = client.post("/ask", headers=headers, json={"model": "gpt-4o-evil", "query": "hello"})
        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"]


# --- Ad-hoc vs plan-loop branching tests ---

def test_adhoc_no_plan_single_invocation():
    """Without an active plan task, /ask runs exactly one subagent with ADHOC_SYSTEM_PROMPT."""
    headers = {"Authorization": f"Bearer {os.environ['CODEX_API_TOKEN']}"}
    mock_proc = _mock_popen(stdout="Here is my ad-hoc answer.", returncode=0)

    mock_no_task = MagicMock()
    mock_no_task.status_code = 404

    with patch("server.requests.get", return_value=mock_no_task), \
         patch("server.subprocess.Popen", return_value=mock_proc) as mock_popen:
        response = client.post("/ask", headers=headers, json={"model": "gpt-4o", "query": "What time is it?"})

    assert response.status_code == 200
    assert response.json()["response"] == "Here is my ad-hoc answer."
    assert mock_popen.call_count == 1
    cmd = mock_popen.call_args[0][0]
    idx = cmd.index("--instructions")
    assert cmd[idx + 1] == ADHOC_SYSTEM_PROMPT


def test_adhoc_active_plan_uses_loop():
    """With an active plan task, /ask uses the normal loop with SYSTEM_PROMPT."""
    headers = {"Authorization": f"Bearer {os.environ['CODEX_API_TOKEN']}"}
    mock_task_proc = _mock_popen(stdout="Task complete.", returncode=0)
    mock_done_proc = _mock_popen(stdout="DONE", returncode=0)

    mock_has_task = MagicMock()
    mock_has_task.status_code = 200
    mock_has_task.json.return_value = {"task": {"id": "t1", "name": "Do something"}}

    with patch("server.requests.get", return_value=mock_has_task), \
         patch("server.subprocess.Popen", side_effect=[mock_task_proc, mock_done_proc]) as mock_popen:
        response = client.post("/ask", headers=headers, json={"model": "gpt-4o", "query": "Run tasks"})

    assert response.status_code == 200
    assert response.json()["response"] == "Task complete."
    assert mock_popen.call_count == 2
    cmd = mock_popen.call_args_list[0][0][0]
    idx = cmd.index("--instructions")
    assert cmd[idx + 1] == SYSTEM_PROMPT
