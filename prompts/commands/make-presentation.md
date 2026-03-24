# Presentation Slide Outline: Secure AI Agent Reference Architecture

Generate a concise slide outline (10-15 slides) for presenting secure-claude to engineering leadership. Frame this as a reference architecture for deploying autonomous AI agents securely.

## Input Sources

Read these using the available MCP tools before writing:

First, check if the threat model and architecture docs already exist:
- `read_workspace_file` on `docs/THREAT_MODEL.md` — output of `/threat-model`
- `read_workspace_file` on `docs/ARCHITECTURE.md` — output of `/architecture-doc`

If those exist, use them as primary sources. If not, read the raw documentation:
- `read_doc` on CONTEXT.md, PLAN.md, WORKSPACE_INTERFACE.md, mcp-tools.json
- `list_files` to understand the codebase structure
- `read_workspace_file` on key source files (app.py, verify_isolation.py, main.go)

## Audience

Engineering leadership: VPs of Engineering, Staff+ engineers, Security architects. They understand Docker, TLS, and API security but may not know MCP, Claude Code, or LLM-specific attack vectors. They care about:
- Is this production-ready or a prototype?
- What's the security posture vs. "just running the AI on a dev laptop"?
- Can we adapt this for our own AI agent deployments?
- What are the known gaps and the roadmap?

## Output

Write the slide outline to `docs/PRESENTATION_OUTLINE.md` using `write_file`.

For each slide, produce:

```
## Slide N: [Title]
**Key message:** One sentence the audience should remember
**Content:** 3-5 bullet points or diagram description
**Speaker notes:** 2-3 sentences of talking points
```

## Slide Structure

Follow this narrative arc, 10-15 slides:

### Opening (2 slides)

**Slide 1: Title**
- Project name, one-line description
- "A reference architecture for running AI coding agents without giving them the keys to the kingdom"

**Slide 2: The problem**
- AI coding agents need broad access: files, git, APIs, tests
- Default today: run on the developer's machine with full credentials
- The "shared laptop" anti-pattern — the AI has everything the developer has
- Stakes: API keys, source code, git push access, network access

### Architecture (3-4 slides)

**Slide 3: Solution overview**
- Six-container architecture diagram (simplified)
- Core principle: "enforce boundaries structurally, never by filtering"
- Agent gets ephemeral tokens, never real credentials

**Slide 4: Credential isolation**
- Token isolation matrix — make it visual
- ANTHROPIC_API_KEY never touches the agent container
- Ephemeral DYNAMIC_AGENT_KEY generated per cluster start

**Slide 5: Network and filesystem isolation**
- int_net — agent has no direct internet access
- os.OpenRoot filesystem jail — Go runtime enforcement, not path filtering
- Read-only mounts where the agent only reads
- Pluggable workspace — any repo that follows the interface

**Slide 6: MCP security layer** (optional)
- MCP-watchdog as security proxy on all tool calls
- 40+ attack class blocking
- Git hook prevention (3-layer defense)

### LLM-Specific Threats (2-3 slides)

**Slide 7: Why AI agents are different**
- Traditional app: validate user input
- AI agent: input comes from the LLM, which can be manipulated
- Prompt injection, tool poisoning, indirect injection via workspace
- The agent is both the operator AND the attack surface

**Slide 8: LLM threat mitigations**
- Prompt injection via workspace → MCP-watchdog + filesystem jail limits blast radius
- Tool poisoning → structured MCP responses, plan-server isolation
- Self-modification → workspace is sub-repo; agent source and runtime are separate
- Credential exfiltration → token isolation ensures agent never has real API keys

**Slide 9: What's hard to defend against**
- Sophisticated prompt injection in natural-looking code comments
- Subtly wrong but logically valid code changes
- Test oracle manipulation — tests pass but code is wrong
- Answer: plan-then-execute workflow keeps humans in the loop

### Operational Model (2 slides)

**Slide 10: Plan-then-execute workflow**
- `plan.sh` → human reviews → `query.sh` executes tasks
- Agent auto-advances, runs tests, commits after each task
- Human reviews at the plan level, not every file edit
- The plan is the control point

**Slide 11: Testing and verification**
- Tester-server: isolated, read-only workspace, no secrets
- Phase 4: test-gate before task completion
- 26 startup isolation checks on claude-server
- Security scans separated from unit tests (network requirement split)

### Positioning (1-2 slides)

**Slide 12: Compared to alternatives**
- vs. "AI on my laptop": no isolation at all
- vs. simple Docker wrapper: no MCP security, no token separation
- vs. commercial platforms: open source, auditable, self-hosted
- This: defense in depth with structural enforcement at every layer

**Slide 13: Maturity and roadmap**
- Complete: Phases 1-3 (isolation, git tools, planning, testing)
- In progress: Phase 4 (autonomous task completion with test gates)
- Next: Phase 5 (resource limits, output sanitization, release)
- Out of scope: git push, CI/CD, multi-agent

### Closing (1 slide)

**Slide 14: Key takeaways**
- AI agents need the same rigor as any privileged system
- Structural enforcement > filtering > hoping the LLM behaves
- Plan-then-execute keeps humans in the loop where it matters
- Open source, designed for adaptation — same guarantees for any repo
- Link to repository

## After the Slides

Add an "Appendix Slides" section listing 3-5 backup slides for Q&A:
- Detailed token isolation matrix
- Full STRIDE summary table
- MCP-watchdog attack class taxonomy
- Startup isolation check inventory (all 26 checks)
- Cost and resource footprint analysis

## Style

- One key message per slide — no slide tries to say two things
- Prefer diagrams over text — describe what the diagram should show
- Use concrete numbers: "26 checks", "6 containers", "40+ classes", "4 tokens"
- Be honest about limitations — leadership respects candor
- Frame gaps as "known risks with a plan" not "unsolved problems"
- Explain MCP and Claude Code briefly when first mentioned
