---
phase: 04-exposure-hardening-data-classification
fixed_at: 2026-09-04T20:40:00Z
review_path: .planning/phases/04-exposure-hardening-data-classification/04-REVIEW.md
iteration: 3
findings_in_scope: 2
fixed: 2
skipped: 0
status: all_fixed
---

# Phase 4: Code Review Fix Report

**Fixed at:** 2026-09-04T20:40:00Z
**Source review:** `.planning/phases/04-exposure-hardening-data-classification/04-REVIEW.md` (iteration 2)
**Iteration:** 3

**Summary:**
- Findings in scope (critical + warning): 2 (WR-06, WR-07)
- Fixed: 2
- Skipped: 0
- Info findings (IN-01..IN-04): out of scope (`fix_scope: critical_warning`), not addressed
- 定稿机制: untouched — no V4 scoring / temperature / sell-engine module modified; both fixes are on the sell bookkeeping CLI path (run_pipeline arg parsing + trading_journal refusal exit codes), which are not finalized mechanisms

## Fixed Issues

### WR-06: run_pipeline --sell documented form crashes with IndexError — usage text contradicts implementation

**Files modified:** `scripts/daily/run_pipeline.py`
**Commit:** c2f24f0
**Applied fix:** Aligned code + docs to the real 3-arg `NAME CODE PRICE` form (the documented 2-arg `CODE PRICE` form never worked in any version — v2.2 onward the branch always indexed `argv[4]`, and a 2-arg invocation has argv length exactly 4, so the old `len(sys.argv) >= 4` guard passed and then crashed with `IndexError` before `record_sell` was reached). Evidence the 3-arg form is the live convention, not the doc:
- The implementation has always parsed `record_sell(argv[2]=name, argv[3]=code, argv[4]=price)` — name-first, matching `record_sell`'s own signature;
- Sibling CLI `record_trader.py --sell NAME CODE PRICE [DATE]` uses the same name-code-price order;
- `--buy NAME CODE PRICE` in the same file uses the same order, and its docstring was already corrected to match on 2026-09-03 with the note 「修正文档(实现按此序解析)」 — the sell docstring line was simply missed in that pass;
- No in-repo wrapper script or test invokes the 2-arg form.

Change: docstring line 8 now reads `python run_pipeline.py --sell NAME CODE PRICE` (with WR-06 note); branch guard tightened to `len(sys.argv) >= 5` so an under-arg invocation falls through to the `Usage:` message instead of a traceback. No change to the `record_sell` call arguments themselves.

### WR-07: WR-02 refusal is exit-code silent — a refused live sell reports success to any wrapper

**Files modified:** `scripts/daily/trading_journal.py`, `scripts/daily/run_pipeline.py`, `tests/test_trading_journal.py`
**Commit:** 39f2fdc
**Applied fix:** Refusal now carries a caller-visible signal end to end:
- `record_sell` returns `None` on all three refusal paths (positions-list name/code 错配; positions-list no-position; legacy single-position no-position) instead of `return pf` — the warning prints stay on stdout (unchanged, pinned by the existing capsys assertions; the WR-07 review snippet's stderr variant would have broken `test_record_sell_mismatch_name_code_refused_no_double_sell`). Success still returns `pf`. The docstring now states the None-on-refusal / pf-on-success contract.
- `run_pipeline.py` sell call site now checks the return: `if record_sell(...) is None: sys.exit(1)` (卖出被拒: 名码错配/空仓, 非零退出防静默漏卖). No in-repo caller inspects the old return value, so the contract break is confined to the one CLI site that now consumes it.
- Pins: the WR-02 mismatch-refusal test now asserts `result is None`; the three success-path tests (correct pair / same-code multi-lot merge / name-fallback) now assert `result is not None`; new test `test_record_sell_refusal_returns_none_no_match_and_legacy` covers the remaining two refusal paths (名码双不中 in positions format; legacy single-position format), asserting None + WARNING + zero file change.

**Status: fixed** — the WR-02 refusal semantics themselves (name/code 错配 refusal) were already flagged for human sign-off in the iteration-1 report; this fix only adds the non-zero exit signal so a refused sell is never silently believed sold. Logic is straightforward (return-value check), and the reviewer's prescribed mapping (`record_sell(...) is None -> sys.exit(1)`) is implemented verbatim, so no further human verification is required beyond the already-pending WR-02 sign-off.

## Skipped Issues

None — both in-scope findings were fixed. The 4 Info findings (IN-01 duplicate `import os`, IN-02 legacy `positions: null`, IN-03 import-side-effect docstring drift, IN-04 errors.py comment drift) are out of scope for `fix_scope: critical_warning` and were intentionally not touched.

---

## Verification Record

- Per-finding: `tests/test_trading_journal.py` — 11 passed (10 existing pins + 1 new WR-07 pin) after the WR-07 change.
- Full suite run in the isolated review-fix worktree (`.claude/worktrees/rf-04-679-1788525031`, branch `gsd-reviewfix/04-679`): **157 passed, 0 failed** (16.94 s). This is the 156-test baseline plus the 1 new WR-07 pin; the environment-conditional health pin (`tests/test_health.py:48`) ran and passed in this worktree (no real `data/api_token.txt` present), which reconciles the reviewer-env count (155 passed + 1 skipped = 156 collected) with the fixer-env count (157 passed = 156 + 1 new pin).
- Syntax checks: `ast.parse` clean on `scripts/daily/trading_journal.py`, `scripts/daily/run_pipeline.py`, `tests/test_trading_journal.py`.
- Fix scope guard: `git diff --name-only c2f24f0~1 39f2fdc` = `scripts/daily/run_pipeline.py`, `scripts/daily/trading_journal.py`, `tests/test_trading_journal.py` — no 定稿机制 module (scoring/temperature/sell_engine/scoring_config) modified.
- Gates ran in the isolated worktree (main checkout was never modified by the fixer; its pre-existing `data/` and `.planning/` dirt is untouched). Worktree results are reproducible from the temp branch `gsd-reviewfix/04-679` until cleanup; after teardown they are reproducible from the fast-forwarded base branch.

---

_Fixed: 2026-09-04T20:40:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 3_
