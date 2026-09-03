---
phase: 03-trigger-runner-job-registry-locks-auth-enforcement
plan: 01
subsystem: api
tags: [jobs, registry, single-flight-lock, subprocess, atomic-write, msvcrt, threading]

requires: []
provides:
  - "api/jobs.py durable registry + spawn governance (03-02 HTTP layer consumes: POST trigger claims via start_job, GET reads via read_job, boot reload via reload_registry in main())"
  - "scripts/daily/job_lock.py shared cross-platform lock (03-03 GUI lock join consumes: top-level import acquire)"
affects: [03-02 actions-router, 03-03 gui-lock, 03-04 smoke]

actuals:
  tokens: 6050
  tasks: 3
  commits: 8

tech-stack:
  added: [msvcrt (byte-range lock), fcntl (posix parity, ImportError split), subprocess.Popen daemon-thread governance]
  patterns: ["tmp + os.replace atomic registry transition with PermissionError retry (WinError-5 reader collision)", "call-time path resolution (LOG_DIR/DATA_DIR module attrs = monkeypatch seam)", "durable-first claim: pending file lands before thread start", "poll readers tolerant of transient replace collision"]

key-files:
  created:
    - api/jobs.py
    - scripts/daily/job_lock.py
    - tests/test_jobs.py
  modified:
    - .gitignore

key-decisions:
  - "write_job retries os.replace on transient PermissionError (4 attempts, 10ms apart): a poll reader's microsecond open window must never flip a transition into a failure or strand the worker (empirical Windows finding, Rule 1)"
  - "run_job's finally sequence guards each step (terminal write / release / lock close / prune) so the OS lock release can never be skipped by a disk-level write failure"
  - "TestClient /health latency test pre-warms 2 requests before the 60 timed requests (framework warm-start is not a latency signal)"

requirements-completed: [ACT-02, ACT-03]

coverage:
  - id: D1
    description: "scripts/daily/job_lock.py shared single-flight lock helper (msvcrt/fcntl split, content-free, dirs at acquire time, zero import side effects)"
    requirement: ACT-03
    verification:
      - kind: unit
        ref: "tests/test_jobs.py#test_job_lock_acquire_deny_reacquire_content_free"
        status: pass
    human_judgment: false
  - id: D2
    description: "api/jobs.py durable per-job JSON registry + spawn governance: atomic transitions, lifecycle succeeded/failed over real subprocesses, UTF-8 emoji log bytes, argv/cwd recorded, claim durable-first"
    requirement: ACT-02
    verification:
      - kind: integration
        ref: "tests/test_jobs.py#test_lifecycle_succeeded_utf8_log_argv_cwd"
        status: pass
      - kind: integration
        ref: "tests/test_jobs.py#test_lifecycle_failed_exit_code_7"
        status: pass
      - kind: unit
        ref: "tests/test_jobs.py#test_claim_durable_pending_then_inmemory_release"
        status: pass
    human_judgment: false
  - id: D3
    description: "reload_registry startup sweep: pending/running -> interrupted in-place atomic rewrite, idempotent, corrupt/dotfile tolerant"
    requirement: ACT-02
    verification:
      - kind: unit
        ref: "tests/test_jobs.py#test_reload_sweep_interrupts_inflight_keeps_terminal"
        status: pass
      - kind: unit
        ref: "tests/test_jobs.py#test_reload_sweep_idempotent_second_sweep"
        status: pass
      - kind: unit
        ref: "tests/test_jobs.py#test_reload_sweep_tolerates_corrupt_and_dotfiles"
        status: pass
    human_judgment: false
  - id: D4
    description: "Registry bounded at 500 terminal jobs (json+log pairs, oldest by mtime); non-terminal preserved; ENOENT-tolerant"
    requirement: ACT-02
    verification:
      - kind: unit
        ref: "tests/test_jobs.py#test_reload_sweep_prune_cap_keeps_500_newest_terminal"
        status: pass
    human_judgment: false
  - id: D5
    description: "Cross-process OS lock evidence: child holds pipeline lock -> parent acquire None; child killed -> parent acquires instantly (OS auto-release)"
    requirement: ACT-03
    verification:
      - kind: integration
        ref: "tests/test_jobs.py#test_job_lock_cross_process_hold_and_kill_releases"
        status: pass
    human_judgment: false
  - id: D6
    description: "SC3: /health answers 200 during a live sleeping child job with p95 wall time < 50ms"
    verification:
      - kind: integration
        ref: "tests/test_jobs.py#test_health_latency_during_running_job"
        status: pass
    human_judgment: false
  - id: D7
    description: "Full-suite gate + data/logs hygiene (tests never touch real data//logs/ trees)"
    verification:
      - kind: other
        ref: "python -m pytest -q -> 71 passed, 1 skipped; git status --porcelain -- data/ logs/ shows only pre-existing user pipeline entries"
        status: pass
    human_judgment: false

