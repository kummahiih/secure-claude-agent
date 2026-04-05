import os
import re
import json
import logging
import secrets
import subprocess
import threading
import time
from datetime import datetime, timezone
import requests
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import setuplogging
from runenv import CLAUDE_API_TOKEN, DYNAMIC_AGENT_KEY, ANTHROPIC_BASE_URL, MCP_API_TOKEN, PLAN_API_TOKEN, TESTER_API_TOKEN, GIT_API_TOKEN, LOG_SERVER_URL, LOG_API_TOKEN, PLAN_SERVER_URL, SYSTEM_PROMPT, PLAN_SYSTEM_PROMPT, ADHOC_SYSTEM_PROMPT
from verify_isolation import verify_all

logger = logging.getLogger(__name__)

COMMANDS_DIR = "/home/appuser/.claude/commands"

ALLOWED_MODELS: frozenset[str] = frozenset({
    "claude-sonnet-4-6",
    "claude-opus-4-6",
    "claude-haiku-4-5-20251001",
})


def _validate_model(model: str) -> str:
    """Raise HTTP 400 if model is not in ALLOWED_MODELS."""
    if model not in ALLOWED_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model}' is not allowed. Allowed models: {sorted(ALLOWED_MODELS)}",
        )
    return model

_SECRET_TOKENS = [
    t for t in [CLAUDE_API_TOKEN, DYNAMIC_AGENT_KEY, MCP_API_TOKEN, PLAN_API_TOKEN, TESTER_API_TOKEN, GIT_API_TOKEN, LOG_API_TOKEN]
    if t
]
_SECRET_RE = re.compile("|".join(re.escape(t) for t in _SECRET_TOKENS)) if _SECRET_TOKENS else None


def _redact_secrets(text: str) -> str:
    """Replace known secret token values in text with [REDACTED]."""
    if _SECRET_RE is None or not isinstance(text, str):
        return text
    return _SECRET_RE.sub("[REDACTED]", text)

_LOG_CA_BUNDLE = "/app/certs/ca.crt"


def _emit_log_event(event: dict) -> None:
    """POST one log event to log-server. Runs in a daemon thread; failures are non-fatal."""
    if not LOG_SERVER_URL or not LOG_API_TOKEN:
        return
    try:
        requests.post(
            f"{LOG_SERVER_URL}/ingest",
            json=event,
            headers={"Authorization": f"Bearer {LOG_API_TOKEN}"},
            verify=_LOG_CA_BUNDLE,
            timeout=5,
        )
    except Exception as exc:
        logger.warning(f"Log emission failed (non-critical): {exc}")


def _log_llm_call(session_id: str, model: str, parsed: dict, duration_ms: int) -> None:
    """Extract token counts from claude JSON output and fire-and-forget to log-server."""
    usage = parsed.get("usage") or {}
    event = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "session_id": session_id,
        "event_type": "llm_call",
        "model": model,
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
        "duration_ms": duration_ms,
    }
    threading.Thread(target=_emit_log_event, args=(event,), daemon=True).start()


def _parse_stream_json(stdout: str) -> tuple[list[dict], str, str | None, bool]:
    """Parse newline-delimited JSON from ``claude --output-format stream-json``.

    Returns (turn_usages, result_text, session_id, is_error) where:
    - turn_usages: list of per-turn usage dicts with keys
      input_tokens, output_tokens, cache_read_input_tokens,
      cache_creation_input_tokens
    - result_text: text from the ``result`` type message (or concatenated
      assistant content as fallback)
    - session_id: from the result message, or None
    - is_error: True when the result message's ``is_error`` flag is set
    """
    turn_usages: list[dict] = []
    result_text: str = ""
    session_id: str | None = None
    is_error: bool = False
    assistant_texts: list[str] = []
    found_result = False

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = obj.get("type")

        if msg_type == "assistant":
            # Collect usage if present
            usage = obj.get("message", {}).get("usage")
            if usage:
                turn_usages.append({
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "cache_read_input_tokens": usage.get("cache_read_input_tokens", 0),
                    "cache_creation_input_tokens": usage.get("cache_creation_input_tokens", 0),
                })
            # Collect assistant text content for fallback
            for block in obj.get("message", {}).get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    assistant_texts.append(block.get("text", ""))

        elif msg_type == "result":
            found_result = True
            result_text = obj.get("result", "")
            session_id = obj.get("session_id")
            is_error = bool(obj.get("is_error", False))

    if not found_result and assistant_texts:
        result_text = "".join(assistant_texts)

    return turn_usages, result_text, session_id, is_error


PATH_BLACKLIST = [
    "\0",
    "..",
    "~",
    ";",
    "|",
    "&",
    "`",
    "$",
    "!",
    "'",
    '"',
    "\\",
    "\n",
    "\r",
    "\t",
    ">",
    "<",
    "*",
    "?",
    "[",
    "{",
    "#",
]

