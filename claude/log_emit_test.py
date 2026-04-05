import os
import sys
import time
import pytest
from unittest.mock import patch, MagicMock

# Inject dummy env vars BEFORE importing
os.environ["LOG_SERVER_URL"] = "https://log-server:8443"
os.environ["LOG_API_TOKEN"] = "dummy-log-token"

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import log_emit
from log_emit import _emit_log_event


def _drain(timeout=1.0):
    """Wait briefly for background thread to complete."""
    time.sleep(timeout)


@patch("log_emit.requests.post")
def test_emit_posts_to_ingest(mock_post):
    mock_post.return_value.status_code = 200
    _emit_log_event({"event_type": "file_read", "path": "foo.py"})
    _drain()
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "https://log-server:8443/ingest"
    assert kwargs["json"] == {"event_type": "file_read", "path": "foo.py"}
    assert kwargs["headers"]["Authorization"] == "Bearer dummy-log-token"


@patch("log_emit.requests.post")
def test_emit_noop_when_url_empty(mock_post):
    original = log_emit.LOG_SERVER_URL
    log_emit.LOG_SERVER_URL = ""
    try:
        _emit_log_event({"event_type": "file_read"})
        _drain()
        mock_post.assert_not_called()
    finally:
        log_emit.LOG_SERVER_URL = original


@patch("log_emit.requests.post")
def test_emit_swallows_exception(mock_post):
    mock_post.side_effect = Exception("connection refused")
    # Should not raise
    _emit_log_event({"event_type": "test_run"})
    _drain()
    mock_post.assert_called_once()


@patch("log_emit.requests.post")
def test_emit_is_nonblocking(mock_post):
    """_emit_log_event returns before the POST completes."""
    import threading
    event = threading.Event()

    def slow_post(*args, **kwargs):
        event.wait(timeout=2)
        return MagicMock(status_code=200)

    mock_post.side_effect = slow_post
    start = time.monotonic()
    _emit_log_event({"event_type": "git_op"})
    elapsed = time.monotonic() - start
    # Should return almost immediately (well under 1s)
    assert elapsed < 0.5
    event.set()
    _drain()


@patch("log_emit.requests.post")
def test_emit_uses_bearer_token(mock_post):
    mock_post.return_value.status_code = 200
    _emit_log_event({"event_type": "file_read"})
    _drain()
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["Authorization"].startswith("Bearer ")


@patch("log_emit.requests.post")
def test_emit_uses_tls_verify(mock_post):
    mock_post.return_value.status_code = 200
    _emit_log_event({"event_type": "file_read"})
    _drain()
    _, kwargs = mock_post.call_args
    assert kwargs["verify"] == "/app/certs/ca.crt"
