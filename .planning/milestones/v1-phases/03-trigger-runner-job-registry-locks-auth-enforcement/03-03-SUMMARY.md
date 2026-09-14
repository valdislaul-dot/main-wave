---
phase: 03-trigger-runner-job-registry-locks-auth-enforcement
plan: 03
subsystem: ui
tags: [gui, streamlit, single-flight-lock, d-01, act-03, msvcrt, cross-platform]

requires:
  - phase: 03-01
    provides: "scripts/daily/job_lock.py shared lock helper (acquire(kind, lock_dir) -> fd|None, msvcrt/fcntl ImportError split, zero import side effects) + data/locks/ gitignore"
  - phase: 03-02
    provides: "API POST /v1/actions/pipeline arbitration on the same data/locks/pipeline.lock (409 with/without running_job_id)"
provides:
  - "GUI one-key refresh (scripts/daily/gui_dashboard.py) joined to the single-flight lock: held -> warning + no spawn; free -> unchanged direct subprocess run; timeout path releases the lock and warns"
affects: [03-04 live smoke, ACT-04 v2 taskkill cleanup, Phase 4/5 GBK-output hardening, next Mac-side rollout]

actuals:
  tokens: 320   # chars/4 over the realized code diff (gui_dashboard.py, 1280 chars; D-01 is deliberately the phase's smallest change — plan estimate 26000 overestimated this slice, confidence: low was accurate)
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - "Top-level module import beside `import morning_check as mc` after the file's own sys.path.insert — same-source Win/Mac GUI import shape (D-03)"
    - "acquire-before-run with st.warning skip path; try/except/finally around the untouched run; release in finally on every exit path incl. subprocess.TimeoutExpired"
    - "Success-path-only st.rerun (done flag): a timeout warning must survive on the frame — an unconditional rerun after the except would wipe the mandated warning"

key-files:
  created: []
  modified:
    - scripts/daily/gui_dashboard.py

key-decisions:
  - "st.rerun sits AFTER the try/except/finally, gated on a done flag: the plan's own structural gate requires finally/fd.close/TimeoutExpired textually BEFORE the first st.rerun in the branch (impossible with rerun inside the try body), and an unconditional trailing rerun would erase the mandatory 'pipeline may still be running' warning on the timeout path. Release guarantees are unchanged — finally closes the fd on every exit path; the success path reruns exactly as before; held-lock and timeout paths keep their warning on the current frame without rerun."
  - "Timeout path completes the script run (no st.stop()): the full panel below the refresh button keeps rendering with the timeout warning on top; the child may survive (probe V4) — v2 ACT-04 owns taskkill cleanup, out of D-01 scope."

requirements-completed: [ACT-03]

coverage:
  - id: D1
    description: "gui_dashboard.py refresh handler joined to the shared single-flight lock (top-level `import job_lock`; acquire(\"pipeline\", BASE/data/locks) before the run; held -> st.warning + no spinner/no subprocess/no rerun; try/except/finally with fd.close(); TimeoutExpired warning; subprocess.run argv/cwd/timeout byte-identical)"
    requirement: ACT-03
    verification:
      - kind: other
        ref: "python -m py_compile scripts/daily/gui_dashboard.py -> exit 0"
        status: pass
      - kind: other
        ref: "structural source gate (import present, acquire before run, finally + fd.close, TimeoutExpired + st.warning in branch) -> 'GUI lock-gate structure OK'"
        status: pass
      - kind: automated_ui
        ref: "best-effort AppTest: full script executed headless (0 boot exceptions); held-lock click on 刷新数据 -> '流水线正在运行中(API或其他入口),本次刷新已跳过' warning, no spawn, no exceptions (script run in /tmp, not committed)"
        status: pass
      - kind: other
        ref: "headless boot smoke: streamlit 1.60.0 on 127.0.0.1:8765 -> HTTP 200 in ~3 s, process tree terminated"
        status: pass
    human_judgment: false
  - id: D2
    description: "End-of-phase human gate: free-lock refresh behaves exactly as before D-01 (spinner + 完成 flow), live-API cross-check in the 03-04 window (POST /v1/actions/pipeline then click refresh -> same warning), Mac-parity boot check at next Mac-side rollout"
    verification: []
    human_judgment: true
    rationale: "A real streamlit click in the user's browser cannot be automated headlessly; the free-lock success path spawns the real run_pipeline.py --fast against live data/ (real writes, 180 s window) so it stays a manual step. AppTest covers only the held-lock half (D1). Mac boot check is a cross-machine rollout step (fcntl branch, [ASSUMED A3])."

duration: 6min
completed: 2026-09-04
status: complete
---

# Phase 03 Plan 03: GUI one-key refresh joins the single-flight lock (D-01, ACT-03) — Summary

