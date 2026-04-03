# Token Consumption Analysis and Optimization

If `docs/TOKEN_USE.md` is the most recent change on edit history print only `DONE` and stop.
Othervice proceed futher on this document.

**Role:** You are an expert in LLM token economics and AI agent efficiency.

**Objective:** Analyze the project's token consumption patterns, identify waste, and produce a prioritized optimization plan saved to `docs/TOKEN_USE.md`.

---

## Rules

### Rule 1: Context Minimization (Mandatory — Evaluate First)

Before analyzing token flows, assess the project's **structural context hygiene**. Context size is the single largest driver of token cost — every round-trip re-sends the full conversation history. Structural decisions that reduce context have multiplicative savings across all other optimizations.

Evaluate and recommend:

1. **Project decomposition** — Is the project a monolith or divided into smaller sub-projects? Each sub-project should have its own:
   - `docs/` folder with scoped `CONTEXT.md` (only that sub-project's architecture)
   - `CLAUDE.md` at the sub-project root (agent instructions scoped to that codebase)
   - Independent `test.sh` (tests only that sub-project)
   - This limits the agent's context window to one sub-project at a time, preventing cross-project context bleed.

2. **Documentation scoping** — Are `docs/CONTEXT.md` and `CLAUDE.md` minimal and focused, or do they contain information irrelevant to the agent's current task? Every extra paragraph is re-sent on every LLM call.

3. **Session isolation** — Does the system spawn one session per task (fresh context) or accumulate context across tasks in a single session? Single-session execution means task N pays for the context of tasks 1 through N-1.

4. **Tool description bloat** — Are MCP tool descriptions verbose? They are re-sent on every LLM call. Count the total tool description token footprint if possible.

5. **File read discipline** — Does the agent read files it doesn't edit? Does it re-read files it already read in the same session?

Flag violations as **context debt** with estimated token cost per session. This section must appear first in the output, before any flow analysis.

### Rule 2: Use Architecture Documentation

Read `docs/ARCHITECTURE.md` to understand the system's components, data flows, and trust boundaries. Map each component interaction to a token-consuming operation (LLM call, tool call, file read, test poll).

### Rule 3: Use Server Logs

Query the log service to obtain real session data. Analyze:
- LLM call counts per phase (planning vs. execution)
- Tool call frequency and round-trip counts
- Test polling patterns (how many polls per test cycle)
- File read patterns (duplicates, unnecessary reads)
- Context size growth across tasks within a session

If the log service is unavailable, document what log data would be needed and what queries to run, so the analysis can be completed when logs become available.

### Rule 4: Quantify Everything

Every finding must include:
- **Current cost**: estimated tokens wasted per session or per task
- **Proposed fix**: specific change (prompt edit, architectural change, infrastructure addition)
- **Expected savings**: percentage or absolute token reduction
- **Implementation effort**: Low / Medium / High

---

## Instructions

1. **Context Minimization Audit** (Rule 1): Assess project structure against the criteria above. Flag violations.

2. **Architecture Review** (Rule 2): Read `docs/ARCHITECTURE.md`. Map the request lifecycle to token-consuming operations. Identify which components generate LLM round-trips.

3. **Log Analysis** (Rule 3): Query the log service for recent session data. If unavailable, specify what data is needed:
   - LLM call timestamps and token counts per call
   - MCP tool call logs with request/response sizes
   - Test execution timing (start → completion → agent poll pattern)
   - File read logs with paths, sizes, and SHA256 (to detect duplicates)
   - Session boundaries (to measure context accumulation)

4. **Waste Identification**: Categorize token waste into:
   - **Polling waste** — unnecessary LLM round-trips waiting for async operations
   - **Context accumulation** — stale context from prior tasks carried forward
   - **Duplicate reads** — same file read multiple times with identical content
   - **Retry waste** — failed operations that could be avoided with better error handling
   - **Tool description overhead** — verbose tool schemas re-sent on every call
   - **Prompt bloat** — system prompt or documentation content that exceeds what's needed
   - **Model misallocation** — expensive models used for simple tasks

5. **Optimization Plan**: For each waste category, propose specific fixes with quantified savings.

6. **Infrastructure Requirements**: Document any infrastructure changes needed:
   - New MCP services (e.g., log aggregation service)
   - Changes to existing services (e.g., blocking test API, output truncation)
   - Prompt modifications
   - Architectural changes (e.g., sub-agent per task, session isolation)

7. **Output**: Save the complete analysis to `docs/TOKEN_USE.md`.

---

## Output Format for `docs/TOKEN_USE.md`

Structure the output document as follows:

```markdown
# Token Consumption Model

**Date:** <date>
**Scope:** <project name and version>
**Data source:** <log session IDs analyzed, or "projected — logs unavailable">

## 1. Context Minimization Audit
<Project structure assessment against Rule 1 criteria>
<Context debt findings with estimated token costs>

## 2. Token Flow Map
<Architecture components mapped to token-consuming operations>
<Diagram or table showing where tokens are spent per request lifecycle>

## 3. Session Analysis
<LLM call counts, tool call frequency, context growth curves>
<Per-task breakdown showing where the budget is spent>

## 4. Waste Taxonomy
<Categorized findings with current cost and root cause>

## 5. Optimization Plan
<Specific fixes grouped by category>

## 6. Infrastructure Requirements
<New services, architectural changes, prompt modifications>

## 7. Prioritized Action Items
| Priority | Item | Category | Current Waste | Expected Savings | Effort | Status |
|----------|------|----------|---------------|------------------|--------|--------|
| P1 | ... | ... | ... | ... | ... | Open |
```

The **Prioritized Action Items** table must be the final section — a ranked, actionable checklist ordered by impact-to-effort ratio, with status tracking (Open / In Progress / Done).
