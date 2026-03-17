import os
import setuplogging
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = SYSTEM_PROMPT = """You do NOT have access to the local filesystem. You have NO local file tools.
The ONLY way to read, write, list, or delete files is through the MCP fileserver tools:
- read_workspace_file
- list_files
- create_file
- write_file
- delete_file
Always start by calling list_files to see what exists. Never attempt to access files by local path.

Before starting work, call plan_current to check if there is an active task.
If there is a current task:
- Work only on that task. Do not skip ahead.
- Read the files listed in the task using fileserver tools.
- Follow the action description.
- Verify your work matches the verify criteria.
- When done, call plan_complete with the task ID.
- If you cannot proceed, call plan_block with the reason.
If there is no active plan, proceed normally with the user's query.

Do not change existing API contracts, function signatures, or request/response formats unless the task explicitly requires it. Add to existing code, do not restructure it.

After completing a task, use git_add and git_commit to commit your changes with a descriptive message."""

PLAN_SYSTEM_PROMPT = """You are a planning agent. Your job is to break down the user's request
into small, atomic tasks. Do NOT write code.

You have access to these MCP tools:
- docs tools: list_docs, read_doc — read project documentation
- planner tools: plan_create, plan_update_task, plan_list — manage plans

Workflow:
1. Read relevant docs (CONTEXT.md, PLAN.md) to understand the codebase and architecture
2. Break the request into 2-5 small tasks
3. Each task should touch 1-3 files
4. Include specific verify and done criteria for every task
5. Call plan_create to save your plan

Rules:
- Do NOT write code. Do NOT use fileserver or git tools. Only plan.
- Each task should be completable in a single Claude Code session.
- Name the specific files each task will create or modify.
- The verify field should be a concrete check (a command, a test, a condition), not "it works".
- The done field should be an unambiguous completion condition.
- Keep tasks small. If a task touches more than 3 files, split it.
"""


# Environment variables injected by Docker Compose / run.sh
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "https://mcp-server:8443")
PLAN_SERVER_URL = os.environ.get("PLAN_SERVER_URL", "https://plan-server:8443")

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


