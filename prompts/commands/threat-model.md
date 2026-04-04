# Generate Threat Model and Prioritized Fixes

If `docs/THREAT_MODEL.md` is the most recent change on edit history print only `DONE` and stop.
Othervice proceed futher on this document.


**Role:** You are an expert application security engineer.

**Objective:** Generate a comprehensive threat model based on the project's architecture, including a prioritized list of security fixes.

**Instructions:**
1. **Context Gathering:** Read the existing architecture documentation located at `docs/ARCHITECTURE_OVERVIEW.md` and `docs/ARCHITECTURE_DETAIL.md`.
2. **Code Reconnaissance:** Briefly scan the source code in the workspace to understand the implementation details of the architecture you just read about.
3. **Threat Modeling:** Perform a threat modeling exercise (e.g., using the STRIDE methodology) based on the architecture and your code review.
4. **Vulnerability Identification:** Identify potential attack vectors, missing trust boundaries, and security weaknesses.
5. **Prioritization:** Create a prioritized list of actionable fixes, ranking them from Critical to Low based on potential impact and exploitability.
6. **Output:** Save the final threat model to `docs/THREAT_MODEL.md` by possibly overwiting the old version.

**Format Requirements for `THREAT_MODEL.md`:**
* **Trust Boundaries:** Define where trust changes across the system.
* **Identified Threats:** Detailed breakdown of potential attack vectors and vulnerabilities.
* **Prioritized Mitigation Plan:** A ranked checklist of fixes (Critical, High, Medium, Low) with actionable steps to resolve them.