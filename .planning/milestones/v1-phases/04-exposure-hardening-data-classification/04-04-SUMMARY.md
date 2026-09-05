---
phase: 04-exposure-hardening-data-classification
plan: 04
subsystem: api
tags: [fastapi, subprocess-argv, sc4, date-whitelist, tdd]

# Dependency graph
requires:
  - phase: 04-01
    provides: frozen error envelope CODE_BY_DETAIL (invalid_date_format / date_not_supported rows), jobs registry + lock scaffold, trigger_action kind whitelist
  - phase: 04-03
    provides: job registry cmd pin shape (term["cmd"][2:]), fake-script argv dump harness in tests/test_actions.py
provides:
  - trigger_action(kind, date=None): four-gate order (404 kind → 422 invalid_date_format → 422 date_not_supported → 202 with appended token)
  - scripts/daily/date_args.py pure-stdlib single-source validator (DATE_RE / parse_date / resolve_date_arg / format_token)
  - session-date gates in run_pipeline.py + morning_check.py (exit 2 before any side effect)
  - subprocess refusal pins proving pre-network refusal + zero data//logs/ writes
affects: [04-05, 04-06, 04-07, verify-work UAT]

# Actuals (#2632) — chars/4 over the realized diff (git diff 11a0d05~1..463f8d2 = 24456 bytes, ~21500 chars after headers/context)
actuals:
  tokens: 5500
  tasks: 3
  commits: 6

# Tech tracking
tech-stack:
  added: []  # pure stdlib only — no new dependencies (by design, date_args.py importable by API chain + CLI)
  patterns:
    - "SC4 fail-loud session-date gate: script refuses non-session --date with exit 2 BEFORE first capture/file write/network call"
    - "single-source validation module consumed by API gate, script gates and tests (no duplicated regex anywhere)"
    - "TDD RED/GREEN per task; subprocess pins only spawn past/invalid dates (never today — child bypasses conftest network monkeypatch)"

key-files:
  created:
    - scripts/daily/date_args.py
    - tests/test_date_args.py
  modified:
    - api/actions.py
    - scripts/daily/run_pipeline.py
    - scripts/daily/morning_check.py
    - tests/test_actions.py

key-decisions:
  - "date_args.py lands partially inside Task 1 GREEN (parse_date + DATE_RE), completed in Task 2 GREEN — plan-sanctioned option (a) so Task 2's RED was genuinely red (ImportError)"
  - "script refusal messages share the ASCII substring 'session date' so one assertion pins both scripts' refusal paths"
  - "script gates accept both --date=X and '--date X' forms (in-repo data_health_check.py:102-110 idiom) via resolve_date_arg; ambiguity (both forms / multiple tokens) → ValueError → exit 2"

patterns-established:
  - "SC4 session-date gate: resolve → compare date.today() → exit 2 ASCII refusal on stderr, stdout zero pollution, positioned as first statement of the pipeline branch (run_pipeline) / top of main() (morning_check)"
  - "argv date token built exclusively from a parsed date object via format_token — raw query strings structurally cannot reach argv (injection-impossible, T-04-13)"
  - "subprocess refusal pins assert git-status hygiene of data//logs/ before AND after each spawn"

requirements-completed: [STA-02, SEC-02]

