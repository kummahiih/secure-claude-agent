# Secure Claude Agent

MCP tool servers and Claude Code integration for the [secure-claude](../../) cluster. This repo is mounted as `/workspace` when the agent is developing its own code.

## What's Inside

This repo contains the code that runs inside `claude-server` — the FastAPI application that wraps Claude Code CLI, plus four MCP stdio servers that give Claude access to files, git, documentation, and planning tools.

```
secure-claude-agent/
├── claude/
│   ├── app.py                  # FastAPI server (POST /ask, POST /plan)
│   ├── verify_isolation.py     # 26 startup isolation checks
│   ├── files_mcp.py            # File operations → HTTPS REST → mcp-server
│   ├── git_mcp.py              # Git operations → subprocess
│   ├── docs_mcp.py             # Read-only docs access
│   └── plan_mcp.py             # Plan operations → HTTPS REST → plan-server
├── fileserver/                 # Go REST server (mcp-server container)
│   ├── main.go                 # os.OpenRoot jail at /workspace
│   └── main_test.go
├── docs/
│   ├── CONTEXT.md              # Architecture and security details
│   └── PLAN.md                 # Development roadmap
└── README.md
```

## MCP Tool Sets

| Tool Set | Tools | Transport | Purpose |
| :--- | :--- | :--- | :--- |
| **fileserver** | read_workspace_file, list_files, create_file, write_file, delete_file, grep_files, replace_in_file, append_file | stdio → HTTPS REST | File operations in /workspace via Go REST server |
| **git** | git_status, git_diff, git_add, git_commit, git_log, git_reset_soft | stdio → subprocess | Git operations with hook prevention and history protection |
| **docs** | list_docs, read_doc | stdio → local fs | Read-only access to project documentation |
| **planner** | plan_current, plan_list, plan_complete, plan_block, plan_create, plan_update_task | stdio → HTTPS REST | Task planning and progress tracking |

## Local Development

Run the Python unit tests:

```bash
cd claude && python -m pytest
```

Run the Go unit tests:

```bash
cd fileserver && go test ./...
```

## Documentation

- [docs/CONTEXT.md](docs/CONTEXT.md) — Architecture, security model, implementation details
- [docs/PLAN.md](docs/PLAN.md) — Development roadmap and current phase
- [docs/mcp-tools.json](docs/mcp-tools.json) — Reference copy of all MCP tool schemas (readable via the docs MCP tool)

## Part of Secure Claude

This repo is a git submodule of [secure-claude](../../). See the parent repo for cluster setup, Docker orchestration, and operational commands.
