import os
import sys
import pytest
import json
from unittest.mock import patch, MagicMock

# Inject dummy env vars BEFORE importing
os.environ["MCP_API_TOKEN"] = "dummy-mcp-token"
os.environ["TESTER_API_TOKEN"] = "dummy-tester-token"
os.environ["MCP_SERVER_URL"] = "https://mcp-server:8443"
os.environ["TESTER_SERVER_URL"] = "https://tester-server:8443"

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from tester_mcp import _dispatch, call_tool, _reset_strike_counter


# Ensure state is clean before every test
@pytest.fixture(autouse=True)
def reset_state():
    _reset_strike_counter()


# --- _dispatch: run_tests ---

@pytest.mark.asyncio
@patch("tester_mcp.requests.post")
async def test_run_tests_success(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"status": "started"}
    result = await _dispatch("run_tests", {})
    data = json.loads(result)
    assert data["status"] == "started"
    args, kwargs = mock_post.call_args
    assert "/run" in args[0]
    assert "Authorization" in kwargs["headers"]


@pytest.mark.asyncio
@patch("tester_mcp.requests.post")
async def test_run_tests_unauthorized(mock_post):
    mock_post.return_value.status_code = 401
    with pytest.raises(PermissionError, match="Unauthorized"):
        await _dispatch("run_tests", {})


@pytest.mark.asyncio
@patch("tester_mcp.requests.post")
async def test_run_tests_already_running(mock_post):
    mock_post.return_value.status_code = 409
    mock_post.return_value.text = "test run already in progress"
    with pytest.raises(RuntimeError, match="already in progress"):
        await _dispatch("run_tests", {})


@pytest.mark.asyncio
@patch("tester_mcp.requests.post")
async def test_run_tests_server_error(mock_post):
    mock_post.return_value.status_code = 500
    mock_post.return_value.text = "internal error"
    with pytest.raises(RuntimeError, match="500"):
        await _dispatch("run_tests", {})


@pytest.mark.asyncio
@patch("tester_mcp.requests.post")
async def test_run_tests_connection_failure(mock_post):
    mock_post.side_effect = Exception("Connection refused")
    with pytest.raises(Exception, match="Connection refused"):
        await _dispatch("run_tests", {})


# --- _dispatch: get_test_results ---

@pytest.mark.asyncio
@patch("tester_mcp.requests.get")
async def test_get_results_pass(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "status": "pass",
        "exit_code": 0,
        "timestamp": "2026-03-19T20:00:00Z",
        "output": "all tests passed"
    }
    result = await _dispatch("get_test_results", {})
    data = json.loads(result)
    assert data == {"status": "pass", "exit_code": 0}
    assert "output" not in data
    assert "timestamp" not in data


@pytest.mark.asyncio
@patch("tester_mcp.requests.get")
async def test_get_results_fail(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "status": "fail",
        "exit_code": 1,
        "timestamp": "2026-03-19T20:00:00Z",
        "output": "FAIL: test_something"
    }
    result = await _dispatch("get_test_results", {})
    data = json.loads(result)
    assert data["status"] == "fail"
    assert data["exit_code"] == 1
    assert "output" in data


@pytest.mark.asyncio
@patch("tester_mcp.requests.get")
async def test_get_results_fail_truncates_long_output(mock_get):
    long_output = "\n".join(f"line {i}" for i in range(100))
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "status": "fail",
        "exit_code": 1,
        "timestamp": "2026-03-19T20:00:00Z",
        "output": long_output
    }
    result = await _dispatch("get_test_results", {})
    data = json.loads(result)
    assert len(data["output"].splitlines()) == 50


@pytest.mark.asyncio
@patch("tester_mcp.requests.get")
async def test_get_results_fail_short_output_unchanged(mock_get):
    short_output = "\n".join(f"line {i}" for i in range(10))
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "status": "fail",
        "exit_code": 1,
        "timestamp": "2026-03-19T20:00:00Z",
        "output": short_output
    }
    result = await _dispatch("get_test_results", {})
    data = json.loads(result)
    assert len(data["output"].splitlines()) == 10


