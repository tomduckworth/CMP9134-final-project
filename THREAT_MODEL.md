STRIDE Threat Modeling: Robot Movement Endpoint (/api/move)
This document analyzes the security posture of the Ground Control Station's critical /api/move endpoint using the Microsoft STRIDE methodology.
1. Threat Matrix
Threat Category	Description & System Risk	Mitigation Status
Spoofing	An attacker fakes their login to send unauthorized move commands.	At Risk: The API relies on local authentication objects. Production requires signed JWT credentials.
Tampering	An attacker intercepts and alters coordinate payloads in transit.	At Risk: HTTP traffic is unencrypted. Deploying to production requires forcing TLS/HTTPS.
Repudiation	An operator sends a harmful command to the physical robot and denies it.	Mitigated: Immutable SQLite AuditLogger database tracks all actions with absolute timestamps and names.
Denial of Service	An attacker floods the FastAPI server with 10,000 requests/sec.	At Risk: The system currently lacks API rate-limiting handlers.
Elevation of Privilege	A standard user with "Viewer" access tries to send "Commander" commands.	Mitigated: Enforced strict Role-Based Access Control (RBAC) at the backend server level.
2. Technical Mitigations
Mitigation 1 (Implemented) — Server-Side RBAC and Auditing
Access privileges are checked on the server before calculations occur. All transactions are logged in an un-alterable SQLite database to ensure full operator accountability:
Mitigation 2 (Planned) — Rate Limiting
To prevent DoS attacks, we plan to implement rate-limiting decorators using slowapi to restrict users to a maximum rate of: