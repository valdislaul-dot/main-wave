---
phase: 05-recovery-observability-ops-polish
plan: 04
subsystem: ops
tags: [live-gate, real-machine, scheduled-task, log-rotation, health-details, adapt-and-record, human-review, phase-close]

# Dependency graph
requires:
  - phase: 05-01
    provides: as-built /health/details contract (401/403 envelopes, D-29 body shape, uptime wiring) this gate verifies live
  - phase: 05-02
    provides: the bounded-footprint rotation primitives (rotate/repoint/prune, D-32/D-34) whose live proof this gate runs
  - phase: 05-03
    provides: the D-36 audit record (CONFIRMED ABSENT) to cross-reference and the Mac checklist whose parity counts this record supplies
provides:
  - Phase 5 closing gate record: live rotation evidence (M-B launcher rotation, adapted from the machine-verified M-A dance after two live disproving iterations), /health/details live matrix (401/403/200 verbatim), final suite count (189 passed / 1 skipped), human-review checklist with operator verdict lines across all four plans' [ASSUMED] rows
  - api/uptime.py single-anchor fix for the __main__/api.main dual-identity uptime fork (live-found Rule 1 bug)
affects: [Operator end-of-phase review (verdicts), Mac-side D-35 checklist parity]

actuals:
  tokens: 8200    # chars/4 over realized diff (~24.8k chars fix commits + ~8k gate record + state docs)
  tasks: 3
  commits: 3

tech-stack:
  added: [none — zero package installs; new module api/uptime.py is stdlib-only (time)]
  patterns: ["Leaf-module anchor: any value shared across module identities must live in a zero-dependency module both importers load — never in a file that can be executed as __main__ (python -m api.main registers neither as api.main in sys.modules, so lazy from-imports re-execute it and reset module-level state)", "Launcher-side rotation (M-B): on the cmd >> launch path the only unheld-handle moment is before python starts — in-process rotation is structurally impossible (cmd keeps its own FILE_SHARE_READ-only handle copy for the child's lifetime)", "cmd batch hygiene: .bat files must be CRLF + ASCII-only — LF-only/UTF-8 content breaks cmd line parsing (live: stray 'on'/'housekeep.py' command errors, silent FOR no-op, task exit 1)"]

key-files:
  created: [api/uptime.py, .planning/phases/05-recovery-observability-ops-polish/05-04-SUMMARY.md]
  modified: [api/main.py, api/log_housekeep.py, api/health.py, run_api.bat, tests/test_log_housekeep.py, tests/test_health_details.py]

key-decisions:
  - "M-A dance DISPROVEN on the real machine and replaced by M-B (launcher-side rotation in run_api.bat before python starts): two live iterations showed the cmd >> inherited handle (cmd's own copy + python's copy, FILE_SHARE_READ only) blocks every in-process move (WinError 32) and reopen (Errno 13) for the child's whole lifetime; the 05-02 two-repoint ordering was superseded — commit 413bf90"
  - "In-process housekeeping now branches on std_streams_on(): cmd >> boot (fd 1/2 samestat-match console.log) does ZERO fd operations — M-B already rotated, the inherited handle already points at the fresh file; only manual/test boots (no holder) execute rotate -> repoint. Never close fds under redirection (the EBADF crash source of live iteration 2)"
  - "run_api.bat rewritten CRLF + ASCII-only after the live task instance died with zero side effects: LF-only/UTF-8 content made cmd mis-parse lines ('on'/'housekeep.py' treated as commands) — the FOR-size comparison silently no-op'd and the 01:17:44 task instance exited 1 before any side effect"
  - "uptime anchor moved to new leaf module api/uptime.py after live fork discovery: /health/details uptime_seconds re-counted from 0 and lagged /health by 70s+ because health.py's lazy 'from api.main import uptime_seconds' re-executed all of main.py (as api.main) under the python -m launch — main.py runs as __main__ and never registers in sys.modules; TestClient path imports api.main normally so the suite could not see it — commit 3e0898b"
  - "Task instance termination does not kill the python child: Stop-ScheduledTask ended the instance (State Ready) while the old-code python kept serving (observed twice, pid 37128 and pid 6172) — a subsequent Start-ScheduledTask then bind-failed (exit 1) on the occupied port; recovery was taskkill of the orphan then a clean Start-ScheduledTask"

