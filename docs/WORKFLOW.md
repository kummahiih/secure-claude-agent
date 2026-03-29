# Ask Endpoint: Agent Workflow

Describes the full execution loop for the `POST /ask` endpoint.

For cluster architecture and security model, see [CONTEXT.md](CONTEXT.md).  
Authoritative source: [`prompts/system/ask.md`](../prompts/system/ask.md).

---

## Step-by-step

```
1. plan_current
       │
       ├─ no active plan ──────────────────────────────► execute query directly
       │
       └─ task exists
              │
              ├─ status = blocked
              │      │
              │      ├─ user signals resolved ────────► plan_unblock (task_id)
              │      │                                        │
              │      │                                        ▼
              │      │                                   execute task (using resume_context)
              │      │
              │      └─ user has NOT signalled ────────► output block reason + resume_context, stop
              │
              └─ status = pending / in_progress
                     │
                     ▼
              execute task (fileserver + git tools)
                     │
                     ├─ no code changed ─────────────► plan_complete
                     │
                     └─ code changed
                            │
                            ▼
                       ┌─ run_tests
                       │       │
                       │       ▼  (poll every few seconds)
                       │  get_test_results
                       │       │
                       │       ├─ status = running ──► poll again
                       │       │
                       │       ├─ status = pass ─────► git_add + git_commit
                       │       │                            │
                       │       │                            ▼
                       │       │                       plan_complete
                       │       │
                       │       └─ status = fail
                       │              │
                       │        attempt ≤ 3? ──yes──► fix code, go to run_tests
                       │              │
                       │             no
                       │              │
                       └─────────────▼
                            plan_block (with failure summary)
                            output explanation to user
```

---

## Rules

| Rule | Detail |
| :--- | :--- |
| Blocked tasks | If user indicates blockage resolved, call `plan_unblock` and resume using `resume_context`; otherwise output reason + `resume_context` and stop |
| Commit gate | Always `git_add` + `git_commit` before `plan_complete` when code changed |
| Test gate | Never call `plan_complete` while tests are failing |
| Retry limit | Up to 3 `run_tests` attempts per task; call `plan_block` after the 3rd failure |
| Polling | Wait a few seconds between `get_test_results` polls |
| Concurrency | `run_tests` returns 409 if a run is already in progress — wait and retry `get_test_results` |

---

## plan_complete behaviour

`plan_complete` auto-advances the plan to the next task. The next `query.sh`
invocation will pick up that task via `plan_current`.

When all tasks are complete, `plan_current` returns no active task. The agent
proceeds without plan context.

---

## Output constraints

The system prompt enforces strict conciseness to conserve context tokens:

- No thought-process narration
- No code explanations or change summaries
- Commit messages ≤ 50 characters
- Prefer `replace_in_file` / `append_file` over full `write_file` rewrites
