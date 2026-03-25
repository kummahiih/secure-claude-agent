# Agent Development Plan

Agent-specific tasks and roadmap.

For overall project phases and risk register, see
[docs/PLAN.md](../../../docs/PLAN.md) in the parent repo.

---

## Completed

### Phase 1 — Isolation Verification

- 26 startup isolation checks in verify_isolation.py
- Credential isolation via DYNAMIC_AGENT_KEY rename
- MCP config as build artifact

### Phase 2 — Git MCP Tools + Docs Access

- git_mcp.py (6 tools), docs_mcp.py (2 tools)
- 3-layer git hook prevention (/dev/null shadow, separated gitdir, core.hooksPath)
- Baseline commit floor
- 25 git tool tests
- `grep_files`, `replace_in_file`, and `append_file` tools added to fileserver MCP (context-lighter file editing and search)
- `create_directory` tool added to fileserver MCP
- `docs/mcp-tools.json` added as a reference copy of all MCP tool schemas (readable via docs MCP)

### Phase 2.5 — Planning MCP Wrapper

- plan_mcp.py: stdio wrapper inside claude-server (6 tools)
- System prompt: plan-aware (/ask checks plan_current), API contract protection
- 28 MCP wrapper tests

### Phase 3 — Tester MCP Wrapper

- tester_mcp.py: stdio wrapper inside claude-server (2 tools: run_tests, get_test_results)
- 13 MCP wrapper tests covering success, auth, conflict, errors, connection failures
- Registered in .mcp.json build artifact alongside fileserver, git, docs, planner
- TESTER_SERVER_URL added to runenv.py
- test.sh updated: unit tests only (no security scans — those run in parent test.sh with network)
- Dummy env var defaults added so tests run in network-isolated tester container

### Phase 4 ✅ Close the Loop

Wired the full plan-execute-test-commit cycle into the agent system prompt.

- Test gate: `run_tests` → poll `get_test_results` → pass required before `plan_complete`
- Retry loop: up to 3 fix attempts; `plan_block` with failure summary after 3rd failure
- Commit gate: `git_add` + `git_commit` before `plan_complete` when code changed
- Blocked task handling: agent outputs block reason and stops — no rework attempted
- End-to-end mock tests covering success path and block-after-retries path
- Full workflow documented in [WORKFLOW.md](WORKFLOW.md)

---

## Phase 5: Hardening

- [ ] Add `conftest.py` with autouse network-blocking fixture
- [ ] Ensure all tests use mocks — no real service calls even if env vars are set
