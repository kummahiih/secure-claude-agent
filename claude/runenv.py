import os
import setuplogging
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PROMPT_DIR = Path(os.environ.get("PROMPT_SYSTEM_DIR", "/app/prompts"))

def _load_prompt(name: str) -> str:
    """Load a system prompt from disk. Graceful fallback if missing in sidecars."""
    path = _PROMPT_DIR / name
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()

SYSTEM_PROMPT = _load_prompt("ask.md")
PLAN_SYSTEM_PROMPT = _load_prompt("plan.md")

# Environment variables injected by Docker Compose / run.sh
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "https://mcp-server:8443")
PLAN_SERVER_URL = os.environ.get("PLAN_SERVER_URL", "https://plan-server:8443")
TESTER_SERVER_URL = os.environ.get("TESTER_SERVER_URL", "https://tester-server:8443")

# Fetch tokens. 
# Do NOT log errors here on missing tokens! 
# verify_isolation.py enforces strict token isolation, meaning these 
# WILL intentionally be missing depending on the container role.
MCP_API_TOKEN = os.getenv("MCP_API_TOKEN")
PLAN_API_TOKEN = os.getenv("PLAN_API_TOKEN")
TESTER_API_TOKEN = os.getenv("TESTER_API_TOKEN")
CLAUDE_API_TOKEN = os.getenv("CLAUDE_API_TOKEN")
DYNAMIC_AGENT_KEY = os.getenv("DYNAMIC_AGENT_KEY")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL")