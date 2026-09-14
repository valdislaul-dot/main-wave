---
phase: 04-exposure-hardening-data-classification
reviewed: 2026-09-04T20:35:00Z
depth: standard
iteration: 2
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
  warning: 2
  info: 4
  total: 6
status: issues_found
---

# Phase 4: Code Review Report (Iteration 2 — fix verification)

**Reviewed:** 2026-09-04T20:35:00Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Iteration-2 re-review of the Phase 4 exposure-hardening deliverables after the `--auto` fix pass (commits a9149eb..d706ee9, WR-01..WR-05). Verified each of the 5 fixes against source and by running the suite in this checkout: **155 passed, 1 skipped** (16.7 s). The skip is `tests/test_health.py:48` — an environment-conditional pin (real `data/api_token.txt` existed from a prior E2E boot); in the fixer's isolated worktree that test ran and passed, which reconciles its "156 passed" record. Fix range touches exactly 6 files (verified via `git diff --name-only a9149eb~1 d706ee9`); **no 定稿机制 module was modified** — scoring/temperature/sell_engine/scoring_config untouched — so no user-confirmation gate is triggered by the code changes themselves.

Per-fix verdicts:

- **WR-01 (test_date_args.py)** — Fix correct. `_git_porcelain()` diff-before/after replaces the absolute-clean precondition; the 4 spawn pins now stay green on the repo's normal daily dirt (reproduced: suite green with `data/auction_state.json` modified + untracked `data/auction/2026-09-04.json` present). The "zero writes" evidence is preserved as a before/after byte diff. Residual flake window (a concurrent process writing data/ between the two porcelain snapshots) is inherent to the diff approach and was present in the prescribed fix.
- **WR-02 (trading_journal.py record_sell)** — Implementation matches the prescribed code-first semantics: `by_code` identity match with name-set refusal, name fallback when code hits nothing, SELL entry records the actually-sold lot's real code/name. 2026-09-03 same-code multi-lot whole-sell merge preserved (pin `test_record_sell_same_code_merges_all_lots_keeps_other_stock`). The 4 new pins are meaningful and pass. The known behavior change stands and needs the human sign-off flagged in the fix report (see WR-07 below): a **name-typo with a valid code is now refused** (empirically confirmed — position not sold, warning printed), whereas pre-fix the code match alone sold it. Refusal is data-safe in all traced paths.
- **WR-03 (save_portfolio/save_journal _replace_retry)** — Fix correct: 4 attempts / 10 ms backoff on PermissionError only, other OSError propagates immediately (D-04 failure pins stay byte-exact green); pins confirm retry-then-success with zero `.tmp` residue and exhaustion raising with the target holding old content. One cosmetic divergence from its cited template (`api/jobs.py:write_job` removes the tmp file before raising on exhaustion; `_replace_retry` does not) — consequence-free because the tmp name is fixed and the next write overwrites it, and the module's residue discipline is already pinned as tolerated (Test 4). Not raised as a finding.
- **WR-04 (run_pipeline Steps 5/7)** — Fix correct: both bare `except: pass` replaced with the house `except Exception` + `[Warning] ...: {e}` pattern; `KeyboardInterrupt`/`SystemExit` no longer swallowed; Step 5/7 now behave exactly like sibling Steps 2/3/6/8. Labels "[Step 7/8]"/"[Step 8/8]" denominator drift is pre-existing cosmetic (out of fix scope).
- **WR-05 (actions.py trigger_action)** — Fix correct and complete for the described failure mode. Verified against `api/jobs.py` claim order: `_claims[kind]` is inserted only after `write_job` succeeds, so the claim-write OSError path leaves zero in-memory claim, zero registry file, and (with the fix) a closed OS-lock fd — pin `test_start_job_claim_failure_releases_os_lock_and_retrigger_ok` exercises the full HTTP path (500 envelope → lock acquirable → re-trigger 202 → succeeded). `fd` is a file object (`job_lock.acquire` returns the `a+b` handle), so the except-path `fd.close()` cannot double-close anything: in the claim-failure path the worker thread never starts, and file-object `close()` is idempotent. The residual Thread.start-failure sub-case (claim file + memory entry persist; next trigger overwrites the memory claim, stale pending file is swept to interrupted at next API restart) is pre-existing, practically unreachable, and self-healing; not raised.

No critical defects. Two warnings remain (both on the sell bookkeeping path — one pre-existing crash, one residual silent-failure gap of the WR-02 semantics change) and the four iteration-1 info items are intentionally untouched (fix scope was critical+warning).

## Warnings

### WR-06: run_pipeline --sell documented form crashes with IndexError — usage text contradicts implementation

