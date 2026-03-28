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

from tester_mcp import _dispatch, call_tool


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
    assert data["status"] == "pass"
    assert data["exit_code"] == 0
    assert "all tests passed" in data["output"]


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
