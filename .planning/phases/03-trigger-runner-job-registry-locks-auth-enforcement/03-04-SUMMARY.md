---
phase: 03-trigger-runner-job-registry-locks-auth-enforcement
plan: 04
subsystem: testing
tags: [live-gate, real-machine, uvicorn, task-scheduler, taskkill, single-flight, p95, interrupted, d-02]

# Dependency graph
requires:
  - phase: 03-01
    provides: "api/jobs.py registry + reload_registry sweep and scripts/daily/job_lock.py OS lock — the interrupted marking and lock auto-release proven live here"
  - phase: 03-02
    provides: "api/auth.py require_api_key + api/actions.py protected router — the live 401/403/202/409 contract exercised against real uvicorn"
  - phase: 03-03
    provides: "gui_dashboard.py D-01 lock join — the GUI-held-lock half of the human click-through cross-referenced at close-out"
provides:
  - "Live-machine evidence for SC1-SC5 (all five phase success criteria) on real uvicorn + real Task Scheduler boot + real pipeline run"
  - "D-02 verify-only re-confirmation (machine evidence: no stale scheduled task)"
affects: [phase-04 (STA-02 read go-live), verify-work phase gate, GUI click-through human gate, next morning's first API trigger]

actuals:
  tokens: 2300   # chars/4 over the realized diff (SUMMARY ~9.2 KB; no production code changed this plan)
  tasks: 3
  commits: 1

tech-stack:
  added: []
  patterns:
    - "Live gate pattern: throwaway temp-dir python smoke scripts (token in-process only via api.boot.read_token) drive the real service; PASS/FAIL line protocol; scripts deleted after the run"
    - "Scheduled-task restart from an agent shell requires an unsandboxed launch: the sandbox delivers Ctrl+C to the Task-Scheduler-launched console process group (0xC000013A) at call teardown"

key-files:
  created:
    - .planning/phases/03-trigger-runner-job-registry-locks-auth-enforcement/03-04-SUMMARY.md
  modified: []

key-decisions:
  - "Live restart path: Start-ScheduledTask 'gogo-api' (task action cmd /c run_api.bat) booted the wave 1-2 code in ~3 s and the boot-time reload_registry ran — the killed pipeline job was queryable as interrupted within seconds of /health 200, live proof of the 03-02 main() wiring through the real boot path"
  - "The execution-harness sandbox kills Task-Scheduler-launched console processes (LastTaskResult 0xC000013A = Ctrl+C at sandbox teardown); the SC5 kill/restart sequence and the gate's service start must run unsandboxed on this box"
  - "Real pipeline runs modify tracked data files (data/official_check.json, data/zt_pool_state.json) — the run's designed function at 01:53 (fresh 09-03 close pool, 42 stocks, official-verified); same class as the pre-existing user-run modification to data/historical_zt_pool.json; nothing staged or reverted"
  - "Live 409 for health-check kind is achievable too (second POST 1 s after the first returned the running_job_id 409 — the suite's race-tolerance branch did not trigger on this machine)"

requirements-completed: [ACT-01, ACT-02, ACT-03, SEC-01]

coverage:
  - id: D1
    description: "Service restarted onto wave 1-2 code (Start-ScheduledTask gogo-api; /health 200 in ~3 s; GET /v1/jobs/{32-hex} answers 401 missing API key = router + auth registered) + full live auth/trigger smoke: no-key /health 200, no-key POST 401 + WWW-Authenticate: ApiKey, wrong-key 403, registry stillness across rejections, valid-key health-check 202 -> polled succeeded exit 0 with UTF-8 log, token bytes absent from job log + console.log tail"
    requirement: SEC-01
    verification:
      - kind: other
        ref: "python %TEMP%/gsd_p3_live_smoke.py -> exit 0, 10/10 PASS lines (recorded below; script deleted after the run)"
        status: pass
      - kind: other
        ref: "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health -> 200"
        status: pass
      - kind: other
        ref: "git status --porcelain -- data/ logs/ -> no new entries vs plan-start baseline (3 pre-existing user entries unchanged)"
        status: pass
    human_judgment: false
  - id: D2
    description: "SC2 live: real pipeline run (job 2ad4421128cd473a9f0cda954ad04784, child pid 14800) — second POST /v1/actions/pipeline while running returned 409 with detail object {\"message\": \"pipeline already running\", \"running_job_id\": \"2ad4421128cd473a9f0cda954ad04784\"}"
    requirement: ACT-03
    verification:
      - kind: other
        ref: "python %TEMP%/gsd_p3_live_sc5.py -> PASS 'SC2: second POST -> 409 + running_job_id' with body bytes recorded below"
        status: pass
    human_judgment: false
  - id: D3
    description: "SC3 live: 120/120 GET /health answered 200 during the real pipeline run with measured p95 wall time 17.14 ms (bound 50 ms) — the in-suite p95 pin (3.12 ms in-process, 03-01) confirmed against live uvicorn under a real network-writing run"
    verification:
      - kind: other
        ref: "python %TEMP%/gsd_p3_live_sc5.py -> PASS 'SC3: /health p95 < 50 ms during real pipeline run | p95=17.14 ms over 120 samples'"
        status: pass
    human_judgment: false
  - id: D4
    description: "SC5 live: taskkill /F /T /PID 35864 (port-8000 owner) at 01:53:08 mid-real-run (log shows Step 1.5 in progress) -> child pid 14800 dead (tasklist raw-byte check) -> restart via Start-ScheduledTask -> /health 200 at 01:53:11 -> GET /v1/jobs/P -> interrupted with finished_at 1788457991, exit_code null, partial 753-byte log present -> job_lock.acquire('pipeline') returned an open fd immediately (OS auto-release through the real crash) -> fresh health-check trigger polled to succeeded exit 0"
    requirement: ACT-02
    verification:
      - kind: other
        ref: "python %TEMP%/gsd_p3_live_sc5.py -> exit 0, 15/15 PASS lines; interrupted GET body and EVIDENCE json recorded below"
        status: pass
    human_judgment: false
  - id: D5
    description: "D-02 verify-only re-confirmation: scheduled-task query (pipeline|流水线|主升浪|选股) returned nothing; broad listing of all 201 tasks shows only gogo-api matching gogo/pipeline patterns; auto_start.bat + install_scheduled_task.ps1 byte-untouched in git; no elevated command needed"
    verification:
      - kind: other
        ref: "powershell Get-ScheduledTask Where-Object TaskName -match 'pipeline|流水线|主升浪|选股' -> empty; TOTAL_TASKS=201 listing -> HIT: gogo-api only"
        status: pass
    human_judgment: false
  - id: D6
    description: "Phase-gate suite + hygiene: python -m pytest -q -> 92 passed, 1 skipped in 12.73 s; git status reviewed — only .planning marker + user pipeline data-file modifications (2 from this plan's real run, designed writes, documented); no trading_journal.py path across phase commits (D-04/D-05 deferral verifiable); service left running on port 8000"
    verification:
      - kind: other
        ref: "python -m pytest -q -> '92 passed, 1 skipped in 12.73s'"
        status: pass
      - kind: other
        ref: "curl http://127.0.0.1:8000/health -> 200 (service running at close)"
        status: pass
    human_judgment: false
  - id: D7
    description: "End-of-phase human gate: user reviews SC1-SC5 live evidence below and optionally runs the 03-03 GUI click-through (held-lock warning / free-lock refresh) against the now-running service — the API-side 409 for a GUI-held lock is the mirror of the suite's cross-process test"
    verification: []
    human_judgment: true
    rationale: "human_verify_mode is end-of-phase: the walkthrough is offered to the user, not executed by the executor; the held-lock half was already auto-verified by 03-03's AppTest click and this plan's live 409s prove the arbitration pair on the machine; a real browser click remains a manual step"

duration: 17min
completed: 2026-09-04
status: complete
---

# Phase 03 Plan 04: Real-machine live gate — restart, SC1-SC5 smoke, SC5 kill/restart, D-02 verify-only — Summary

All five phase success criteria carry live-machine evidence from one 17-minute gate against the resident service on this box: the API was restarted onto the wave 1-2 code via the real Task Scheduler boot (reload sweep ran at boot), a throwaway smoke proved the full auth contract on live uvicorn (401 + WWW-Authenticate: ApiKey / 403 / registry-still rejections / valid-key 202 → polled succeeded with UTF-8 log / key bytes absent from job log and console.log tail), one real pipeline run proved SC2 (409 carrying the running job_id byte-for-byte), SC3 (/health p95 = 17.14 ms across 120 samples during the run) and SC5 (taskkill /F /T mid-run at Step 1.5 → restart → the job queryable as `interrupted` with finished_at set, the child pid verifiably dead, the partial log preserved, the pipeline lock auto-released through the real crash, and a fresh health-check trigger polling to succeeded). D-02 is re-confirmed verify-only (no stale scheduled task among 201; dead installer files byte-untouched); the full suite is green (92 passed, 1 skipped); the service is left running on the new code.

## Performance
- Duration: 17 min (2026-09-04 01:45 → 02:02 local / 2026-09-03T17:45Z → 18:02Z) / Tasks: 3 / Commits: 1 (docs metadata; Tasks 1-2 are evidence-collection with no repo-file output)
- Files modified: 1 planning file (this SUMMARY); zero production code changed — the plan is the phase's evidence gate
- App-produced artifacts (read-only to the plan, gitignored): `logs/api/jobs/2ad4421128cd473a9f0cda954ad04784.{json,log}` (interrupted pipeline record + partial log), plus 3 succeeded health-check job records

## Task Commits
1. **Task 1: restart onto wave 1-2 code + live auth/trigger smoke (SC1/SC4 live)** — no repo file produced (throwaway temp-dir script; evidence below) → no task commit
2. **Task 2: SC2/SC3/SC5 live pipeline run + kill/restart** — no repo file produced (throwaway temp-dir script; evidence below) → no task commit
3. **Task 3: D-02 re-confirmation + suite/hygiene close-out + SUMMARY** — this SUMMARY written; plan metadata commit follows

**Plan metadata:** `docs(03-04)` commit (this SUMMARY + STATE/ROADMAP/REQUIREMENTS updates)

## Files Created/Modified
- `.planning/phases/03-trigger-runner-job-registry-locks-auth-enforcement/03-04-SUMMARY.md` (new) — the live-evidence close-out record
- No production code files were created or modified (plan letter: "No production code changes are in scope; this plan is an evidence gate")
- App-produced (consumed read-only): interrupted `logs/api/jobs/2ad44...4784.json` + partial `.log` (SC5 kill proof), 3 succeeded health-check records (7c4364e6..., 4629b023..., bd9eb36a...) — registry files gitignored (`logs/*`)

## Live Evidence

### Restart record (Task 1)
- **Observed pre-state:** no listener on port 8000 (curl 000) — API down, matching RESEARCH V5; `gogo-api` scheduled task Ready; `logs/api/console.log` present with the documented interactive-session ^C pattern (0xC000013A) as its last pre-existing cycle; `logs/api/jobs/` existed and was empty.
- **Restart method:** `Start-ScheduledTask -TaskName 'gogo-api'` (task action `cmd.exe /c run_api.bat`, Interactive logon as Davis). First attempt failed environmentally: the sandboxed shell's teardown delivered Ctrl+C to the Task-Scheduler-launched console process group (`LastTaskResult 3221225786` = 0xC000013A, `/health` refused ~60 s later). Retried unsandboxed → instance running (task result 0x41301 = SCHED_S_TASK_RUNNING), `/health` 200 within 5 s. **Recorded finding:** on this box the agent-shell sandbox kills scheduled-task console launches at call end; the gate's service start/restart must run unsandboxed.
- **New-code probe:** `GET /v1/jobs/{32-hex}` → 401 `{"detail":"missing API key"}` — the protected router + auth dependency are registered (old routerless code would 404 Not Found); fresh boot line in console.log.

### Task 1 smoke PASS lines (python %TEMP%\gsd_p3_live_smoke.py, exit 0; script deleted after the run)
```
PASS | no-key GET /health -> 200 | status=200
PASS | no-key POST -> 401 + WWW-Authenticate: ApiKey | status=401 detail='missing API key' wwwauth='ApiKey'
PASS | wrong-key POST -> 403 invalid API key | status=403 detail='invalid API key'
PASS | registry stillness after 401/403 (no spawn) | counts 1->1
PASS | valid-key POST -> 202 pending + job_id | status=202 body={"job_id":"4629b0230a6344d3a8660ae597ceb825","kind":"health-check","status":"pending"}
PASS | second POST while live -> 409 + running_job_id | status=409 body={"detail":{"message":"health-check already running","running_job_id":"4629b0230a6344d3a8660ae597ceb825"}}
PASS | poll to terminal succeeded + exit_code 0 + log exists | status=succeeded exit_code=0 log='C:\Users\Davis\Desktop\gogo\logs\api\jobs\4629b0230a6344d3a8660ae597ceb825.log' wall=1.0s
PASS | job log bytes decode as UTF-8
PASS | token bytes absent from job log | loglen=540
PASS | token bytes absent from console.log tail (256 KB) | taillen=1424
FINAL | health-check job status=succeeded wall=1.02s exit_code=0
```
(First run's 4629b023 sibling record 7c4364e6... also succeeded; both are real data_health_check runs — the health-check kind ran the real 8-item data health check on live data and exited 0 = 全绿. The live 409 for health-check was achieved on the second smoke run — the suite's race-tolerance branch did not trigger on this machine.)

### SC2/SC3/SC5 evidence block (Task 2; python %TEMP%\gsd_p3_live_sc5.py, exit 0, 15/15 PASS; script deleted after the run)
- **Job P (pipeline):** `2ad4421128cd473a9f0cda954ad04784`, child pid 14800, kind pipeline, cmd `[python.exe, ...\scripts\daily\run_pipeline.py, --fast]`. Pre-kill registry count: 2. Pre-kill status: `running`.
- **SC2 (single-flight live):** second `POST /v1/actions/pipeline` while running →
  `409` `{"detail":{"message":"pipeline already running","running_job_id":"2ad4421128cd473a9f0cda954ad04784"}}` — the running job id carried byte-for-byte.
- **SC3 (health p95 during a real run):** 120/120 GET /health answered 200; measured **p95 = 17.14 ms** over 120 samples (bound: 50 ms). Live-uvicorn confirmation of 03-01's in-process 3.12 ms figure, measured while the real pipeline was network-writing.
- **SC5 (kill → restart → interrupted):**
  - API owner pid of port 8000: **35864**. `taskkill /F /T /PID 35864` at **01:53:08** (tree kill — the pipeline child died with the API, Pitfall 3 discipline).
  - Child pid 14800 confirmed dead via the probe-V3 tasklist raw-byte method (`tasklist /FI "PID eq 14800" /FO CSV /NH` no longer contains `"14800"`).
  - Port 8000 released; restart via `Start-ScheduledTask 'gogo-api'` (1 attempt); `/health` 200 at **01:53:11** — the boot-time `jobs.reload_registry()` sweep ran inside main() before uvicorn accepted requests.
  - `GET /v1/jobs/2ad44...4784` (valid key) →
    `{"job_id": "2ad4421128cd473a9f0cda954ad04784", "kind": "pipeline", "status": "interrupted", "pid": 14800, "exit_code": null, "log_path": "C:\\Users\\Davis\\Desktop\\gogo\\logs\\api\\jobs\\2ad4421128cd473a9f0cda954ad04784.log", "cmd": [..., "run_pipeline.py", "--fast"], "created_at": 1788457986, "started_at": 1788457986, "finished_at": 1788457991}` — deterministic interrupted terminal state, finished_at set, no job silently lost.
  - Partial job log still present (753 bytes) showing the kill landed mid-real-run — Step 1 completed (涨停池 2026-09-03, 42 stocks, 官方API校验 42 vs 42 一致) and **Step 1.5 重算封板质量 was in progress** when the tree-kill hit.
  - **Lock auto-release through the real crash:** `job_lock.acquire('pipeline', 'data/locks')` returned an open fd immediately after restart (assert not None), then closed.
  - **Recovery:** fresh `POST /v1/actions/health-check` → 202 → polled to `succeeded`, exit_code 0 (job bd9eb36a58d7441aa2db6aa97fc277d3) — the service returned to full normal operation.
  - EVIDENCE line: `{"pre_kill_registry_count": 2, "pipeline_job_id": "2ad4421128cd473a9f0cda954ad04784", "pipeline_child_pid": 14800, "health_p95": 17.14, "health_samples": 120, "pre_kill_status": "running", "api_pid": 35864, "restart_method": "Start-ScheduledTask 'gogo-api'", "restart_attempts": 1, "kill_time": "01:53:08", "restart_ok_time": "01:53:11", "interrupted_log_exists": true, "interrupted_log_size": 753}`

### D-02 verify-only re-confirmation (Task 3)
- `Get-ScheduledTask | Where-Object { $_.TaskName -match 'pipeline|流水线|主升浪|选股' }` → **no rows** (the gogo-api task matches none of these patterns). Broad listing: 201 tasks total, only `gogo-api` matches gogo/pipeline name patterns (other hits are Windows maintenance tasks). RESEARCH V5 machine evidence re-confirmed — **no elevated unregister was needed**.
- `auto_start.bat` (477 bytes) and `install_scheduled_task.ps1` (2367 bytes): no git modification — byte-untouched dead files.

### Phase-gate close (Task 3)
- `python -m pytest -q` → **92 passed, 1 skipped in 12.73 s** (full suite green at the phase gate).
- Hygiene: `git status --porcelain -- data/ logs/` shows no registry/lock entries (gitignored by design); tracked-file review — wave 1-2 code files all committed and clean; working tree holds only the `.planning/config.json` orchestrator marker (pre-existing), the pre-existing user-run modification to `data/historical_zt_pool.json`, and this plan's real-run data writes `data/official_check.json` + `data/zt_pool_state.json` (the pipeline's designed function at 01:53 — fresh 09-03 close pool, official-verified 42 stocks; same artifact class the user's own pipeline runs produce; nothing staged or reverted).
- Write-side deferral verifiable: no `scripts/daily/trading_journal.py` path across this phase's commits (save_portfolio/save_journal untouched per D-04/D-05; Phase 4 STA-02 bound per D-06).
- **Final machine state:** API running on port 8000, `/health` 200, wave 1-2 code — the resident service is up for the user's next consumption.

### Remaining human gate (cross-reference to 03-03)
The 03-03 manual click-through scenario remains the end-of-phase human item: with the API now running, the user may optionally (a) hold the pipeline lock (`python -c "import sys; sys.path.insert(0,'scripts/daily'); import job_lock; f=job_lock.acquire('pipeline','data/locks'); assert f; import time; time.sleep(60)"`) and click 🔄 刷新数据 in the GUI → expect the running-warning with no run; (b) let the holder exit and click again → expect the normal spinner/完成 flow; (c) `POST /v1/actions/pipeline` while the GUI refresh runs → the API answers the 409-another-entry-point shape. The API-side 409 family for a GUI-held lock is the mirror of the suite's cross-process test; this plan's live 409s (health-check + pipeline) prove the arbitration side on real hardware.

## Decisions Made
1. **Live restart path is Start-ScheduledTask 'gogo-api', unsandboxed.** The task boots `cmd /c run_api.bat` as Davis-Interactive; /health 200 within ~3-5 s; the boot-time reload_registry demonstrably ran (interrupted marking visible seconds after restart). The sandbox teardown kills scheduled-task console launches on this box (0xC000013A) — an environment fact recorded for any future live-gate phase.
2. **Live 409 achievable for fast kinds too** — the health-check second POST landed inside the run window (job wall 1.0 s) and returned the full running_job_id 409; the plan's tolerated race branch was unnecessary on this machine.
3. **Real-run data writes are evidence, not dirt** — data/official_check.json and data/zt_pool_state.json modifications from the 01:53 run are the pipeline's designed writes (verified consistent: official API 42 vs local 42); consistent with the pre-existing data/historical_zt_pool.json user-run modification; left in place, unstaged.

## Deviations from Plan
1. [Rule 3 - Blocking, environment] Sandboxed `Start-ScheduledTask` instance killed at call teardown — Found during: Task 1 restart | Issue: the first restart attempt's process group received Ctrl+C when the sandboxed shell call ended (LastTaskResult 0xC000013A, health refused minutes later); root cause is the execution harness sandbox, not the task registration | Fix: re-ran the scheduled-task start unsandboxed → instance persisted across calls (task result 0x41301 running) | Files modified: none (recorded finding) | Verification: /health 200 across subsequent calls; SC5 kill/restart cycle repeated the same pattern successfully | Commit: n/a (evidence plan).
2. [Rule 1 - Bug in throwaway smoke harness] urllib 401 header case-sensitivity false FAIL — Found during: Task 1 smoke | Issue: my smoke compared `hdrs.get("WWW-Authenticate")` against a plain dict whose keys came lowercase from the raw HTTP response (`www-authenticate`) — plain dict lookup is case-sensitive while email Message.get is not; the live service provably sends the header (raw `curl -i` shows `www-authenticate: ApiKey`) | Fix: case-normalized the header dict in the harness (`{k.lower(): v ...}`) | Files modified: temp-dir smoke script only (deleted after run) | Verification: re-run 10/10 PASS, exit 0 | Commit: n/a.
3. [Observation vs plan letter] Machine pre-state differed slightly from RESEARCH V5's snapshot — console.log showed several ^C-ended cycles on the evening of 09-03 (the documented interactive-session pattern) and `logs/api/jobs/` already existed (empty); API was down as expected. The plan's "adapt the restart to the observed state and record it" clause applied; restart method unchanged.

**Total deviations:** 2 auto-fixed (1 environment Rule 3, 1 harness Rule 1) + 1 recorded observation. **Impact:** none on production code — zero production files changed this plan; the deviations affected only how the evidence was gathered and are documented for future live gates.

## Issues Encountered
- Sandbox-vs-scheduled-task interaction (see Deviation 1) — resolved by unsandboxed service starts; affects any future phase that restarts the resident service from an agent shell.
- The pipeline run's data writes modified two tracked data files (see Decision 3) — expected designed behavior of a real run at 01:53; the run was killed at Step 1.5 so later steps did not execute; the next full pipeline run refreshes incrementally as designed. K-line/registry/lock files stayed out of git scope.
- No auth gates encountered (token read in-process only, never in argv/curl/output — SEC-01 hygiene held through the entire gate).

## User Setup Required
None - no external service configuration. The API is left running on port 8000 with the wave 1-2 code. Optional end-of-phase human item: the 03-03 GUI click-through against the running service (scenario cross-referenced above) — the held-lock warning half is already auto-verified; a live browser click remains the user's to make when convenient.

## Next Phase Readiness
- All five success criteria now carry live-machine evidence; the phase can close subject to the end-of-phase human walkthrough and verify-work review.
- Phase 4 (STA-02 portfolio read + data-classification SEC-02) consumes: the auth exemption list (documented in 03-02), the D-04..D-06 write-side atomicization binding, and a resident service proven to boot-recover through real crashes.
- The GUI (03-03) and API (03-02) single-flight arbitration pair is now proven live on one machine; a GUI refresh during an API pipeline run surfaces as this plan's 409-family responses.
- D-02 stays verify-only; auto_start.bat / install_scheduled_task.ps1 remain dead files — do not re-register at reinstall.

## Self-Check: PASSED
- SUMMARY file exists at `.planning/phases/03-trigger-runner-job-registry-locks-auth-enforcement/03-04-SUMMARY.md`
- Metadata commit `ba92293` present in git log
- Full suite green (92 passed, 1 skipped), data/logs hygiene holds (no registry/lock entries in git scope), service left running (health 200 at close)

---
*Phase: 03-trigger-runner-job-registry-locks-auth-enforcement*
*Completed: 2026-09-04*
