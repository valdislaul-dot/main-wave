---
phase: "1"
slug: "service-skeleton-health-liveness"
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: "2026-09-03"
---

# Phase 1 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Process env/shell → service boot | GOGO_API_HOST/GOGO_API_PORT/GOGO_API_TOKEN cross from an untrusted shell into the boot decision | bind decision, token value |
| data/ filesystem → boot | data/api_token.txt is the token at rest; shared with pipeline state files, possibly-public repo | token value |
| Probe client → /health handler | Bare GET surface; no input bytes accepted | none (response only) |
| Repo → git remote | Possibly-public repo; sync_cloud.py auto-commits from an explicit allow-list | source only (token excluded) |
| Task Scheduler → run_api.bat → python | Scheduled boot-time execution as the interactive user | code execution path |
| Installer execution context | install_api_task.ps1 path derivation decides which bat runs | task store mutation |
| Local filesystem → registered task | console.log output channel; token file in launch tree | log lines |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-01-01 | Information Disclosure | api/main.py boot + captured stdout/stderr | high | mitigate | D-05 fixed ASCII notice only; boot.py never prints; tests assert sole-stdout; access_log=False | closed |
| T-01-02 | Elevation of Privilege / Spoofing | api/main.py main() bind decision | high | mitigate | SEC-03 fail-closed before ensure_token (Pitfall-2); loopback default; non-zero exit + ASCII stderr; live E2E verified | closed |
| T-01-03 | Information Disclosure | .gitignore / commit staging | high | mitigate | D-06 same-commit ignore entry (commit 240989f); specific-path staging; git check-ignore exit 0; never tracked | closed |
| T-01-04 | Tampering | /health uptime value | low | mitigate | time.monotonic(), never time.time() | closed |
| T-01-05 | Denial of Service (disk) | logs/api/console.log growth | low | accept | access_log=False; rotation explicitly Phase 5 (OPS-03) — accepted this phase | closed |
| T-01-06 | Spoofing | port 8000 bind | low | accept | Loopback-only default; impostor surfaces as clear uvicorn bind error; mutual auth Phase 4+ | closed |
| T-01-07 | Tampering / DoS | GET /health handler purity | medium | mitigate | No middleware/deps; suite pins 200-no-header in-memory-only (Pitfall 6) | closed |
| T-01-SC | Tampering | pip installs (pytest) | high | mitigate | RESEARCH Package Legitimacy Audit 4/4 canonical, no postinstall, requires_python compatible | closed |
| T-01-02-01 | Tampering | install_api_task.ps1 path derivation | high | mitigate | D-09 %~dp0/$PSScriptRoot only; config probe asserts WorkingDirectory == real repo root (machine-verified) | closed |
| T-01-02-02 | Denial of Service | Task Scheduler execution-time limit | high | mitigate | -ExecutionTimeLimit PT0S (unlimited) — machine-verified; default 3-day limit would kill the resident service | closed |
| T-01-02-03 | Elevation of Privilege | Task principal | high | mitigate | D-07 Interactive/Limited for current user, never SYSTEM — machine-verified | closed |
| T-01-02-04 | Denial of Service | Duplicate task instances / stray processes | low | mitigate | MultipleInstances IgnoreNew + unregister-then-register idempotency (task count == 1); port freed before scheduled boot | closed |
| T-01-02-05 | Tampering | run_api.bat on disk (repo may be public-readable) | medium | accept | Write access to the repo tree already = code execution as the user; public access is read-only; integrity guarding out of scope (Phase 4 note) | closed |
| T-01-02-06 | Information Disclosure | console.log content | low | accept | Boot lines only; D-05 notice carries no secret; rotation Phase 5 | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| R-01 | T-01-05 | Console log grows with uvicorn boot lines until reboot; rotation is explicitly Phase 5 (OPS-03) | Planner disposition (accepted at plan time) | 2026-09-03 |
| R-02 | T-01-06 | A local process binding 8000 first can impersonate the probe endpoint; mutual auth is out of scope until Phase 4+ | Planner disposition (accepted at plan time) | 2026-09-03 |
| R-03 | T-01-02-05 | Anyone able to write the repo tree already executes code as the interactive user; boot-time task adds no capability | Planner disposition (accepted at plan time) | 2026-09-03 |
| R-04 | T-01-02-06 | console.log holds only boot lines and the token-free D-05 notice | Planner disposition (accepted at plan time) | 2026-09-03 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-09-03 | 14 | 14 | 0 | gsd-secure-phase orchestrator (L1, ASVS 1 short-circuit — register authored at plan time, threats_open: 0) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-09-03
