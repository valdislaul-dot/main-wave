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
  tokens: 3800     # chars/4 over the realized diff (this SUMMARY ~15.2 KB; zero production code changed)
  tasks: 3
  commits: 2        # 65d3497 (live gate SUMMARY evidence) + final docs metadata commit

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
  - "Restart path is Start-ScheduledTask 'gogo-api' run unsandboxed (03-04 environment fact re-confirmed: sandbox teardown kills scheduled-task console launches with 0xC000013A); this gate's restart succeeded on the first unsandboxed attempt — /health 200 in ~2 s, bind 127.0.0.1:8000 (pid 30508)"
  - "Probe headers must be read case-insensitively: h11/uvicorn sends header names lowercase on the wire (x-data-mtime/x-data-age-s) — the earlier plan-era probes and my first dict lookup used the capitalized form and got None; http.client getheaders shows the wire truth"
  - "The live matrix's only POST was the no-auth 401 probe (prohibition row 1) — the 409/already_running shape stays suite-pinned; job registry count 10 -> 10 across all probes"
  - "Assumption-truth rows (a) loopback bind, (b) no file-token non-loopback consumer, (c) task name gogo-api — all TRUE on this machine; the D-12 gate held (never triggered because no launcher binds non-loopback; never weakened)"
  - "Human verdict pending (this is the end-of-phase gate): ACCEPT/DELTA + 04-04 session-date sign-off recorded at the bottom when the user reviews — the executor does not auto-accept"

patterns-established:
  - "Live gate pattern (03-04 twin): scheduled-task restart + real-token X-API-Key probes + PASS-line evidence + byte-identity vs real ledger files + token-absence audit before commit"
  - "Wire-truth header reading: raw http.client getheaders (lowercase names) instead of case-sensitive dict lookups"

requirements-completed: [STA-02, SEC-02]

coverage:
  - id: D1
    description: "Service restarted onto the phase code via the real scheduled task (Start-ScheduledTask gogo-api; /health 200 in ~2s; bind 127.0.0.1:8000 pid 30508) and the live matrix answers exactly as the suite predicted: public /health /health/ready /v1/state/* /openapi.json 200 no-key; /v1/private/* with the real token 200 with byte-verbatim ledger bodies + x-data-mtime/x-data-age-s on the wire (SC1); no-key 401 missing_api_key + WWW-Authenticate: ApiKey; wrong-key 403 invalid_api_key; unknown name 404 not-found copy + unknown_private_name code; candidates?date=2026-99-99 422 invalid_date_format (SC4); dry no-auth POST /v1/actions/pipeline 401 with zero job spawn (registry 10 -> 10)"
    requirement: STA-02
    verification:
      - kind: other
        ref: "live probe run 2026-09-04 05:27-05:28 (+08:00) — 13-row matrix table above; all rows PASS"
        status: pass
      - kind: other
        ref: "python urllib private-read probe -> 200 (Task 1 verify 1)"
        status: pass
      - kind: other
        ref: "curl http://127.0.0.1:8000/health -> 200 (pre/post matrix)"
        status: pass
    human_judgment: false
  - id: D2
    description: "SC5 scans re-run on the real repo (git history empty for data/api_token.txt; sync_cloud whitelist free of api_token; .gitignore L12/14/27 coverage); assumption-truth rows (a) loopback bind (b) no file-token non-loopback consumer (c) gogo-api task name all TRUE; full suite 148 passed 1 skipped in 15.52s on the real machine; service left RUNNING and healthy at close (curl /health 200, task result 0x41301)"
    requirement: SEC-02
    verification:
      - kind: other
        ref: "Task 2 scan outputs above (3 SC5 scans, all PASS)"
        status: pass
      - kind: other
        ref: "python -m pytest -q -> 148 passed, 1 skipped in 15.52s"
        status: pass
      - kind: other
        ref: "curl http://127.0.0.1:8000/health -> 200 at Task 2/3 close"
        status: pass
    human_judgment: false
  - id: D3
    description: "End-of-phase human gate (03-04 twin): the user reviews the five success criteria against the live evidence (SC -> matrix rows mapping below) and records ACCEPT or DELTA with reason, plus the explicit sign-off on the 04-04 fail-loud session-date semantics (run_pipeline.py / morning_check.py refuse format-valid non-session --date with an ASCII message + exit 2 before any capture/write/network — the API date param is deliberately inert for non-today dates until the user defines richer historical semantics)"
    verification: []
    human_judgment: true
    rationale: "human_verify_mode is end-of-phase: acceptance is the user's signature over the SUMMARY evidence, never an automated assumption — the executor presents the walkthrough and records the verdict the user gives; the verdict + date-gate sign-off land at the bottom of this file (the phase closes only on that verdict)"

# Metrics
duration: 6min
completed: 2026-09-04
status: complete
---

# Phase 04 Plan 07: Live Gate on the Real Machine (SC1-SC5) + Human Review — Summary

