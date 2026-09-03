---
phase: 04-exposure-hardening-data-classification
plan: 02
subsystem: scripts
tags: [atomic-write, os-replace, json-ledger, windows, tdd, data-integrity]

# Dependency graph
requires:
  - phase: 02-read-only-state-endpoints-defensive-read-layer
    provides: "Phase 2 defensive read layer + D-04/D-05/D-06 signed wire contract (raw passthrough + X-Data headers) — this plan closes the write-side precondition (D-06: 写侧原子化为 STA-02 上线前置) those reads depend on"
provides:
  - "save_portfolio/save_journal rewritten from direct open('w') truncating writes to the D-05-prescribed same-dir .tmp + os.replace atomic pattern (zt_pool.py:72-78 template) — readers can never observe a half-written logs/portfolio.json or logs/trading_journal.json; a crash between tmp write and replace never loses the last committed ledger"
  - "Byte-identical wire behavior for every caller: identical target paths, identical dump options (indent=2/ensure_ascii=False), identical return contract, zero schema mutation (no last_updated injection — the zt_pool template's last_updated line does not transfer)"
  - "tests/test_trading_journal.py contract suite (4 tests): atomic success shape with zero .tmp residue, unchanged loader round-trip, forced os.replace failure keeps previous target content byte-for-byte, failure-path .tmp residue pinned — module-global PORTFOLIO_FILE/JOURNAL_FILE monkeypatch seam, zero contact with real logs/"
affects: [04-03 (private /v1/private/portfolio|journal readers built on atomic ledger files), 04-07 (real-machine live gate can never serve a torn ledger), phase-05 ops polish]

actuals:
  tokens: 2019   # chars/4 over the realized diff (8076 chars across scripts/daily/trading_journal.py + tests/test_trading_journal.py)
  tasks: 2
  commits: 2

tech-stack:
  added: []
  patterns:
    - "Same-dir .tmp sibling + os.replace atomic write (zt_pool save_state L72-78 template now shared by trading_journal writers): same-volume guarantee on NTFS; os.replace only — os.rename fails when the target exists on Windows; success path leaves zero .tmp residue, failure path residue tolerated (template has no cleanup)"
    - "Module-global file-path seam for tests: PORTFOLIO_FILE/JOURNAL_FILE read at call time, monkeypatched to tmp_path — no import side effects added, real ledger never touched"

key-files:
  created:
    - tests/test_trading_journal.py - D-04..D-06 atomic-write contract suite (4 tests, module-attr monkeypatch fixture, os.replace failure injection)
  modified:
    - scripts/daily/trading_journal.py - save_portfolio L45-47 + save_journal L57-59 rewritten to tmp+os.replace; one docstring note; everything else byte-untouched

key-decisions:
  - "Only the two functions change (D-05 scope): record_hold_valuation's daily_valuations.json truncate-write and every other script write path stay byte-untouched; threat T-04-06 accepted as planned"
  - "Failure-path .tmp residue tolerated exactly as the zt_pool template behaves (no try/finally cleanup): Test 4 pins tmp-exists-with-new-content; the load-bearing invariant is target-keeps-old-content (D-04), asserted in both Test 3 and Test 4"
  - "Text-mode open('w') semantics preserved (incl. Windows CRLF translation) so output bytes are identical to the pre-change writer; suite byte-pins normalize CRLF against the LF json.dumps reference (empirically confirmed on this box: os.linesep='\\r\\n', text-mode writes produce CRLF; real ledger files are LF-only from other writers — loaders are newline-agnostic, no caller impact)"
  - "[ASSUMED] read-collision retry (api/jobs.py 4x10ms PermissionError loop) unnecessary — kept as the documented escalation if 04-07's live gate ever observes a collision under load; no change to this plan's contract"

patterns-established:
  - "Atomic ledger write: serialize to same-dir .tmp, os.replace(tmp, target) — a torn JSON can never be served as fresh data (D-04 基调), matching the Phase 2 read-side defense"
  - "Failure-injection pinning: monkeypatch os.replace to raise once, assert the untouched target holds the last committed bytes — proves crash-safety without touching real files"

requirements-completed: [STA-02, SEC-02]

