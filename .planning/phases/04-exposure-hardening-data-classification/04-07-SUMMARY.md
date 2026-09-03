---
phase: 04-exposure-hardening-data-classification
plan: 07
subsystem: testing
tags: [live-gate, real-machine, uvicorn, task-scheduler, sc1-sc5, envelope, private-reads, loopback, d-12, human-gate]

# Dependency graph
requires:
  - phase: 04-exposure-hardening-data-classification (04-01)
    provides: "unified error envelope + frozen code table (missing_api_key/invalid_api_key/unknown_private_name/invalid_date_format/not_found) — the body shapes the live matrix pins against the real service"
  - phase: 04-exposure-hardening-data-classification (04-02)
    provides: "atomic ledger writes (tmp + os.replace) — the read-side contract the private probes serve byte-verbatim on the real files"
  - phase: 04-exposure-hardening-data-classification (04-03)
    provides: "/v1/private/* token-gated namespace + candidates D-14 semantics — the live probes' target surface"
  - phase: 04-exposure-hardening-data-classification (04-04)
    provides: "date whitelist + session-date fail-loud gates — the live date-422 row and the sign-off item"
  - phase: 04-exposure-hardening-data-classification (04-05)
    provides: "D-12 env-forced-token boot fix — the assumption-truth rows re-verify the real launcher posture against it"
  - phase: 04-exposure-hardening-data-classification (04-06)
    provides: "SC5 scan baseline rows + PROJECT.md classification table + local README known-limits — the scan set this gate re-runs on the real repo"
  - phase: 03-trigger-runner-job-registry-locks-auth-enforcement (03-04)
    provides: "the twin live-gate shape (Start-ScheduledTask restart, unsandboxed-session requirement, envelope probes, human walkthrough record)"
provides:
  - "Live-machine evidence for SC1-SC5: the resident service restarted onto the phase code via the real scheduled task, live matrix recorded (public 200s, private 200 byte-verbatim + X-Data-* headers, 401/403/404/422 envelope shapes, dry no-auth POST 401), SC5 scans re-run on the real repo, assumption truths recorded, full suite green, service left running"
  - "The SC1-SC5 → evidence mapping the end-of-phase human gate reviews (user ACCEPT/DELTA verdict + date-gate sign-off recorded at the bottom)"
