---
phase: 01-service-skeleton-health-liveness
plan: 02
subsystem: infra
tags: [windows, task-scheduler, autostart, launcher, powershell, bat, ops]

# Dependency graph
requires:
  - phase: 01-service-skeleton-health-liveness (01-01)
    provides: api/ package (FastAPI app, GET /health, python -m api.main boot) — the entry run_api.bat launches
provides:
  - run_api.bat repo-root launcher (%~dp0-derived, logs/api capture, PYTHONUTF8=1) — OPS-01 tooling half
  - scripts/daily/install_api_task.ps1 idempotent Task Scheduler installer (gogo-api task)
  - Registered Task Scheduler task gogo-api (AtStartup + 5-min delay, current user Interactive/Limited, never SYSTEM)
affects: [phase-2 state endpoints (service assumed resident), phase-5 log rotation (console.log growth), verify-work end-of-phase reboot UAT]

actuals:
  tokens: 725
  tasks: 3
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Launcher path strategy: cd /d %~dp0 (never a hardcoded BASE — D-09); logs/api auto-created by the bat"
    - "Installer path strategy: $PSScriptRoot climbed twice to the repo root; resolved paths echoed as anti-regression evidence"
    - "Boot-trigger delay via direct CIM property assignment ($Trigger1.Delay = 'PT5M') — PS 5.1 -RandomDelay is silently dropped for boot triggers"

key-files:
  created: [run_api.bat, scripts/daily/install_api_task.ps1]
  modified: []

key-decisions:
  - "Installer runs ELEVATED on this machine: non-elevated Register-ScheduledTask is denied (0x80070005) — RESEARCH assumption A1 disproven; the legacy installer's 'run as administrator' header was required, not legacy caution"
  - "Boot-trigger delay delivered as fixed Delay=PT5M, not RandomDelay: PS 5.1's -RandomDelay parameter is silently dropped for AtStartup triggers (MSFT_TaskBootTrigger CIM class has no RandomDelay property; the task XML schema rejects <RandomDelay> inside <BootTrigger> — confirmed against Register-ScheduledTask -Xml AND schtasks, both error at (32,20)); the legacy convention task never actually carried a random delay either. Fixed 5-min delay preserves the D-07 intent ('runs ~5 min after boot for network readiness') and matches the plan's own reboot-check expectation of ~6 minutes"

patterns-established:
  - "Task Scheduler registration requires elevation on this box; installer header states it, execution uses silent elevation (Davis in Administrators, ConsentPromptBehaviorAdmin=0)"
  - "Trigger verification reads the task XML (Export-ScheduledTask), not CIM properties — Delay/RandomDelay are not reliably surfaced on CIM trigger objects"

requirements-completed: [OPS-01]

