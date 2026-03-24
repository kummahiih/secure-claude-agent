# Security-Annotated Architecture Document

Generate a comprehensive architecture document for the secure-claude project, annotated with security properties at every layer. This document should serve as the authoritative reference for how the system works and why each design choice was made.

## Files to Examine

Use `read_doc`, `read_workspace_file`, `list_files`, and `grep_files` to read everything before writing.

Start with documentation:
- `read_doc` on CONTEXT.md, PLAN.md, WORKSPACE_INTERFACE.md, mcp-tools.json

Then read source by layer:

### Layer 1: Orchestration & Infrastructure
- `docker-compose.yml` — service definitions, networks, volumes, depends_on, environment
- `start-cluster.sh` — container startup orchestration
- `run.sh` — certificate generation, token rotation, cluster launch sequence
- All `Dockerfile.*` — base images, build stages, installed packages, USER directives, COPY patterns
- `.secrets.env.example` — expected environment variables

### Layer 2: Ingress & TLS
- `caddy/Caddyfile` or equivalent — TLS configuration, upstream routing, header handling
- Any `caddy_entrypoint.sh` — startup checks for Caddy

### Layer 3: Agent Core
- `claude/app.py` — FastAPI endpoints (/ask, /plan), subprocess invocation
- `claude/verify_isolation.py` — all 26 startup checks (document each one)
- `prompts/system/ask.md` — system prompt for /ask
- `prompts/system/plan.md` — system prompt for /plan
- `.mcp.json` — MCP tool registration

### Layer 4: MCP Tool Servers
- `claude/files_mcp.py` — stdio wrapper for file operations
- `claude/git_mcp.py` — stdio wrapper for git (note hook prevention)
- `claude/docs_mcp.py` — stdio wrapper for docs
- `claude/plan_mcp.py` — stdio wrapper for planner
- `claude/tester_mcp.py` — stdio wrapper for tester

### Layer 5: Backend Services
- `fileserver/main.go` — Go file server (os.OpenRoot jail implementation)
- `fileserver/main_test.go` — what's tested at the jail level
- Planner and tester source (if accessible through docs or workspace)

### Layer 6: Proxy
- `proxy/` directory — LiteLLM configuration

### Layer 7: Security Middleware
- Grep for `mcp-watchdog` — how it wraps MCP servers, its configuration

### Test Infrastructure
- `test.sh` — what properties are verified and how

## Output

Write the architecture document to `docs/ARCHITECTURE.md` using `write_file`. Structure it as follows:

### 1. System Overview
A 2-3 paragraph executive summary: what the system does, who it's for, and its core security thesis ("enforce boundaries structurally, never by filtering").

### 2. Service Inventory
For each of the six containers, document:
- **Role** — what it does in one sentence
- **Base image and build** — Dockerfile details, stages, final image
- **Runtime user** — UID, capabilities
- **Exposed ports** — internal and external
- **Environment variables consumed** — which tokens/config it expects
- **Volume mounts** — host path, container path, mode (ro/rw), purpose
- **Startup checks** — isolation/integrity checks before accepting traffic
- **Security annotations** — attack surface and how it's constrained

### 3. Network Topology
Document the Docker network architecture:
- Which services are on which networks
- Which services can reach which other services
- Where TLS is terminated and re-established
- Full packet path from external client through to Anthropic API
- Annotate each hop with: protocol, authentication mechanism, encryption status

### 4. Data Flow Diagrams
Describe these flows in detail (use ASCII diagrams):

**Flow A: User query execution (/ask)**
- From `query.sh` through every hop to Anthropic API and back
- Every authentication check, TLS handshake, token used

**Flow B: Plan creation (/plan)**
- From `plan.sh` through to plan-server writing JSON

**Flow C: MCP file operation**
- Claude Code tool call → mcp-watchdog → files_mcp.py → HTTPS REST → Go fileserver → os.OpenRoot → filesystem
- Every validation/filtering step

**Flow D: Test execution**
- Claude tool call → tester_mcp.py → tester-server → subprocess → test.sh output → back to agent

**Flow E: Git commit**
- Claude tool call → git_mcp.py → git subprocess → gitdir
- Hook prevention layers

### 5. Authentication & Authorization Chain
- How each token is generated (run.sh)
- Which services hold which tokens (token isolation matrix)
- How tokens are validated at each service boundary
- Token lifecycle (ephemeral per cluster start vs. persistent)
- Blast radius analysis if a token is compromised

### 6. Filesystem Security Model
- Workspace symlink mechanism and repo switching
- os.OpenRoot jail — how it prevents path traversal
- tmpfs shadow over .git — why and how
- Read-only vs read-write mount decisions and rationale
- Git directory separation (worktree vs gitdir)

### 7. MCP Security Architecture
- stdio → REST translation pattern and why it was chosen
- mcp-watchdog: what it intercepts, attack classes blocked, configuration
- Tool registration: how .mcp.json is built and baked into image
- Input validation on each MCP tool — what's validated and where

### 8. Design Trade-offs
For each major decision, document what was chosen, what was rejected, why, security implications, and known limitations. Cover at minimum:
- Claude Code CLI subprocess vs. SDK integration
- stdio MCP wrappers vs. direct HTTP MCP protocol
- Submodule split vs. monorepo
- Plan storage in parent repo vs. agent workspace
- Pinned Claude Code version vs. latest
- Direct subprocess test runner vs. Docker-in-Docker
- Shared MCP_API_TOKEN vs. per-service tokens
- System prompts as files vs. inline strings

### 9. Operational Security
- Certificate generation and rotation process
- Secret management (.secrets.env lifecycle)
- Log handling — what's logged, what's redacted
- Upgrade path for Claude Code version changes
- Post-startup isolation verification

### 10. Comparison to Alternatives
Briefly position against:
- Running Claude Code directly on the host
- Using LangChain/LangGraph with tool calling
- Commercial AI agent platforms
- Simple Docker container with API key mounted

Highlight additional security guarantees this architecture provides.

## Formatting

- Use clear section headers and consistent formatting
- Include ASCII diagrams for network topology and data flows
- Reference specific file paths and function/handler names
- Annotate security properties inline: `[AUTH: MCP_API_TOKEN]`, `[JAIL: os.OpenRoot]`, `[TLS: internal CA]`
- Note any discrepancies between documentation and actual implementation
