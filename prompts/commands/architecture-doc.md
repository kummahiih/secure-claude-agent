# Generate Architecture Documentation

If `docs/ARCHITECTURE.md` is the most recent change on edit history print only `DONE` and stop.
Othervice proceed futher on this document.

**Role:** You are an expert software architect.

**Objective:** Explore the currently mounted workspace and generate a comprehensive architecture document. 

**Instructions:**
1. **Analyze the Workspace:** Thoroughly explore the mounted repository. Identify the primary programming languages, frameworks, entry points, and overall directory structure.
2. **Component Mapping:** Analyze how the different components and microservices interact. Identify API boundaries, internal network segments, and data flow.
3. **Dependencies:** Identify any external dependencies, databases, or third-party services.
4. **Synthesize:** Combine your findings into a clear, structured technical document.
5. **Output:** Create the `docs/` directory if it does not already exist. Save the final documentation to `docs/ARCHITECTURE.md` by possibly overwiting the old version. 

**Format Requirements for `ARCHITECTURE.md`:**
* **Overview:** High-level summary of the system's purpose.
* **System Components:** Detailed breakdown of each service/module.
* **Data Flow:** Explanation of how data moves through the system.
* **Technology Stack:** List of languages, frameworks, and core libraries.