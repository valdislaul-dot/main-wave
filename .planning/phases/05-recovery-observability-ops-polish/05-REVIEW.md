---
phase: 05-recovery-observability-ops-polish
reviewed: 2026-09-05T01:08:02Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - api/health.py
  - api/uptime.py
  - api/log_housekeep.py
  - api/jobs.py
  - api/main.py
  - run_api.bat
  - tests/test_health_details.py
  - tests/test_auth.py
  - tests/test_boot.py
  - tests/test_jobs.py
  - tests/test_log_housekeep.py
findings:
  critical: 0
  warning: 3
  info: 4
  total: 7
status: issues_found
---

# Phase 5: Code Review Report

**Reviewed:** 2026-09-05T01:08:02Z
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Reviewed the Phase 5 delta: auth-gated `GET /health/details` (api/health.py + api/uptime.py single-leaf anchor), log-rotation primitives (api/log_housekeep.py, run_api.bat M-B launcher rotation, api/main.py boot block), PRUNE_CAP 500→20 (api/jobs.py), and their contract suites. Cross-checked against api/auth.py, api/boot.py, api/actions.py, api/errors.py, api/state.py, scripts/daily/config.py, scripts/daily/job_lock.py, tests/conftest.py, and the live state under logs/api/jobs (5 terminal pairs; logs/ gitignored).

The Windows cmd `>>` launch path is well analyzed and the live-verified constraints (deny-share handle, M-B window, CRLF/ASCII batch hygiene, dual-identity uptime anchor) are correctly reflected in code. The 401/403/200 matrix, D-29 shape, null legs, and cap-20 prune semantics are suite-pinned and consistent with the implementation. Three Warnings remain — one platform-conditional logic gap in the in-process boot branch, one test-isolation gap that touches the real registry with now-destructive pruning, and one shape-validation gap in the shared registry-scan tolerance contract.

## Warnings

### WR-01: True-branch rotate success strands fd 1/2 on the renamed console.log.1 (no repoint)

**File:** `api/main.py:123-126`
**Issue:** When `std_streams_on(console_log)` is True, the boot block attempts `rotate_console_log` and only prints a warning on error. If the rotation *succeeds* (file > 5MB and rename permitted), fd 1/2 still point at the renamed inode — now `console.log.1` — and nothing repoints them to a fresh `console.log`. Consequences of a successful True-branch rotate:
1. The current session's entire output (uvicorn banner onward) lands in `console.log.1`, the file named "one generation old"; the `console.log` path is left absent until the next launch creates it.
2. At the following boot, a `> 5MB` `console.log` is renamed over the existing `.1` (`os.replace`, log_housekeep.py:44), discarding the previous generation — including that session's live tail.

On the Windows cmd `>>` path this cannot occur (the inherited handle denies FILE_SHARE_DELETE, so rename fails and the warning fires — the designed degraded mode). But on POSIX (Mac rollout per D-35 runs the suite; shell `>>` redirect launches allow rename with open fds) and on any launcher that grants share-delete on the redirected handle, rotation succeeds and the session log is silently misplaced. The False branch performs the correct rotate → repoint dance; the True branch omits the repoint half. Note the code already captures the success signal in `_rotated` (line 124) but never uses it.

**Fix:** Repoint when rotation actually succeeded:
```python
if log_housekeep.std_streams_on(console_log):
    _rotated, rotate_err = log_housekeep.rotate_console_log(console_log)
    if _rotated:  # rename succeeded -> heal fd split (POSIX / share-delete launchers)
        repoint_err = log_housekeep.repoint_std_streams(console_log)
        if repoint_err:
            print(f"WARNING: log repoint failed - {repoint_err} - continuing boot", file=sys.stderr)
    elif rotate_err:
        print(f"WARNING: console.log rotation skipped - {rotate_err} - continuing boot", file=sys.stderr)
```
On Windows cmd `>>` this stays a no-op (rotate cannot succeed), preserving the live-verified M-B behavior.

### WR-02: test_boot full-boot tests escape the isolation pin and run reload_registry against the real logs/api/jobs

**File:** `tests/test_boot.py:118-129, 151-162, 166-177, 209-225` (with `api/main.py:106`, `api/jobs.py:191-219`)
**Issue:** Four tests call `api.main.main()` to completion but patch only `api.main.DATA_DIR`/`api.main.LOG_DIR`. `main()` invokes `jobs.reload_registry()` with the default base, which resolves `api.jobs.LOG_DIR` — unpatched, pointing at the real `logs/api/jobs`. The suite's own isolation pin ("real data/ and logs/ zero touch", CRITICAL 数据隔离 in the other test modules) is therefore violated:
1. If the suite runs while the real scheduled service has a pending/running job, the real job file is rewritten to `interrupted` with a fresh `finished_at` (jobs.py:216-218) — live registry corruption from a test run.
2. The tail `prune(base, cap)` (jobs.py:219, 222-254) now applies the Phase 5 cap of **20** (was 500). During the transition window — a real registry still holding >20 terminal pairs accumulated under the old cap — each of the four full-boot tests silently deletes the oldest terminal json+log pairs from the real registry.
3. The gate's hygiene claim (`git status --porcelain -- data/ logs/` empty, 05-04-SUMMARY C3) cannot detect any of this: `logs/` is gitignored (`logs/*`, `logs/*.log`), so writes to the real registry are invisible to git. The "no suite test touches the real registry" prohibition was verified with a blind check.

