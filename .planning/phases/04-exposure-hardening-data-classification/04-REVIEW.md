---
phase: 04-exposure-hardening-data-classification
reviewed: 2026-09-04T12:15:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - api/errors.py
  - api/main.py
  - api/private.py
  - api/actions.py
  - scripts/daily/trading_journal.py
  - scripts/daily/date_args.py
  - scripts/daily/run_pipeline.py
  - scripts/daily/morning_check.py
  - tests/test_errors.py
  - tests/test_state.py
  - tests/test_auth.py
  - tests/test_actions.py
  - tests/test_trading_journal.py
  - tests/test_private.py
  - tests/test_date_args.py
  - tests/test_boot.py
findings:
  critical: 0
  warning: 5
  info: 4
  total: 9
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-09-04T12:15:00Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Reviewed the Phase 4 exposure-hardening deliverables: unified machine-readable error envelope (api/errors.py + main.py registration), token-gated /v1/private/* raw-passthrough reads (api/private.py), trigger `?date=` whitelist (date_args.py + actions.py), atomic ledger writes (trading_journal.py), WR-01 env-forced-token boot hardening (main.py), and the 8 test files pinning them.

Cross-checks performed: freeze-table audit of every api/* HTTPException raise-site text against CODE_BY_DETAIL (complete — all 12 raise texts mapped, only framework-origin rows unused), auth/router dependency wiring, whitelist-before-compose ordering in private/actions, 202/409/lock semantics in actions/jobs, session-date gate ordering in both scripts, and byte/header contracts. Test suite result: 95 passed, 4 failed — all four failures are the spawn tests in tests/test_date_args.py failing on their own precondition (dirty data/ tree, see WR-01). Manual subprocess verification confirms the refusal paths themselves behave exactly as pinned (exit 2, empty stdout, ASCII stderr, no traceback, zero writes). No critical defects found; five warnings and four info items below.

The envelope, private read layer, date gate, and boot hardening are carefully built and well-pinned by tests; the findings concentrate on error-path resource cleanup, a ledger matching hazard, and two write-side robustness gaps.

## Warnings

### WR-01: Spawn-refusal tests fail whenever data/ has uncommitted changes — suite is red in normal daily repo state

**File:** `tests/test_date_args.py:114-121, 141, 156`
**Issue:** All four real-spawn tests (`test_real_script_refuses_past_session_date_exit2`, `test_real_script_refuses_invalid_date_exit2` for both scripts) first assert `_git_data_logs_clean()`, which requires `git status --porcelain -- data/ logs/` to be completely empty. This is not the normal state of this repo: every trading-day morning run (per the project workflow, morning_check at 9:25-9:35) modifies tracked `data/auction_state.json` and leaves untracked `data/auction/YYYY-MM-DD.json`; commits/pushes happen only when the user says 推送/同步. In the current working tree all 4 tests fail on the precondition (verified by run: `4 failed, 95 passed`), even though the refusal behavior itself is correct (manually verified: both scripts exit 2 with the ASCII message on stderr, empty stdout, no traceback, no writes). A red suite on every non-committed day will erode the phase's regression pins.
**Fix:** Compare porcelain output before vs. after each spawn instead of requiring a clean start, or exclude the known daily artifacts (`data/auction_state.json`, `data/auction/`) from the cleanliness check:
```python
def _porcelain():
    out = subprocess.run(["git", "status", "--porcelain", "--", "data/", "logs/"],
                         capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=30)
    return out.stdout.strip()
# in test: before = _porcelain(); ...spawn...; assert _porcelain() == before
```

### WR-02: record_sell matches positions by name-OR-code — a mismatched name/code pair silently sells two positions

**File:** `scripts/daily/trading_journal.py:118`
**Issue:** `matched = [p for p in positions if p['name'] == name or p['code'] == code]` unions every position whose name OR code matches the arguments. The 2026-09-03 fix intent is merging multiple buy lots of the *same* stock; but if the caller passes the name of position A together with the code of a different open position B (typo'd code, or stale name — record_sell has no caller-side validation), both A and B are removed, both proceeds credited, and the ledger records a double sell. This ledger is now served as truth through the token-gated /v1/private/portfolio|journal endpoints, so the corruption propagates to every consumer.
**Fix:** Require an exact single-stock match: if any position carries the code, match only by code; otherwise fall back to name-only when unambiguous:
```python
by_code = [p for p in positions if p['code'] == code]
matched = by_code if by_code else [p for p in positions if p['name'] == name]
if not matched or (by_code and any(p['name'] != name and name not in ('', p['code']) for p in by_code)):
    print(f'[Journal] WARNING: no position matches {name}/{code}')
    return pf
```

### WR-03: save_portfolio/save_journal have no os.replace retry — a reader collision splits the portfolio/journal commit

**File:** `scripts/daily/trading_journal.py:46-53, 63-68`
**Issue:** Phase 4 (D-04..D-06) made the ledger writes atomic, and this phase simultaneously introduces token-gated readers (GET /v1/private/journal, /v1/private/portfolio) that hold brief `open('rb')` handles. On this platform, os.replace into a destination file that is momentarily open by a reader raises PermissionError (WinError-5 class) — a collision this repo has actually observed, which is why the sibling writer `api/jobs.py:write_job` (73-85) retries 4 attempts with 10 ms backoff before giving up. The ledger savers do not retry: a collision at `save_portfolio`'s replace crashes `record_sell` before anything is persisted (safe), but a collision at `save_journal`'s replace (line 68) crashes *after* the portfolio was already replaced — positions/cash updated on disk while the journal entry is lost, and the two files the API serves disagree permanently (a rerun of the sell finds no position).
**Fix:** Apply the same bounded PermissionError retry as `api/jobs.py:write_job` to both savers:
```python
for attempt in range(4):
    try:
        os.replace(tmp, PORTFOLIO_FILE)
        return
    except PermissionError:
        if attempt < 3:
            time.sleep(0.01)
            continue
        raise
```

### WR-04: run_pipeline Steps 5 and 7 swallow all failures silently (bare `except: pass`)

**File:** `scripts/daily/run_pipeline.py:166, 181`
**Issue:** `generate()` (Step 5) and `capture_tboard()` (Step 7) are wrapped in bare `except: pass` — no message at all, unlike every other step which prints `[Warning] ... 失败`. A broken daily report or T字板 capture exits the pipeline with success and no diagnostics; a regression in those modules becomes invisible. Bare `except` also catches KeyboardInterrupt/SystemExit, making Ctrl-C dead during those steps.
**Fix:** Match the house pattern used by every other step:
```python
try:
    from generate_report import generate
    generate()
except Exception as e:
    print(f'[Warning] 报告生成失败: {e}')
```

### WR-05: trigger_action leaves the OS single-flight lock held if claim/spawn raises after acquire

**File:** `api/actions.py:99-115`
**Issue:** `fd = job_lock.acquire(...)` succeeds, then `jobs.start_job(kind, cmd, fd)` (line 114) can raise OSError from `write_job` during `claim` (disk full/permission) or `threading.Thread(...).start()` can fail. There is no try/finally that closes `fd`, unlike the worker side (`jobs.run_job` finally unconditionally closes the lock fd). Release then depends on CPython refcounting of the frame after the unhandled exception propagates — nothing in the code guarantees it. While the fd lives, the kind's OS lock is held: subsequent triggers of that kind return 409 `already_running_other_entry` even though no job exists, with no registry entry to inspect. In the Thread.start-failure case the in-memory claim also persists, making the kind unrecoverable without an API restart.
**Fix:**
```python
fd = job_lock.acquire(kind, jobs.locks_dir())
if fd is None:
    ...  # existing 409 branches
try:
    job = jobs.start_job(kind, cmd, fd)
except Exception:
    try:
        fd.close()
    except OSError:
        pass
    raise
return {"job_id": job["job_id"], "kind": job["kind"], "status": job["status"]}
```

## Info

### IN-01: Duplicate `import os`

**File:** `scripts/daily/trading_journal.py:5-6`
**Issue:** `import json, os` immediately followed by `import os`. Harmless but sloppy; the file was touched in this phase for the atomic-write change.
**Fix:** Drop line 6.

### IN-02: Legacy single-position sell writes `"positions": null` into the schema

**File:** `scripts/daily/trading_journal.py:124-141`
**Issue:** When a legacy portfolio (no `positions` list, only `position`) is sold through the else branch, `positions` is bound to `None` and line 139 persists `pf['positions'] = None` — a null where consumers expect a list or an absent key. No current consumer crashes (all use falsy checks), but it is a schema pollution that survives until the next buy heals it.
**Fix:** In the else branch set `positions = []` (or `pf.setdefault('positions', [])`) before removal so the saved file always carries a real list.

### IN-03: api/state.py + api/private.py docstrings claim "导入无副作用 / 不做文件 I/O" while the config import chain runs os.makedirs

**File:** `api/private.py:27-31`, `api/state.py:14-18`, `scripts/daily/config.py:13-14`
**Issue:** Both module docstrings assert the import chain has no file I/O ("后者导入链仅 os/sys/platform"), but `scripts.daily.config` executes `os.makedirs(...)` for four directories at import time. The dirs normally exist so the effect is a no-op, but on a fresh/read-only deployment, importing `api.main`/`api.private`/`api.state` creates directories — exactly the class of import side effect that `tests/test_date_args.py:test_import_purity_no_side_effects` (98) forbids for date_args. The docstrings overstate the purity guarantee.
**Fix:** Correct the docstrings to "零网络能力导入; import 链仅建目录(幂等 makedirs), 不打印/不绑端口", or move the makedirs out of import time.

### IN-04: errors.py comment drift — "400 日期参数族" but both raise sites use 422

**File:** `api/errors.py:49`
**Issue:** The freeze-table comment labels the date rows "400 日期参数族", but both raise sites (`api/private.py:170`, `api/actions.py:92`) raise 422 with those texts. Cosmetic, but the table is the frozen contract — a reader cross-checking status families will be misled.
**Fix:** Change the comment to "422 日期参数族".

---

_Reviewed: 2026-09-04T12:15:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