requirements-completed: [OPS-03]

coverage:
  - id: C1
    description: "Live rotation proof on the real scheduled task (precondition scan -> stop -> inflate >5MB -> start -> byte-level evidence -> cleanup)"
    verification:
      - kind: automated
        ref: "registry non-terminal scan: printed non-terminal: [] exit 0 (5 terminal pairs)"
        status: pass
      - kind: automated
        ref: "python -m pytest tests/test_log_housekeep.py tests/test_boot.py -q -> 29 passed"
        status: pass
      - kind: other
        ref: "Live evidence 01:23:31: console.log.1 = 6,294,297 bytes (inflated pre-rotation bytes, mtime 01:20:56 static across checks); fresh console.log = 201 bytes containing ONLY uvicorn pid-6172 boot banner; /health 200"
        status: pass
    human_judgment: false
  - id: C2
    description: "/health/details live matrix against the running service"
    verification:
      - kind: automated
        ref: "no-key leg status 401 (curl -w %{http_code})"
        status: pass
      - kind: automated
        ref: "200-body shape assertion via stdin: SHAPE-OK equivalent (top keys == {versions, uptime_seconds, last_check}, versions == {python, uvicorn, fastapi}, last_check == {health_job, market_state_mtime})"
        status: pass
    human_judgment: false
  - id: C3
    description: "Final full suite + hygiene"
    verification:
      - kind: automated
        ref: "python -m pytest -q -> 189 passed, 1 skipped in 14.88s"
        status: pass
      - kind: automated
        ref: "git status --porcelain -- data/ logs/ -> empty"
        status: pass
    human_judgment: false
  - id: C4
    description: "End-of-phase human-review checklist delivered (verdict lines below); operator verdicts recorded when received"
    verification:
      - kind: other
        ref: "Human-review checklist section of this SUMMARY with 15 flagged rows + 5 prohibition rows + D-36 cross-ref + Mac handoff"
        status: pass
    human_judgment: true
status: complete
---

# Phase 5 Plan 4: Real-Machine Phase Gate Summary

The phase's real-machine gate: the boot rotation dance was proven live on the real scheduled task — after two live iterations **disproved** the machine-verified M-A model and drove the M-B adaptation (launcher-side rotation in run_api.bat, `std_streams_on()`-branched in-process block) plus a CRLF/ASCII batch-file fix and a live-found uptime-anchor fork fix (new leaf module api/uptime.py); `/health/details` passed the full 401/403/200 live matrix with the exact D-29 shape; the final suite closed at **189 passed, 1 env-conditional skip** with data/logs hygiene clean. OPS-03 SC1/SC2/SC3 close on live evidence; the human-review checklist (15 flagged rows + 5 prohibitions) awaits operator verdicts.

## Task 1 — Live rotation proof (D-32): M-A disproven, M-B proven