affects: [verify-work phase gate, phase-05 ops polish, next trading session's first API consumer]

actuals:
  tokens: 0        # placeholder — computed at close-out over the realized diff
  tasks: 3
  commits: 0       # placeholder — filled at close-out

tech-stack:
  added: []        # zero packages — probes use stdlib (urllib/http.client) + curl only
  patterns:
    - "Live gate pattern (03-04 twin): scheduled-task restart, real-token X-API-Key header probes (token read in-process, never printed), PASS-line evidence protocol, byte-identity vs the real ledger files, token-absence audit on captured output before commit"
    - "Probe headers read case-insensitively: h11 sends header names lowercase on the wire (x-data-mtime), a plain dict lookup of the capitalized name returns None — the raw-header dump (http.client getheaders) is the wire truth"

key-files:
  created:
    - .planning/phases/04-exposure-hardening-data-classification/04-07-SUMMARY.md - the live-gate evidence log: restart record + live matrix + SC5 raw outputs + assumption truths + suite output + SC1-SC5 mapping + human verdict
  modified: []

key-decisions:
  - "Placeholder until close-out"

patterns-established:
  - "Placeholder until close-out"

requirements-completed: [STA-02, SEC-02]

# Metrics — filled at close-out
duration: Xmin
completed: 2026-09-04
status: complete
---

# Phase 04 Plan 07: Live Gate on the Real Machine (SC1-SC5) + Human Review — Summary

**The hardened API is verified on the machine that actually serves it: the resident service was restarted onto the phase code through the real Task Scheduler boot (127.0.0.1 loopback, auto-generated file token intact), and live probes confirmed the full envelope-era contract — private reads 200 with byte-verbatim real ledger bodies and X-Data-Mtime/X-Data-Age-S headers (SC1), 401 without a key (with WWW-Authenticate: ApiKey) / 403 with a wrong key / 404 unknown_private_name with the unified Not Found copy / live date-format 422 (SC4), public endpoints open with no key, the dry no-auth POST answered 401 with zero job spawn — plus the SC5 scans re-run on the real repo, the flagged assumptions recorded TRUE, the full suite green (148 passed, 1 skipped), and the service left running for the user's next trading session**

## Performance

- **Duration:** TBD (filled at close-out)
- **Started:** 2026-09-04 05:25 (+08:00)
- **Completed:** 2026-09-04 (close-out)
- **Tasks:** 3
- **Files modified:** 1 (this SUMMARY; zero production code — the plan is the phase's evidence gate, 03-04 twin)

## Task 1 — Restart + live matrix (SC1/SC4 live)

### Pre-state observed (2026-09-04 05:25-05:26 +08:00)

- No listener on port 8000 (`curl /health` → 000; netstat empty) — API was down, so no old-code owner needed stopping.
- Scheduled task `gogo-api` exists, State Ready; LastTaskResult 3221225786 (0xC000013A = the documented sandbox/interactive Ctrl+C pattern from 03-04); `logs/api/console.log` tail shows repeated ^C-ended uvicorn cycles (the known interactive-session pattern), last cycle server 30916.
- `data/api_token.txt` present (existence checked only; value never printed); `logs/portfolio.json` (603 B) + `logs/trading_journal.json` (22,703 B) present (Sep 3 09:51); newest candidates file `logs/candidates_2026-09-03.json`, legacy decoy `candidates_v3_2026-08-07.json` present.
- Git hygiene: `git status --porcelain -- data/ logs/` empty.

### Restart record

- **Method:** `Start-ScheduledTask -TaskName 'gogo-api'` (task action boots `cmd /c run_api.bat` per the 03-04 record). Started unsandboxed per the 03-04 environment fact (the sandbox teardown delivers Ctrl+C to Task-Scheduler-launched console processes — 0xC000013A).
- **Outcome:** LastTaskResult 267009 (0x41301 = SCHED_S_TASK_RUNNING) at 05:26:27; `/health` → 200 within ~2 s (uptime_seconds 8 at first probe).
- **Bind observed:** `netstat -ano` → `TCP 127.0.0.1:8000 LISTENING pid 30508` — **loopback bind confirmed** (assumption-truth (a) TRUE; the D-12 env-only gate was not triggered because the launcher binds the loopback default, and the loopback branch auto-generates/keeps the file token as designed).
- **Fresh boot line in console.log:** `INFO: Started server process [30508]` + startup complete — the 04-01/03/05 `api/main.py` code generation boots from the real scheduled task.

### Live matrix (read-only probes; token read from data/api_token.txt into the X-API-Key header only, never printed; every captured line checked for the token value — none found)

| # | Probe (method + path + auth) | Status | Body | Headers / notes |
|---|------------------------------|--------|------|-----------------|
| 1 | GET /health — no key | 200 | `{"status":"ok","uptime_seconds":N}` | public |
| 2 | GET /health/ready — no key | 200 | `{"status":"ready"}` | public |
| 3 | GET /v1/state/market_state — no key | 200 | raw market_state body, 897 bytes | public (market/temperature open) |
| 4 | GET /openapi.json — no key | 200 | schema body, 4,883 bytes | public read-only schema (envelope-era openapi_url live) |
| 5 | GET /v1/private/portfolio — no key | 401 | `{"detail":"missing API key","code":"missing_api_key"}` | `WWW-Authenticate: ApiKey` present (D-10 live) |
| 6 | GET /v1/private/portfolio — wrong key | 403 | `{"detail":"invalid API key","code":"invalid_api_key"}` | no challenge (D-10 live) |
| 7 | GET /v1/private/portfolio — real token (X-API-Key) | 200 | **byte-IDENTICAL** to logs/portfolio.json (603 B) | `x-data-mtime: 1788400301`, `x-data-age-s: 70552`, `content-type: application/json` (no charset), no X-Data-Stale — **SC1 live** |
| 8 | GET /v1/private/journal — real token | 200 | **byte-IDENTICAL** to logs/trading_journal.json (22,703 B) | X-Data-Mtime/X-Data-Age-S present — **SC1 live** |
| 9 | GET /v1/private/candidates — real token, no date | 200 | **byte-IDENTICAL** to logs/candidates_2026-09-03.json (newest non-legacy by the D-14 rule) | X-Data-Mtime/X-Data-Age-S present — **SC1 live** |
| 10 | GET /v1/private/candidates?date=20260903 — real token | 200 | byte-IDENTICAL to the same file | compact format normalizes to the same file |
| 11 | GET /v1/private/unknown-name — real token | 404 | `{"detail":"Not Found","code":"unknown_private_name"}` | unified 404 copy + per-site code live |
| 12 | GET /v1/private/candidates?date=2026-99-99 — real token | 422 | `{"detail":"date must be YYYY-MM-DD or YYYYMMDD","code":"invalid_date_format"}` | **SC4 live** (whitelist gate on the wire) |
| 13 | POST /v1/actions/pipeline — no key (dry, body `{}`) | 401 | `{"detail":"missing API key","code":"missing_api_key"}` | **no job started** — job registry count unchanged (10 → 10); never a successful POST |

**No real pipeline or morning-check was ever triggered** (prohibition row 1): the matrix's only POST was the no-auth 401 probe; the 409/already_running shape stays suite-pinned (04-01). Token value absent from every captured probe line and from `logs/api/console.log` (scan: `token-in-console: False`).

### Task 1 verify gates (all pass)

- `python -c "urllib … /v1/private/portfolio with X-API-Key"` → **200** (automated live private-read probe)
- `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health` → **200**
- `git status --porcelain -- data/ logs/` → **empty** (isolation pin — no live probe wrote data/)
- Job registry count 10 → 10 across all probes (zero spawns)

## Task 2 — SC5 re-run on the real repo + assumption truths + full suite + service left running

### SC5 scans on the real machine (04-06 scan set re-run here; raw outputs)

- **Scan 1 — token in git history:** `git log --all --oneline -- data/api_token.txt` → *(empty output — PASS, token never committed; matches 04-06 baseline)*
- **Scan 2 — sync_cloud whitelist:** `grep -n "api_token" scripts/daily/sync_cloud.py` → *(no output lines — PASS; whitelist L29-36 is data/*.json + data/auction/*.json only; matches 04-06 baseline)*
- **Scan 3 — .gitignore coverage:** `grep -n -E "api_token|logs" .gitignore` → `12:data/api_token.txt`, `14:logs/*`, `27:logs/*.log` *(PASS — byte-identical rows to the 04-06 baseline)*

### Assumption-truth rows (04-05 [ASSUMED] rows + this plan's task-name assumption)

| Assumption | Machine-truth test | Result |
|------------|--------------------|--------|
| (a) The launch path (run_api.bat + Task Scheduler) binds the loopback default | Boot outcome observed live: `netstat -ano` shows `TCP 127.0.0.1:8000 LISTENING` (pid 30508); boot succeeded through the loopback branch — no GOGO_API_TOKEN present, file token kept, D-12 refusal NOT triggered (it only fires for non-loopback binds) | **TRUE** |
| (b) No file-token non-loopback consumer exists | run_api.bat sets no GOGO_API_HOST/GOGO_API_TOKEN (env-parse falls to main()'s `127.0.0.1` default, D-08); scheduled-task action is `cmd /c run_api.bat`; the service boots on loopback only — a non-loopback file-token consumer would have needed a host override that does not exist in the launcher chain | **TRUE** (if it were false, the restart would have halted loudly on the D-12 gate — the gate held, never weakened) |
| (c) Task Scheduler task name "gogo-api" exists as recorded | `schtasks`/PowerShell query found `gogo-api` (State Ready); `Start-ScheduledTask -TaskName 'gogo-api'` succeeded (LastTaskResult 0x41301) | **TRUE** |

### Full suite on the real machine

- `python -m pytest -q` → **148 passed, 1 skipped in 15.52 s** (full phase suite green on the real machine — matches the 04-06 baseline count; a local verification run, not a real pipeline)

### Final machine state (Task 2 close)

- Service **RUNNING** on port 8000 (`/health` → 200; scheduled-task LastTaskResult 267009 = 0x41301 running), phase code, loopback posture, `data/api_token.txt` intact — left running for the user's next trading session (never killed at gate close).
- Hygiene: `git status --porcelain -- data/ logs/` empty; whole-repo tracked working tree clean.

### Task 2 verify gates (all pass)

- `git log --all --oneline -- data/api_token.txt` → empty (SC5)
- `grep -n "api_token" scripts/daily/sync_cloud.py` → no output lines (SC5)
- `python -m pytest -q` → 148 passed, 1 skipped, exit 0
- `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health` → 200 (service left running and healthy)
- `git status --porcelain -- data/ logs/` → empty (isolation pin)

<!-- gsd:write-continue -->
