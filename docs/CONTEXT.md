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
    timeout=300,
    env={..., "ANTHROPIC_API_KEY": DYNAMIC_AGENT_KEY}
)
```

### System prompt behavior

- `/plan` endpoint: Claude reads docs, creates plan via plan_create. No code execution.
- `/ask` endpoint: Claude calls plan_current first. If a task exists, works on it, then calls plan_complete. If no plan, proceeds normally.
- API contract protection: system prompt instructs Claude not to change existing interfaces unless explicitly required.

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
its own tool registrations at runtime.

---

## Fileserver MCP Tools

The fileserver MCP exposes 8 tools over stdio → HTTPS REST → Go fileserver:

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

`docs/mcp-tools.json` is a reference copy of all MCP tool schemas, readable via
`read_doc` from the docs MCP tool.
