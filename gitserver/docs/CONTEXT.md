# secure-claude-gitserver: Project Context

## What This Is

A Go REST server that executes git operations against the repository mounted at `/workspace`
with git data at `/gitdir`. Part of the secure-claude cluster — sits alongside the
fileserver (mcp-server), plan-server, and tester-server as shared infrastructure.

The gitserver receives `/workspace:ro` and `/gitdir:rw`, executes git commands on demand,
and enforces a baseline commit floor to prevent unauthorized history rewrites.

## Architecture

```
claude-server
  └─> POST/GET endpoints (Bearer GIT_API_TOKEN)
        └─> git-server:8443
              └─> git subprocess
                    ├─ GIT_DIR=/gitdir
                    └─> GIT_WORK_TREE=/workspace
```

## Endpoints

| Method | Path | Auth | Description |
| :--- | :--- | :--- | :--- |
| GET | /status | Bearer GIT_API_TOKEN | git status --short |
| GET | /diff | Bearer GIT_API_TOKEN | git diff [--cached] |
| POST | /add | Bearer GIT_API_TOKEN | git add (stage files) |
| POST | /commit | Bearer GIT_API_TOKEN | git commit with message |
| GET | /log | Bearer GIT_API_TOKEN | git log --oneline |
| POST | /reset | Bearer GIT_API_TOKEN | git reset --soft (bounded by baseline) |
| GET | /health | None | Healthcheck |

## Response Format

**GET /status**
```json
{"output": "M  main.go\n?? scratch.txt"}
```

**GET /diff?staged=false&submodule_path=**
```json
{"output": "diff --git a/main.go b/main.go\n..."}
```

**POST /add**
```json
// request: {"paths": ["main.go", "README.md"]}
{"output": ""}
```

**POST /commit**
```json
// request: {"message": "fix: correct off-by-one", "submodule_path": ""}
{"output": "[main 1a2b3c4] fix: correct off-by-one\n 1 file changed"}
```

**GET /log?max_count=10&submodule_path=**
```json
{"output": "1a2b3c4 fix: correct off-by-one\n8d9e0f1 initial commit"}
```

**POST /reset**
```json
// request: {"count": 1, "submodule_path": ""}
{"output": "HEAD is now at 8d9e0f1 initial commit"}
```

**GET /health**
```json
{"ok": true}
```

## Security

Follows the same isolation pattern as mcp-server (fileserver) and tester-server:

- Runs as UID 1000 (appuser), non-root
- TLS with internal CA-signed certificate
- Bearer token auth (GIT_API_TOKEN) on all endpoints except /health
- entrypoint.sh rejects startup if forbidden secrets are present
- Workspace mounted read-only — only /gitdir is read-write
- Hook prevention: `core.hooksPath=/dev/null` + `--no-verify` on commits (workspace is `:ro` — no hook files can be written)
- Baseline commit floor: captures HEAD at startup, rejects resets past that point

## Token Isolation

| Token | git-server |
| :--- | :--- |
| ANTHROPIC_API_KEY | forbidden |
| DYNAMIC_AGENT_KEY | forbidden |
| CLAUDE_API_TOKEN | forbidden |
| MCP_API_TOKEN | forbidden |
| PLAN_API_TOKEN | forbidden |
| TESTER_API_TOKEN | forbidden |
| GIT_API_TOKEN | required |

## Configuration

| Env var | Default | Description |
| :--- | :--- | :--- |
| GIT_API_TOKEN | (required) | Bearer token for auth |
| GIT_DIR | /gitdir | Path to the git object store |
| GIT_WORK_TREE | /workspace | Path to the working tree |
| GIT_BASELINE_COMMIT | (captured at startup) | Oldest commit reset is allowed to reach |
| SSL_CERT_FILE | /app/certs/ca.crt | CA bundle for TLS |

## Decisions

| Decision | Chosen | Rejected | Reason |
| :--- | :--- | :--- | :--- |
| Language | Go | Python | Matches fileserver/tester pattern, single static binary |
| Hook prevention | 2 layers (hooksPath + --no-verify) | tmpfs shadow | Workspace is :ro — shadow is redundant; mcp-server needs it because workspace is rw |
| Baseline enforcement | Server-side at startup | Client-side | Prevents bypass; git-server owns the git state |
| Workspace access | Read-only mount | Read-write | File writes go through mcp-server; gitserver only reads worktree |
| Concurrency | Serialised via OS-level git locking | Explicit mutex | Git handles concurrent index writes natively |