@pytest.mark.asyncio
@patch("tester_mcp.requests.get")
async def test_get_results_running(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "status": "running",
        "exit_code": 0,
        "timestamp": "2026-03-19T20:00:00Z",
        "output": ""
    }
    result = await _dispatch("get_test_results", {})
    data = json.loads(result)
    assert data["status"] == "running"


@pytest.mark.asyncio
@patch("tester_mcp.requests.get")
async def test_get_results_pending(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "status": "pending",
        "exit_code": 0,
        "timestamp": "",
        "output": ""
    }
    result = await _dispatch("get_test_results", {})
    data = json.loads(result)
    assert data["status"] == "pending"


@pytest.mark.asyncio
@patch("tester_mcp.requests.get")
async def test_get_results_unauthorized(mock_get):
    mock_get.return_value.status_code = 401
    with pytest.raises(PermissionError, match="Unauthorized"):
        await _dispatch("get_test_results", {})


@pytest.mark.asyncio
@patch("tester_mcp.requests.get")
async def test_get_results_server_error(mock_get):
    mock_get.return_value.status_code = 500
    mock_get.return_value.text = "internal error"
    with pytest.raises(RuntimeError, match="500"):
        await _dispatch("get_test_results", {})


@pytest.mark.asyncio
@patch("tester_mcp.requests.get")
async def test_get_results_connection_failure(mock_get):
    mock_get.side_effect = Exception("Connection refused")
    with pytest.raises(Exception, match="Connection refused"):
        await _dispatch("get_test_results", {})


# --- _dispatch: 3-Strike Rule ---

@pytest.mark.asyncio
@patch("tester_mcp.requests.get")
@patch("tester_mcp.requests.post")
async def test_3_strike_rule_blocks_run(mock_post, mock_get):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"status": "started"}

    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"status": "fail"}

    # Strike 1
    await _dispatch("run_tests", {})
    await _dispatch("get_test_results", {})

    # Strike 2
    await _dispatch("run_tests", {})
    await _dispatch("get_test_results", {})

    # Strike 3
    await _dispatch("run_tests", {})
    await _dispatch("get_test_results", {})

    # 4th run attempt should be blocked
    with pytest.raises(RuntimeError, match="HARD STOP"):
        await _dispatch("run_tests", {})


@pytest.mark.asyncio
@patch("tester_mcp.requests.get")
@patch("tester_mcp.requests.post")
async def test_3_strike_rule_resets_on_pass(mock_post, mock_get):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"status": "started"}

    # Strike 1 & 2
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"status": "fail"}
    await _dispatch("run_tests", {})
    await _dispatch("get_test_results", {})
    await _dispatch("run_tests", {})
    await _dispatch("get_test_results", {})

    # Pass resets the counter
    mock_get.return_value.json.return_value = {"status": "pass"}
    await _dispatch("run_tests", {})
    await _dispatch("get_test_results", {})

    # Two more fails shouldn't block
    mock_get.return_value.json.return_value = {"status": "fail"}
    await _dispatch("run_tests", {})
    await _dispatch("get_test_results", {})
    await _dispatch("run_tests", {})
    await _dispatch("get_test_results", {})

    # 3rd run after pass is allowed
    await _dispatch("run_tests", {})


# --- get_test_results: wait=true and timeout=330 ---

@pytest.mark.asyncio
@patch("tester_mcp.requests.get")
async def test_get_results_uses_wait_param(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "status": "pass", "exit_code": 0, "timestamp": "", "output": ""
    }
    await _dispatch("get_test_results", {})
    args, kwargs = mock_get.call_args
    assert "wait=true" in args[0]


@pytest.mark.asyncio
@patch("tester_mcp.requests.get")
async def test_get_results_uses_long_timeout(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "status": "pass", "exit_code": 0, "timestamp": "", "output": ""
    }
    await _dispatch("get_test_results", {})
    _, kwargs = mock_get.call_args
    assert kwargs["timeout"] == 330


