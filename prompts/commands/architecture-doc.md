# Generate Architecture Documentation

If both `docs/ARCHITECTURE_OVERVIEW.md` and `docs/ARCHITECTURE_DETAIL.md` exist and `docs/ARCHITECTURE_DETAIL.md` is the most recent change on edit history, print only `DONE` and stop.
Otherwise proceed further on this document.

**Role:** You are an expert software architect.

**Objective:** Explore the currently mounted workspace and generate comprehensive architecture documentation split across two files: an overview document needed for every coding task, and a detail document needed only for security/infrastructure tasks.

**Instructions:**
1. **Analyze the Workspace:** Thoroughly explore the mounted repository. Identify the primary programming languages, frameworks, entry points, and overall directory structure.
2. **Component Mapping:** Analyze how the different components and microservices interact. Identify API boundaries, internal network segments, and data flow.
3. **Dependencies:** Identify any external dependencies, databases, or third-party services.
4. **Synthesize:** Combine your findings into clear, structured technical documents.
5a. **Output Overview:** Create the `docs/` directory if it does not already exist. Save `docs/ARCHITECTURE_OVERVIEW.md` by possibly overwriting the old version.
5b. **Output Detail:** Save `docs/ARCHITECTURE_DETAIL.md` by possibly overwriting the old version. This file must be written **after** the overview file.

**Format Requirements for `docs/ARCHITECTURE_OVERVIEW.md`:**
* **Overview:** High-level summary of the system's purpose.
* **System Components:** Detailed breakdown of each service/module.
* **Data Flow:** Explanation of how data moves through the system.
* **Technology Stack:** List of languages, frameworks, and core libraries.
* **MCP Tool Architecture:** Description of the MCP tool sets, transport layers, and access patterns.
* **Workspace Interface:** How the workspace is mounted, accessed, and isolated.

**Format Requirements for `docs/ARCHITECTURE_DETAIL.md`:**
* **Network Topology:** Internal network segments, TLS configuration, and service-to-service routing.
* **Security Architecture:** Credential isolation, filesystem jails, startup checks, and token matrix.
* **Design Decisions:** Key architectural decisions with rationale and rejected alternatives.
