---
phase: 05-recovery-observability-ops-polish
plan: 02
subsystem: api
tags: [fastapi, job-registry, log-rotation, dup2, os.replace, file-sharing, windows]

# Dependency graph
requires:
  - phase: 05-01
    provides: auth-gated /health/details surface and phase-5 conventions; boot-then-ops foundation the housekeeping block joins after reload_registry
provides:
  - OPS-03 SC2 rotation half: console.log 5MB one-generation rotation + registry capped at 20 terminal-status pairs (D-32/D-33)
  - api/log_housekeep.py pure-function primitives (D-34): rotate_console_log / repoint_std_streams / prune_job_logs
  - main() boot housekeeping dance repoint -> rotate -> repoint -> prune with WARNING-not-fatal discipline (M-A)
  - test_boot.py LOG_DIR isolation seam for the housekeeping block
affects: [05-03 (Mac checklist + scheduled-task confirm read the bounded-footprint claim), 05-04 (real-machine live gate proves the two-repoint dance on the cmd >> console)]

actuals:
  tokens: 4235    # chars/4 over realized diff (16,939 chars, git diff c9995f3..HEAD, 6 files)
  tasks: 3
  commits: 7

tech-stack:
  added: [none — stdlib os/sys only per T-05-SC]
  patterns: [M-A std-handle dance (repoint -> rotate -> repoint), boot housekeeping primitives returning (rotated, error)/error|None, call-time module-attr path/cap resolution as the monkeypatch seam, single api.main.LOG_DIR patch isolating the whole boot block]

key-files:
  created: [api/log_housekeep.py, tests/test_log_housekeep.py]
  modified: [api/jobs.py, tests/test_jobs.py, api/main.py, tests/test_boot.py]

key-decisions:
  - "Cap-20 boundary seed: 25 terminal + 3 inflight -> reload_registry sweeps inflight to interrupted (in-place rewrite = newest mtimes) then tail-prune deletes the 8 oldest terminal pairs -> exactly 20 .json (17 newest terminal + 3 interrupted); interrupted counts toward the cap"
  - "Windows two-repoint dance order repoint -> rotate -> repoint is the only working order (cmd >> inherited handle lacks FILE_SHARE_DELETE, machine-verified 2026-09-04; dup2 replacement releases it before os.replace; second repoint lands streams on the fresh file) — uniform dance even under threshold (rotate no-op) keeps the order stable; live proof deferred to the 05-04 gate"
  - "log_housekeep is zero-config pure-function: defaults (console.log path, registry dir, cap) resolve via api.jobs module attrs at call time — one LOG_DIR monkeypatch isolates the whole module; primitives never raise and never print"
  - "Failure discipline in main(): first-repoint error still attempts rotate; at most ONE ascii WARNING to stderr; never exit/raise on housekeeping failure — SEC-03 fatal-exit paths untouched"
  - "Boot-test isolation via a single api.main.LOG_DIR patch: every path the block touches is derived from main's own LOG_DIR attr (never module-default bare calls, which would dup2 the real logs tree onto pytest fds); refusal-path tests patched too for uniformity"

patterns-established:
  - "M-A std-handle dance: boot block = repoint -> rotate -> repoint -> prune between reload_registry and the lazy uvicorn import, with the FILE_SHARE_DELETE rationale in a 5-line comment"
  - "Housekeeping primitives are pure and tolerant: (rotated, error) / error|None / None return shapes, ascii-error conversion for GBK consoles, per-file OSError: pass — suite pins every OSError leg"
  - "Call-time resolution seam: defaults compose jobs.LOG_DIR / jobs_dir() / jobs.PRUNE_CAP when invoked, so monkeypatching the owning module attr isolates callers of the same module"

requirements-completed: [OPS-03]

