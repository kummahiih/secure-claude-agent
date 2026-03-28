import os
import json
import logging
import secrets
import subprocess
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import setuplogging
from runenv import CLAUDE_API_TOKEN, DYNAMIC_AGENT_KEY, ANTHROPIC_BASE_URL, MCP_API_TOKEN, SYSTEM_PROMPT, PLAN_SYSTEM_PROMPT
from verify_isolation import verify_all

logger = logging.getLogger(__name__)

COMMANDS_DIR = "/home/appuser/.claude/commands"


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
    name = query[1:].split()[0]
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
    query: str
    model: str  # kept for API compatibility, passed as --model to claude



@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/ask")
async def ask_agent(request: QueryRequest, token: str = Depends(verify_token)):
    """External endpoint routed through Caddy, secured with Bearer token."""
    logger.info(f"Received authenticated query: {request.query} for model: {request.model}")
    query = _expand_slash_command(request.query)
    try:
        result = subprocess.run(
            [
                "claude", "--print", "--dangerously-skip-permissions",
                "--output-format", "json",
                "--mcp-config", "/home/appuser/sandbox/.mcp.json",
                "--model", request.model,
                "--system-prompt", SYSTEM_PROMPT,
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

        logger.info(f"stdout: {result.stdout!r}")
        logger.info(f"stderr: {result.stderr!r}")
        logger.info(f"returncode: {result.returncode}")
        logger.info(f"result: {result!r}")

        if result.returncode != 0:
            logger.error(f"Claude Code exited with error: {result.stderr}")
            _check_upstream_errors(result.stderr)
            return {"error": result.stderr}

        try:
            parsed = json.loads(result.stdout)
            if parsed.get("is_error"):
                error_text = parsed.get("result", "Unknown error")
                _check_upstream_errors(error_text)
                return {"error": error_text}
            return {"response": parsed.get("result", "")}
        except json.JSONDecodeError:
            # fallback in case output is plain text
            return {"response": result.stdout.strip()}

    except subprocess.TimeoutExpired:
        logger.error("Claude Code timed out.")
        return {"error": "Agent timed out."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Agent execution failed: {e}")
        return {"error": str(e)}


@app.post("/plan")
async def plan_agent(request: QueryRequest, token: str = Depends(verify_token)):
    """Planning endpoint — Claude produces a plan without writing code."""
    logger.info(f"Received planning query: {request.query} for model: {request.model}")
    query = _expand_slash_command(request.query)
    try:
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

        logger.info(f"stdout: {result.stdout!r}")
        logger.info(f"stderr: {result.stderr!r}")
        logger.info(f"returncode: {result.returncode}")

        if result.returncode != 0:
            logger.error(f"Claude Code exited with error: {result.stderr}")
            _check_upstream_errors(result.stderr)
            return {"error": result.stderr}

        try:
            parsed = json.loads(result.stdout)
            if parsed.get("is_error"):
                error_text = parsed.get("result", "Unknown error")
                _check_upstream_errors(error_text)
                return {"error": error_text}
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