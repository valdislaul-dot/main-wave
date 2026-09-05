---
phase: "03"
slug: "trigger-runner-job-registry-locks-auth-enforcement"
status: verified
threats_open: 0
asvs_level: 1
created: "2026-09-04"
---

# Phase 03 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Consumer → API | Untrusted HTTP requests cross here: header X-API-Key, path params {kind}/{job_id}; auth gate answers 401/403 before any logic | API key, action kind, job_id |
| API → child process | Fixed-map argv list + scrubbed inherited env cross into child python processes | command args, env (token popped) |
| API → registry/log files | Job JSON written only by the API (atomic tmp+os.replace); child writes its own log handle | job state, stdout/stderr bytes |
| Worker thread → child process | argv + inherited env handed to child; child writes its own log file | command args, log bytes |
| Filesystem → reload sweep | Registry files are the crash-safe source of truth; boot sweeps rewrite after crash | pending/running → interrupted |
| Process boundary (GUI/other runner) | Same-machine processes contend on data/locks/{kind}.lock — the OS arbitrates | byte-range lock |
| Executor shell → live service | 03-04 verification commands hit the real resident API; key exists only inside python | API key (python-only) |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-03-01 | Tampering | Registry file writes | high | mitigate | tmp + os.replace atomic writes (pid-suffixed tmp); read side opens→reads→closes; WinError-5 collision retry | closed |
| T-03-02 | Tampering | Crash-state registry inconsistency | high | mitigate | reload_registry deterministically rewrites pending/running → interrupted with finished_at at boot; per-job atomic marking; no PID probe (ACT-05 v2 owns orphans) | closed |
| T-03-03 | Information Disclosure | Child stdio encoding | medium | mitigate | Spawn env adds PYTHONIOENCODING=utf-8; lifecycle test pins UTF-8 emoji bytes in log | closed |
| T-03-04 | Denial of Service | Unbounded registry growth | medium | mitigate | prune keeps newest 500 terminal jobs at finalize + boot sweep; never prunes pending/running; ENOENT-tolerant | closed |
| T-03-05 | Tampering | Lock-file holder spoofing / stale locks | medium | mitigate | Content-free lock files (byte 0 locked); OS auto-release on holder death; holder context in registry/memory only | closed |
| T-03-06 | Denial of Service | Lock starvation via stranded GUI fd | low | mitigate | GUI releases in finally (03-03); OS releases byte-range lock on GUI death | closed |
| T-03-07 | Elevation of Privilege | Module import side effects | low | mitigate | job_lock.py / jobs.py side-effect-free at import; lock dirs created at acquire time only | closed |
| T-03-08 | Spoofing | require_api_key / all protected routes | critical | mitigate | Router-level dependency; 401 + `WWW-Authenticate: ApiKey`; 403 via hmac.compare_digest constant-time; fail-closed when no token; reuses Phase 1 read_token chain | closed |
| T-03-09 | Information Disclosure | Token in logs/env/children | high | mitigate | uvicorn access_log=False; fixed-string errors; spawn env pops GOGO_API_TOKEN; grep-audit test asserts token byte absent everywhere | closed |
| T-03-10 | Tampering / RCE | kind → command construction | high | mitigate | Fixed-map lookup, unknown → 404 before lock/claim/spawn; argv constants-only via _cmd_for, shell=False; bodies never parsed; no user input reaches argv | closed |
| T-03-11 | Tampering | job_id path composition | high | mitigate | `^[0-9a-f]{32}$` gate before any path join; malformed ids → 404 with zero file access; corrupt files → 503, never 500 | closed |
| T-03-12 | Denial of Service | Unauthorized re-trigger / double execution | medium | mitigate | Single-flight OS lock before claim; in-memory map → instant 409 with running_job_id; rejected requests spawn nothing | closed |
| T-03-13 | Elevation of Privilege | main() boot-order drift | medium | mitigate | main() gains exactly three additions; SEC-03 fail-closed order untouched and diff-auditable; reload in main(), not lifespan hook | closed |
| T-03-14 | Denial of Service | GUI double-run during an API job | high | mitigate | acquire-before-run on the same pipeline.lock; held → st.warning + no spawn (D-01); OS auto-release on GUI death | closed |
| T-03-15 | Tampering | Stranded lock via the timeout path | high | mitigate | try/finally with fd.close() around the run; TimeoutExpired warns pipeline may still run; v2 ACT-04 owns child taskkill | closed |
| T-03-16 | Elevation of Privilege | GUI import side effects / config coupling | medium | mitigate | job_lock imported as bare top-level module, zero scripts.* imports, zero import-time side effects; msvcrt/fcntl ImportError split for Mac parity | closed |
| T-03-17 | Information Disclosure | API key in shell/argv/output | high | mitigate | Key read and used only inside python via api.boot.read_token; never in shell commands/curl/repo files/output; smoke scripts in OS temp dir, deleted after run | closed |
| T-03-18 | Denial of Service | Live run colliding with user's market flow | high | mitigate | Time rule before every block; real pipeline triggers gated outside weekday 09:15-15:00 or explicit approval (precondition); health-check kind safe anytime | closed |
| T-03-19 | Denial of Service | Non-tree kill leaving orphan that double-runs | high | mitigate | taskkill /F /T on port-8000 owner pid; child death verified before restart; post-restart GET shows interrupted; post-crash lock acquire succeeds | closed |
| T-03-20 | Tampering | Registry/lock/log files entering git | medium | mitigate | logs/ + data/locks/ gitignored (03-01 added locks line); git status asserted after every task; tracked-file status reviewed at close-out — live-run data writes (official_check.json, zt_pool_state.json) left unstaged and documented in 03-04 SUMMARY | closed |
| T-03-21 | Tampering | D-02 evidence drift (task reappears) | low | mitigate | Verify-only re-query at close-out with hard halt if stale task exists; 03-04 re-confirmed absent (201 tasks, only gogo-api) | closed |

*Status: open · closed · open — below {block_on} threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|

No accepted risks — all 21 threats mitigated and verified.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-09-04 | 21 | 21 | 0 | gsd-secure-phase (execute-phase orchestrator) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-09-04

---

## Security Audit 2026-09-04

| Metric | Count |
|--------|-------|
| Threats found | 21 |
| Closed | 21 |
| Open | 0 |

Register authored at plan time (all four PLAN.md carry `<threat_model>` blocks, T-03-01..T-03-21). ASVS level 1, block threshold high → L1 grep-depth classification sufficient (short-circuit rule); every mitigation mapped to green automated evidence (test_actions.py 10 / test_auth.py 8 / test_jobs.py 13, full suite 92 passed) plus the 03-04 real-machine live gate (SC1-SC5, taskkill /F /T recovery, key-bytes-absent audit, D-02 verify-only). T-03-20 note: the live pipeline run's designed writes to two tracked data files were reviewed at close-out, left unstaged, and documented in the 03-04 SUMMARY — registry/lock/log artifacts themselves never entered tracked trees.
