---
phase: 01-service-skeleton-health-liveness
plan: 01
subsystem: api
tags: [fastapi, uvicorn, pytest, health, secrets, token, fail-closed, testclient]

# Dependency graph
requires: []
provides:
  - api/ regular package (repo's first package, D-01) with FastAPI app, GET /health, main() boot sequence
  - api/boot.py pure helpers (is_loopback/read_token/has_token/ensure_token)
  - fail-closed boot semantics (SEC-03) with D-03/D-04/D-05 token policy at rest
  - .gitignore data/api_token.txt entry (D-06, same commit as generator)
  - requirements.txt floors for fastapi/uvicorn/pytest/httpx
  - repo's first pytest suite (OPS-02): pytest.ini + tests/ (network-blocking + env-cleanup fixtures)
affects: [01-02 (run_api.bat autostart), phase-2 state endpoints, phase-3 auth (must exempt /health), phase-4 token audit]

actuals:
  tokens: 3643
  tasks: 3
  commits: 4

# Tech tracking
tech-stack:
  added: [fastapi>=0.115.14, uvicorn>=0.51.0, pytest>=8.3 (9.1.1 installed), httpx>=0.25.2]
  patterns:
    - "PEP 420 namespace import via pytest.ini pythonpath = . (Pitfall 1)"
    - "Lazy import of uvicorn inside main() keeps import api.main side-effect-free"
    - "Pure boot helpers with explicit path/env params (tmp_path/monkeypatch testable)"
    - "Env-first-file-second token read (kline_source.py shape, D-04)"
    - "Autouse network-block fixture with loopback carve-out (Windows ProactorEventLoop socketpair)"
    - "Fake sys.modules module to patch lazily-imported uvicorn.run in tests"

key-files:
  created: [api/__init__.py, api/boot.py, api/main.py, pytest.ini, tests/conftest.py, tests/test_health.py, tests/test_boot.py]
  modified: [.gitignore, requirements.txt]

key-decisions:
  - "boot.py never prints; the D-05 fixed ASCII notice lives only in api/main.py's loopback branch"
  - "SEC-03 refusal wording: ASCII English naming the bound host and the remedy (GOGO_API_TOKEN / data/api_token.txt)"
  - "Network-block fixture exempts loopback destinations: asyncio ProactorEventLoop init does an internal 127.0.0.1 socketpair connect on Windows; blanket socket.connect block breaks TestClient (Rule 3 fix)"
  - "PYTEST_DEBUG_TEMPROOT redirect in pytest_configure: machine %TEMP%/pytest-of-Davis has owner-denied ACLs (Jul 2026 leftover), tmp cleanup scandir raises PermissionError (Rule 3 fix)"
  - "uvicorn.run patched via fake module pre-seeded in sys.modules: api/main.py imports uvicorn lazily inside main(), so no api.main.uvicorn attribute exists for monkeypatch.setattr"

patterns-established:
  - "New top-level modules import path constants from scripts/daily/config.py; zero sys.path/BASE boilerplate (D-02)"
  - "Boot guard: if __name__ == '__main__': main() — module import creates only the app object (Pitfall 3)"
  - "time.monotonic() uptime anchor captured at import (T-01-04)"
  - "App-level: docs_url=None/redoc_url=None/openapi_url=None; no middleware, no dependencies on /health (Pitfall 6)"
  - "Test hygiene: autouse _clean_env deletes GOGO_API_* env; tmp_path for all token files; import-side-effect pinned with pre-existence guard"

requirements-completed: [HLT-01, SEC-03, OPS-02]

coverage:
  - id: D1
    description: "api/ package: FastAPI app (docs disabled), GET /health pure in-memory always-200 with exact body, main() boot sequence, __main__ guard"
    requirement: HLT-01
    verification:
      - kind: integration
        ref: "live E2E: python -m api.main on 127.0.0.1:8017 then urllib probe asserting status==ok and int uptime>=0"
        status: pass
      - kind: unit
        ref: "python -m pytest tests/test_health.py (3 passed)"
        status: pass
      - kind: other
        ref: "python -c 'import scripts.daily.config, api.main; print(api.main.app.title)' -> 'gogo API'"
        status: pass
    human_judgment: false
  - id: D2
    description: "SEC-03 fail-closed boot: non-loopback bind without configured token refuses with clear stderr message, exits non-zero, creates NO token file (Pitfall-2 ordering — check before any generation); loopback default generates via secrets and prints only the D-05 notice"
    requirement: SEC-03
    verification:
      - kind: other
        ref: "live E2E refusal: GOGO_API_HOST=0.0.0.0 python -m api.main -> exit 1, stderr names host+remedy, data/api_token.txt absent after"
        status: pass
      - kind: unit
        ref: "python -m pytest tests/test_boot.py (15 passed, incl. case-5 Pitfall-2 regression + D-05 sole-notice assertions)"
        status: pass
    human_judgment: false
  - id: D3
    description: "D-06: data/api_token.txt git-ignored in the same commit as the token-generating code; token value never printed (D-05)"
    requirement: SEC-03
    verification:
      - kind: other
        ref: "git check-ignore -v data/api_token.txt -> .gitignore:12 (exit 0)"
        status: pass
    human_judgment: false
  - id: D4
    description: "OPS-02: repo's first pytest suite runs green offline — network-blocking autouse fixture, env-cleanup fixture, import mechanics (pytest.ini pythonpath=.)"
    requirement: OPS-02
    verification:
      - kind: other
        ref: "python -m pytest -q -> 18 passed, 1 skipped"
        status: pass
    human_judgment: false

# Metrics
duration: 8min
completed: 2026-09-03
status: complete
---

# Phase 01 Plan 01: Service Skeleton + /health Liveness Summary

**Repo's first package and resident service slice: FastAPI GET /health (pure in-memory always-200, monotonic uptime), SEC-03 fail-closed boot that refuses non-loopback binds without a configured token BEFORE any auto-generation (Pitfall-2 ordering), D-03/D-05 token-at-rest with the D-06 same-commit .gitignore rule, and the repo's first offline pytest suite — 18 passed, 1 skipped, zero network access.**

## Performance

- **Duration:** 8 min (477 s)
- **Started:** 2026-09-02T22:22:29Z
- **Completed:** 2026-09-02T22:30:26Z
- **Tasks:** 3 (1 tracer + 2 auto)
- **Files modified:** 9 (7 created, 2 modified)

## Accomplishments

- **Tracer slice proven end-to-end on the machine (Task 1):** `python -m api.main` with `GOGO_API_HOST=0.0.0.0` and no token refused with exit 1, named the host and remedy on stderr, and created no `data/api_token.txt` (run first, before any token existed). A loopback boot on port 8017 answered `/health` 200 with `{"status": "ok", "uptime_seconds": 0}` (int >= 0), and the port was released on termination. The tracer `<verify>` re-run after commit also passed (loopback probe, `git check-ignore`, import title) — no checkpoint needed (`end-of-phase` verify mode, automated-only checks).
- **api/ package built per D-01/D-02:** first package in the repo (only `__init__.py` in 116+ .py files), importing `DATA_DIR` from `scripts/daily/config.py` with zero per-file `sys.path`/`BASE` boilerplate. `api/main.py` keeps module import side-effect-free (boot + lazy `uvicorn.run` behind the `__main__` guard) so TestClient never boots, binds, or touches the real token file.
- **First-start loopback boot generated `data/api_token.txt`** via `secrets.token_urlsafe(32)` (single-line utf-8) and printed only the fixed ASCII notice; the value never appears in any output (D-05). The `.gitignore` entry landed in the same commit as the generator (D-06, commit `240989f`).
- **Repo's first pytest suite (OPS-02) is green offline:** pytest.ini (`pythonpath = .`, `testpaths = tests`), autouse network-block + `GOGO_API_*` env-cleanup fixtures, 4 HLT-01 `/health` contract tests (200 without any auth header, exact key set, monotonic uptime, import side-effect-free), and 15 SEC-03/D-03/D-04/D-05 boot tests including the Pitfall-2 refusal regression (SystemExit non-zero AND no token file in the tmp DATA_DIR after refusal).

## Task Commits

Each task was committed atomically:

1. **Task 1 (tracer): api package with /health and fail-closed boot** - `240989f` (feat)
2. **Task 2: pytest infra + HLT-01 /health contract tests** - `b9bc550` (test)
3. **Task 3: SEC-03/D-03/D-05 boot tests, full suite green** - `2531701` (test)

**Plan metadata:** (docs commit follows this SUMMARY)

## Files Created/Modified

- `api/__init__.py` - empty regular-package marker (repo's first package)
- `api/boot.py` - pure stdlib helpers: `is_loopback` (localhost + ipaddress; invalid/empty strings fail closed to non-loopback), `read_token`/`has_token` (env-first-file-second, D-04), `ensure_token` (secrets.token_urlsafe(32), utf-8 single line, never prints)
- `api/main.py` - `app` (FastAPI, docs disabled, no middleware), `health()` at `GET /health`, `main()` boot sequence (SEC-03 check before any `ensure_token`; generation only on loopback branch; D-05 notice; lazy uvicorn import), `__main__` guard, ASCII-only console text, `sys.stdout.reconfigure(encoding="utf-8")` at boot
- `pytest.ini` - `[pytest]` pythonpath = . / testpaths = tests (import mechanics)
- `tests/conftest.py` - autouse `_no_network` (loopback-aware socket.connect guard) + `_clean_env` (GOGO_API_* deletion) + `pytest_configure` temproot redirect
- `tests/test_health.py` - HLT-01 contract via TestClient; import-side-effect test skips when the real token file pre-exists (as it now does on this machine after the E2E boot)
- `tests/test_boot.py` - the 7 planned case groups as 15 tests
- `.gitignore` - `data/api_token.txt` added beside the existing plaintext-token entries (line 12)
- `requirements.txt` - appended `fastapi>=0.115.14`, `uvicorn>=0.51.0`, `pytest>=8.3`, `httpx>=0.25.2` in the existing `>=floor` style

## Decisions Made

Followed the plan as written; the three decisions below are implementation-level fixes required by live machine behavior (documented as deviations):

1. **Loopback carve-out in the network-block fixture** - blanket `socket.socket.connect` blocking breaks asyncio event-loop creation on Windows (ProactorEventLoop internal 127.0.0.1 socketpair), which TestClient's anyio portal needs. Loopback is not a data source, so the guard now raises only for non-loopback destinations.
2. **`PYTEST_DEBUG_TEMPROOT` redirect in conftest `pytest_configure`** - the machine's `%TEMP%\pytest-of-Davis` (July 2026 leftover) denies enumeration even to the owner; pytest's tmp-dir cleanup scandir raises PermissionError. The official temproot override points tmp at `%TEMP%\pytest-temproot-gogo`. Repairing the ACLs would need elevation (UAC) - not appropriate for an agent; redirect is deterministic and Mac-harmless.
3. **uvicorn.run test patching via fake `sys.modules` entry** - `api/main.py` imports uvicorn lazily inside `main()` (function-local binding), so `monkeypatch.setattr("api.main.uvicorn.run", ...)` cannot work (no `api.main.uvicorn` attribute exists). Tests pre-seed a fake `uvicorn` module with a no-op `run(app=None, **kw)`; assertion content unchanged from the plan.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Network-block fixture broke TestClient on Windows (event-loop socketpair)**
- **Found during:** Task 2 (tests/test_health.py - all TestClient tests errored at fixture setup)
- **Issue:** The blanket `socket.socket.connect` block (vibe-astock model quoted in 01-PATTERNS.md) raises inside asyncio `ProactorEventLoop` initialization, which performs an internal loopback socketpair connect on Windows. TestClient's anyio portal cannot start its event loop.
- **Fix:** `_no_network` now delegates real connects for loopback destinations (ipaddress.is_loopback or "localhost") and raises AssertionError only for non-loopback hosts, keeping the loud tripwire for any real data-source access.
- **Files modified:** tests/conftest.py
- **Verification:** mechanism reproduced in isolation (blanket block breaks `asyncio.new_event_loop()`, guarded patch does not); tests/test_health.py 3 passed
- **Committed in:** b9bc550 (part of Task 2 commit)

**2. [Rule 3 - Blocking] pytest tmp-dir PermissionError from broken-ACL leftover directory**
- **Found during:** Task 3 (all tmp_path tests errored at setup)
- **Issue:** `%TEMP%\pytest-of-Davis` (2026-07 leftover) denies directory enumeration even to owner Davis (icacls grant also denied - needs elevation). pytest's `make_numbered_dir_with_cleanup` scandir of the rootdir raises `PermissionError: [WinError 5]`.
- **Fix:** `pytest_configure` in tests/conftest.py sets pytest's official `PYTEST_DEBUG_TEMPROOT` override (read lazily at first tmp use) to a fresh `%TEMP%\pytest-temproot-gogo` root. pytest.ini stays exactly as planned (pythonpath + testpaths only).
- **Files modified:** tests/conftest.py
- **Verification:** tests/test_boot.py all 15 pass after fix
- **Committed in:** 2531701 (part of Task 3 commit)

**3. [Rule 3 - Blocking] monkeypatch target for uvicorn.run does not exist**
- **Found during:** Task 3 (test authoring - mechanics adjusted before first run per the plan's own note)
- **Issue:** main.py imports uvicorn lazily inside `main()` (function-local name), so the plan's suggested `monkeypatch.setattr("api.main.uvicorn.run", ...)` resolves no attribute.
- **Fix:** per the plan's explicit adjustment permission ("adjust the test to patch the origin module - the assertion content must not change"), tests pre-seed a fake `uvicorn` module (no-op `run(app=None, **kw)`) into `sys.modules`; main()'s lazy import picks it up.
- **Files modified:** tests/test_boot.py
- **Verification:** all 15 boot tests pass; no real socket is ever bound
- **Committed in:** 2531701 (part of Task 3 commit)

---

**Total deviations:** 3 auto-fixed (all Rule 3 - blocking)
**Impact on plan:** None on scope or contracts - all three were execution-mechanics/environment fixes; every acceptance criterion and must-have truth is met.

## Issues Encountered

Beyond the three deviations above: `python -m pytest tests/test_boot.py` initially reported `TypeError` on the fake uvicorn `run` (first positional `app` arg not accepted) - fixed within the same authoring pass. The HLT-01 import-side-effect test correctly skips on this machine because the E2E loopback boot legitimately created the real token file (guard is by design; on a fresh checkout it runs).

## User Setup Required

None - no external service configuration required. Note: `data/api_token.txt` now exists locally (generated by the Task 1 E2E loopback boot - this is the designed at-rest location, gitignored). Delete it to force a fresh token on next loopback boot.

## Next Phase Readiness

- Plan 01-02 (Windows autostart: run_api.bat + Task Scheduler installer) can build directly on `python -m api.main` - the entry it launches is proven: binds loopback, generates the token on first start, answers `/health` on 127.0.0.1:8000.
- The boot sequence, token convention, and import mechanics locked here are the ones Phases 2-5 extend; any future auth middleware must exempt `/health` (pinned by the OPS-02 suite).
- Machine notes for 01-02: no git hooks active; port 8000 was free at research time; `logs/*` already gitignored so `logs/api/console.log` needs no new entry.

---
*Phase: 01-service-skeleton-health-liveness*
*Completed: 2026-09-03*

## Self-Check: PASSED
- All 7 source/infra files present; SUMMARY.md present
- Commits verified: 240989f (feat), b9bc550 (test), 2531701 (test), 9b683ad (docs)