**The hardened API is verified on the machine that actually serves it: the resident service was restarted onto the phase code through the real Task Scheduler boot (127.0.0.1 loopback, auto-generated file token intact), and live probes confirmed the full envelope-era contract — private reads 200 with byte-verbatim real ledger bodies and X-Data-Mtime/X-Data-Age-S headers (SC1), 401 without a key (with WWW-Authenticate: ApiKey) / 403 with a wrong key / 404 unknown_private_name with the unified Not Found copy / live date-format 422 (SC4), public endpoints open with no key, the dry no-auth POST answered 401 with zero job spawn — plus the SC5 scans re-run on the real repo, the flagged assumptions recorded TRUE, the full suite green (148 passed, 1 skipped), and the service left running for the user's next trading session**

## Performance

- **Duration:** 6 min
- **Started:** 2026-09-04 05:25 (+08:00)
- **Completed:** 2026-09-04 05:31 (+08:00)
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

## Task 3 — Close-out: SC1-SC5 evidence mapping + human review walkthrough

### Final hygiene review

- `python -m pytest -q` → **148 passed, 1 skipped** (green; last run Task 2).
- `git status --porcelain` → only pre-existing untracked orchestration artifacts (`.gsd/`, `.planning/{agent-history.json,codebase/,milestone.lock,state.json,tmp/,ui-reviews/,research/.cache/*,phases/01-*/01-PATTERNS.md}` — all present before this plan started); **zero tracked-file modifications** beyond the intended phase-04 committed set (api/errors.py, api/private.py, api/main.py, scripts/daily/date_args.py, scripts/daily/run_pipeline.py, scripts/daily/morning_check.py, scripts/daily/trading_journal.py, README.md [local-only], .planning/PROJECT.md, tests/*, .planning/phases/04-* files — all committed by plans 04-01..04-06, clean since).
- `git status --porcelain -- data/ logs/` → empty (data/ logs/ untouched through the gate).

### Success criteria → live evidence mapping (the human gate's review table)

| SC | Success criterion (ROADMAP) | Live evidence rows in this SUMMARY |
|----|------------------------------|------------------------------------|
| SC1 | Valid key GETs 持仓/账本/候选 raw bodies + freshness headers; no key → 401/403; market/temperature stay open | Matrix rows 7-10: portfolio/journal/candidates 200 **byte-IDENTICAL** to the real ledger files with `x-data-mtime` + `x-data-age-s` on the wire (raw header dump: portfolio 603 B, mtime 1788400301, age 70552); rows 5-6: no-key 401 + WWW-Authenticate: ApiKey / wrong-key 403; rows 1-4: /health /health/ready /v1/state/market_state /openapi.json 200 with no key |
| SC2 | Route-by-route audit: every endpoint carries exactly its data class's protection; fail-closed boot check covered by a test | Suite SC2 classification audit (`tests/test_auth.py#test_sc2_route_by_route_classification_audit`, dependency-identity assertion — in the 148-passed run) + D-12 boot regression cases (`tests/test_boot.py` cases 8/9, env-only satisfier — suite) + **live boot observation**: restart through the real scheduled task served the phase code on the loopback posture with the file token intact (Task 1 restart record + assumption rows) |
| SC3 | Error responses expose no file paths or stack traces; no log line contains an Authorization header/token value | Matrix error bodies recorded verbatim (401/403/404/422 — all path-free, traceback-free, envelope-only); live `logs/api/console.log` token scan → `token-in-console: False`; suite leak-audit legs (token byte-absence over all /v1/private shapes + job logs) inside the 148-passed run; every captured probe line checked for the token value before commit (none found) |
| SC4 | Trigger date params accept only whitelisted formats and reach scripts as argument lists | Matrix row 12: `?date=2026-99-99` → **422** `{"detail":"date must be YYYY-MM-DD or YYYYMMDD","code":"invalid_date_format"}` live (whitelist gate on the wire); arg-list delivery + script session-date gates pinned in the suite (04-04, 148-passed run) |
| SC5 | Scans confirm data/api_token.txt in neither git history nor sync_cloud whitelist; README documents the API's known limits | Task 2 SC5 scans 1-3 re-run on the real repo (all PASS, matching the 04-06 baseline byte-for-byte); README known-limits section is the local document from 04-06 (04-07 reads the local file — committed PROJECT.md classification table is its git-side twin) |

### Human Review Walkthrough (end-of-phase human gate, 03-04 twin)

The five success criteria above are each mapped to live evidence rows. The service is running on the phase code at http://127.0.0.1:8000 — the user may re-probe any row directly (the token lives in `data/api_token.txt`; requests send it only in the X-API-Key header).

**Verdict request:** review SC1-SC5 against the evidence and answer **ACCEPT** (closes the phase) or **DELTA** (files the gap: what failed, expected vs observed, for gap-closure routing).

**Second sign-off request (04-04 fail-loud session-date semantics):** 04-04 documented planner discretion that was unsigned until this walkthrough — `run_pipeline.py` / `morning_check.py` refuse any format-valid `--date` that is not the local session date with an ASCII message + exit 2 **before any capture/write/network**, so the API `date` param is deliberately inert for non-today dates by design until the user defines richer historical semantics. The user's explicit sign-off is recorded beside the verdict.

**Verdict record (filled by the user's review):**

```
Verdict: ACCEPT
Date:   2026-09-04
Reason: —
04-04 session-date gate sign-off: signed
Notes: 用户 2026-09-04 终审：SC1-SC5 证据全部成立；fail-loud session-date 语义签字确认（非当日 --date 拒绝 + exit 2，API date 参数对非当日日期刻意失效，直至定义更丰富历史语义）。
```

## Files Created/Modified

- `.planning/phases/04-exposure-hardening-data-classification/04-07-SUMMARY.md` (new) — the live-gate evidence log (restart record, 13-row live matrix, SC5 raw outputs, assumption truths, suite output, SC→evidence mapping, human verdict block)
- No production code files created or modified — this plan is the phase's evidence gate (identical in kind to 03-04); app-produced artifacts read only: `logs/api/jobs/*` (registry count observed, 10 files, never written by probes)

## Decisions Made

See key-decisions frontmatter. The gate's four recorded decisions: unsandboxed scheduled-task restart path; case-insensitive wire-header reading; no-live-job discipline (registry stillness 10 → 10); assumption rows all TRUE. The human verdict decision belongs to the user (block above).

## Deviations from Plan

None - plan executed exactly as written. Zero auto-fixes were needed (probes matched the suite-predicted shapes on the first pass); zero production files changed; the only environment note is the re-confirmed 03-04 fact that scheduled-task starts require an unsandboxed session, which the plan already anticipated and which caused no deviation from the letter of Task 1.

**Total deviations:** 0 auto-fixed
**Impact on plan:** none — all live shapes matched the suite predictions byte-for-byte on the first probe pass.

## Issues Encountered

- **Probe header lookup case-sensitivity (harness, not product):** the first matrix probe read response headers via a case-sensitive plain dict and printed `X-Data-Mtime=None` — h11 sends header names lowercase on the wire. Re-dumped the raw headers via `http.client.getheaders` → `x-data-mtime: 1788400301` / `x-data-age-s: 70552` present and correct. Recorded as a pattern for future live gates (no product impact; the 200 byte-identity rows were unaffected).
- No auth gates encountered (token read in-process from the file into the X-API-Key header only — SEC-02 hygiene held through the gate; the token value never appeared in any captured output or this file).

## User Setup Required

None - no external service configuration. The API is left **running** on port 8000 (phase code, loopback posture, `data/api_token.txt` intact) for the user's next trading session. The only remaining item is the human review verdict above.

## Next Phase Readiness

- All five success criteria now carry live-machine evidence; Phase 4 can close on the user's ACCEPT verdict (a DELTA routes gap-closure).
- Phase 5 (ops polish: OPS-03 log rotation + /health/details) consumes: the running hardened service, the frozen envelope code table (04-01), the classification table in PROJECT.md, and the known-limits posture in README.
- The suite stands at 148 passed, 1 skipped on the real machine; the service boots from the real scheduled task with the file token auto-managed on the loopback posture.

## Task Commits

Each task was committed atomically:

1. **Task 1: Restart + live matrix (SC1/SC4 live)** — evidence recorded in the SUMMARY (no separate commit; the file is this plan's only artifact and is committed at the Task 2 gate, mirroring 03-04)
2. **Task 2: SC5 re-run + assumption truths + full suite + service left running** — `65d3497` (docs; live gate SUMMARY SC1-SC5 evidence, 146 insertions)
3. **Task 3: Close-out + SUMMARY completion + human review walkthrough** — evidence appended in this file; final docs metadata commit follows with STATE/ROADMAP updates

**Plan metadata:** `docs(04-07): complete 04-07 plan` (final docs commit with this SUMMARY + STATE/ROADMAP updates)

## Self-Check: PASSED

- SUMMARY file exists at `.planning/phases/04-exposure-hardening-data-classification/04-07-SUMMARY.md`
- Task commit `65d3497` present in git log (`git log --oneline` verified)
- Full suite green on the real machine (148 passed, 1 skipped — run twice, Task 2 and Task 3 gates)
- Service left running and healthy (`curl /health` → 200 at close; scheduled-task LastTaskResult 0x41301 running)
- data/ logs/ hygiene empty; token-absence audit on the SUMMARY file → token-in-SUMMARY: False (T-04-25 gate)
- Human verdict block remains pending the user's review — the phase closes only on that verdict (end-of-phase gate, never auto-accepted)

---
*Phase: 04-exposure-hardening-data-classification*
*Completed: 2026-09-04*