coverage:
  - id: D1
    description: "save_portfolio/save_journal atomic via same-dir tmp + os.replace with byte-identical output and zero schema mutation (D-04..D-06); only the two writers + docstring note changed"
    requirement: STA-02
    verification:
      - kind: unit
        ref: "tests/test_trading_journal.py#test_atomic_success_shape_no_tmp_residue"
        status: pass
      - kind: unit
        ref: "tests/test_trading_journal.py#test_round_trip_unchanged_through_loaders"
        status: pass
      - kind: unit
        ref: "tests/test_trading_journal.py#test_replace_failure_keeps_previous_committed_content"
        status: pass
      - kind: unit
        ref: "tests/test_trading_journal.py#test_failure_path_residue_pinned_target_holds_old"
        status: pass
      - kind: unit
        ref: "python -m pytest -q (111 passed, 1 skipped — full-suite regression gate)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Suite data isolation — real logs/ ledger files never touched; RED phase proved the D-04 defect against the truncating writers (Tests 3/4 red: DID NOT RAISE OSError)"
    requirement: SEC-02
    verification:
      - kind: unit
        ref: "git status --porcelain -- data/ logs/ (empty after both task stages)"
        status: pass
      - kind: unit
        ref: "python -m pytest tests/test_trading_journal.py -q pre-change (2 failed, 2 passed — red evidence recorded in SUMMARY)"
        status: pass
    human_judgment: false

# Metrics
duration: 3min
completed: 2026-09-04
status: complete
---

# Phase 04 Plan 02: Ledger Write-Side Atomicity — save_portfolio/save_journal on tmp+os.replace Summary

**logs/portfolio.json and logs/trading_journal.json writes are now atomic (same-dir .tmp + os.replace, zt_pool template): the truncating-writer defect D-04 targets is proven red by the new contract suite, then closed — readers can never observe a half-written ledger, a forced replace failure keeps the last committed content byte-for-byte, and every existing caller sees byte-identical output**

## Performance

- **Duration:** 3 min
- **Started:** 2026-09-03T20:30:08Z
- **Completed:** 2026-09-03T20:32:28Z
- **Tasks:** 2 (TDD: RED suite + GREEN writers)
- **Files modified:** 2 (1 scripts/ + 1 tests/)

## Accomplishments