# Coverage metadata (#1602) — per-deliverable traceability, all automation-proven
coverage:
  - id: D1
    description: "trigger_action date param with four-gate order: 404 kind whitelist first, 422 invalid_date_format for bad format/calendar, 422 date_not_supported for zero-param kinds, valid date appends one normalized token --date=YYYY-MM-DD at END of fixed command; zero spawn on any 404/422"
    requirement: SEC-02
    verification:
      - kind: integration
        ref: "tests/test_actions.py#test_date_param_valid_delivery_appended_argv_pins"
        status: pass
      - kind: integration
        ref: "tests/test_actions.py#test_date_invalid_formats_422_zero_spawn"
        status: pass
      - kind: integration
        ref: "tests/test_actions.py#test_date_on_zero_param_kinds_422_not_supported"
        status: pass
      - kind: integration
        ref: "tests/test_actions.py#test_unknown_kind_with_date_404_kind_gate_first"
        status: pass
    human_judgment: false
  - id: D2
    description: "scripts/daily/date_args.py single-source validator: whitelist regex (YYYY-MM-DD | YYYYMMDD), real-calendar parse, argv resolution (both token forms, None when absent, ValueError on invalid/multiple), canonical format_token; pure stdlib with zero import side effects and ASCII-only messages"
    requirement: SEC-02
    verification:
      - kind: unit
        ref: "tests/test_date_args.py#test_parse_date_accepts_both_whitelist_formats"
        status: pass
      - kind: unit
        ref: "tests/test_date_args.py#test_parse_date_rejects_bad_format_and_calendar"
        status: pass
      - kind: unit
        ref: "tests/test_date_args.py#test_resolve_date_arg_absent_returns_none"
        status: pass
      - kind: unit
        ref: "tests/test_date_args.py#test_resolve_date_arg_equals_and_space_forms"
        status: pass
      - kind: unit
        ref: "tests/test_date_args.py#test_resolve_date_arg_ambiguity_and_empty_rejected"
        status: pass
      - kind: unit
        ref: "tests/test_date_args.py#test_format_token_canonical_shape"
        status: pass
      - kind: unit
        ref: "tests/test_date_args.py#test_import_purity_no_side_effects"
        status: pass
    human_judgment: false
  - id: D3
    description: "run_pipeline.py session-date gate: first statement of the pipeline branch (after --status/--buy/--sell/--value dispatcher, before Step 1 banner); non-session or invalid --date → ASCII stderr refusal containing 'session date' + exit 2 before any capture/file write/network; no token → byte-identical Phase 3 behavior"
    requirement: SEC-02
    verification:
      - kind: integration
        ref: "tests/test_date_args.py#test_real_script_refuses_past_session_date_exit2[run_pipeline.py---fast]"
        status: pass
      - kind: integration
        ref: "tests/test_date_args.py#test_real_script_refuses_invalid_date_exit2[run_pipeline.py---fast]"
        status: pass
    human_judgment: false
  - id: D4
    description: "morning_check.py session-date gate: top of main() after stdout reconfigure, before candidates load / auction capture; same resolve + equality + exit 2 shape with lazy date_args import mirroring the file's idiom"
    requirement: SEC-02
    verification:
      - kind: integration
        ref: "tests/test_date_args.py#test_real_script_refuses_past_session_date_exit2[morning_check.py---quick]"
        status: pass
      - kind: integration
        ref: "tests/test_date_args.py#test_real_script_refuses_invalid_date_exit2[morning_check.py---quick]"
        status: pass
    human_judgment: false
  - id: D5
    description: "tests/test_actions.py date-param contract pins extended to full suite (whole-file run green alongside pre-existing kind/lock/job pins)"
    verification:
      - kind: integration
        ref: "tests/test_actions.py (17 tests, full file)"
        status: pass
    human_judgment: false
  - id: D6
    description: "End-to-end green: python -m pytest -q full suite 146 passed + 1 skipped; git status --porcelain -- data/ logs/ empty after every run; suite spawns real scripts only in the pre-network refusal pins (past/invalid dates only)"
    verification:
      - kind: integration
        ref: "python -m pytest tests/ (146 passed, 1 skipped, 14.98s)"
        status: pass
      - kind: other
        ref: "git status --porcelain -- data/ logs/ (empty after full suite)"
        status: pass
    human_judgment: false

# Metrics
duration: 13min
completed: 2026-09-03
status: complete
---

# Phase 04 Plan 04: Trigger Date Whitelist (SC4) Summary

**Whitelisted dates on pipeline/morning-check reach the scripts as one trailing `--date=YYYY-MM-DD` arg-list token via a four-gate API (404/422 before any spawn), validated single-source in pure-stdlib date_args.py, with both scripts refusing non-session dates (exit 2) before any side effect**

## Performance

- **Duration:** 13 min
- **Started:** 2026-09-03T20:50:06Z
- **Completed:** 2026-09-03T21:02:43Z
- **Tasks:** 3
- **Files modified:** 6 (4 source, 2 test)

