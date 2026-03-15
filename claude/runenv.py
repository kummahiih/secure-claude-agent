import os
import setuplogging
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "You do NOT have access to the local filesystem. You have NO local file tools. The ONLY way to read, write, list, or delete files is through the MCP fileserver tools (read_workspace_file, list_files, create_file, write_file, delete_file). Always start by calling list_files to see what exists. Never attempt to access files by local path."

# Environment variables injected by Docker Compose / run.sh
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "https://mcp-server:8443")
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


