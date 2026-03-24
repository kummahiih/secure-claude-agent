import os
import setuplogging
import logging

logger = logging.getLogger(__name__)

from pathlib import Path

_PROMPT_DIR = Path("/app/prompts")

def _load_prompt(name: str) -> str:
    """Load a system prompt from disk. Fails hard if missing."""
    path = _PROMPT_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"System prompt not found: {path}")
    return path.read_text(encoding="utf-8").strip()

SYSTEM_PROMPT = _load_prompt("ask.md")
PLAN_SYSTEM_PROMPT = _load_prompt("plan.md")


# Environment variables injected by Docker Compose / run.sh
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "https://mcp-server:8443")
PLAN_SERVER_URL = os.environ.get("PLAN_SERVER_URL", "https://plan-server:8443")
TESTER_SERVER_URL = os.environ.get("TESTER_SERVER_URL", "https://tester-server:8443")

MCP_API_TOKEN = os.getenv("MCP_API_TOKEN")
if not MCP_API_TOKEN:
    logging.error("MCP_API_TOKEN is not set!")

CLAUDE_API_TOKEN = os.getenv("CLAUDE_API_TOKEN")
if not CLAUDE_API_TOKEN:
    logging.error("CLAUDE_API_TOKEN is not set!")

DYNAMIC_AGENT_KEY = os.getenv("DYNAMIC_AGENT_KEY")
# Ensure we have the key, otherwise the agent will fail silently with 401s
if not DYNAMIC_AGENT_KEY:
    logging.error("DYNAMIC_AGENT_KEY (passed as DYNAMIC_AGENT_KEY) is not set!")

ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL")
if not ANTHROPIC_BASE_URL:
    logging.error("ANTHROPIC_BASE_URL is not set!")