## Accomplishments

- `trigger_action(kind, date=None)` four-gate order: kind whitelist 404 first (date never consulted before kind), format/calendar validation via date_args → 422 `invalid_date_format`, capability gate (pipeline/morning-check only) → 422 `date_not_supported`, then `_cmd_for(kind, extra_args=...)` appends one normalized token `--date=YYYY-MM-DD` AFTER the fixed D-09 args — proven byte-exact by the fake-script argv pins (recorded argv == `[cmd[1], "--fast", "--date=2026-09-03"]`); 422/404 paths leave the registry dir empty (zero spawn).
- New pure-stdlib `scripts/daily/date_args.py` — the single source of the whitelist regex + real-calendar parse (T-04-15). API gate, both script gates and all tests consume it; no duplicated regex anywhere. Zero import side effects (pinned by a sys.modules-delta purity test), ASCII-only messages, importable by both the API chain and CLI scripts.
- Session-date gates wired into `run_pipeline.py` (first statement of the pipeline branch, pre-edit else-branch at line 46, after the `--status/--buy/--sell/--value` dispatcher and before the Step 1 banner) and `morning_check.py` (top of `main()` pre-edit line 457-458, after stdout reconfigure, before candidate load / auction capture). Non-session or invalid `--date` → ASCII stderr refusal containing "session date" + exit 2, stdout zero pollution, before any capture/file write/network. No token → today's normal behavior, byte-identical to pre-Phase-4 runs.
- Subprocess refusal pins spawn the REAL scripts with past (2026-01-01) and invalid (`not-a-date`) dates only — never today (a today-dated child bypasses the conftest network monkeypatch and would execute the live pipeline). Each pin asserts exit 2 + stderr refusal + no traceback + `git status --porcelain -- data/ logs/` clean before AND after.
- Full suite green: **146 passed, 1 skipped** (14.98s); hygiene `git status --porcelain -- data/ logs/` empty.

## Task Commits

Each task was committed atomically:

1. **Task 1: API date param whitelist gate (tracer, TDD)** - `11a0d05` (test: date-param argv delivery pins, RED 3 failed/1 passed by design) + `0174cbd` (feat: trigger date whitelist param (SC4), GREEN)
2. **Task 2: date_args single-source validator (TDD)** - `693523a` (test: date validator matrix, RED) + `bd1bd44` (feat: single-source date validator module, GREEN)
3. **Task 3: script-side session-date gates + refusal pins** - `11f5a08` (feat: session-date gate in run_pipeline + morning_check) + `463f8d2` (test: script refusal subprocess pins)

**Plan metadata:** docs commit at close-out (04-04-SUMMARY.md)

_Note: Task 2's RED was genuinely red (ImportError on resolve_date_arg/format_token) because date_args.py's parse_date half landed in Task 1 GREEN per plan-sanctioned option (a)._

## Files Created/Modified

- `scripts/daily/date_args.py` - NEW. Single-source validator: `DATE_RE` whitelist regex, `parse_date(value)` (regex + real calendar via `date.fromisoformat` / explicit ints, ValueError with ASCII message), `resolve_date_arg(argv)` (both `--date=X` and `--date X` forms, absent → None, multiple/empty → ValueError), `format_token(d)` → `--date=YYYY-MM-DD`. Pure re/sys/datetime, zero import side effects.
- `api/actions.py` - `from scripts.daily import date_args, job_lock` (config import unchanged); `_cmd_for(kind, extra_args=())` gained an extra-args slot appended after fixed args; `trigger_action(kind, date=None)` with the four-gate order; docstring SC4 section (gate order, D-28 literal shape).
- `scripts/daily/run_pipeline.py` - imports `resolve_date_arg` + `date`; session-date gate as first statement of the pipeline branch (lines 46-59 post-edit): ValueError → invalid-value refusal exit 2; resolved date != `date.today()` → non-session refusal exit 2.
- `scripts/daily/morning_check.py` - `from datetime import date` added to the existing datetime import; gate at top of `main()` (lines 458-472 post-edit) with lazy `from date_args import resolve_date_arg` mirroring the file's in-function import idiom.
- `tests/test_actions.py` - four date-param tests appended (valid delivery argv pins incl. compact 20260903 → normalized dashed token, invalid-format 422 matrix with empty-registry assertions, zero-param kinds 422, unknown kind 404-first).
- `tests/test_date_args.py` - NEW. 7 matrix/purity tests + 4 subprocess refusal pins (2 scripts × past/invalid dates).