duration: 11min
completed: 2026-09-03
status: complete
---

# Phase 03 Plan 01: Shared single-flight lock + durable job registry + spawn governance — Summary

Durable ACT-02/ACT-03 execution core proven end-to-end on this machine: `scripts/daily/job_lock.py` (msvcrt byte-range lock, content-free, OS auto-release) + `api/jobs.py` (per-job atomic JSON registry, daemon worker threads with the V1 UTF-8 spawn env, deterministic-interrupted boot sweep, 500-cap terminal prune), pinned by a 13-test contract suite over real subprocesses. 71 passed / 1 skipped full-suite.

## Performance
- Duration: 11 min (2026-09-03T16:58:42Z -> 17:09:48Z) / Tasks: 3 / Commits: 8 (7 code+test + 1 docs)
- Files modified: 4 (2 new modules, 1 new test file, .gitignore +1 line)

## Accomplishments
- **Shared lock helper (`job_lock.py`, 57 lines)**: RESEARCH Pattern 1 verbatim semantics — msvcrt byte-range lock on win32 / fcntl.flock on posix (ImportError split), content-free lock files (byte 0 locked, nothing written), dirs created at acquire time only, zero `scripts.*` imports and zero import side effects (serves both the API's package-chain import and the GUI's top-level import shape).
- **Durable registry + spawn governance (`api/jobs.py`)**: per-job JSON under `logs/api/jobs/{job_id}.json`; every transition is tmp+os.replace (pid-suffixed tmp, same dir). `claim` writes the pending file BEFORE `Thread.start` — durable at accept. Worker thread: running+pid → `proc.wait()` → succeeded(rc 0)/failed(rc≠0); spawn env pops `GOGO_API_TOKEN` (SEC-01 hygiene) and adds `PYTHONIOENCODING=utf-8` (never PYTHONUTF8=1); CREATE_NO_WINDOW on nt; stdout/stderr straight to the sibling `{job_id}.log` handle (no pipes). A child printing Chinese + emoji (中文-测试-⚠️) logs clean UTF-8 and exits 0 — the V1 regression pin.
- **Crash recovery (SC5)**: `reload_registry` rewrites any pending/running file to deterministic terminal `interrupted` + finished_at (atomic in place), skips corrupt/dotfiles, missing dir created; `prune` keeps only the newest 500 terminal json+log pairs, ENOENT-tolerant, never touches non-terminal files.
- **Cross-process lock evidence**: real child process holds `pipeline.lock` → parent `acquire` returns None; child killed → parent re-acquires instantly (OS auto-release — no stale-lock protocol exists, probe V2 pinned in-suite).
- **SC3 latency**: during a live sleeping child job, 60 in-process GET /health all 200, observed p95 = 3.12 ms (bound: 50 ms). Live-uvicorn confirmation belongs to 03-04.
- `.gitignore` + `data/locks/` (registry already covered by `logs/*`).

