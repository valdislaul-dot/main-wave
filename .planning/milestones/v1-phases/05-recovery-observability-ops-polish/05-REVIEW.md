---
phase: 05-recovery-observability-ops-polish
reviewed: 2026-09-05T02:05:00Z
depth: standard
iteration: 2
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
  warning: 1
  info: 3
  total: 4
status: issues_found
---

# Phase 5: Code Review Report (iteration 2 — fix verification)

**Reviewed:** 2026-09-05T02:05:00Z
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Re-review of the Phase 5 tree after the iteration-1 fixer applied 3 fixes (commits d4ad4ae, a07279b, 11645c4). Verified each fix against the current source, the fix diffs, the new test matrix rows, and by running the full suite in the main checkout. All three applied fixes are correct and regression-free for the Windows deployment; one warning remains — the second half of WR-02 (in-process fd dup2 during full-boot tests) that the fixer did not address.

**Fix verification results:**

- **WR-03 (dict-shape guards) — verified fixed.** `isinstance(job, dict)` guards now sit at all three scan sites with correct short-circuit ordering (`api/jobs.py:214` reload_registry, `api/jobs.py:241` prune, `api/health.py:89` scan; `None` from a listdir/read race is also covered by the guard). The 4 new matrix rows (`test_health_job_null_non_object_json_skipped`, `test_health_job_non_object_files_do_not_shadow_valid_succeeded`, `test_reload_sweep_tolerates_non_object_json`, `test_prune_skips_non_object_json_still_trims_others`) are all mutation-meaningful — each 500s/crashes on the pre-fix code. Trim arithmetic in `test_prune_skips_non_object_json_still_trims_others` checks out (22 valid − 2 oldest + 1 non-object = 21). `api/actions.py:129-145` (GET /v1/jobs/{id}) is a single-file direct read, not a scan — its documented 503/404 classification contract is intact and it never calls `.get()`, so no fourth site exists.
- **WR-01 (True-branch repoint) — verified correct by analysis; POSIX branch remains needs-human-verification (as fixer marked).** `api/main.py:124-131` consumes `_rotated` exactly per the prescribed fix: `_rotated` → repoint with its own WARNING; `elif rotate_err` → rotation-skipped warning; no-op → silence. Windows cmd `>>` production path is byte-identical to iteration 1 (deny-share handle makes `_rotated=True` structurally unreachable — the new code is inert there). Flush ordering is safe: `repoint_std_streams` flushes stdout/stderr before dup2 (log_housekeep.py:65-66), so the tail of buffered output lands in the renamed `.1` inode via the still-open fds — no lost or misdirected bytes. Only reachable on POSIX/share-delete launchers (D-35 Mac rollout) — cannot be exercised on this machine; keep the human-verification flag.
- **WR-02 (registry isolation) — registry-escape vector closed and empirically confirmed.** All 4 full-boot tests pin both seams (`api.jobs.LOG_DIR` + `api.jobs.DATA_DIR`, test_boot.py:129-130/164-165/183-184/229-230); the SEC-03-gate tests (case 5/8) need no pin because `SystemExit` fires at main.py:89 before `reload_registry()` at main.py:106 (verified in main() ordering). Grep confirms test_boot is the only module invoking `main()`/`reload_registry`. Independent reproduction in the main checkout: full suite **193 passed, 1 skipped in 16.59s** (matches the fixer's claim; +4 = exactly the WR-03 rows over the 189 baseline); real `logs/api/jobs` sha256 `637e2c7c…` byte-identical before/after; `git status --porcelain -- data/ logs/` empty.
- **Scope hygiene:** fix commits touch only api/jobs.py, api/health.py, api/main.py, tests/test_health_details.py, tests/test_jobs.py, tests/test_boot.py — no 定稿机制 modules (V4 scoring/temperature/sell-engine), run_api.bat untouched. run_api.bat verified still CRLF-only (14 CRLF, 0 bare LF) and ASCII-only (0 non-ASCII bytes).

One warning remains open (WR-04 below) — it is the "Additionally" paragraph of iteration-1 WR-02 that the fixer's fix did not cover, and it is now empirically demonstrated to degrade test reliability in a standard pytest mode. The three iteration-1 Info items (IN-01/03/04) carry over unchanged; IN-02 is resolved by the WR-01 fix (True branch now consumes `_rotated`; the remaining unused False-branch binding at main.py:133 is an underscore-discard convention, not a defect).

## Warnings

### WR-04: Full-boot tests dup2 the pytest runner's fd 1/2 onto a tmp console.log — verified output/failure-report loss under `pytest -s`

**File:** `tests/test_boot.py:125, 160, 177, 222` (via `api/main.py:133-134` → `api/log_housekeep.py:50-76`)
**Issue:** The WR-02 fix pinned the registry seams, but the four full-boot tests still run the boot housekeeping block for real inside the pytest process. When fd 1/2 do not point at console.log (any test/manual launch — the False branch), `main()` calls the real `repoint_std_streams(console_log)`, which dup2s the **test runner's own fd 1/2** onto the tmp_path console.log (log_housekeep.py:67-73). Iteration-1 review noted this as "currently tolerated by pytest capture"; it is only tolerated because default fd-capture makes pytest independent of OS fd 1/2. Empirically confirmed on this machine:

```
$ python -m pytest tests/test_boot.py -s -q
...........            <- stops at 11 dots
```

The first full-boot test (test #12, test_loopback_boot_prints_only_notice_and_creates_token) hijacks fd 1/2; the remaining 6 progress dots and the entire `17 passed` summary are written into `tmp_path/api/console.log`, which pytest deletes at teardown. Under `-s` (the standard debugging mode for exactly these boot tests), any failure in the 6 tests after the hijack point — or in later test files in a full-suite `-s` run — produces **no visible traceback or summary**: silent-failure window with only the exit code as signal. Default-capture runs (CI, this suite's own runs) are unaffected, which is why 193-passed runs look healthy.

**Fix:** No-op the fd-touching primitive in the four full-boot tests before calling `main()` (main() resolves `log_housekeep.repoint_std_streams` at call time, so the patch takes effect; real repoint behavior stays pinned by test_log_housekeep's subprocess probes, so no coverage is lost; no assertion in these tests depends on repoint's side effects — the boot prints occur before housekeeping and the WARNING paths require errors the no-op avoids):
```python
monkeypatch.setattr(
    api.log_housekeep, "repoint_std_streams", lambda path=None: None
)
```
(A module-level autouse fixture in test_boot applying this for every `main()`-invoking test is equivalent.) With that, the four full-boot tests keep testing everything they assert — token generation, SEC-03/D-12 refusal ordering, print pins — while no longer mutating the runner's process-wide fd state.

## Info

### IN-01: Rotation threshold duplicated across launcher and module

**File:** `run_api.bat:12` (with `api/log_housekeep.py:23`)
**Issue:** `MAX_CONSOLE_LOG_BYTES = 5 * 1024 * 1024` (python) and the literal `5242880` (bat) are the same constant in two languages, kept in sync only by cross-referencing comments. Unchanged from iteration 1; currently in sync (5242880 == 5 MB).
**Fix:** Pin the coupling in a test (e.g., assert the bat contains the literal `str(api.log_housekeep.MAX_CONSOLE_LOG_BYTES)`), so any one-sided change fails the suite.

### IN-03: Rotation is boot-bound only; in-session console.log growth is unbounded

**File:** `run_api.bat:12`, `api/main.py:117-137`
**Issue:** Rotation fires only at process start. Structurally forced by the cmd `>>` deny-share handle (in-process rotation impossible — live-proven) and operator-accepted; live footprint tiny (405 bytes after two days). Recorded-limitation note, not a defect.
**Fix:** None required for the Windows deployment; record in README known-limits that a long-lived un-restarted session grows console.log past the threshold by design.

### IN-04: run_api.bat does not check the move errorlevel

**File:** `run_api.bat:12`
**Issue:** If `move /y` fails (documented orphan state — old python still holding console.log deny-share), the bat proceeds, the `>>` open fails, and the task exits 1 with no distinguishing diagnostic. Diagnosability gap only.
**Fix:** Optional one-liner for a distinct signature (e.g., `move /y ... >nul 2>&1 || echo ROTATION-FAILED > "logs\api\rotate_error.flag"`), keeping CRLF + ASCII-only.

---

_Reviewed: 2026-09-05T02:05:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
_Iteration: 2_