**File:** `scripts/daily/run_pipeline.py:8` (docstring), `:40-41` (branch)
**Issue:** The module docstring documents `python run_pipeline.py --sell CODE PRICE` (2 args), but the branch requires the undocumented 3-arg form NAME CODE PRICE and guards with `len(sys.argv) >= 4` while indexing `sys.argv[4]`. Running the documented form crashes (empirically confirmed — full traceback, `IndexError: list index out of range` at line 41, nothing sold). This predates the phase (v2.2 era) and was missed by iteration 1; it sits directly on the sell path whose semantics WR-02 just hardened, and a user following the file's own usage text at 9:30 gets a traceback instead of a sale. Crash is write-safe (occurs before `record_sell` is invoked).
**Fix:** Require the real shape and correct the usage text:
```python
        elif cmd == '--sell' and len(sys.argv) >= 5:
            record_sell(sys.argv[2], sys.argv[3], float(sys.argv[4]))
```
and change line 8 of the docstring to `python run_pipeline.py --sell NAME CODE PRICE`. Alternatively, accept the 2-arg code+price form by resolving the name from the portfolio (`load_portfolio` lookup by code) — but that reintroduces name-derivation logic the WR-02 fix deliberately removed from the ledger, so the first option is preferred.

### WR-07: WR-02 refusal is exit-code silent — a refused live sell reports success to any wrapper

**File:** `scripts/daily/trading_journal.py:147-150, 154-156` (refusal paths), `scripts/daily/run_pipeline.py:41` (only sell call site)
**Issue:** Both refusal paths (`name/code 错配` and `no position`) print a console `[Journal] WARNING` and `return pf` — normal return, no exception. `run_pipeline --sell` ignores the return and exits 0. Empirically confirmed: with a two-position ledger, `record_sell('楚天龙', '000428', 5.0)` and the name-typo case `record_sell('楚天隆', '003040', 5.0)` (valid code of a held stock, slightly wrong name) both print the warning, sell nothing, and return a pf — so the CLI process ends with exit code 0. The WR-02 fix intentionally widened the refusal surface (a name-typo with a *valid* code — the exact case a hurried morning sell produces — was previously sold via code match), so the live-money consequence (user believes the position is sold; it remains) is newly reachable in a plausible way. The refusal text is visible to a human watching stdout, which is why this is not critical, but any scripted/wrapper invocation — including the token-gated API workflow this phase serves — cannot distinguish "sold" from "refused" by exit code. This is the residual half of the fix report's "requires human verification" item.
**Fix:** Give refusal a caller-visible signal. Minimal change with no contract break for existing callers (no in-repo caller inspects the return value; the pins assert file state, not the return):
```python
        # in both refusal paths:
        print(f'[Journal] WARNING: ...', file=sys.stderr)
        return None
```
and in `run_pipeline.py:41`:
```python
        if record_sell(sys.argv[2], sys.argv[3], float(sys.argv[4])) is None:
            sys.exit(1)  # 卖出被拒: 空仓/名码错配, 非零退出防静默漏卖
```
Update the docstring of `record_sell` to state the None-on-refusal contract.

## Info

### IN-01: Duplicate `import os`

**File:** `scripts/daily/trading_journal.py:5-6`
**Issue:** `import json, os` immediately followed by `import os`. Harmless; untouched by the fixer (out of fix scope).
**Fix:** Drop line 6.

### IN-02: Legacy single-position sell still writes `"positions": null` into the schema

**File:** `scripts/daily/trading_journal.py:138, 174`
**Issue:** In the legacy else branch (no `positions` key), the local `positions` stays `None` and line 174 persists `pf['positions'] = None` — the same schema pollution iteration 1 flagged; WR-02 did not touch this branch.
**Fix:** In the else branch set `positions = []` before line 174 (or `pf.setdefault('positions', [])`), so the saved file always carries a real list.

### IN-03: api/private.py + api/state.py docstrings still overstate import purity

**File:** `api/private.py:27-31`, `api/state.py:14-18`, `scripts/daily/config.py:13-14`
**Issue:** Both docstrings claim the config import chain has no I/O ("后者导入链仅 os/sys/platform"), but `scripts.daily.config` executes `os.makedirs` for four directories at import time (re-verified). Normally a no-op; on a fresh/read-only deployment the import creates directories — the class of side effect `tests/test_date_args.py:test_import_purity_no_side_effects` forbids for date_args.
**Fix:** Correct the docstrings to "导入链仅 os/sys/platform + 幂等 makedirs; 不打印/不绑端口".

### IN-04: errors.py freeze-table comment drift — "400 日期参数族" but both raise sites are 422

**File:** `api/errors.py:49`
**Issue:** The comment labels the date rows "400 日期参数族"; both raise sites (`api/private.py:170`, `api/actions.py:92`) raise 422. The table is the frozen contract — the label misleads cross-checks.
**Fix:** Change the comment to "422 日期参数族".

---

_Reviewed: 2026-09-04T20:35:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
_Iteration: 2_
