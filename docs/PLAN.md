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

### Phase 2.5 — Planning MCP Wrapper

- plan_mcp.py: stdio wrapper inside claude-server (6 tools)
- System prompt: plan-aware (/ask checks plan_current), API contract protection
- 28 MCP wrapper tests

---

## Phase 3: Test Runner MCP Tool

- [ ] Add `conftest.py` with autouse network-blocking fixture
- [ ] Ensure pytest and go test can run against this repo's code in isolation

---

## Phase 4: Close the Loop

- [ ] End-to-end test: plan → execute all tasks → tests pass → committed
- [ ] Handle test failures triggering re-plan
- [ ] Handle blocked tasks

---

## Phase 5: Hardening

- [ ] `append_file` and `replace_in_file` tools (context-lighter file editing)
