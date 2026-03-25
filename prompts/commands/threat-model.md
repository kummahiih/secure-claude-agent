# Threat Model Analysis

Perform a comprehensive threat model of the secure-claude project. This is a hardened containerized environment for running Claude Code as an autonomous AI agent with MCP tool access.

## Files to Examine

Read these files using the available MCP tools (`read_doc`, `read_workspace_file`, `list_files`, `grep_files`). Build a complete picture before writing anything.

Start with documentation for context:
- `read_doc` on CONTEXT.md, PLAN.md, WORKSPACE_INTERFACE.md, mcp-tools.json
- `list_files` to get the full workspace tree

Then read source files in this order:

### Infrastructure & Orchestration
- `docker-compose.yml` in the cluster root (if workspace is the parent repo)
- All `Dockerfile.*` files — note base images, USER directives, COPY patterns
- `start-cluster.sh` — startup sequence and token generation
- `run.sh` — certificate generation, secret rotation, cluster launch
- `caddy/Caddyfile` or equivalent — TLS termination, routing

### Authentication & Credentials
- `.secrets.env.example` — expected secret variables
- `proxy/` directory — LiteLLM proxy configuration
- Any `*_wrapper.py` or `*_entrypoint.sh` — startup isolation checks

### Agent Runtime
- `claude/server.py` — FastAPI server, request handling, subprocess invocation
- `claude/verify_isolation.py` — startup isolation checks
- `prompts/system/ask.md` and `prompts/system/plan.md` — system prompts
- `.mcp.json` — MCP tool registration baked into the image

### MCP Tool Servers (Attack Surface)
- `claude/files_mcp.py` — file operations wrapper
- `claude/git_mcp.py` — git operations wrapper
- `claude/docs_mcp.py` — docs access wrapper
- `claude/plan_mcp.py` — planner wrapper
- `claude/tester_mcp.py` — tester wrapper
- `fileserver/main.go` — Go REST file server with os.OpenRoot jail
- `fileserver/main_test.go` — what's tested at the jail level

### Test Suite (reveals what's already tested)
- `test.sh` — unit tests
- Grep for `assert`, `check`, `verify` to understand coverage patterns

## Output Structure

Write the threat model to a new file using `write_file`. Save it as `docs/THREAT_MODEL.md`. Structure it with these sections:

### 1. Assets Inventory
Enumerate what needs protection. For each asset, state confidentiality/integrity/availability requirements:
- API keys (ANTHROPIC_API_KEY, DYNAMIC_AGENT_KEY, CLAUDE_API_TOKEN, MCP_API_TOKEN)
- Source code in /workspace
- Git history and .git directory
- Plan state (JSON files)
- Test outputs
- TLS certificates and CA material
- Docker socket (should NOT be accessible)
- Container runtime environment variables

### 2. Trust Boundaries
Identify at minimum:
- External network → Caddy ingress
- Caddy → claude-server
- claude-server → MCP stdio servers → REST backends
- claude-server → LiteLLM proxy → Anthropic API
- Agent subprocess → filesystem mounts
- Host → container boundary
- Container → container (int_net)

### 3. Threat Actors
Consider these profiles:
- **Malicious external caller** — has network access to Caddy:8443
- **Compromised LLM output** — Claude Code produces adversarial tool calls
- **Prompt injection via workspace content** — malicious code/comments in /workspace files
- **Compromised dependency** — supply chain attack in pip/npm/go packages
- **Insider with host access** — can read .secrets.env, Docker volumes

### 4. Attack Vectors (with LLM-Specific Threats)
For each vector, describe the attack, prerequisites, and impact:

**Infrastructure attacks:**
- Container escape
- Network segmentation bypass
- Volume mount traversal
- Environment variable leakage
- TLS downgrade or MITM on internal network

**LLM-specific attacks:**
- **Prompt injection** — workspace files containing instructions that override system prompt
- **Tool poisoning** — crafted MCP tool responses that cause unintended actions
- **Plan manipulation** — adversarial plan content that directs data exfiltration
- **Git history poisoning** — commits that introduce malicious content read by the agent
- **Test oracle manipulation** — crafted test output that tricks the agent into marking bad code as passing
- **Indirect prompt injection via docs** — malicious content in docs/ read through docs_mcp
- **Token exfiltration via tool calls** — agent tricked into writing secrets to workspace files
- **Recursive self-modification** — agent modifying its own MCP wrappers or app.py through fileserver

**Authentication/authorization attacks:**
- Token replay or theft
- Privilege escalation between token scopes
- Bypass of MCP_API_TOKEN validation

### 5. Existing Mitigations
Map each attack vector to existing controls found in the codebase. Reference specific files and code patterns:
- Credential isolation (token matrix)
- Network isolation (int_net, no direct internet from claude-server)
- Filesystem jail (os.OpenRoot)
- Git hook prevention (3-layer: tmpfs shadow, separated gitdir, hooksPath=/dev/null)
- Baseline commit floor
- MCP-watchdog (40+ attack class blocking)
- Startup isolation checks (verify_isolation.py, entrypoint scripts)
- Non-root containers, cap_drop
- Read-only mounts where appropriate
- Plan-server isolation from workspace and git
- Tester-server read-only workspace access

### 6. Residual Risks
For each remaining gap, assess:
- **Severity** (Critical / High / Medium / Low)
- **Likelihood** (High / Medium / Low)
- **Description** of what could go wrong
- **Recommended mitigation** — concrete, actionable steps

Pay special attention to:
- Anything relying on `tls_insecure_skip_verify`
- Missing resource limits (CPU, memory, timeout) on containers
- Output sanitization gaps in test runner
- The shared MCP_API_TOKEN between plan-server and tester-server
- Any hardcoded paths or credentials found in source
- Claude Code version pinning risks
- Subprocess timeout adequacy (600s)

### 7. STRIDE Summary Table
Create a table mapping each component to Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, and Elevation of Privilege findings.

## Tone and Emphasis

- Be specific and evidence-based — cite file paths and code patterns, not general categories
- Prioritize LLM-specific threats since this is an AI agent deployment
- Flag any "security by convention" that should be "security by enforcement"
- Note where the project already exceeds typical security for this class of system
- Be honest about residual risk — this is for internal engineering review, not marketing