coverage:
  - id: D1
    description: "Registry provably capped at 20 terminal-status pairs with swept-interrupted counting toward the cap: PRUNE_CAP single constant (api/jobs.py:26, no second copy), 25 terminal + 3 inflight seed -> exactly 20 .json (17 newest terminal + 3 interrupted), oldest 8 pairs deleted json+log, second reload no-op; run_job finally-prune trims to 20 too; corrupt json skipped while others still trimmed"
    requirement: OPS-03
    verification:
      - kind: unit
        ref: "tests/test_jobs.py#test_reload_sweep_prune_cap_keeps_20_newest_terminal"
        status: pass
      - kind: unit
        ref: "tests/test_jobs.py#test_run_job_finally_prune_trims_to_cap_20"
        status: pass
      - kind: unit
        ref: "tests/test_jobs.py#test_prune_skips_corrupt_json_still_trims_others"
        status: pass
    human_judgment: false
  - id: D2
    description: "api/log_housekeep.py pure-function primitives (D-34): rotate_console_log (5MiB threshold, os.replace to .1 one-generation overwrite, under-threshold/missing no-op, default path via jobs.LOG_DIR at call time, OSError -> ascii error); repoint_std_streams (flush + os.open O_WRONLY|O_APPEND|O_CREAT + dup2 to fds 1/2, no sys.stdout wrapper rebuild — subprocess probe proves bytes land on real fds); prune_job_logs (delegates jobs.prune, cap resolved at call time, idempotent)"
    requirement: OPS-03
    verification:
      - kind: unit
        ref: "tests/test_log_housekeep.py#test_rotate_over_threshold_renames_to_dot1_overwrites_prev"
        status: pass
      - kind: unit
        ref: "tests/test_log_housekeep.py#test_rotate_exactly_at_limit_is_noop"
        status: pass
      - kind: unit
        ref: "tests/test_log_housekeep.py#test_rotate_oserror_returns_ascii_error_never_raises"
        status: pass
      - kind: unit
        ref: "tests/test_log_housekeep.py#test_repoint_real_fds_subprocess_probe"
        status: pass
      - kind: unit
        ref: "tests/test_log_housekeep.py#test_prune_job_logs_cap_resolved_at_call_time"
        status: pass
    human_judgment: false
  - id: D3
    description: "main() boot housekeeping dance wired between jobs.reload_registry() and the lazy uvicorn import: console_log and jobs_dir_path resolved once from main's LOG_DIR attr, four calls repoint -> rotate -> repoint -> prune with a 5-line ordering comment (FILE_SHARE_DELETE rationale); WARNING-not-fatal discipline — at most one ascii stderr WARNING, housekeeping never blocks boot (SEC-03 fatal paths untouched)"
    requirement: OPS-03
    verification:
      - kind: unit
        ref: "tests/test_boot.py#test_loopback_boot_prints_only_notice_and_creates_token"
        status: pass
      - kind: unit
        ref: "tests/test_boot.py#test_loopback_boot_generates_token_and_exits_normally"
        status: pass
      - kind: unit
        ref: "tests/test_boot.py#test_env_token_non_loopback_proceeds_with_ascii_warning_no_token_echo"
        status: pass
    human_judgment: false
  - id: D4
    description: "test_boot.py isolation seam: all six main()-calling tests patch api.main.LOG_DIR -> tmp_path beside DATA_DIR, so the housekeeping block exercises primitives against tmp trees only (loopback err==\"\" pins the block's silence on success); full-suite regression green with data/ and logs/ untouched"
    requirement: OPS-03
    verification:
      - kind: unit
        ref: "tests/test_boot.py#test_non_loopback_without_token_refuses_and_creates_no_file"
        status: pass
      - kind: unit
        ref: "tests/test_boot.py#test_non_loopback_file_token_only_refuses_without_uvicorn"
        status: pass
      - kind: other
        ref: "python -m pytest -q (185 passed, 1 skipped) + git status --porcelain -- data/ logs/ (empty)"
        status: pass
    human_judgment: false

# Metrics
duration: 10min
completed: 2026-09-05
status: complete
---

# Phase 5 Plan 2: Bounded disk footprint — console.log rotation + registry cap 20 Summary