coverage:
  - id: D1
    description: "run_api.bat repo-root launcher: exactly 5 ASCII lines (cd /d %~dp0, logs\\api mkdir, PYTHONUTF8=1, python -m api.main >> logs\\api\\console.log 2>&1), no absolute path; live boot from the user-profile directory brought /health to 200 status ok with console.log capturing the uvicorn startup line, and the manual test process was killed freeing port 8000"
    requirement: OPS-01
    verification:
      - kind: other
        ref: "bat launched from C:/Users/Davis (neutral cwd) -> urllib probe asserted status==ok and int uptime>=0 within 30s"
        status: pass
      - kind: other
        ref: "test -s logs/api/console.log && grep -c 'Uvicorn running on http://127.0.0.1:8000' -> 1"
        status: pass
      - kind: other
        ref: "taskkill of the LISTENING pid -> netstat shows no :8000 LISTENING entry"
        status: pass
    human_judgment: false
  - id: D2
    description: "install_api_task.ps1: ASCII-only, $PSScriptRoot-derived paths (echoed), unregister-then-register -Force idempotency, cmd.exe /c wrapper with WorkingDirectory, ONE AtStartup trigger with 5-minute delay, convention settings plus unlimited ExecutionTimeLimit, Interactive/Limited principal for current user"
    requirement: OPS-01
    verification:
      - kind: other
        ref: "two consecutive elevated installer runs exit 0; (Get-ScheduledTask -TaskName 'gogo-api' | Measure-Object).Count == 1"
        status: pass
      - kind: other
        ref: "config probe: State Ready; Execute cmd.exe; Arguments '/c \"C:\\Users\\Davis\\Desktop\\gogo\\run_api.bat\"'; WorkingDirectory C:\\Users\\Davis\\Desktop\\gogo; Triggers count 1; LogonType Interactive; RunLevel Limited; UserId Davis; RestartCount 3; RestartInterval PT10M; ExecutionTimeLimit PT0S; MultipleInstances IgnoreNew; StartWhenAvailable True"
        status: pass
      - kind: other
        ref: "Export-ScheduledTask XML contains <Delay>PT5M</Delay> (schema-supported equivalent of the plan's 5-min random delay)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Starting the registered task boots the service: Start-ScheduledTask gogo-api -> /health 200 status ok within 60s; task State Running, LastTaskResult 267009 (0x41301 SCHED_S_TASK_HAS_NOT_RUN — success class, active first instance, no failure code); console.log grew 4 -> 8 lines with a second uvicorn startup line; service left running; full pytest suite still green (18 passed, 1 skipped)"
    requirement: OPS-01
    verification:
      - kind: other
        ref: "Start-ScheduledTask + urllib poll (12 x 5s) asserted status==ok"
        status: pass
      - kind: other
        ref: "Get-ScheduledTask State Running; Get-ScheduledTaskInfo LastTaskResult 267009; console.log line count grew past baseline"
        status: pass
      - kind: other
        ref: "python -m pytest -q -> 18 passed, 1 skipped (Plan 01-01 gate holds)"
        status: pass
    human_judgment: false
  - id: D4
    description: "Real-reboot auto-start: after the next Windows reboot the gogo-api task fires (AtStartup + 5-min delay) and /health answers 200 at 127.0.0.1:8000 with no manual start"
    requirement: OPS-01
    verification: []
    human_judgment: true
    rationale: "Requires a physical Windows reboot and a human wait (~6 min post-logon) — cannot be automated in this execution; outcome slot recorded below for end-of-phase verification to harvest. If the task does not fire after a reboot, re-run the installer (idempotent) and consider a logon trigger — REPORT to the user rather than silently changing the trigger design"

# Metrics
duration: 9min
completed: 2026-09-03
status: complete
---

# Phase 01 Plan 02: Windows Autostart Summary

**Repo-root run_api.bat launcher plus the idempotent gogo-api Task Scheduler installer, both machine-verified live: the bat boots the resident service from any working directory with all output captured to logs/api/console.log, and Start-ScheduledTask brings /health to a green 200 on 127.0.0.1:8000 — with the real-reboot auto-start confirmation handed off as the end-of-phase human check.**

## Performance

