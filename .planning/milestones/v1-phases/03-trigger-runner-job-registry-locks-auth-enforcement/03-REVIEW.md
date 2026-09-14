---
phase: 03-trigger-runner-job-registry-locks-auth-enforcement
reviewed: 2026-09-03T18:14:32Z
depth: standard
files_reviewed: 10
files_reviewed_list:
  - .gitignore
  - api/actions.py
  - api/auth.py
  - api/jobs.py
  - api/main.py
  - scripts/daily/gui_dashboard.py
  - scripts/daily/job_lock.py
  - tests/test_actions.py
  - tests/test_auth.py
  - tests/test_jobs.py
findings:
  critical: 0
  warning: 6
  info: 3
  total: 9
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-09-03T18:14:32Z
**Depth:** standard
**Files Reviewed:** 10
**Status:** issues_found

## Summary

Reviewed the Phase 03 trigger/job-registry/lock/auth surface: `api/jobs.py` durable registry + spawn governance, `api/actions.py` protected trigger/job router, `api/auth.py` X-API-Key gate, `api/main.py` registration/boot, `scripts/daily/job_lock.py` shared lock, `scripts/daily/gui_dashboard.py` lock-join, `.gitignore`, and the three contract test suites. The happy-path lifecycle (202 -> pending -> running -> succeeded/failed, atomic registry writes, 409 matrix, auth 401/403, route-level traversal rejection) is well designed and thoroughly pinned by tests; the lock-ordering and durable-first claim design are sound, and I found no exploitable security vulnerability and no blocker in the primary paths.

The findings concentrate in error paths and cross-module consistency, all in the WARNING/INFO range:

1. **Lock/claim stranding on write failure** — the module's own doctrine ("release can never be skipped", 03-01 Decision 2) is violated by three unguarded write sites (`run_job` pre-try write, `trigger_action` claim failure, `reload_registry` boot sweep write). Each converts a transient disk error into a permanently blocked kind or a dead API process.
2. **`backtest-weights` kind silently rewrites the user-confirmed scoring weights** (`scoring_config.json` v4) — an action the project's 定稿机制 gates behind explicit user confirmation and a monthly schedule is now remotely triggerable without any gate.
3. **GUI drift vs. the 2026-09-03 finalized temperature mechanism** — the dashboard's market-env block still advises on the old two-tier thresholds (e.g. `极弱 → 观望/1-3仓` where the final rule is `空仓`).
4. **GUI timeout path releases the single-flight lock while the timed-out child may still be running**, opening a real concurrent-pipeline window (deferral to ACT-04 v2 noted in docs but worth scheduling sooner).

## Warnings

### WR-01: `run_job` running-state write sits outside the try/finally — claim + OS lock strand on write failure

**File:** `api/jobs.py:132-140` (write at line 136; `try:` only begins at line 141)
**Issue:** `run_job` performs `job["log_path"]/status/started_at` assignment and `write_job(job, base)` (line 136) *before* the `try:` block whose `finally` (lines 158-172) owns `release(job["kind"])` and `lock_fd.close()`. `write_job` retries only `PermissionError` (4 x 10 ms) and re-raises any persistent `OSError` — disk full, AV hold beyond 40 ms, or any non-`PermissionError` `OSError` (which raises immediately, no retry). When line 136 raises, the exception escapes the worker thread and the `finally` never runs: the in-memory `_claims[kind]` entry and the OS single-flight lock fd are stranded for the API process lifetime. Every subsequent POST of that kind then returns 409 with a **dead** `running_job_id` (claim hit), and the GUI refresh on the same lock is blocked too. This directly contradicts the module's own comment (line 163: "释放必须永远执行") and 03-01 Decision 2 ("release can never be skipped"). The same class of hole exists for the post-Popen `write_job` at line 153: if it raises after a *successful* spawn, the `except` marks the job failed and the finally releases the lock while the child is still running, permitting a second concurrent run of the same kind.
**Fix:** Move the entire body after `claim` inside the guarded region, e.g.:

```python
try:
    job["log_path"] = os.path.join(base, job["job_id"] + ".log")
    job["status"] = "running"
    job["started_at"] = int(time.time())
    write_job(job, base)
    env = dict(os.environ)
    ...
    with open(job["log_path"], "wb", buffering=0) as fh:
        proc = subprocess.Popen(...)
    job["pid"] = proc.pid
    write_job(job, base)
    job["exit_code"] = proc.wait()
    job["status"] = "succeeded" if proc.returncode == 0 else "failed"
except Exception:
    job["status"], job["exit_code"] = "failed", None
    # note: if Popen already succeeded the child must be killed here,
    # otherwise the finally releases the lock under a live child
finally:
    job["finished_at"] = int(time.time())
    try:
        write_job(job, base)
    except OSError:
        pass
    release(job["kind"])
    try:
        lock_fd.close()
    except OSError:
        pass
    ...
```

