# Agent Context

Implementation details specific to secure-claude-agent.

For cluster-level architecture, security model, and token isolation matrix,
see [docs/CONTEXT.md](../../../docs/CONTEXT.md) in the parent repo.

---

## claude-server Subprocess Call

```python
subprocess.run(
    ["claude", "--print", "--dangerously-skip-permissions",
     "--output-format", "json",
     "--mcp-config", "/home/appuser/sandbox/.mcp.json",
     "--model", request.model,
     "--system-prompt", SYSTEM_PROMPT,
     "--", request.query],
    timeout=600,
    env={..., "ANTHROPIC_API_KEY": DYNAMIC_AGENT_KEY}
)
```

### System prompt behavior

- `/plan` endpoint: Claude reads docs, creates plan via plan_create. No code execution.
- `/ask` endpoint: Claude calls plan_current first. If a task exists, works on it, then calls plan_complete. If no plan, proceeds normally.
- API contract protection: system prompt instructs Claude not to change existing interfaces unless explicitly required.

---

## Prompts

All prompt content lives in `cluster/agent/prompts/` and is baked into the
claude-server image at build time (no runtime bind-mount).

### System prompts (`prompts/system/`)

Copied to `/app/prompts/` inside the image. Read by `runenv.py` at startup and
held in memory as `SYSTEM_PROMPT` / `PLAN_SYSTEM_PROMPT`. Passed to Claude Code
via `--system-prompt <text>` in the subprocess call.

| File | Variable | Endpoint | Purpose |
| :--- | :--- | :--- | :--- |
| ask.md | SYSTEM_PROMPT | POST /ask | Instructs Claude to execute tasks, follow the active plan, run tests, and commit |
| plan.md | PLAN_SYSTEM_PROMPT | POST /plan | Instructs Claude to produce a plan only — no code execution |

### Slash commands (`prompts/commands/`)

Copied to `/home/appuser/.claude/commands/` inside the image. Discovered and
invoked by Claude Code at runtime as `/command-name`.

| File | Slash command | Purpose |
| :--- | :--- | :--- |
| architecture-doc.md | /architecture-doc | Generate an architecture document for the workspace |
| make-presentation.md | /make-presentation | Generate a presentation outline |
| threat-model.md | /threat-model | Generate a threat model for the workspace |

### Editing conventions

- Plain Markdown only — no shell variables, no template expansion.
- Keep system prompts self-contained: Claude Code receives no other context about
  the cluster from the prompt itself (it reads `docs/CONTEXT.md` via the docs MCP).
- The directory tree inside the image is owned by root and mode 444/555 so the
  agent cannot modify its own prompts at runtime.

---

## Git Hook Prevention (3 layers)

1. mcp-server: `/dev/null` shadow on `.git` — fileserver can't see git data
2. claude-server: gitdir at `/gitdir` — fileserver MCP can't reach hooks
3. git_mcp.py: `core.hooksPath=/dev/null` + `--no-verify` on every call

---

## Git History Protection

A baseline commit floor is established at container startup, preventing the agent
from erasing pre-existing history via `git_reset_soft`.

---

## Startup Isolation Checks (verify_isolation.py)

26 checks run at container startup. These verify credential separation, filesystem
boundaries, and mount correctness. Checks run only at startup, never in MCP
subprocess children — Claude Code passes ANTHROPIC_API_KEY to children, which
would false-positive.

---

## MCP Config as Build Artifact

`.mcp.json` is baked into the Docker image at build time. The agent cannot modify
its own tool registrations at runtime. Five MCP servers are registered: fileserver,
git, docs, planner, and tester.

---

## Fileserver MCP Tools

The fileserver MCP exposes 9 tools over stdio → HTTPS REST → Go fileserver:

| Tool | Purpose |
| :--- | :--- |
| list_files | Recursively list all files in /workspace |
| read_workspace_file | Read a file |
| create_file | Create a new empty file |
| write_file | Overwrite entire file contents |
| delete_file | Remove a file |
| grep_files | Regex search across all files; returns `file:lineno: line` matches |
| replace_in_file | Replace all occurrences of a string in a file |
| append_file | Append content to a file |
| create_directory | Create a new directory |

---

## Tester MCP Tools

The tester MCP exposes 2 tools over stdio → HTTPS REST → tester-server:

| Tool | Purpose |
| :--- | :--- |
| run_tests | Start an async test run (executes /workspace/test.sh). Returns 409 if already running. |
| get_test_results | Get last test result as JSON (status, exit_code, timestamp, output) |

The tester-server runs tests as direct subprocesses — no Docker socket required.
The workspace is mounted read-only so tests cannot modify source code.

---

## Environment Variables (runenv.py)

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| MCP_SERVER_URL | https://mcp-server:8443 | Fileserver REST endpoint |
| PLAN_SERVER_URL | https://plan-server:8443 | Plan-server REST endpoint |
| TESTER_SERVER_URL | https://tester-server:8443 | Tester-server REST endpoint |
| MCP_API_TOKEN | (required) | Bearer token for internal services |
| CLAUDE_API_TOKEN | (required) | Bearer token for ingress auth |
| DYNAMIC_AGENT_KEY | (required) | Ephemeral API key for LiteLLM proxy |
| ANTHROPIC_BASE_URL | (required) | LiteLLM proxy URL |

`docs/mcp-tools.json` is a reference copy of all MCP tool schemas, readable via
`read_doc` from the docs MCP tool.
