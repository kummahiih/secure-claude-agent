import os
import sys
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from runenv import CLAUDE_API_TOKEN, DYNAMIC_AGENT_KEY, ANTHROPIC_BASE_URL, MCP_API_TOKEN, SYSTEM_PROMPT


# Ensure the local directory is in the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from server import app

client = TestClient(app)


# --- Auth Tests ---

def test_fastapi_endpoint_unauthorized():
    # 1. Test missing token entirely
    response = client.post("/ask", json={"model": "claude-sonnet-4-6", "query": "What is the status?"})
    assert response.status_code == 401

    # 2. Test invalid token
    headers = {"Authorization": "Bearer completely-wrong-token"}
    response = client.post("/ask", headers=headers, json={"model": "claude-sonnet-4-6", "query": "What is the status?"})
    assert response.status_code == 401


def test_fastapi_endpoint_authorized_success():
    headers = {"Authorization": f"Bearer {os.environ['CLAUDE_API_TOKEN']}"}
    mock_task = MagicMock()
    mock_task.returncode = 0
    mock_task.stdout = "Here is the status."

    mock_done = MagicMock()
    mock_done.returncode = 0
    mock_done.stdout = "DONE"

    expected_call = (
        [
            "claude", "--print", "--dangerously-skip-permissions",
            "--output-format", "json",
            "--mcp-config", "/home/appuser/sandbox/.mcp.json",
            "--model", "claude-sonnet-4-6",
            "--system-prompt", SYSTEM_PROMPT,
            "--", "What is the status?"],
    )
    expected_kwargs = dict(
        cwd="/home/appuser/sandbox",
        capture_output=True,
        text=True,
        timeout=600,
        env={
            **os.environ,
            "CLAUDE_CONFIG_DIR": "/home/appuser",
            "HOME": "/home/appuser",
            "ANTHROPIC_API_KEY": DYNAMIC_AGENT_KEY,
        }
    )

    with patch("server.subprocess.run", side_effect=[mock_task, mock_done]) as mock_run:
        response = client.post("/ask", headers=headers, json={"model": "claude-sonnet-4-6", "query": "What is the status?"})
        assert response.status_code == 200
        json_response = response.json()
        assert json_response["response"] == "Here is the status."
        assert mock_run.call_count == 2
        assert mock_run.call_args_list[0] == (expected_call, expected_kwargs)


def test_fastapi_endpoint_authorized_claude_error():
    headers = {"Authorization": f"Bearer {os.environ['CLAUDE_API_TOKEN']}"}
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "claude: error: subprocess failed"

    with patch("server.subprocess.run", return_value=mock_result):
        response = client.post("/ask", headers=headers, json={"model": "claude-sonnet-4-6", "query": "What is the status?"})
        assert response.status_code == 200
        json_response = response.json()
        assert "error" in json_response
        assert "subprocess failed" in json_response["error"]


def test_fastapi_endpoint_disallowed_model():
    headers = {"Authorization": f"Bearer {os.environ['CLAUDE_API_TOKEN']}"}
    response = client.post("/ask", headers=headers, json={"model": "bad-model", "query": "What is the status?"})
    assert response.status_code == 400
    assert "bad-model" in response.json()["detail"]


def test_fastapi_endpoint_timeout():
    import subprocess
    headers = {"Authorization": f"Bearer {os.environ['CLAUDE_API_TOKEN']}"}

    with patch("server.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=120)):
        response = client.post("/ask", headers=headers, json={"model": "claude-sonnet-4-6", "query": "Hang forever"})
        assert response.status_code == 200
        json_response = response.json()
        assert "error" in json_response
        assert "timed out" in json_response["error"]


def test_fastapi_endpoint_unexpected_exception():
    headers = {"Authorization": f"Bearer {os.environ['CLAUDE_API_TOKEN']}"}

    with patch("server.subprocess.run", side_effect=Exception("Unexpected failure")):
        response = client.post("/ask", headers=headers, json={"model": "claude-sonnet-4-6", "query": "Crash this"})
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
    headers = {"Authorization": f"Bearer {os.environ['CLAUDE_API_TOKEN']}"}
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = (
        "Calling plan_current... task t1 returned.\n"
        "Working on task...\n"
        "Calling run_tests... status: pass.\n"
        "Calling git_commit... committed.\n"
        "Calling plan_complete... done."
    )

    with patch("server.subprocess.run", return_value=mock_result) as mock_run:
        response = client.post("/ask", headers=headers, json={"model": "claude-sonnet-4-6", "query": "Run the plan loop"})
        assert response.status_code == 200
        json_response = response.json()
        assert "error" not in json_response
        call_args = mock_run.call_args
        assert "--system-prompt" in call_args[0][0]
        idx = call_args[0][0].index("--system-prompt")
        assert call_args[0][0][idx + 1] == SYSTEM_PROMPT


def test_plan_loop_block_after_retries():
    headers = {"Authorization": f"Bearer {os.environ['CLAUDE_API_TOKEN']}"}
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = (
        "Calling plan_current... task t2 returned.\n"
        "Attempt 1: run_tests failed.\n"
        "Attempt 2: run_tests failed.\n"
        "Attempt 3: run_tests failed.\n"
        "Calling plan_block... blocked due to repeated test failures."
    )

    with patch("server.subprocess.run", return_value=mock_result) as mock_run:
        response = client.post("/ask", headers=headers, json={"model": "claude-sonnet-4-6", "query": "Run the plan loop with failures"})
        assert response.status_code == 200
        json_response = response.json()
        assert "error" not in json_response
        call_args = mock_run.call_args
        assert "--system-prompt" in call_args[0][0]
        idx = call_args[0][0].index("--system-prompt")
        assert call_args[0][0][idx + 1] == SYSTEM_PROMPT


class TestModelAllowlist:
    def test_ask_rejects_unknown_model(self):
        headers = {"Authorization": f"Bearer {os.environ['CLAUDE_API_TOKEN']}"}
        response = client.post("/ask", headers=headers, json={"model": "gpt-4", "query": "hello"})
        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"]

    def test_plan_rejects_unknown_model(self):
        headers = {"Authorization": f"Bearer {os.environ['CLAUDE_API_TOKEN']}"}
        response = client.post("/plan", headers=headers, json={"model": "gpt-4", "query": "hello"})
        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"]

    def test_ask_accepts_allowed_model(self):
        headers = {"Authorization": f"Bearer {os.environ['CLAUDE_API_TOKEN']}"}
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "ok"
        with patch("server.subprocess.run", return_value=mock_result):
            response = client.post("/ask", headers=headers, json={"model": "claude-sonnet-4-6", "query": "hello"})
        assert response.status_code == 200

    def test_ask_rejects_empty_model(self):
        headers = {"Authorization": f"Bearer {os.environ['CLAUDE_API_TOKEN']}"}
        response = client.post("/ask", headers=headers, json={"model": "", "query": "hello"})
        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"]

    def test_model_validation_is_exact_match(self):
        headers = {"Authorization": f"Bearer {os.environ['CLAUDE_API_TOKEN']}"}
        response = client.post("/ask", headers=headers, json={"model": "claude-sonnet-4-6-evil", "query": "hello"})
        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"]