- **Duration:** 9 min
- **Started:** 2026-09-02T22:39:11Z
- **Completed:** 2026-09-02T22:48:19Z
- **Tasks:** 3 (all auto)
- **Files modified:** 2 created (committed in 1 feat commit per the plan's Task-3 default)

## Accomplishments

- **run_api.bat proven from a neutral directory (Task 1):** launched from `C:\Users\Davis` (not the repo root), the bat's `cd /d "%~dp0"` brought the service up — urllib probe returned 200 `{"status": "ok", "uptime_seconds": N}` within 1 second; `logs/api/console.log` was auto-created and contains the uvicorn startup line. The manual test process was killed and port 8000 verified free before the scheduled-task boot (cleanup mandatory per the plan).
- **gogo-api task registered idempotently with machine-verified configuration (Task 2):** two installer runs both exit 0 and leave exactly one task. Configuration probe confirms: State Ready, `cmd.exe` executing `/c "C:\Users\Davis\Desktop\gogo\run_api.bat"` with WorkingDirectory = the real repo root (no stale-path literal anywhere), one AtStartup (boot) trigger, RestartCount 3 / PT10M, StartWhenAvailable, MultipleInstances IgnoreNew, ExecutionTimeLimit PT0S (unlimited — the 3-day default can never kill the resident service), Interactive/Limited principal for user Davis — never SYSTEM.
- **Scheduled-task boot live-probed (Task 3):** `Start-ScheduledTask gogo-api` → `/health` 200 status ok within seconds; State Running; LastTaskResult 267009 (0x41301 = SCHED_S_TASK_HAS_NOT_RUN, a success-class code for the still-active first instance — no failure code); console.log grew 4 → 8 lines with the second uvicorn startup line. The service is LEFT RUNNING as the phase end-state.
- **Phase gate holds:** full pytest suite still green after the autostart work — 18 passed, 1 skipped (unchanged from Plan 01-01).

## Task Commits

Tasks 1-3 committed together at Task 3's end per the plan's default (launcher + installer + live evidence land in one commit; specific-path staging only — no token/log files):

1. **Tasks 1-3: run_api.bat launcher + gogo-api autostart task** - `10d462e` (feat)

**Plan metadata:** docs commit follows this SUMMARY.

## Files Created/Modified

- `run_api.bat` - repo-root launcher (5 ASCII lines): `cd /d "%~dp0"` (D-09), `if not exist logs\api mkdir logs\api`, `set PYTHONUTF8=1` (Pitfall-5 belt), `python -m api.main >> logs\api\console.log 2>&1` — the scheduled task's payload and the one-command local start
- `scripts/daily/install_api_task.ps1` - idempotent Task Scheduler installer for `gogo-api`: `$PSScriptRoot` climbed twice to the repo root (echoed as anti-regression evidence), unregister-then-register `-Force`, `cmd.exe /c "<bat>"` action with WorkingDirectory, one AtStartup trigger with `Delay = 'PT5M'`, convention settings + `-ExecutionTimeLimit (New-TimeSpan -Seconds 0)`, Interactive/Limited principal for `$env:USERNAME`, ASCII-only (comments in English — A4)

## Decisions Made

1. **Installer must run elevated on this machine** — non-elevated `Register-ScheduledTask` is denied (0x80070005); RESEARCH assumption A1 ("no elevation required for current-user registration") is disproven on this box. The plan's contingency ("if access is denied, run that one command elevated once and continue") was applied; elevation is silent here (Davis is in Administrators and `ConsentPromptBehaviorAdmin=0`). The installer header now states the requirement. Every future run needs elevation.
2. **Boot-trigger delay delivered as fixed `Delay = PT5M` instead of `RandomDelay`** — see Deviation 2 below; user-visible behavior (service comes up ~5 minutes after boot) is unchanged from the plan's expectation, and the reboot check's "wait ~6 minutes" wording still holds.
3. **Verification reads task XML, not CIM trigger properties** — `Export-ScheduledTask` is the authoritative view for trigger delay; CIM objects do not surface Delay/RandomDelay reliably on boot triggers.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Task registration denied without elevation (assumption A1 false)**
- **Found during:** Task 2 (first non-elevated installer run)
- **Issue:** `Register-ScheduledTask` failed with `PermissionDenied HRESULT 0x80070005` — the root task folder denies non-elevated create on this machine, exactly what the plan's contingency anticipated ("if access is denied, run that one command elevated once and continue").
- **Fix:** ran the installer elevated via `Start-Process -Verb RunAs` (silent: Davis in Administrators + `ConsentPromptBehaviorAdmin=0`); both runs exit 0, exactly one task registered. The installer's header comment now states elevation is required.
- **Files modified:** scripts/daily/install_api_task.ps1 (header note only)
- **Verification:** task count == 1; full config probe green
- **Committed in:** 10d462e

**2. [Rule 3 - Blocking] PS 5.1 `-RandomDelay` silently dropped on AtStartup triggers — delivered as fixed 5-minute delay**
- **Found during:** Task 2 (config probe showed empty RandomDelay; task XML had `<BootTrigger />` with no delay element)
- **Issue:** `New-ScheduledTaskTrigger -AtStartup -RandomDelay (New-TimeSpan -Minutes 5)` accepts the parameter but produces a trigger with NO delay: the machine's `MSFT_TaskBootTrigger` CIM class has no RandomDelay property (only `Delay`), and the task XML schema rejects `<RandomDelay>` inside `<BootTrigger>` — confirmed against two independent validators (`Register-ScheduledTask -Xml` and `schtasks.exe /Create /XML`, both error "task XML contains unexpected node (32,20): RandomDelay") and COM late binding (`ITrigger.RandomDelay` not reachable). The legacy convention installer carries the same latent bug — its task never actually had the random delay either.
- **Fix:** set the schema-supported fixed delay directly on the CIM trigger instance (`$Trigger1.Delay = 'PT5M'`), verified to round-trip into the registered task XML (`<Delay>PT5M</Delay>`). User-visible behavior matches the plan intent ("runs ~5 min after boot for network readiness" — the plan's own reboot check says "wait about 6 minutes after login (AtStartup trigger + 5-minute random delay)"). The plan's Task-2 verify criterion "RandomDelay is not 5 minutes" maps to the XML `<Delay>PT5M</Delay>`.
- **Files modified:** scripts/daily/install_api_task.ps1 (trigger creation + explanatory comment)
- **Verification:** `Export-ScheduledTask` XML contains `<Delay>PT5M</Delay>` after a fresh installer run
- **Committed in:** 10d462e

**3. [Rule 3 - Environment] Plan's Task-2 verify commands run the installer non-elevated — on this machine that path is denied**
- **Found during:** Task 2 verification
- **Issue:** the verify's `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/daily/install_api_task.ps1` invocation exits non-zero on this box (access denied at registration — deviation 1). The installer's behavior under elevation is identical by construction.
- **Fix:** ran the identical command elevated; exit 0 on both runs; the rest of the verify (task count, config probe) ran as specified and passed.
- **Files modified:** none
- **Verification:** two elevated runs exit 0; task count exactly 1; config probe all green
- **Committed in:** 10d462e

---

**Total deviations:** 3 auto-fixed (all Rule 3 — one environment/privilege finding, one platform-capability finding, one verify-invocation adaptation)
**Impact:** No scope or contract change beyond the trigger-delay nuance: the registered task carries a fixed 5-minute delay instead of a random one because Windows Task Scheduler cannot express a random delay on boot triggers (the legacy convention never actually had one either). Every must-have truth is satisfied with that single documented substitution; the two new files contain no absolute path and no stale BASE line.

## Reboot Backstop (End-of-Phase Human Check) — OUTCOME SLOT

- **Status:** ⬜ PENDING — real reboot not performed during execution (machine left running; service up via the scheduled task)
- **Instructions:** reboot the machine, wait about 6 minutes after login (AtStartup trigger + 5-minute delay), then WITHOUT starting anything manually probe `http://127.0.0.1:8000/health` and confirm 200 with body `{"status": "ok", ...}`.
- **Observed outcome:** _(fill in at end-of-phase verification: passed / what was observed instead — e.g. task did not fire; then re-run the installer and consider a logon trigger, REPORTING rather than silently changing the trigger design)_

## Issues Encountered

None beyond the three deviations above (all diagnosed to root cause and resolved with the machine's own evidence). The background launcher job's exit code 1 after the cleanup taskkill is the expected cmd exit once its child python was force-killed, not a failure.

## User Setup Required

- One physical action, at the next convenient reboot: the Reboot Backstop check above. Nothing in this phase blocks on it — it is harvested at end-of-phase verification.
- Note: the installer now requires an elevated PowerShell on this machine (deviation 1). Re-running it is otherwise idempotent and safe.

## Next Phase Readiness

- **Resident service is live via the OS:** the gogo-api task (AtStartup + 5-min delay, Interactive/Limited, restart-on-failure) makes the service self-healing across reboots — the resident-service promise ROADMAP SC2 depends on. The task's action and working directory are machine-verified to point at the real repo root, so a future repo rename breaks loudly at install time, never silently.
- **Diagnostic channel established:** any boot failure (SEC-03 refusal, bind error, missing module) lands in `logs/api/console.log` (tail it) and surfaces in `Get-ScheduledTaskInfo LastTaskResult` — the Phase 2+ operator loop can rely on both.
- **Machine facts recorded for later phases:** registration needs elevation (A1 false); PS 5.1 cannot express random boot-trigger delays (fixed Delay used); the legacy convention task never carried the delay either — 01-VALIDATION.md's draft manual row (old CJK task name, curl) predates RESEARCH assumption A4 and this plan is authoritative (ASCII `gogo-api`, urllib probes); validate-phase will reconcile.

---
*Phase: 01-service-skeleton-health-liveness*
*Completed: 2026-09-03*