## Decisions Made

- Followed plan-sanctioned option (a) for the tracer ordering tension: landed `date_args.py`'s parse half inside Task 1 GREEN so Task 2's RED was genuinely red; module completed in Task 2 GREEN.
- Both scripts' refusal messages embed the shared ASCII substring "session date" so one stderr assertion pins both scripts' refusal paths (valid-past and invalid variants).
- Script gates accept the space-separated `--date <date>` form too (in-repo `data_health_check.py:102-110` manual-CLI idiom), resolved by the same single-source `resolve_date_arg`; both-forms-present or multiple tokens → ValueError → same exit-2 refusal (ambiguity fail-loud).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] import-purity test order dependence (false failure in full suite)**
- **Found during:** Task 2 (test_import_purity_no_side_effects)
- **Issue:** Absolute assertion `"scripts.daily.config" not in sys.modules` passed standalone but failed in full-suite order — earlier test files (test_actions → api.main → scripts.daily.config) legitimately import config first. False positive, not a module regression.
- **Fix:** Rewrote the test to measure the sys.modules DELTA (pop date_args → snapshot before → import → assert no added scripts.* module beyond namespace parents scripts/scripts.daily/date_args itself). Purity contract unchanged: date_args import pulls no config, prints nothing.
- **Files modified:** tests/test_date_args.py
- **Verification:** matrix 7/7 standalone, full suite green
- **Committed in:** 693523a/693523a-amended within Task 2 GREEN (bd1bd44 final state)

**2. [Rule 1 - Bug] Task 3 draft pins would have run the live pipeline at RED time**
- **Found during:** Task 2 planning (before any commit)
- **Issue:** Initial tests/test_date_args.py draft included Task 3 subprocess pins while the scripts lacked gates — running those red would have spawned the REAL pipeline (network + data writes, forbidden in-suite).
- **Fix:** Restructured the file to matrix-only; Task 3 pins appended via Edit AFTER the gates shipped in 11f5a08 (Task 3 is type auto, no RED run required). Pins only spawn past/invalid dates, never today.
- **Files modified:** tests/test_date_args.py
- **Verification:** pins green on first run post-gate (11/11 in file, 0.95s)
- **Committed in:** 463f8d2

---

**Total deviations:** 2 auto-fixed (2 Rule 1 — both test-fidelity issues, no product-code deviation)
**Impact on plan:** No scope creep; product code shipped exactly as planned. The purity-test fix corrected a measurement bug; the pin-ordering fix enforced the plan's own safety invariant (never spawn the real pipeline in-suite).

## Issues Encountered

- None beyond the two auto-fixes above. All four refusal paths additionally verified live by hand before the pins were written (rc=2, stderr routing confirmed with stdout suppressed, hygiene checked after each manual probe).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 04-05/04-06/04-07 can extend the same patterns: four-gate ordering (kind 404 precedes parameter logic), single-source validator modules consumed by API + scripts + tests, and pre-network subprocess pins as the standard proof shape for "refusal before side effects".
- The `data_health_check.py --date` space-form idiom and the manual-CLI path remain untouched (dispatch on argv[1] != --fast still routes to --status/--buy/--sell/--value; a date token can never occupy argv[1] because the API appends after fixed args).

## Self-Check: PASSED

All 6 created/modified files verified present on disk; all 6 production commits (11a0d05, 0174cbd, 693523a, bd1bd44, 11f5a08, 463f8d2) verified in git log; full suite 146 passed + 1 skipped; data//logs/ hygiene clean.

---
*Phase: 04-exposure-hardening-data-classification*
*Completed: 2026-09-03*