Additionally, each of these four tests executes `repoint_std_streams` for real inside the pytest process (main.py:129), dup2-ing the test runner's own fd 1/2 onto the tmp console.log — currently tolerated by pytest capture, but it is the in-process boot path running with real side effects rather than a patched one.

**Fix:** Patch the jobs seams in the four full-boot tests, mirroring test_jobs' fixture:
```python
monkeypatch.setattr(api.jobs, "LOG_DIR", str(tmp_path))
monkeypatch.setattr(api.jobs, "DATA_DIR", str(tmp_path))
```
(or add an autouse fixture to test_boot doing this for every test), and strengthen the hygiene check to assert the real registry is byte-identical before/after the suite rather than relying on git status of untracked files.

### WR-03: Registry scans assume dict JSON — valid non-object JSON raises AttributeError (500 on /health/details, boot crash)

**File:** `api/health.py:89` (also `api/jobs.py:214`, `api/jobs.py:241`)
**Issue:** All three registry scans guard `read_job` against `OSError`/`ValueError` (missing file, torn file, corrupt JSON) but not against *well-formed JSON of the wrong shape*. `read_job` (jobs.py:88-99) returns whatever `json.load` produces. A registry file containing `[1, 2]`, `"hello"`, `42`, or `true` parses cleanly and then:
- `api/health.py:89` — `job.get("kind")` raises AttributeError → unhandled → **500** on `GET /health/details`. This directly violates the module's documented contract "扫描永不被外来字节打成 5xx (T-05-03)" and its test matrix (test_health_details covers corrupt JSON `{not json` at line 238-244 but not parseable non-object JSON).
- `api/jobs.py:214` (reload_registry) and `api/jobs.py:241` (prune) — same AttributeError. In reload_registry the trailing `prune(base, cap)` (line 219) is unwrapped, so the exception propagates out of `main()`'s boot sequence (main.py:106) after token handling — the API **fails to start** until the offending file is removed by hand.

Write paths always produce dicts (write_job), so a realistic trigger requires an external writer or operator hand-edit — but the tolerance contract explicitly promises immunity to "外来字节", and this is exactly the class of file the scans claim to survive.

**Fix:** Type-guard after every read in the three scan sites:
```python
job = jobs.read_job(stem, base)
if not isinstance(job, dict):
    continue  # 非对象 JSON (list/str/int/bool/null) -> 跳过, 绝不 5xx / 绝不崩 boot
```
(`job is None` checks become redundant but harmless.) Add a test seeding a parseable non-object file (e.g., `[1,2]`) asserting 200-with-null on /health/details and no-raise through reload_registry/prune.

## Info

### IN-01: Rotation threshold duplicated across launcher and module

**File:** `run_api.bat:12` (with `api/log_housekeep.py:23`)
**Issue:** `MAX_CONSOLE_LOG_BYTES = 5 * 1024 * 1024` (python) and the literal `5242880` (bat) are the same constant in two languages, kept in sync only by cross-referencing comments. A future threshold change in one place silently diverges the M-B window from the in-process check. Both comments acknowledge the coupling; a drift guard is cheap.
**Fix:** Pin the coupling in a test (e.g., assert the bat contains the literal `str(api.log_housekeep.MAX_CONSOLE_LOG_BYTES)`), so any one-sided change fails the suite.

### IN-02: `_rotated` is assigned in both branches and never read

**File:** `api/main.py:124, 128`
**Issue:** Both branch assignments bind `_rotated` but nothing consumes it — the rotation-success signal is computed and discarded. Beyond being dead, it is the very signal needed for the WR-01 fix.
**Fix:** Fold into WR-01's fix (consume `_rotated` in the True branch).

### IN-03: Rotation is boot-bound only; in-session console.log growth is unbounded

**File:** `run_api.bat:12`, `api/main.py:117-133`
**Issue:** Rotation fires only at process start (launcher M-B / boot block). During a continuous session that exceeds 5MB, console.log grows without bound until the next restart. This is structurally forced by the cmd `>>` deny-share handle (in-process rotation impossible — live-proven) and is the operator-accepted D-32 boot-check design, but it does not literally meet SC2's "disk footprint stays bounded through weeks of continuous running **with no manual cleanup**" unless the machine/session restarts within the growth budget. Live evidence shows the footprint is tiny in practice (405 bytes after two days, access_log off), so this is a recorded-limitation note, not a defect.
**Fix:** None required for the Windows deployment; record in README known-limits that a long-lived un-restarted session grows console.log past the threshold by design.

### IN-04: run_api.bat does not check the move errorlevel

**File:** `run_api.bat:12`
**Issue:** If `move /y` fails (the documented orphan state — Stop-ScheduledTask leaves the old python holding console.log deny-share, per 05-04-SUMMARY), the bat proceeds, the subsequent `>>` open fails, and the task exits 1 with no distinguishing diagnostic — the same LastTaskResult 1 signature as the recorded port-occupancy failure. Recovery (taskkill the orphan) is documented, so this is a diagnosability gap only.
**Fix:** Optional one-liner for a distinct signature:
```bat
if exist "logs\api\console.log" for %%A in ("logs\api\console.log") do if %%~zA GTR 5242880 move /y "logs\api\console.log" "logs\api\console.log.1" >nul 2>&1 || echo ROTATION-FAILED > "logs\api\rotate_error.flag"
```

---

_Reviewed: 2026-09-05T01:08:02Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