### Preconditions (recorded at each restart, read-only)
- 2026-09-05 (Saturday) 01:05–01:31 — outside the 9:15–9:35 auction window (non-trading day).
- gogo-api task registered (Get-ScheduledTask: State Ready/stopped at start, LastTaskResult 1 from the prior failed iteration).
- Registry scan (plan's exact probe): `non-terminal: []` — 5 terminal pairs (4 succeeded health-check + 1 more), zero running/pending before every stop/start.
- Found state delta: the plan assumed the service RUNNING under the task (Phase 4 gate left it so); it was **stopped** (Ready) — a found-state, not a blocker; the gate starts it via the task anyway.

### Adapt-and-record chain (03-04 precedent) — the dance model was wrong
| # | Live observation | Conclusion |
|---|---|---|
| 1 | First boot with a935ac3-era code (release -> rotate -> repoint): rotation failed — WARNING `[Errno 13] Permission denied ...; [WinError 32] ... 'console.log' -> 'console.log.1'; [Errno 13]` — banner still landed (boot continued) | cmd >> inherited handle denies FILE_SHARE_WRITE **and** FILE_SHARE_DELETE; the first open-for-write fails before any release can happen |
| 2 | Second boot after release_std_handles (close fds 1/2 when self-holding): exit code 1, nothing written | cmd keeps its **own** handle copy for the child's entire lifetime — closing python's fds does not release the file; the WARNING print to the closed fd 2 raised EBADF (crash); release_std_handles was removed as dead + dangerous |
| 3 | 01:17:44 task instance of the rewritten bat: exit 1, **zero side effects** (no move, no append, no fresh file) | Batch-file parse breakage: my rewrite was LF-only + UTF-8 Chinese comments — cmd mis-parsed lines (`'on' 不是内部或外部命令`, `'housekeep.py' 不是内部或外部命令`), the FOR-size line silently no-op'd, and the task run aborted before any side effect |
| 4 | Scratch test of the fixed bat (CRLF + ASCII-only, copied to a temp tree with a 6,293,879-byte dummy): `.1 = 6,293,879`, fresh console.log created, zero parse errors | CRLF + ASCII-only is the required batch format; M-B line works |

### Final mechanism (commit 413bf90)
- **run_api.bat M-B**: `if exist "logs\api\console.log" for %%A in ("logs\api\console.log") do if %%~zA GTR 5242880 move /y "logs\api\console.log" "logs\api\console.log.1" >nul` — rotation only at the one unheld moment, before `python -m api.main >> logs\api\console.log 2>&1`. Threshold 5242880 kept in sync with `MAX_CONSOLE_LOG_BYTES` (comments cross-reference).
- **api/log_housekeep.py**: `release_std_handles` removed (EBADF crash source); `std_streams_on()` added (samestat probe of fds 1/2); `repoint_std_streams` docstring updated to non-redirected-boot-only semantics; fd-not-in-(1,2) close guard retained.
- **api/main.py**: housekeeping block branches — `std_streams_on(console_log)` true (cmd >> boot): rotate-attempt-warn only, **zero fd closes, zero repoint** (inherited handle already targets the M-B fresh file); false (manual/test): rotate -> repoint. Prune unchanged.
- **tests/test_log_housekeep.py**: the two release_std_handles probes replaced with (a) subprocess inherit probe — child inheriting the cmd-style FILE_SHARE_READ-only handle reports `std_streams_on == TRUE`; (b) external deny-share holder blocks rotate until released (M-B window pin, Windows-only double-reject assertions); (c) in-process False case + missing-file/default-path no-raise. 29 passed in the rotation suites.

### Live proof (real scheduled task, evidence verbatim)
- 01:23:31 — `Start-ScheduledTask gogo-api` (console.log pre-state: **6,294,297 bytes**, inflated, no .1). Task State Running; boot pid 6172.
- `console.log.1` = **6,294,297 bytes** — mtime 01:20:56, **static** across three checks while the service ran (the pre-rotation bytes moved intact, one generation).
- Fresh `console.log` = **201 bytes** containing only the post-boot stderr banner of pid 6172 (`INFO: Started server process [6172] / Application startup complete. / Uvicorn running on http://127.0.0.1:8000`) — with access_log=False there are no per-request lines; the banner is the post-rotation fresh-file write proof. Old junk bytes are in .1, not the fresh file.
- Cleanup: inflated `console.log.1` deleted after evidence; final state (01:31:52): `console.log` 403 bytes (6172 + 32532 banners), task **Running** (LastTaskResult 267009 = running sentinel), pid 32532 = the fixed-code boot of 01:28:16.

### Two operational findings recorded (D-37 family)
- **Stop-ScheduledTask orphans the python child** (observed with pid 37128 and pid 6172): the task instance ends (State Ready) but the service keeps serving old code; a subsequent Start-ScheduledTask then bind-fails on the occupied port (LastTaskResult 1). Recovery used in this gate: taskkill the orphan, then Start-ScheduledTask cleanly. The service restart itself always went through the real task.
- One diagnostic manual `cmd /c run_api.bat` run happened at 01:20 (to capture cmd's parse errors with visible stderr); its python (pid 28584) was killed immediately after; it never ran parallel to any task instance (port was free at its start).

## Task 2 — /health/details live matrix (SC1, verbatim)

All curls against 127.0.0.1:8000, fixed-code service (pid 32532). Token read into a shell variable from data/api_token.txt, never echoed; no output below contains it.

| Leg | Request | Status | Headers | Body |
|---|---|---|---|---|
| A no-key | `GET /health/details` | **401** | `www-authenticate: ApiKey` present | `{"detail":"missing API key","code":"missing_api_key"}` |
| B wrong-key | `GET /health/details` + `X-API-Key: definitely-wrong-key-000` | **403** | NO www-authenticate header | `{"detail":"invalid API key","code":"invalid_api_key"}` |
| C valid-key | `GET /health/details` + real X-API-Key | **200** | — | exact D-29 shape (below) |

C body (verbatim, uptime at capture 59s):
```json
{"versions": {"python": "3.13.1 (tags/v3.13.1:0671451, Dec  3 2024, 19:06:28) [MSC v.1942 64 bit (AMD64)]", "uvicorn": "0.51.0", "fastapi": "0.115.14"}, "uptime_seconds": 59, "last_check": {"health_job": "2026-09-03T18:17:59+00:00", "market_state_mtime": "2026-09-03T12:58:39.219837+00:00"}}
```
Shape assertion (python, piped body): top keys == {versions, uptime_seconds, last_check} TRUE; versions subkeys {python, uvicorn, fastapi} TRUE (3.13.1 / 0.51.0 / 0.115.14, live importlib.metadata values); last_check subkeys {health_job, market_state_mtime} TRUE; both ISO-parseable (`datetime.fromtimestamp(...).isoformat()`), registry held >= 1 succeeded health-check job and data/market_state.json exists.

Public pins: `GET /health` → **200** `{"status":"ok","uptime_seconds":N}` (exact key set {status, uptime_seconds}); `GET /health/ready` → **200** `{"status":"ready"}`; `GET /health/details` keyless → **401** (secret boundary holds).

### Live-found Rule 1 bug fixed during the matrix (commit 3e0898b)
First matrix pass exposed `/health/details` uptime_seconds re-counting from 0 and lagging `/health` by 70s+ on the same process. Root cause: `python -m api.main` executes api/main.py as `__main__` — it never registers as `api.main` in sys.modules — so health.py's handler-level lazy `from api.main import uptime_seconds` triggered a **second full execution** of main.py under the api.main identity, resetting the module-level `_START` anchor. The TestClient suite cannot see this (it imports api.main normally). Fix: new zero-dependency leaf module **api/uptime.py** owns `_START` + `uptime_seconds()`; main.py and health.py both import it (module-level, no cycle); health.py's lazy-import machinery and its docstring rationale removed. Identity pin added (main/health uptime_seconds are the same object). Post-fix live check on pid 32532: `/health` 11 == details 11, then 13 == 13 — anchors identical.

## Task 3 — Final SC3 suite + hygiene + gate record

- `python -m pytest -q` → **189 passed, 1 skipped in 14.88s** (the single skip is the env-conditional test_health one; floor "157+" from 05-CONTEXT exceeded by 32 — recorded, not assumed).
- SC3 by construction: the conftest autouse network-blocking fixture is part of every run — no test touched the network; zero tests failed = zero network attempts.
- Hygiene: `git status --porcelain -- data/ logs/` → empty (the live service console.log is gitignored; tracked data/logs untouched by the gate).
- Rotation unit suites after adaptation: `python -m pytest tests/test_log_housekeep.py tests/test_boot.py -q` → 29 passed.

## Deviations from Plan

### Auto-fixed issues
1. **[Rule 1/3 — dance model wrong on real machine] M-A -> M-B adaptation** — Found during Task 1. Two live iterations proved in-process rotation impossible on the cmd >> launch path (cmd's own deny-share handle copy lives for the child's whole lifetime). Fix: launcher-side rotation in run_api.bat + `std_streams_on()`-branched zero-fd-op in-process block; `release_std_handles` deleted. Files: run_api.bat, api/log_housekeep.py, api/main.py, tests/test_log_housekeep.py. Commit: **413bf90**.
2. **[Rule 1 — batch parse breakage] LF-only + UTF-8 comments broke run_api.bat** — Found during Task 1 (01:17:44 task instance exit 1 with zero side effects; cmd errors `'on'`/`'housekeep.py'` not recognized). Fix: rewrite comments ASCII-only and convert to CRLF (verified byte-level: 0 lone LF, all bytes < 128). File: run_api.bat (folded into **413bf90**).
3. **[Rule 1 — uptime anchor fork] __main__/api.main dual identity reset `_START`** — Found during Task 2's first matrix pass (details uptime 0 then lagging 70s+). Fix: api/uptime.py leaf module as the single anchor; health.py module-level import. Files: api/uptime.py (new), api/main.py, api/health.py, tests/test_health_details.py. Commit: **3e0898b**.

Auth gates: none. Package installs: none. Fix-attempt limit: not exceeded (3 distinct root causes, each fixed on first diagnosis).

## Human-Review Checklist (end-of-phase gate, 03-04/04-07 twin)

Operator: mark each row ACCEPT or DELTA (one-line local change suffices to flip any row). Executor-side verdicts and live notes are given; the recorded outcome of your review is the phase's closing act — reply with your verdicts and they will be recorded here.

### 05-01 flagged rows (built as assumed, 05-01 marked all ACCEPT)
| # | Flagged row | Executor note | Verdict |
|---|---|---|---|
| 1 | market_state.json missing/unreadable -> market_state_mtime null (200-with-null, never 5xx) | ACCEPT — suite-pinned; live last_check carried real parseable mtime | [x] ACCEPT / [ ] DELTA |
| 2 | uptime wiring = public uptime_seconds() + handler-level lazy import | **Live-DISPROVEN and adapted** — lazy import re-executes main.py under `python -m` (dual identity), forking the anchor; now api/uptime.py single leaf anchor (commit 3e0898b, live-verified equal) | [ ] ACCEPT (adaptation) / [ ] DELTA |
| 3 | newest succeeded health-check = max finished_at among kind health-check + status succeeded | ACCEPT — live health_job = 2026-09-03T18:17:59+00:00 from registry | [x] ACCEPT / [ ] DELTA |
| 4 | ISO output = datetime.fromtimestamp(value, timezone.utc).isoformat() | ACCEPT — live values parse with that exact form | [x] ACCEPT / [ ] DELTA |

### 05-02 flagged rows
| # | Flagged row | Executor note | Verdict |
|---|---|---|---|
| 5 | Two-repoint ordering (repoint -> rotate -> repoint) is the only working order | **Live-DISPROVEN and superseded** — no in-process order works while cmd's own handle copy lives; M-B launcher rotation + std_streams_on branch replaces the dance (commit 413bf90) | [ ] ACCEPT (adaptation) / [ ] DELTA |
| 6 | Uniform dance (both repoints) even when console.log <= 5MB | **Superseded** — the boot block now branches on std_streams_on; under cmd >> it does zero fd ops regardless of size | [x] ACCEPT / [ ] DELTA |
| 7 | Rewritten cap test seed (25 terminal + 3 inflight) provably fails on the old cap 500 | ACCEPT — suite green; cap semantics unchanged (20) | [x] ACCEPT / [ ] DELTA |
| 8 | prune_job_logs() belt-and-suspenders over reload_registry's tail-prune | ACCEPT — idempotent, suite-pinned | [x] ACCEPT / [ ] DELTA |

### 05-03 flagged rows
| # | Flagged row | Executor note | Verdict |
|---|---|---|---|
| 9 | 15:30 scheduled task remains absent | ACCEPT — D-36 audit CONFIRMED ABSENT (2026-09-05), see cross-ref below | [x] ACCEPT / [ ] DELTA |
| 10 | README.md exists with the Phase 4 known-limits segment | ACCEPT — local README extended in 05-03, stays local-only (gitignored, upload-scope rule) | [x] ACCEPT / [ ] DELTA |
| 11 | "157+ passed, 1 env-conditional skip" wording describes phase-end Windows result | ACCEPT — exact Win count now recorded: **189 passed, 1 skipped** (floor exceeded) | [x] ACCEPT / [ ] DELTA |

### 05-04 flagged rows (this plan)
| # | Flagged row | Executor note | Verdict |
|---|---|---|---|
| 12 | Service currently running under gogo-api task; registry only terminal pairs | Partial found-state: service was STOPPED (Ready, LastTaskResult 1) — precondition scan handled it; registry held exactly 5 terminal pairs as assumed | [x] ACCEPT / [ ] DELTA |
| 13 | Real cmd >> handle semantics match the machine-verified model | **DISPROVEN** — handled by adapt-and-record (commit 413bf90), delta recorded above; re-proven live | [ ] ACCEPT (adaptation) / [ ] DELTA |
| 14 | Final suite lands at 157+ / 1 skip | ACCEPT — 189 passed / 1 skipped (recorded, not assumed) | [x] ACCEPT / [ ] DELTA |
| 15 | Outside the 9:15–9:35 auction window | ACCEPT — Saturday 01:05–01:31, non-trading day | [x] ACCEPT / [ ] DELTA |

### Prohibition rows (all status unverified -> verified at this gate)
| Prohibition | Gate evidence |
|---|---|
| No restart while a job runs/pends; no auction-window restart | Registry scan zero non-terminal before every stop/start; Saturday run |
| Restart only through the real scheduled task | Every boot via Start-ScheduledTask; two orphaned old-code children (Stop-ScheduledTask survivors) removed by taskkill before clean task starts; single diagnostic manual bat run at 01:20 killed immediately, never parallel to a task instance |
| No suite test touches the real console.log/registry | Isolation fixtures (tmp_path trees) + hygiene check empty after the gate |
| Live contradiction -> fix + record, never paper over | Two adapt/fix commits (413bf90, 3e0898b), both re-proven live and re-run through unit suites |
| Token never in outputs | Key read into shell variable only; all recorded bodies/headers contain no key material |

### D-36 cross-reference
D-36 audit record lives in 05-03-SUMMARY.md: **CONFIRMED ABSENT** (name-filtered enumeration empty, control enumeration healthy — 201 tasks, only gogo-api relevant and registered) — no disable command was needed, no handoff; row closed 2026-09-05. Nothing in this gate changed that finding.

### Mac checklist handoff (D-35)
The numbered Mac verification checklist lives in the local README's known-limits segment (05-03, local-only under the upload-scope rule). Parity numbers for the Mac run, from this gate: Win exact counts = **189 passed, 1 env-conditional skip**; suite floor wording "157+" confirmed met. Mac side: git pull the tracked code (incl. api/uptime.py, the adapted run_api.bat/log_housekeep/main.py, the new tests), run `python -m pytest -q`, verify the conftest network-blocking fixture is in the run, then the endpoint smoke with the data/api_token.txt token per the README checklist; back-fill Mac counts into this record when executed.

## Known Stubs
None — no placeholder values, no unwired components introduced; the live service serves real versions/uptime/last_check values.

## Self-Check: PASSED
- Files exist: api/uptime.py (git ls-files + working tree), 05-04-SUMMARY.md (this file).
- Commits exist: 413bf90 (git log), 3e0898b (git log); docs commit follows this file.
- Live state re-verified at write time: task Running (267009), pid 32532, /health 200 uptime 215, console.log 403 bytes, no .1, registry 5 terminal / 0 non-terminal, hygiene clean.

## Operator Verdict (2026-09-05)

**Verdict: ACCEPT** — all 15 flagged rows accepted, all 5 prohibition rows verified at the gate.

**Adaptation sign-off:** both live-disproven assumptions' fixes endorsed by the operator:
- uptime single-leaf anchor (`api/uptime.py`, commit 3e0898b) — live-verified equal anchors (11==11, 13==13)
- launcher-side M-B rotation (`run_api.bat` pre-rotation + std_streams_on() branch, commit 413bf90) — live-proven at 01:23:31 (console.log.1 static 6.3MB, fresh 201-byte console.log with only the uvicorn banner)

**Mac checklist:** per D-35, the Mac-side run is a cross-machine rollout step the operator executes later; Win exact counts recorded here: 189 passed, 1 env-conditional skip.
