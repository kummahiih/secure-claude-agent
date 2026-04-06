import os
import sys
import pytest
import json
from unittest.mock import patch

# Inject dummy env vars BEFORE importing
os.environ.setdefault("LOG_API_TOKEN", "dummy-log-token")
os.environ.setdefault("LOG_SERVER_URL", "https://log-server:8443")

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from log_mcp import _dispatch, call_tool


# --- list_sessions ---

@pytest.mark.asyncio
@patch("log_mcp.requests.get")
async def test_list_sessions_success(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = [{"session_id": "s1"}]
    result = await _dispatch("list_sessions", {})
    data = json.loads(result)
    assert data[0]["session_id"] == "s1"
    args, kwargs = mock_get.call_args
    assert "/sessions" in args[0]
    assert "Authorization" in kwargs["headers"]


@pytest.mark.asyncio
@patch("log_mcp.requests.get")
async def test_list_sessions_with_params(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = []
    await _dispatch("list_sessions", {"limit": 10, "since": "2026-01-01T00:00:00Z"})
    _, kwargs = mock_get.call_args
    assert kwargs["params"]["limit"] == 10
    assert kwargs["params"]["since"] == "2026-01-01T00:00:00Z"


@pytest.mark.asyncio
@patch("log_mcp.requests.get")
async def test_list_sessions_unauthorized(mock_get):
    mock_get.return_value.status_code = 401
    with pytest.raises(PermissionError, match="Unauthorized"):
        await _dispatch("list_sessions", {})


@pytest.mark.asyncio
@patch("log_mcp.requests.get")
async def test_list_sessions_server_error(mock_get):
    mock_get.return_value.status_code = 500
    mock_get.return_value.text = "internal error"
    with pytest.raises(RuntimeError, match="500"):
        await _dispatch("list_sessions", {})


# --- get_session_summary ---

@pytest.mark.asyncio
@patch("log_mcp.requests.get")
async def test_get_session_summary_success(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"session_id": "s1", "total_tokens": 1000}
    result = await _dispatch("get_session_summary", {"session_id": "s1"})
    data = json.loads(result)
    assert data["total_tokens"] == 1000
    args, _ = mock_get.call_args
    assert "/sessions/s1/summary" in args[0]


@pytest.mark.asyncio
@patch("log_mcp.requests.get")
async def test_get_session_summary_not_found(mock_get):
    mock_get.return_value.status_code = 404
    with pytest.raises(FileNotFoundError):
        await _dispatch("get_session_summary", {"session_id": "missing"})


@pytest.mark.asyncio
@patch("log_mcp.requests.get")
async def test_get_session_summary_unauthorized(mock_get):
    mock_get.return_value.status_code = 401
    with pytest.raises(PermissionError, match="Unauthorized"):
        await _dispatch("get_session_summary", {"session_id": "s1"})


# --- query_logs ---

@pytest.mark.asyncio
@patch("log_mcp.requests.post")
async def test_query_logs_success(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = [{"event": "llm_call"}]
    result = await _dispatch("query_logs", {"session_id": "s1", "event_type": "llm_call"})
    data = json.loads(result)
    assert data[0]["event"] == "llm_call"
    args, kwargs = mock_post.call_args
    assert "/sessions/s1/query" in args[0]
    assert kwargs["json"]["event_type"] == "llm_call"


@pytest.mark.asyncio
@patch("log_mcp.requests.post")
async def test_query_logs_with_time_range(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = []
    time_range = {"from": "2026-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z"}
    await _dispatch("query_logs", {"session_id": "s1", "time_range": time_range})
    _, kwargs = mock_post.call_args
    assert kwargs["json"]["time_range"] == time_range


@pytest.mark.asyncio
@patch("log_mcp.requests.post")
async def test_query_logs_no_filter(mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = []
    await _dispatch("query_logs", {"session_id": "s1"})
    _, kwargs = mock_post.call_args
    assert "event_type" not in kwargs["json"]


@pytest.mark.asyncio
@patch("log_mcp.requests.post")
async def test_query_logs_not_found(mock_post):
    mock_post.return_value.status_code = 404
    with pytest.raises(FileNotFoundError):
        await _dispatch("query_logs", {"session_id": "missing"})


@pytest.mark.asyncio
@patch("log_mcp.requests.post")
async def test_query_logs_unauthorized(mock_post):
    mock_post.return_value.status_code = 401
    with pytest.raises(PermissionError, match="Unauthorized"):
        await _dispatch("query_logs", {"session_id": "s1"})


# --- get_token_breakdown ---

@pytest.mark.asyncio
@patch("log_mcp.requests.get")
async def test_get_token_breakdown_success(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = [{"input_tokens": 500, "output_tokens": 200}]
    result = await _dispatch("get_token_breakdown", {"session_id": "s1"})
    data = json.loads(result)
    assert data[0]["input_tokens"] == 500
    args, _ = mock_get.call_args
    assert "/sessions/s1/tokens" in args[0]


@pytest.mark.asyncio
@patch("log_mcp.requests.get")
async def test_get_token_breakdown_not_found(mock_get):
    mock_get.return_value.status_code = 404
    with pytest.raises(FileNotFoundError):
        await _dispatch("get_token_breakdown", {"session_id": "missing"})


@pytest.mark.asyncio
@patch("log_mcp.requests.get")
async def test_get_token_breakdown_unauthorized(mock_get):
    mock_get.return_value.status_code = 401
    with pytest.raises(PermissionError, match="Unauthorized"):
        await _dispatch("get_token_breakdown", {"session_id": "s1"})


# --- unknown tool ---

@pytest.mark.asyncio
async def test_unknown_tool():
    with pytest.raises(ValueError, match="Unknown tool"):
        await _dispatch("nonexistent_tool", {})


# --- tool count ---

@pytest.mark.asyncio
async def test_tool_count():
    from log_mcp import list_tools
    tools = await list_tools()
    assert len(tools) == 5
    names = {t.name for t in tools}
    assert names == {"list_sessions", "get_session_summary", "query_logs", "get_token_breakdown", "get_file_dedup_report"}


# --- call_tool: success returns isError=False ---

@pytest.mark.asyncio
@patch("log_mcp.requests.get")
async def test_call_tool_success(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = []
    result = await call_tool("list_sessions", {})
    assert result.isError is False


# --- call_tool: error returns isError=True ---

@pytest.mark.asyncio
@patch("log_mcp.requests.get")
async def test_call_tool_error(mock_get):
    mock_get.return_value.status_code = 401
    result = await call_tool("list_sessions", {})
    assert result.isError is True


@pytest.mark.asyncio
async def test_call_tool_unknown():
    result = await call_tool("nonexistent_tool", {})
    assert result.isError is True
    assert "Unknown tool" in result.content[0].text
