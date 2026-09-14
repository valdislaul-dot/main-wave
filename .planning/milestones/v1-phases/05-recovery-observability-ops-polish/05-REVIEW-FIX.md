---
phase: 05-recovery-observability-ops-polish
fixed_at: 2026-09-05T01:30:27Z
review_path: .planning/phases/05-recovery-observability-ops-polish/05-REVIEW.md
iteration: 3
findings_in_scope: 1
fixed: 1
skipped: 0
status: all_fixed
---

# Phase 5: Code Review Fix Report

**Fixed at:** 2026-09-05T01:30:27Z
**Source review:** .planning/phases/05-recovery-observability-ops-polish/05-REVIEW.md
**Iteration:** 3

**Summary:**
- Findings in scope: 1 (Warning WR-04; 0 Critical; Info findings IN-01/03/04 out of scope per fix_scope=critical_warning)
- Fixed: 1
- Skipped: 0

## Fixed Issues

### WR-04: Full-boot tests dup2 the pytest runner's fd 1/2 onto a tmp console.log — verified output/failure-report loss under `pytest -s`

**Files modified:** `tests/test_boot.py`
**Commit:** 4068f2b
**Applied fix:** No-oped the fd-touching primitive in the four full-boot tests that run `main()` to completion (test_loopback_boot_prints_only_notice_and_creates_token, test_loopback_boot_generates_token_and_exits_normally, test_env_token_satisfies_non_loopback_check, test_env_token_non_loopback_proceeds_with_ascii_warning_no_token_echo), following the module's existing WR-02 pin scope (case 5/8 exit at the SEC-03 gate, main.py:89, before the housekeeping block, so they never reach repoint and need no pin). The fix follows the file's established `_patch_uvicorn_run` helper idiom: a `_noop_repoint(monkeypatch)` helper does `monkeypatch.setattr(api.log_housekeep, "repoint_std_streams", lambda path=None: None)`, and each of the four tests calls it immediately before `api.main.main()`. `main()` resolves `log_housekeep.repoint_std_streams` at call time (module attribute, main.py:127/134), so the patch takes effect. Real repoint behavior stays pinned by tests/test_log_housekeep.py's subprocess probes — zero coverage loss — and no assertion in the four tests depends on repoint's side effects (boot prints all occur before the housekeeping block). Module docstring and import block (`import api.log_housekeep`) updated to document the WR-04 pin rationale.

## Verification

- Tier 1 (re-read/diff) and Tier 2 (python py_compile) passed for the modified file.
- **Worktree runs** (isolated worktree `C:/Users/Davis/Desktop/gogo/.claude/worktrees/rf-05-906-1788571452`, branch gsd-reviewfix/05-906, python 3.13): reproduced the WR-04 symptom pre-fix — `python -m pytest tests/test_boot.py -s -q` output stopped at 11 dots (the 4th full-boot test hijacks fd 1/2; remaining 6 dots + summary written into tmp console.log and deleted at teardown). Post-fix: `-s` run shows all 17 dots and the full `17 passed` summary (17 passed in 0.29s); full-suite `-s` run shows the complete `194 passed in 16.57s` summary end-to-end (exit 0) — the silent-failure window is closed for boot tests and later files alike. Default-capture runs unchanged: tests/test_boot.py 17 passed, full suite **194 passed, 0 skipped in 15.75s** (the env-conditional test_health skip — real data/api_token.txt absence check — does not apply in a fresh worktree with no real token file; 194 == the main-checkout baseline 193 passed + 1 skipped). `git status --porcelain` after the suite: only `tests/test_boot.py` modified — no data/ or logs/ writes.
- **Main checkout run:** not re-run this iteration (iteration-2 review already established the 193 passed + 1 skipped main-checkout baseline on the pre-WR-04 tree; this fix touches only tests/test_boot.py and was fully exercised in the worktree, including the `-s` probes the main checkout cannot run without the fix).
- Scope hygiene: fix touches only `tests/test_boot.py`; `run_api.bat` untouched (still CRLF + ASCII-only); 定稿机制 modules untouched (V4 scoring/temperature/sell-engine); no data/logs writes.

---

_Fixed: 2026-09-05T01:30:27Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 3_