## Task Commits
1. **Task 1 (tracer, tdd): lock + lifecycle suite** — `012bf67` (test, red) + `bc54a1f` (feat: job_lock.py + api/jobs.py + .gitignore). Tracer gate: re-ran verify end-to-end after commit — pass, expanded to Task 2.
2. **Task 2 (auto, tdd): reload sweep + prune cap** — `7ee02c4` (test, red) + `c4100ca` (feat: reload_registry).
3. **Task 3 (auto): cross-process + SC3 + full gate** — `5ce3782` (fix: write_job replace retry) + `b946f01` (test: cross-process hold/kill + health latency).
**Plan metadata:** (docs commit, final)
TDD pairs present for both tdd tasks (test before feat in git log).

## Files Created/Modified
- `api/jobs.py` — public surface as built (the 03-02/03-03 contract; do not rename):
  - Module state: `PRUNE_CAP = 500`, `TERMINAL = ("succeeded", "failed", "interrupted")`, `_claims = {}`, `_claims_lock = threading.Lock()`
  - `jobs_dir()` -> `LOG_DIR/api/jobs`, `locks_dir()` -> `DATA_DIR/locks` (both resolved at call time from module attrs — monkeypatch seam)
  - `new_job(kind, cmd)` -> dict with exactly: job_id (uuid4 hex), kind, status="pending", pid, exit_code, log_path, cmd (argv list copy), created_at, started_at, finished_at (nulls)
  - `write_job(job, base=None)` — tmp `.{job_id}.tmp-{pid}` + json.dump(ensure_ascii=False) + os.replace; **os.replace retried 4x on PermissionError (10 ms apart)**; persistent failure removes tmp and re-raises
  - `read_job(job_id, base=None)` — open→read→close utf-8; missing -> None; OSError/ValueError propagate (classification belongs to 03-02)
  - `is_running(kind)` / `claim(kind, job, base=None)` (file first, then `_claims[kind]`) / `release(kind)`
  - `run_job(job, lock_fd, base=None)` — worker target; env copy pops GOGO_API_TOKEN, sets PYTHONIOENCODING=utf-8; CREATE_NO_WINDOW on nt; `with open(log_path,"wb",buffering=0)` only wraps Popen (parent handle closes at with-exit; child keeps its inherited copy); spawn exception -> status failed/exit_code None; finally: finished_at + guarded write_job / release / guarded lock close / guarded prune (release can never be skipped)
  - `start_job(kind, cmd, lock_fd, base=None)` — new_job → claim → daemon Thread(run_job) → return job (caller must hold the OS lock; worker releases it)
  - `reload_registry(base=None, cap=PRUNE_CAP)` — makedirs exist_ok, pending/running → interrupted + finished_at via write_job, corrupt/dotfile skip, ends with prune(base, cap)
  - `prune(base=None, cap=PRUNE_CAP)` — terminal-only pairs by json mtime, oldest first, json+log deleted together, `except OSError: pass` per remove
  - Imports: json/os/subprocess/sys/threading/time/uuid + `from scripts.daily.config import DATA_DIR, LOG_DIR, PROJECT_ROOT` (used only inside functions). Zero import side effects; console text ASCII-only.
- `scripts/daily/job_lock.py` — `acquire(kind, lock_dir)` -> open fd or None; `_try`/`_release` msvcrt/fcntl ImportError split; content-free; zero import side effects; no scripts.* imports.
- `tests/test_jobs.py` — 13 tests, Chinese module docstring: lock unit, succeeded/failed lifecycle over real fake-script subprocesses (UTF-8 emoji bytes, argv/cwd, log_path), claim durability + is_running/release, read_job classification, reload sweep ×3 (interrupt/idempotent/corrupt+dotfile), prune cap 500, cross-process hold/kill, /health p95 latency. Autouse fixture monkeypatches `api.jobs.LOG_DIR/DATA_DIR` to tmp_path + clears `_claims`; helpers `fake_script`, `wait_status`, `wait_terminal`, `_read_tolerant` (poll readers swallow the transient WinError-5 window and retry next tick).
- `.gitignore` — + `data/locks/` beside `data/api_token.txt`.