The streamlit panel's 🔄 刷新数据 button now arbitrates on the exact lock file the API uses — `data/locks/pipeline.lock` (kind `pipeline`) — via the 03-01 shared helper: a click while any holder owns the lock is refused with a visible running-warning and spawns nothing; a free-lock refresh keeps its direct `subprocess.run([sys.executable, 'scripts/daily/run_pipeline.py', '--fast'], cwd=BASE, capture_output=True, text=True, timeout=180)` shape byte-identical; the try/finally release means even the pre-existing `timeout=180` orphan hazard cannot strand the lock. One file modified, verified by compile + structural source gates + a real headless boot + a headless held-lock click + the full pytest suite.

## Performance
- Duration: ~6 min (2026-09-03T17:36:57Z → 17:42Z) / Tasks: 2 / Commits: 2 (1 code + 1 plan metadata)
- Files modified: 1 code file (scripts/daily/gui_dashboard.py), +0 new modules, +0 API changes, +0 lock-helper changes

## Accomplishments
- **D-01 lock-join edit (three insertion points only, everything else byte-identical):**
  1. Import join — `import job_lock` on line 17, immediately after `import morning_check as mc` (line 16), following the file's existing `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`. No `scripts.`-prefixed import; job_lock.py untouched (stays free of scripts.* imports and import-time side effects per its 03-01 build contract) — the same source file boots on Mac via the fcntl ImportError branch (D-03, Pitfall 7).
  2. Refresh-handler lock guard — the button branch moved from lines 86-92 to 87-106:
     - line 88: one-line Chinese comment (D-01 single-flight join, kind pipeline, same `data/locks/pipeline.lock` as the API);
     - line 89: `fd = job_lock.acquire("pipeline", os.path.join(BASE, "data", "locks"))` — BASE is the existing repo-root constant the refresh already passes as `cwd`; no new path constants, no `scripts.daily.config` import;
     - line 91: `fd is None` → `st.warning("流水线正在运行中(API或其他入口),本次刷新已跳过")` and the branch stops — no spinner, no subprocess, no st.rerun;
     - lines 93-99: `try:` wraps the untouched spinner + subprocess.run + success line, `done = True` after the run;
     - lines 101-102: `except subprocess.TimeoutExpired:` → `st.warning("刷新超时——管线可能仍在后台运行,请查看日志后再试")` (probe V4: the child may survive the timeout; v2 ACT-04 owns taskkill cleanup);
     - lines 103-104: `finally: fd.close()` — release on every exit path;
     - lines 105-106: `if done: st.rerun()` — success path only.
     The subprocess.run argv list, `cwd=BASE`, `capture_output=True`, `text=True`, `timeout=180`, the success line, and the spinner text are byte-identical to HEAD.