def _expand_slash_command(query: str) -> str:
    """Expand a /command-name query into the contents of the matching .md file.

    claude --print does not honour user-defined slash commands (those only work
    in the interactive REPL).  When the caller sends "/architecture-doc" we
    load the corresponding prompt file and use that as the actual query so the
    agent receives the full instruction set.

    Queries that don't start with '/' are returned unchanged.
    """
    if not query.startswith("/"):
        return query
    # Strip the leading slash and any trailing whitespace/args
    parts = query[1:].split()
    if not parts:
        return query
    name = parts[0]
    # Harden against path traversal: keep only the final component
    name = os.path.basename(name)
    if not name or any(bad in name for bad in PATH_BLACKLIST):
        logger.warning(f"Rejected potentially malicious slash command name: {query!r}")
        return query
    cmd_path = os.path.join(COMMANDS_DIR, f"{name}.md")
    if os.path.isfile(cmd_path):
        logger.info(f"Expanding slash command /{name} from {cmd_path}")
        with open(cmd_path, encoding="utf-8") as fh:
            return fh.read()
    logger.warning(f"Unknown slash command: /{name} (no file at {cmd_path})")
    return query


def _check_upstream_errors(text: str) -> None:
    """Raise HTTPException if text contains upstream error markers."""
    if not text:
        return
        
    # Catch Auth Errors (502 Bad Gateway to proxy)
    if 'OAuth token has expired' in text or 'authentication_error' in text:
        raise HTTPException(
            status_code=502,
            detail='Upstream API authentication failure \u2014 please refresh your ANTHROPIC_API_KEY.',
        )
        
    # Catch Rate Limit Errors (429 Too Many Requests)
    if 'rate_limit_error' in text or '429' in text or 'Too Many Requests' in text:
        raise HTTPException(
            status_code=429,
            detail='Upstream API rate limit exceeded. Please try again later.'
        )