# --- _dispatch: unknown tool ---

@pytest.mark.asyncio
async def test_unknown_tool():
    with pytest.raises(ValueError, match="Unknown tool"):
        await _dispatch("nonexistent_tool", {})


# --- call_tool: success returns isError=False ---

@pytest.mark.asyncio
@patch("tester_mcp.requests.get")
async def test_call_tool_success(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "status": "pass", "exit_code": 0, "timestamp": "", "output": ""
    }
    result = await call_tool("get_test_results", {})
    assert result.isError is False
    data = json.loads(result.content[0].text)
    assert data["status"] == "pass"


# --- call_tool: error returns isError=True ---

@pytest.mark.asyncio
@patch("tester_mcp.requests.get")
async def test_call_tool_error(mock_get):
    mock_get.return_value.status_code = 401
    result = await call_tool("get_test_results", {})
    assert result.isError is True
    assert len(result.content) > 0


@pytest.mark.asyncio
async def test_call_tool_unknown():
    result = await call_tool("nonexistent_tool", {})
    assert result.isError is True
    assert "Unknown tool" in result.content[0].text

# --- test_run log event emission ---

@pytest.mark.asyncio
@patch("tester_mcp.threading.Thread")
@patch("tester_mcp.requests.get")
async def test_get_results_emits_log_event_on_pass(mock_get, mock_thread):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "status": "pass", "exit_code": 0, "timestamp": "", "output": "ok"
    }
    mock_thread_instance = MagicMock()
    mock_thread.return_value = mock_thread_instance

    await _dispatch("get_test_results", {})

    mock_thread.assert_called_once()
    _, kwargs = mock_thread.call_args
    event = kwargs["args"][0]
    assert event["event_type"] == "test_run"
    assert event["exit_code"] == 0
    assert event["output_size_bytes"] == len("ok")
    assert kwargs["daemon"] is True
    mock_thread_instance.start.assert_called_once()


@pytest.mark.asyncio
@patch("tester_mcp.threading.Thread")
@patch("tester_mcp.requests.get")
async def test_get_results_emits_log_event_on_fail(mock_get, mock_thread):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "status": "fail", "exit_code": 1, "timestamp": "", "output": "FAILED test_foo"
    }
    mock_thread_instance = MagicMock()
    mock_thread.return_value = mock_thread_instance

    await _dispatch("get_test_results", {})

    mock_thread.assert_called_once()
    _, kwargs = mock_thread.call_args
    event = kwargs["args"][0]
    assert event["event_type"] == "test_run"
    assert event["exit_code"] == 1
    assert event["output_size_bytes"] == len("FAILED test_foo")


@pytest.mark.asyncio
@patch("tester_mcp.threading.Thread")
@patch("tester_mcp.requests.get")
async def test_get_results_emits_duration_ms_when_present(mock_get, mock_thread):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "status": "pass", "exit_code": 0, "timestamp": "", "output": "", "duration_ms": 1234
    }
    mock_thread_instance = MagicMock()
    mock_thread.return_value = mock_thread_instance

    await _dispatch("get_test_results", {})

    _, kwargs = mock_thread.call_args
    event = kwargs["args"][0]
    assert event["duration_ms"] == 1234


@pytest.mark.asyncio
@patch("tester_mcp.threading.Thread")
@patch("tester_mcp.requests.get")
async def test_get_results_does_not_emit_on_running(mock_get, mock_thread):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "status": "running", "exit_code": 0, "timestamp": "", "output": ""
    }

    await _dispatch("get_test_results", {})

    mock_thread.assert_not_called()


@pytest.mark.asyncio
@patch("tester_mcp.threading.Thread")
@patch("tester_mcp.requests.get")
async def test_get_results_does_not_emit_on_pending(mock_get, mock_thread):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "status": "pending", "exit_code": 0, "timestamp": "", "output": ""
    }

    await _dispatch("get_test_results", {})

    mock_thread.assert_not_called()