- **Verification battery (Task 2):**
  - `python -m py_compile scripts/daily/gui_dashboard.py` → exit 0.
  - Structural source gate → printed `GUI lock-gate structure OK` (import present; acquire before run; finally + fd.close; TimeoutExpired + st.warning in the branch segment).
  - Headless boot smoke — `python -m streamlit run scripts/daily/gui_dashboard.py --server.headless true --server.port 8765` answered HTTP 200 in ~3 s (poll via node fetch, 90 s window); process tree terminated via `taskkill /F /T` (root PID 12824, child 33984).
  - Supplementary automated held-lock click (best-effort, not in the plan's gate list): streamlit AppTest executed the full real script headlessly with zero boot exceptions; with the pipeline lock held API-job-style (`job_lock.acquire("pipeline", "data/locks")`), clicking 刷新数据 produced the exact running-warning text, no subprocess spawn, no exceptions. This auto-verifies the held-lock half of the human click-through.
  - Full-suite regression — `python -m pytest -q` from the repo root: **92 passed, 1 skipped in 12.77 s** (up from 71 passed at 03-01 close; 03-02's auth/trigger suites included).
  - Hygiene — `git status --porcelain -- data/ logs/` shows only the three pre-existing user pipeline entries documented in the 03-01 SUMMARY (`M data/historical_zt_pool.json`, untracked `data/zt_pool/20260902.json` / `20260903.json`); the boot smoke, AppTest and suite added nothing. `data/locks/pipeline.lock` created by the AppTest holder is gitignored (`data/locks/`, 03-01) — an expected app artifact identical to what the manual click-through step (a) creates.

## Task Commits
1. **Task 1: gui_dashboard.py D-01 lock-join edit** — `d0df7a3` (feat(03-03): GUI refresh joins single-flight lock (D-01))
2. **Task 2: verify battery** — no repo file produced (evidence recorded here; AppTest harness lived in /tmp) → no task commit
**Plan metadata:** `(docs) commit, final`

## Files Created/Modified
- `scripts/daily/gui_dashboard.py` — the only code file. Import block: +`import job_lock` (line 17). Refresh branch (now lines 87-106): acquire-before-run, held → warning skip path, try/except/finally with `fd.close()`, TimeoutExpired warning, success-only `st.rerun()`. All other lines byte-identical (git diff shows exactly these two hunks).

## Manual click-through scenario (human, end-of-phase — D2)
Recorded for the end-of-phase human gate; run when convenient (the API cross-check needs the 03-04 window):

(a) **Hold the lock the way an API job would** — in a terminal at the repo root:
```
python -c "import sys; sys.path.insert(0, 'scripts/daily'); import job_lock; f = job_lock.acquire('pipeline', 'data/locks'); assert f, 'lock busy'; import time; time.sleep(60)"
```
(b) **Within that minute, launch the GUI** (`streamlit run scripts/daily/gui_dashboard.py`) and click 🔄 刷新数据 — **expected:** the warning `流水线正在运行中(API或其他入口),本次刷新已跳过` appears, NO spinner, NO run, NO rerun (panel stays on the current frame). This half was already auto-verified by the AppTest click (D1).
(c) **Let the holder exit** (the sleep ends or Ctrl+C), click 🔄 刷新数据 again — **expected:** the normal spinner `拉涨停池+评分(轻量)...` then `完成!` and the panel reruns with fresh data — identical to pre-D-01 behavior.
(d) **Optional live-API cross-check (03-04 window):** with the API running, `POST /v1/actions/pipeline` (valid X-API-Key), then click refresh during the run — **expected:** the same running-warning and no second run (GUI-held runs surface as the API's 409-family response and vice versa).
(e) **Mac-parity rollout note:** at the next Mac-side rollout, boot the same file there — the fcntl ImportError branch must load job_lock and the GUI must boot unchanged ([ASSUMED A3] flock equivalence; Mac runs stay serial-by-convention with no crontab lock, so the lock is advisory cooperation only — verify, don't assume).

## Decisions Made
1. **Success-only st.rerun after the try/except/finally (done flag), not st.rerun inside the try body.** The plan letter said to wrap spinner+run+success+rerun in the try; the plan's own blocking structural gate requires `finally:` / `fd.close()` / `subprocess.TimeoutExpired` to appear textually before the first `st.rerun` in the button branch — impossible when rerun is inside the try. And an unconditional trailing rerun would erase the mandatory timeout warning (streamlit clears the frame on rerun). The chosen shape satisfies the gate, keeps every release guarantee (finally closes the fd on all exit paths — success, timeout, any other exception), and preserves behavior: success path reruns last exactly as before; held-lock and timeout paths keep their warning on the current frame.
2. **Timeout path completes the run instead of st.stop()** — the panel below the refresh button keeps rendering with the timeout warning on top. The child may still be alive after TimeoutExpired (probe V4 consequence); D-01's contract is warn-and-release, cleanup is v2 ACT-04.

## Deviations from Plan
1. [Plan-letter vs verify-gate reconciliation] st.rerun placed after (not inside) the try/finally, gated on a `done` flag — required by the plan's own acceptance gate (textual ordering) and by the mandatory visible timeout warning; no release guarantee weakened. — Found during: Task 1 implementation | Files modified: scripts/daily/gui_dashboard.py | Verification: structural gate prints `GUI lock-gate structure OK`; AppTest held-lock click passes; full suite 92 passed | Commit: d0df7a3.
2. [Rule 2 - Robustness, plan-completing] None — the plan letter's other constraints (byte-identical run mechanics, finally-release, no scripts.* import, content-free lock, no stale-cleanup machinery, warning text) were implemented exactly; no additional gaps found.

**Total deviations:** 1 (structural placement, no behavior or interface change). **Impact:** none — gate- and letter-satisfying shape; behavior matches the plan's intent on every path.

## Issues Encountered
- None. (Note: the timeout path could not be exercised live — it needs a >180 s real pipeline run; its evidence is the structural gate + code review, and the warning text is what the human may see in production. Pre-existing GUI `capture_output=True`/GBK degradation remains out of D-01 scope, flagged for Phase 4/5 hardening in RESEARCH.)

## User Setup Required
None - no external service configuration required. The end-of-phase human gate is the click-through scenario above (held-lock warning, free-lock refresh, optional live-API cross-check in the 03-04 window) plus the Mac-parity boot note at next Mac rollout.

## Next Phase Readiness
- 03-04 (live smoke) can now exercise the full SC2 story: API-triggered pipeline run → GUI click during the run shows the warning (the 409-vs-GUI arbitration pair is live on one machine); POST /v1/actions/pipeline while the GUI refresh runs surfaces as the API's 409-without-job_id form.
- v2 ACT-04 (taskkill cleanup of timed-out pipeline children) is the follow-on for the GUI timeout warning path; ACT-05 orphan adoption remains backlogged.
- SC2 "any other entry point" is now covered on this machine: API (03-02) + GUI (03-03) share the same OS byte-range lock; the 15:30 scheduled task remains the only un-locked runner pending the D-02 user decision.

## Self-Check: PASSED