app = FastAPI(title="Secure Claude Code Server")
security = HTTPBearer()


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Validates the Bearer token in constant time to prevent timing attacks."""
    if not CLAUDE_API_TOKEN:
        logger.error("CLAUDE_API_TOKEN is not configured on the server.")
        raise HTTPException(status_code=500, detail="Server configuration error.")

    if not secrets.compare_digest(credentials.credentials, CLAUDE_API_TOKEN):
        logger.warning("Failed authentication attempt on /ask endpoint.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return credentials.credentials


class QueryRequest(BaseModel):
    query: str = Field(max_length=100_000)
    model: str = Field(max_length=200)  # kept for API compatibility, passed as --model to claude



@app.get("/health")
async def health_check():
    return {"status": "ok"}


_DONE_MARKER = "DONE"
_MAX_TASK_ITERATIONS = 50


def _has_active_plan_task() -> bool:
    """Return True if plan-server has an active task, False if none.

    Treats unreachable plan server or unknown errors as True (loop behaviour)
    so that existing logic is preserved when the plan server is unavailable.
    """
    if not PLAN_SERVER_URL or not PLAN_API_TOKEN:
        return True
    try:
        resp = requests.get(
            f"{PLAN_SERVER_URL}/current",
            headers={"Authorization": f"Bearer {PLAN_API_TOKEN}"},
            verify=_LOG_CA_BUNDLE,
            timeout=5,
        )
        if resp.status_code == 404:
            return False
        if resp.status_code == 200:
            return bool(resp.json().get("task"))
        return True  # Unknown status — default to loop
    except Exception:
        return False  # Unreachable — fall back to ad-hoc single invocation


def _run_subagent(query: str, model: str, system_prompt: str) -> tuple[dict, int]:
    """Spawn one claude --print subprocess and return (parsed_output, duration_ms)."""
    t0 = time.monotonic()
    result = subprocess.run(
        [
            "claude", "--print", "--dangerously-skip-permissions",
            "--output-format", "json",
            "--mcp-config", "/home/appuser/sandbox/.mcp.json",
            "--model", model,
            "--system-prompt", system_prompt,
            "--", query,
        ],
        cwd="/home/appuser/sandbox",
        capture_output=True,
        text=True,
        timeout=600,
        env={
            **os.environ,
            "CLAUDE_CONFIG_DIR": "/home/appuser",
            "HOME": "/home/appuser",
            "ANTHROPIC_API_KEY": DYNAMIC_AGENT_KEY,
        },
    )
    duration_ms = int((time.monotonic() - t0) * 1000)
    logger.debug(f"stdout: {_redact_secrets(result.stdout)!r}")
    logger.debug(f"stderr: {_redact_secrets(result.stderr)!r}")
    logger.debug(f"returncode: {result.returncode}")
    logger.info(
        f"Subagent completed: returncode={result.returncode} "
        f"stdout_bytes={len(result.stdout)} stderr_bytes={len(result.stderr)}"
    )
    return result, duration_ms


@app.post("/ask")
async def ask_agent(request: QueryRequest, token: str = Depends(verify_token)):
    """External endpoint routed through Caddy, secured with Bearer token.

    Loops through plan tasks, spawning a fresh claude --print subagent per task.
    Each subagent executes exactly one task then exits. The loop stops when the
    subagent outputs DONE (no remaining tasks) or on error.
    """
    logger.info(f"Received authenticated query: {request.query} for model: {request.model}")
    _validate_model(request.model)
    query = _expand_slash_command(request.query)

    task_responses: list[str] = []

    try:
        if not _has_active_plan_task():
            # No active plan task — single ad-hoc invocation, no DONE loop
            logger.info("No active plan task — running ad-hoc single invocation")
            session_id = secrets.token_hex(8)
            result, duration_ms = _run_subagent(query, request.model, ADHOC_SYSTEM_PROMPT)

            if result.returncode != 0:
                logger.error(f"Subagent exited with error: {_redact_secrets(result.stderr)}")
                _check_upstream_errors(result.stderr)
                return {"error": result.stderr}

            try:
                parsed = json.loads(result.stdout)
                if parsed.get("is_error"):
                    error_text = parsed.get("result", "Unknown error")
                    _check_upstream_errors(error_text)
                    return {"error": error_text}
                response_text = parsed.get("result", "")
                _log_llm_call(parsed.get("session_id") or session_id, request.model, parsed, duration_ms)
            except json.JSONDecodeError:
                response_text = result.stdout.strip()

            return {"response": response_text}

        for iteration in range(_MAX_TASK_ITERATIONS):
            logger.info(f"Spawning subagent iteration {iteration + 1}/{_MAX_TASK_ITERATIONS}")
            session_id = secrets.token_hex(8)

            result, duration_ms = _run_subagent(query, request.model, SYSTEM_PROMPT)

            if result.returncode != 0:
                logger.error(f"Subagent exited with error: {_redact_secrets(result.stderr)}")
                _check_upstream_errors(result.stderr)
                return {"error": result.stderr, "responses": task_responses}

            try:
                parsed = json.loads(result.stdout)
                if parsed.get("is_error"):
                    error_text = parsed.get("result", "Unknown error")
                    _check_upstream_errors(error_text)
                    return {"error": error_text, "responses": task_responses}
                response_text = parsed.get("result", "")
                _log_llm_call(parsed.get("session_id") or session_id, request.model, parsed, duration_ms)
            except json.JSONDecodeError:
                response_text = result.stdout.strip()

            task_responses.append(response_text)

            # Subagent signals no remaining tasks — stop the loop
            if response_text.strip() == _DONE_MARKER:
                logger.info("Subagent returned DONE — no more tasks.")
                break

            # Pre-spawn check: stop if plan-server has no remaining tasks
            if not _has_active_plan_task():
                logger.info("No remaining plan tasks — stopping loop")
                break

        combined = "\n\n---\n\n".join(r for r in task_responses if r.strip() != _DONE_MARKER)
        return {"response": combined or _DONE_MARKER}

    except subprocess.TimeoutExpired:
        logger.error("Subagent timed out.")
        return {"error": "Agent timed out.", "responses": task_responses}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Agent execution failed: {e}")
        return {"error": str(e)}


@app.post("/plan")
async def plan_agent(request: QueryRequest, token: str = Depends(verify_token)):
    """Planning endpoint — Claude produces a plan without writing code."""
    logger.info(f"Received planning query: {request.query} for model: {request.model}")
    _validate_model(request.model)
    query = _expand_slash_command(request.query)
    session_id = secrets.token_hex(8)
    try:
        t0 = time.monotonic()
        result = subprocess.run(
            [
                "claude", "--print", "--dangerously-skip-permissions",
                "--output-format", "json",
                "--mcp-config", "/home/appuser/sandbox/.mcp.json",
                "--model", request.model,
                "--system-prompt", PLAN_SYSTEM_PROMPT,
                "--", query],
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
        duration_ms = int((time.monotonic() - t0) * 1000)

        logger.debug(f"stdout: {_redact_secrets(result.stdout)!r}")
        logger.debug(f"stderr: {_redact_secrets(result.stderr)!r}")
        logger.debug(f"returncode: {result.returncode}")
        logger.info(f"Claude Code completed: returncode={result.returncode} stdout_bytes={len(result.stdout)} stderr_bytes={len(result.stderr)}")

        if result.returncode != 0:
            logger.error(f"Claude Code exited with error: {_redact_secrets(result.stderr)}")
            _check_upstream_errors(result.stderr)
            return {"error": result.stderr}

        try:
            parsed = json.loads(result.stdout)
            if parsed.get("is_error"):
                error_text = parsed.get("result", "Unknown error")
                _check_upstream_errors(error_text)
                return {"error": error_text}
            _log_llm_call(parsed.get("session_id") or session_id, request.model, parsed, duration_ms)
            return {"response": parsed.get("result", "")}
        except json.JSONDecodeError:
            return {"response": result.stdout.strip()}

    except subprocess.TimeoutExpired:
        logger.error("Claude Code timed out.")
        return {"error": "Agent timed out."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Agent execution failed: {e}")
        return {"error": str(e)}


if __name__ == "__main__":
    import uvicorn
    verify_all(role="claude-server")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        ssl_keyfile="/app/certs/agent.key",
        ssl_certfile="/app/certs/agent.crt"
    )