### WR-02: `trigger_action` leaks the acquired OS lock if `start_job`'s durable claim write fails

**File:** `api/actions.py:71-88`
**Issue:** `job_lock.acquire` (line 72) succeeds, then `jobs.start_job(kind, cmd, fd)` (line 87) performs the durable pending-file write inside `claim` (`api/jobs.py:113-115`). If that `write_job` raises a persistent `OSError`, the exception propagates out of `trigger_action` unhandled -> bare 500, and the open lock fd is never closed (no worker was started, so `run_job`'s finally never runs). The kind's OS lock is then held until the API process restarts: all later triggers get `409 {"message": "<kind> already running (another entry point)"}` with nothing actually running, and the GUI refresh (same `data/locks/pipeline.lock`) is refused as well. The 404/409 paths are carefully side-effect-free, but this 500 path has the worst side effect of all — a poisoned lock.
**Fix:** Wrap the `start_job` call and close the fd on failure:

```python
try:
    job = jobs.start_job(kind, cmd, fd)
except OSError:
    try:
        fd.close()
    except OSError:
        pass
    raise HTTPException(503, detail="job could not be started")
```

(Consider the same guard for a `Thread.start` failure, which would strand both the claim and the fd.)

### WR-03: `reload_registry` boot-sweep rewrite is unguarded — one unwritable file prevents the API from starting

**File:** `api/jobs.py:214-218` (caller: `api/main.py:76`)
**Issue:** The sweep guards reads (`read_job` -> `except (OSError, ValueError): continue`) but the interrupted-status rewrite `write_job(job, base)` (line 218) is unprotected. A single job file that cannot be rewritten (disk full, permission/ACL change, AV lock beyond the 4 x 10 ms retry window) raises `OSError` out of `reload_registry`, which `main()` calls between the SEC-03 token block and `uvicorn.run` — the exception kills the boot sequence and the whole API refuses to start because of one bad registry file. This contradicts the module docstring's "绝不中断扫描" doctrine, which is only actually true for the read side.
**Fix:** Guard the rewrite like the read:

```python
if job is None or job.get("status") not in ("pending", "running"):
    continue
job["status"] = "interrupted"
job["finished_at"] = int(time.time())
try:
    write_job(job, base)
except OSError:
    continue  # leave as-is; next boot retries
```

### WR-04: `backtest-weights` kind silently overwrites the user-confirmed V4 scoring weights

**File:** `api/actions.py:46` (KIND_CMDS) + `scripts/daily/backtest_v4.py:378-407`
**Issue:** `"backtest-weights": ("backtest_v4.py", ())` triggers the script's *default* mode: a 500-group random weight search that, on completion, writes the newly found weights straight back into `data/scoring_config.json` (`cfg['v4']['weights']`, lines 380-386) and appends `data/weight_history.json` (lines 388-407). Per the project's 定稿机制 (CLAUDE.md, 2026-08-25): scoring weights are user-confirmed frozen configuration, re-search is a scheduled monthly-1st action, and 改动需用户明确确认. The new HTTP surface now makes this config mutation remotely triggerable at any time with no confirmation gate, and it is non-idempotent by construction — each run is a fresh random search, so an accidental double trigger churns a validated config with an unvalidated candidate (and the search is long-running on top of holding the `backtest-weights` lock). The D-09 whitelist was designed as "fixed commands safe to trigger"; this entry does not fit that description.
**Fix:** Add a report-only/no-write mode to `backtest_v4.py` (compute + print + history-readonly, skip the `scoring_config.json` write-back) and point the kind at it, or drop the kind from the map until a confirm-gated flow exists. At minimum, gate the write-back on an explicit flag the HTTP kind never passes.

### WR-05: GUI market-environment block contradicts the 2026-09-03 finalized four-tier temperature mechanism

**File:** `scripts/daily/gui_dashboard.py:142-151`
**Issue:** This block still implements the old two-tier heuristic and its advice contradicts the user-finalized 温度开关四档 (2026-09-03 拍板, implemented as the pure function `temperature.decide_temp_switch`, constants `ZT_WEAK=40 / ZT_SUB=65 / ZT_STRONG=110` at `scripts/daily/temperature.py:11-13`):
- `zt_n < 40 or max_cons <= 2` -> GUI prints "🌡️ 弱市 ... 观望/1-3仓"; the mechanism says 极弱 -> **空仓** (半仓 only on a 升温日 exception).
- `zt_n >= 70 and max_cons >= 5` -> GUI prints "🌡️ 强势"; the mechanism's 强市 line is `zt_n >= 110`.
- Middle ranges collapse to "🌡️ 正常 / 常规仓位" instead of 弱市下沿(40-64) -> 1/3仓 and 弱市(65-109) -> 半仓, and none of the 降档 rules (骤降 -30%/-2板, 竞价二次确认 gap<=-0.5%, 赚钱效应转负) are reflected.

The dashboard is the user's daily post-close panel and this block directly advises position sizing; displaying advice that contradicts the finalized mechanism (e.g. suggesting 1-3仓 where the rule is 空仓) can feed a wrong trading decision.
**Fix:** Replace lines 142-151 with a call to the existing pure function, mirroring `morning_check.compute_environment`:

```python
from temperature import decide_temp_switch
res = decide_temp_switch(zt_n, max_cons, zt_prev, max_cons_prev,
                         avg_gap=auc_gap, money_effect=me)
st.markdown(f"**{res['env']}**：昨日涨停 {zt_n} 只，最高 {max_cons} 板 → {res['switch']}")
```

with the T-1/T-2 pool counts and downgrade inputs sourced the same way `morning_check` does.

### WR-06: GUI timeout path releases the single-flight lock while the timed-out child may still be running

**File:** `scripts/daily/gui_dashboard.py:96-106`
**Issue:** On `subprocess.TimeoutExpired` (line 101) the code warns and the `finally` closes the lock fd — but `subprocess.run(timeout=180)` does **not** kill the child on timeout (documented CPython behavior; the pipeline keeps running to completion). The lock is therefore released while the orphaned pipeline is still mid-write. A subsequent API `POST /v1/actions/pipeline` (which will get 202, since the OS lock is now free) or a second GUI refresh then starts a *second* concurrent pipeline writing the same `data/` files — exactly the double-run the single-flight lock (ACT-03, this phase's core deliverable) exists to prevent. The risk is plausible: a `--fast` run on a slow network/data day can exceed 180 s. The 03-03 summary defers child cleanup to "v2 ACT-04" — documented, but the deferral leaves a hole in the guarantee this phase shipped.
**Fix:** On the timeout path, terminate the child before releasing the lock (Python >= 3.7: use `subprocess.run(..., timeout=180)` inside `try/except`, keep the `proc` handle — e.g. use `Popen` + `communicate(timeout=180)` — and in the `except` do a tree kill: `proc.kill()` on POSIX / `taskkill /F /T /PID <pid>` on Windows, then `proc.wait()`), or schedule the ACT-04 taskkill work into the same release window so the lock is never freed under a live child.

## Info

### IN-01: Stale GUI label text contradicts actual V4 / score_min behavior

**File:** `scripts/daily/gui_dashboard.py:85, 198`
**Issue:** Line 85 renders "V3评分 | ≥{cfg['score_min']}分 | 竞价4-8%" in the title bar, but the GUI has scored with `score_v4` since 2026-08-26 (see comment at line 237) and v3 config was removed. Line 198's empty-state caption hardcodes "评分≥10 且竞价4-8%" while the actual filter (line 181) applies `cfg['score_min']` (50 per project config) — when no buyable stock exists the caption states the wrong threshold and misleads about why.
**Fix:** Change line 85 to "V4评分", and line 198 to `f"无可买标的（评分≥{cfg['score_min']} 且竞价4-8%）"`.

### IN-02: Unused import in api/jobs.py

**File:** `api/jobs.py:19`
**Issue:** `import sys` is never referenced in the module (all `sys.executable` usage lives in `api/actions.py`).
**Fix:** Remove the import.

### IN-03: Orphan tmp files accumulate in the registry directory

**File:** `api/jobs.py:69-70, 234-236` (`write_job` tmp naming; `prune` scan)
**Issue:** If the process dies (or a non-`PermissionError` `OSError` fires) between tmp creation and `os.replace`, `.{job_id}.tmp-{pid}` files are left behind forever: `prune` only considers `*.json` names and explicitly skips dotfiles (line 235), and `reload_registry` also skips them. Growth is unbounded over crash events (one or two files per crash, so slow, but permanent).
**Fix:** In `prune`, additionally remove stale dot-prefixed `*.tmp-*` files (e.g. older than 1 day) — they can never belong to a live writer since each writer's tmp exists only for milliseconds.

---

_Reviewed: 2026-09-03T18:14:32Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