## Decisions Made
1. **write_job replace retry (Rule 1, empirical):** Windows os.replace collides with a concurrently-open read handle (µs window). Without retry, a poll reader could make a transition write raise: inside run_job's try it spuriously marked a healthy job `failed`; outside (running-state write) it killed the worker thread and stranded the OS lock. Bounded retry (4×10 ms) keeps every transition atomic-and-eventual; the tmp file persists across attempts so retries are idempotent. (Documented in api/jobs.py docstring as a WinError-5-class note extension to api/state.py:62-63.)
2. **run_job finally is fully guarded:** terminal write / release / lock close / prune each isolated so release always runs — a disk-level write failure must never strand the single-flight lock.
3. **Latency test pre-warm:** 2 untimed GETs before the 60 timed requests so framework warm-start is not counted as latency (assertion bound unchanged at 50 ms p95).
4. Test-side only: lifecycle poll for `running` requires pid non-null (running is written twice — pre-Popen pid=None and post-Popen), making the transition pin deterministic.

## Deviations from Plan
1. [Rule 1 - Bug] Popen attribute: plan pseudocode used `proc.exit_code` which does not exist (`returncode` is the attribute); the AttributeError was caught by run_job's except and rewrote the real exit code to None, misclassifying every job as failed. — Found during: Task 1 GREEN verification | Fix: `proc.returncode` | Files modified: api/jobs.py | Verification: lifecycle tests green (exit 0 → succeeded, exit 7 → failed) | Commit: bc54a1f (folded into the feat commit).
2. [Rule 1 - Bug] Windows replace-vs-read collision corrupts transitions (see Decision 1). — Found during: Task 3 verification (intermittent lifecycle failure; suite runs took 8 s timeout when the worker thread died) | Fix: write_job retries os.replace 4×10 ms on PermissionError; poll readers tolerant | Files modified: api/jobs.py, tests/test_jobs.py | Verification: 8/8 consecutive full-file runs green, 71 passed full suite | Commit: 5ce3782.
3. [Rule 2 - Robustness] run_job finally sequence unguarded in plan letter — a failing terminal write would skip `release` and strand the OS lock + claim until restart. — Found during: Task 1 implementation review | Fix: each finally step isolated (see Decision 2) | Files modified: api/jobs.py | Verification: lifecycle + full suite green; release always executes | Commit: bc54a1f.

**Total deviations:** 3 auto-fixed (2 Rule 1, 1 Rule 2). **Impact:** all three were correctness issues in the plan's letter that would have surfaced as flaky/spurious job failures on this machine; auto-fixes keep the pinned public interface and semantics identical.

## Issues Encountered
- Transient `PermissionError` on registry reads while the writer's os.replace is in flight (both directions of the documented WinError-5 class) — fixed at the writer (retry) and made the test pollers tolerant; stable across 8 consecutive file-suite runs.
- Pre-existing working-tree entries under data/ (`M data/historical_zt_pool.json`, untracked `data/zt_pool/20260902.json` / `20260903.json`) were present before this plan and are user pipeline output — the hygiene verify is clean of any new entries; nothing was staged or reverted.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- 03-02 (actions router + auth) consumes the pinned interface: POST handler acquires the OS lock then calls `start_job(kind, cmd, lock_fd)`; GET /v1/jobs/{job_id} calls `read_job` (404 on None, 503 on OSError, classification of ValueError); `main()` gains one `reload_registry()` line after the SEC-03/token block. read_job's documented transient-OSError behavior means the GET layer should map OSError to 503 (never a bare 500).
- 03-03 (GUI lock join) imports `job_lock` top-level and calls `acquire("pipeline", <data/locks>)`, releasing in finally.
- 03-04 live smoke: SC5 kill scenario must use `taskkill /F /T` (tree-kill keeps the orphan edge clean); live-uvicorn P95 re-confirms the 3.12 ms in-process figure.
- Lock helper and registry field set are additive-tolerant consumer surfaces (assumption A6 held by design).

## Self-Check: PASSED