**OPS-03 SC2 rotation half delivered: PRUNE_CAP 500→20 (single constant), pure-function api/log_housekeep.py (5MiB .1 rotation, dup2 repoint, prune delegation), and the main() boot dance repoint → rotate → repoint → prune between reload_registry and the uvicorn import — WARNING-not-fatal, ASCII-only, zero new dependencies — with the suite isolated via api.main.LOG_DIR patches and the real-machine proof deferred to 05-04.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-09-04T16:45:57Z
- **Completed:** 2026-09-04T16:56:01Z
- **Tasks:** 3
- **Files modified:** 6 (2 created + 4 modified)

## Accomplishments
- Registry cap: PRUNE_CAP 500→20 at api/jobs.py:26 — the only semantic diff line; both prune call sites (run_job finally, reload_registry tail) share the constant; test pins 25 terminal + 3 inflight → exactly 20 .json (17 newest terminal + 3 swept-interrupted), oldest 8 pairs deleted json+log, second reload idempotent, corrupt-json skip leg, finally-prune leg
- api/log_housekeep.py (D-34): rotate_console_log / repoint_std_streams / prune_job_logs — pure functions, explicit path params, defaults resolved via api.jobs attrs at call time (single monkeypatch seam), OSError-tolerant with ascii error strings, zero prints, zero import side effects; 9-test suite incl. a subprocess probe proving dup2'd fd 1/2 bytes land in the target file
- main() boot dance (M-A, D-32/D-34): block after jobs.reload_registry() with paths derived once from main's LOG_DIR attr; guarded makedirs of the console.log dir; four calls repoint → rotate → repoint → prune; one consolidated ascii WARNING on failure, never fatal — SEC-03 exits untouched; run_api.bat untouched
- test_boot.py: all six main()-calling tests gain api.main.LOG_DIR → tmp_path (loopback err=="" assertions pin the block's success-silence; refusal tests patched uniformly although they exit before the block)

## Task Commits

Each task was committed atomically:

1. **Task 1 (TDD): PRUNE_CAP 500→20 + cap-test rewrite** - `5ac1274` (test, amended), `5de5e69` (feat)
2. **Task 2 (TDD): log_housekeep primitives** - `463a586` (test, amended), `f08a50c` (feat)
3. **Task 3: main() housekeeping dance + boot LOG_DIR patches** - `7a55750` (feat), `498545a` (test)

**Plan metadata:** docs commit pending (this summary + STATE/ROADMAP/REQUIREMENTS updates)

## Files Created/Modified
- `api/jobs.py` - PRUNE_CAP 500→20 (D-33, single constant, api/jobs.py:26)
- `tests/test_jobs.py` - cap test rewritten to 20-remain boundary (25+3 seed), finally-prune leg, corrupt-skip leg added
- `api/log_housekeep.py` - new: pure-function rotation/repoint/prune primitives (D-34), MAX_CONSOLE_LOG_BYTES 5 MiB
- `tests/test_log_housekeep.py` - new: 9-test suite (threshold/one-generation/no-op/OSError/default-path, prune cap-edge/idempotence/call-time, subprocess fd probe)
- `api/main.py` - import region + housekeeping block between reload_registry and lazy uvicorn import (paths from LOG_DIR attr, WARNING-not-fatal)
- `tests/test_boot.py` - api.main.LOG_DIR → tmp_path added to all six main()-calling tests

## Decisions Made
- Cap-20 boundary math (D-33): seed 25 terminal + 3 inflight; sweep rewrites inflight to interrupted with now-mtimes; tail-prune removes the 8 oldest terminal pairs → exactly 20 .json remain (17 terminal + 3 interrupted). Interrupted counts toward the cap — the rewritten test pins the exact boundary the plan specified
- Two-repoint dance order is the only working order on Windows: cmd `>>` inherited console.log handle lacks FILE_SHARE_DELETE (machine-verified 2026-09-04), so the first repoint (dup2 replacement) must release it before os.replace can rename; the second repoint lands fd 1/2 on the fresh file or uvicorn stderr would fall into console.log.1. Uniform dance runs under threshold too (rotate no-ops) so the ordering is stable; flagged for the 05-04 live gate
- log_housekeep defaults (console.log path, jobs dir, cap) resolve through api.jobs module attrs at call time — no config import, one LOG_DIR monkeypatch isolates the entire module
- Boot-test isolation via main's own LOG_DIR attr: every housekeeping path derives from it, so a single api.main.LOG_DIR patch keeps the block off the real logs/api tree (bare default-resolution calls would have dup2'd the REAL console.log onto pytest's fds 1/2 — invisible to the gitignore-blind hygiene pin)
- Failure discipline: first-repoint error still attempts rotate (may succeed); at most one consolidated ascii WARNING to stderr; never exit/raise — SEC-03 fatal-exit discipline untouched

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Guarded os.makedirs of the console.log parent dir in the boot block**
- **Found during:** Task 3 (main() housekeeping block design against test_boot.py)
- **Issue:** The plan's four housekeeping calls require logs/api to exist (os.open O_CREAT fails when the parent dir is absent), but the block as specified assumed the dir exists. In boot tests tmp_path/api never exists (reload_registry runs against the REAL registry in these tests, creating only the real tree), so the first repoint would fail → WARNING on stderr → breaks the loopback tests' err=="" pins; a production boot from a clean checkout would print a spurious warning on first boot too
- **Fix:** Guarded `os.makedirs(os.path.dirname(console_log), exist_ok=True)` with `except OSError: pass` at the top of the block — directory creation failure falls through to the primitives' own tolerant error reporting; boot never blocked
- **Files modified:** api/main.py
- **Verification:** tests/test_boot.py green with err=="" preserved (silent success); full suite green
- **Committed in:** 7a55750 (Task 3 feat commit)

---

**Total deviations:** 1 auto-fixed (1 missing critical)
**Impact on plan:** Necessary for the suite isolation seam and first-boot correctness. No scope creep — no behavior beyond directory readiness.

## Issues Encountered
- RED-commit test-authoring bugs (fixed via `git commit --amend` before GREEN, so the RED commits stayed test-only): (1) stem-vs-name comparison bug in the new cap tests — list membership compared full file names against extension-stripped stems, fixed with `p.name[: -len(".json")]`; (2) corrupt-test seed arithmetic — 22 seeds with 1 corrupt left only 1 pair over cap (not 2), re-seeded to range(23) so prune deletes the 2 oldest valid pairs and the assertion set matches; (3) rotate default-path test wrote under tmp_path/logs/api instead of tmp_path/api — the autouse fixture patches api.jobs.LOG_DIR to tmp_path itself, so the no-arg call resolves to tmp_path/api/console.log
- run_job finally-prune leg: prune is run_job's LAST finally step, after the terminal file write — the test polls (`_wait_for`) until exactly 20 jsons exist instead of asserting immediately after wait_terminal

## Next Phase Readiness
- Bounded-footprint claims ready for the 05-04 live gate: console.log rotates at 5MiB to .1 (one generation), registry holds ≤20 terminal pairs from the first boot (both prune sites + boot prune_job_logs share the single constant)
- Flagged for 05-04: prove the two-repoint dance on the real cmd `>>` console (rotation actually renames, uvicorn stderr lands in the fresh console.log, no WinError 32), plus the uniform-dance-under-threshold path on a real boot
- 05-03 (Mac checklist / scheduled-task confirm) can read the rotation-half claim as suite-backed; no blockers

## Self-Check: PASSED

- Files verified present: api/log_housekeep.py, tests/test_log_housekeep.py, api/main.py, api/jobs.py, tests/test_jobs.py, tests/test_boot.py, this SUMMARY file
- Commits verified in git log: 5ac1274, 5de5e69, 463a586, f08a50c, 7a55750, 498545a

---
*Phase: 05-recovery-observability-ops-polish*
*Completed: 2026-09-05*