- **RED defect proof (Task 1):** new `tests/test_trading_journal.py` suite run against the pre-change truncating writers — Tests 1/2 pass (writes are valid JSON today), **Tests 3/4 fail red with `Failed: DID NOT RAISE OSError`**: the direct `open('w')` truncates the target before any simulated failure can occur and never calls `os.replace`, so the failure-injection cannot even fire — the target is already overwritten. Exactly the defect D-04 predicts; the red run is the acceptance evidence.
- **GREEN writers (Task 2):** `save_portfolio` (pre-edit L45-47) and `save_journal` (pre-edit L57-59) rewritten to the D-05-prescribed pattern — serialize to `PORTFOLIO_FILE + '.tmp'` / `JOURNAL_FILE + '.tmp'` sibling, then `os.replace(tmp, target)`. Same-dir tmp = same volume = atomic replace on NTFS; `os.replace` only (never `os.rename` — fails when target exists on Windows). No `os.makedirs(dirname)` line and no `state['last_updated']` injection transferred from the template (callers guarantee LOG_DIR exists via module import; ledger schema is the user's and must not be mutated).
- **Contract suite green 4/4:** no `.tmp` residue on success, loaders round-trip the saved bytes to exactly the input structure, forced `os.replace` failure (raise-once injection) leaves the target holding the previous good content byte-for-byte, failure-path `.tmp` residue pinned (exists, holds the new content — the template performs no cleanup; target still holds the old content).
- **Zero caller impact:** full suite 111 passed, 1 skipped in 13.02s (04-01 baseline 107 passed + 4 new); `git status --porcelain -- data/ logs/` empty after both stages — the suite never touched the real ledger.
- **Module-global seam preserved:** `PORTFOLIO_FILE`/`JOURNAL_FILE` remain read-at-call-time (trading_journal.py L11-12); the fixture monkeypatches them to `tmp_path` files exactly like the tests/test_boot.py module-attr pattern. Import-time `os.makedirs(LOG_DIR)` side effect is pre-existing and harmless. No new import side effects added.

## Exact New Writer Bodies (scripts/daily/trading_journal.py)

```python
def save_portfolio(pf):
    # 原子写 (D-04..D-06, zt_pool save_state 模板): 同目录 .tmp 保证同卷, os.replace 原子替换
    # (Windows 上 os.rename 对已存在目标会失败, 禁用); 读者永不 observe 半写 JSON。
    # 不注入 last_updated 等字段 —— 账本 schema 是用户的 (与旧写者字节一致)。
    tmp = PORTFOLIO_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(pf, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PORTFOLIO_FILE)


def save_journal(journal):
    # 原子写 (D-04..D-06, zt_pool save_state 模板): 同上 —— 同目录 .tmp + os.replace
    tmp = JOURNAL_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(journal, f, ensure_ascii=False, indent=2)
    os.replace(tmp, JOURNAL_FILE)
```

Module docstring gained one line: `Phase 4 (D-04..D-06): save_portfolio/save_journal 原子写 —— 同目录 .tmp + os.replace`. Diff footprint: +11/-2 in trading_journal.py; `load_journal`, `record_buy`, `record_sell`, `record_hold_valuation` (incl. its daily_valuations.json truncate-write at L191-198 region) and all loaders byte-untouched (D-05 scope).

## RED Run Evidence (Task 1, against pre-change writers)

```
$ python -m pytest tests/test_trading_journal.py -q
FAILED tests/test_trading_journal.py::test_replace_failure_keeps_previous_committed_content
FAILED tests/test_trading_journal.py::test_failure_path_residue_pinned_target_holds_old
2 failed, 2 passed in 0.79s

E       Failed: DID NOT RAISE OSError        (both failures)
```

**Interpretation:** the truncating writer opens the target with `'w'` (truncate) and never calls `os.replace`, so the injected failure never fires and the previous good content is already destroyed — the suite cannot pass until the write is atomic. This is the D-04 defect made executable, and it is what Task 2's tmp+os.replace rewrite satisfies.

## Task Commits

Each task was committed atomically:

1. **Task 1 (TDD RED): ledger atomic-write contract suite** — `3c3406d` (test; 2 failed 2 passed by design)
2. **Task 2 (GREEN): atomic ledger writes via tmp+os.replace** — `dab80a3` (fix; 4/4 green)

**Plan metadata:** pending final docs commit.

## Files Created/Modified

- `tests/test_trading_journal.py` - created; D-04..D-06 contract suite: Chinese docstring naming the zt_pool template oracle and the data-isolation pin; `ledger_files` fixture (module-attr monkeypatch of `PORTFOLIO_FILE`/`JOURNAL_FILE` to tmp_path), `_force_replace_failure_once` (os.replace raise-once injection), `_serialize`/`_normalize` helpers (Windows CRLF-agnostic byte pins)
- `scripts/daily/trading_journal.py` - modified; only save_portfolio (L45-47) + save_journal (L57-59) + one docstring note

## Decisions Made

See key-decisions frontmatter. No user decision was required — this plan carries no checkpoints and all four must-have truths were verified by the suite:
- writers go through the tmp+os.replace shape (Truth 1) — asserted by Tests 3/4
- wire behavior unchanged: identical paths/bytes/return, no field injection (Truth 2) — asserted by Tests 1/2 (byte pins + `json.loads(raw) == input`), full-suite regression gate
- scope exactly two functions, seam preserved, no new import side effects (Truth 3) — diff footprint +11/-2, diff-verified
- simulated mid-write failure keeps previous content (Truth 4) — Test 3 byte-for-byte
- no .tmp residue on success + loader round-trip (Truth 5) — Tests 1/2; suite never touches real logs/ (Truth 6) — hygiene gate empty both stages

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- **Windows CRLF vs LF byte pinning (design note, not a defect):** Python 3.13 text-mode `open('w')` on this box translates `\n` → `\r\n` (empirically confirmed: `os.linesep == '\r\n'`, trial write produced CRLF bytes), while the real `logs/portfolio.json` on disk is LF-only (written by some other tool/editor). Because the new writers keep the identical `open(tmp, 'w', encoding='utf-8')` text-mode shape, output bytes are byte-identical to the pre-change writers — the caller-facing invariant that matters. The suite's byte pins therefore normalize CRLF→LF before comparing against the `json.dumps(..., indent=2)` LF reference (platform-sound on both line-ending regimes), and the untouched-target assertions in Tests 3/4 compare exact bytes against canonical LF pre-writes (a successful replace would have produced CRLF bytes and failed the pin — the assertions are not vacuous).
- Pre-existing duplicate `import os` at trading_journal.py L4-5 — out of D-05 scope, left byte-untouched.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **04-03 (private /v1/private/{portfolio,journal} readers) can build directly on atomic ledger files**: the Phase 2 read layer plus this write side means a torn ledger can never be served — D-06's 上线前置 is closed in Wave 1 as designed
- **04-07 live gate escalation documented**: if the real-machine gate ever observes a read collision under load (WinError-5 on held handles), escalate to the api/jobs.py write_job 4x10ms PermissionError retry variant in a new plan delta — no change to this plan's contract
- Full suite: 111 passed, 1 skipped; `git status --porcelain -- data/ logs/` empty throughout

---
*Phase: 04-exposure-hardening-data-classification*
*Completed: 2026-09-04*

## Self-Check: PASSED

Files verified present: scripts/daily/trading_journal.py (atomic writers, diff +11/-2), tests/test_trading_journal.py (4 tests). Commits verified in git log: 3c3406d (RED), dab80a3 (GREEN). Contract suite 4/4 green; full suite 111 passed, 1 skipped; data/ and logs/ untouched.
