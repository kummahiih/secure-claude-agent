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

---

## Phase 4: Close the Loop

- [X] Update system prompt to instruct agent to run tests after code changes
- [X] Add test-gate: agent should call run_tests + get_test_results before plan_complete
- [ ] End-to-end test: plan → execute all tasks → tests pass → committed
- [ ] Handle test failures triggering re-plan or retry
- [ ] Handle blocked tasks

---

## Phase 5: Hardening

- [ ] Add `conftest.py` with autouse network-blocking fixture
- [ ] Ensure all tests use mocks — no real service calls even if env vars are set
