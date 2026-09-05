---
phase: 05-recovery-observability-ops-polish
plan: 01
subsystem: api
tags: [fastapi, auth, health-details, importlib-metadata, iso8601, pytest]

# Dependency graph
requires:
  - phase: 04-exposure-hardening-data-classification
    provides: require_api_key dependency-object identity (router-level), frozen CODE_BY_DETAIL envelope, SC2 route-by-route audit, private-router skeleton
provides:
  - Auth-gated GET /health/details with the exact D-29 body shape {versions, uptime_seconds, last_check}
  - uptime_seconds() public helper in api/main.py shared by /health and /health/details
  - OSError/ValueError-tolerant registry scan pattern (mirrors jobs.prune) for ops reads
  - First ISO-8601 UTC output in the API surface (datetime.fromtimestamp(tz=utc).isoformat())
affects: [05-02, 05-03, 05-04 live gate on real machine]

actuals:
  tokens: 6383    # chars/4 over realized diff (25,535 chars, git diff 25e758e..HEAD)
  tasks: 3
  commits: 4

tech-stack:
  added: [importlib.metadata (stdlib, lazy versions read), ISO-8601 datetime output (stdlib)]
  patterns: [router-level require_api_key on dedicated module (private.py twin), handler-level lazy import for circular-safe cross-module read, call-time os.path.join composition seam, per-file (OSError, ValueError) tolerance in registry scans]

key-files:
  created: [api/health.py, tests/test_health_details.py]
  modified: [api/main.py, tests/test_auth.py]

key-decisions:
  - "[ASSUMED] market_state.json missing/unreadable -> market_state_mtime: null — ACCEPT (built as assumed; never 5xx)"
  - "[ASSUMED] uptime wiring = public uptime_seconds() beside _START + handler-level lazy import in health_details — ACCEPT (module-level import would circular-fail by construction)"
  - "[ASSUMED] newest succeeded health-check = max finished_at among registry jsons with kind health-check + status succeeded — ACCEPT"
  - "[ASSUMED] ISO output = datetime.fromtimestamp(value, timezone.utc).isoformat() with in-test frozen-value equality — ACCEPT"
  - "Registry directory is NOT re-derived in api/health.py: DATA_DIR held on health module; registry located via api.jobs.jobs_dir() (single source of truth) with the LOG_DIR seam on api.jobs — plan frontmatter 'DATA_DIR/LOG_DIR' realized accordingly, zero unused imports"
  - "importlib.metadata imported as module attribute (not from-import) so the versions-fallback monkeypatch seam works"

patterns-established:
  - "New secret-tier route module = private.py twin: router = APIRouter(dependencies=[Depends(require_api_key)]), SC2 audit extended in the same task"
  - "Cross-module anchor reads go through a public helper + request-time lazy import (never module-level import of the app entry)"

requirements-completed: [OPS-03]

coverage:
  - id: D1
    description: "Auth-gated GET /health/details: router-level require_api_key with dependency-object identity; 401 missing API key + WWW-Authenticate: ApiKey / 403 invalid API key with no challenge; SC2 audit classifies the route 机密级 in the same commit"
    requirement: OPS-03
    verification:
      - kind: unit
        ref: "tests/test_health_details.py#test_gate_matrix_no_key_401_wrong_key_403_valid_200"
        status: pass
      - kind: unit
        ref: "tests/test_auth.py#test_sc2_route_by_route_classification_audit"
        status: pass
      - kind: unit
        ref: "tests/test_health_details.py#test_fail_closed_403_no_token_configured"
        status: pass
    human_judgment: false
  - id: D2
    description: "Exact D-29 body shape: top-level key set {versions, uptime_seconds, last_check}, versions subkeys {python, uvicorn, fastapi} with live lazy values (never hardcoded, self-consistency-asserted), PackageNotFoundError -> unknown"
    requirement: OPS-03
    verification:
      - kind: unit
        ref: "tests/test_health_details.py#test_exact_d29_shape_top_level_and_sub_key_sets"
        status: pass
      - kind: unit
        ref: "tests/test_health_details.py#test_versions_self_consistency_with_importlib_metadata"
        status: pass
      - kind: unit
        ref: "tests/test_health_details.py#test_versions_unknown_on_packagenotfound"
        status: pass
    human_judgment: false
  - id: D3
    description: "last_check wired to the jobs registry and data/market_state.json: ISO equality on os.utime-frozen finished_at/mtime, every data-absence leg answers 200 with the honest null (missing/empty dir, failed-only, other-kind, corrupt json, dotfile registry, missing/unstat-able market_state)"
    requirement: OPS-03
    verification:
      - kind: unit
        ref: "tests/test_health_details.py#test_registry_and_market_state_wired_iso"
        status: pass
      - kind: unit
        ref: "tests/test_health_details.py#test_health_job_null_missing_jobs_dir"
        status: pass
      - kind: unit
        ref: "tests/test_health_details.py#test_market_state_mtime_null_when_stat_fails"
        status: pass
      - kind: unit
        ref: "tests/test_health_details.py#test_no_path_or_token_leak_in_bodies"
        status: pass
    human_judgment: false
  - id: D4
    description: "uptime_seconds() public helper in api/main.py sharing the module-import monotonic anchor; /health behavior byte-unchanged beside the new route (public byte pins survive untouched)"
    verification:
      - kind: unit
        ref: "tests/test_health_details.py#test_uptime_anchored_to_health"
        status: pass
      - kind: unit
        ref: "tests/test_health.py#test_health_body_has_exact_keys_and_json_type"
        status: pass
      - kind: unit
        ref: "tests/test_health_details.py#test_public_health_exact_pins_beside_details"
        status: pass
    human_judgment: false
  - id: D5
    description: "Frozen 04-01 envelope purity: api/errors.py zero diff, zero new raise texts, zero console output in the route module; full-suite regression green (174 passed, 1 skipped) with data/ and logs/ untouched"
    verification:
      - kind: other
        ref: "git diff -- api/errors.py (empty) + python -m pytest -q (174 passed, 1 skipped)"
        status: pass
    human_judgment: false

# Metrics
duration: 6min
completed: 2026-09-05
status: complete
---

# Phase 5 Plan 1: Auth-gated GET /health/details (OPS-03 SC1) Summary

**OPS-03 SC1 delivered: 机密级 GET /health/details with the exact D-29 body {versions, uptime_seconds, last_check} — lazy sys.version/importlib.metadata reads, the shared /health monotonic anchor, registry-sourced newest succeeded health-check ISO, market_state os.stat mtime ISO, every absence leg a 200 with null — on the frozen auth/envelope foundation with the SC2 classification pin in the same commit.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-09-04T16:34:16Z
- **Completed:** 2026-09-04T16:40:00Z
- **Tasks:** 3
- **Files modified:** 4 (2 new + 2 modified)

## Accomplishments

- `api/health.py` — secret-tier route module (private.py twin): `router = APIRouter(dependencies=[Depends(require_api_key)])` with the same dependency-object identity the SC2 audit asserts; GET /health/details assembles the D-29 dict; helpers `_versions()` (importlib.metadata, PackageNotFoundError → "unknown"), `_latest_succeeded_health_check()` (kind == "health-check" AND status == "succeeded", max finished_at, OSError/ValueError-tolerant per jobs.prune), `_iso()` (datetime.fromtimestamp(tz=utc).isoformat()).
- `api/main.py` — public `uptime_seconds()` immediately after the `_START` anchor; `/health` body switched to call it (behavior byte-unchanged — test_health.py pins untouched); two-line `health_router` import + include with the 机密级 router-level-auth comment.
- `tests/test_health_details.py` — 18-test contract suite: gate matrix, exact key sets, ISO equality on frozen values, uptime anchor sharing, full null matrix (6 health_job + 2 market_state variants), fail-closed no-token leg, versions fallback + self-consistency, leak hygiene, public /health pins.
- `tests/test_auth.py` — SC2 audit `expected_secret` gains `/health/details` in the same task (suite goes red the moment a route lands unclassified); module docstring updated: D-11 exemption list is per-path enumeration, /health/details is 机密级 and joins the audit set.
- Full suite: **174 passed, 1 skipped** (measured baseline 156 passed, 1 skipped → +18). `git status --porcelain -- data/ logs/` empty at every gate. `api/errors.py` zero diff.

Example 200 body captured live from the suite (isolated tmp paths, frozen values):

```json
{
  "versions": {
    "python": "3.13.1 (tags/v3.13.1:0671451, Dec  3 2024, 19:06:28) [MSC v.1942 64 bit (AMD64)]",
    "uvicorn": "0.51.0",
    "fastapi": "0.115.14"
  },
  "uptime_seconds": 0,
  "last_check": {
    "health_job": "2026-09-15T08:04:39+00:00",
    "market_state_mtime": "2026-09-15T08:05:00+00:00"
  }
}
```

## Task Commits

Each task was committed atomically (TDD RED → GREEN order per task 1):

1. **Task 1 (tracer, tdd): /health/details slice end-to-end** — three commits:
   - `871d0ed` (test, RED): health-details contract suite — 5 tracer behaviors; red on ModuleNotFoundError: api.health
   - `837fcd7` (test, RED): SC2 audit expected_secret + /health/details — red until the route lands classified
   - `643346a` (feat, GREEN): auth-gated GET /health/details (D-29..D-31) + uptime_seconds anchor — api/health.py + api/main.py; both suites green
2. **Task 2 (auto, tdd): full OPS-03 SC1 matrix** — `6079be0` (test): null legs, fail-closed, versions fallback, leak hygiene, public pins; first run green = no-drift proof (production code from Task 1 already carried the tolerance, Phase 3 precedent)
3. **Task 3 (auto): close-out proofs + SUMMARY** — verified api/errors.py zero diff, no console prints, full suite 174 passed 1 skipped, hygiene clean; this SUMMARY

**Plan metadata commit:** final docs commit (see git log for `docs(05-01): complete auth-gated health-details plan`).

## Files Created/Modified

- `api/health.py` - NEW: 机密级 /health/details route module (router-level require_api_key, D-29 assembly, _versions/_latest_succeeded_health_check/_iso helpers, zero side effects, no console output)
- `api/main.py` - MOD: uptime_seconds() public helper beside _START; /health body calls it; health_router import + include (4 insertions total in the diff)
- `tests/test_health_details.py` - NEW: full OPS-03 SC1 contract suite (18 tests; _isolated autouse fixture, write_token, _seed_registry_job with kind/finished_at, _write_market_state with frozen os.utime)
- `tests/test_auth.py` - MOD: SC2 expected_secret += "/health/details"; docstring D-11/SC2 wording (per-path exemption enumeration, new route 机密级)

## Decisions Made

- All four planner-裁定 [ASSUMED] rows **ACCEPT** (built exactly as flagged; fallbacks not needed):
  1. market_state.json missing/unreadable → `market_state_mtime: null` (never the 503 fallback — the 200-with-null semantics is the endpoint's honest report of absence)
  2. uptime wiring = public `uptime_seconds()` in api/main.py + handler-level lazy import in the route (module-level import of api.main would circular-fail: main imports health before _START exists)
  3. "newest succeeded health-check job" = max `finished_at` among kind == "health-check" + status == "succeeded" registry jsons
  4. ISO output = `datetime.fromtimestamp(value, timezone.utc).isoformat()`; suite freezes values via os.utime and asserts equality against in-test computation of the same expression
- Registry directory single-source: api/health.py holds `DATA_DIR` only; the registry is reached through `api.jobs.jobs_dir()`/`read_job` (LOG_DIR seam on api.jobs). Plan frontmatter's "DATA_DIR/LOG_DIR module attrs" is thus realized as DATA_DIR on health + the jobs module's own LOG_DIR — no unused import, no duplicated path logic.
- `import importlib.metadata` (module attr) rather than `from importlib.metadata import version`: keeps the module-level monkeypatch seam the versions-fallback test relies on.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Non-int finished_at type guard in the registry scan**
- **Found during:** Task 1 (api/health.py implementation, threat model T-05-03 cross-check)
- **Issue:** The literal scan shape (compare `job.get("finished_at")` directly) would 500 on a crafted registry json carrying a non-int finished_at (e.g. string "abc") — `TypeError` is not covered by the `except (OSError, ValueError)` tolerance, violating T-05-03 "crafted/corrupt files must never 5xx"
- **Fix:** `if not isinstance(finished, int) or isinstance(finished, bool): continue` — malformed finished_at fields are skipped like other corrupt content
- **Files modified:** api/health.py
- **Verification:** corrupt-json null leg passes; scan tolerates any malformed field shape
- **Committed in:** 643346a (Task 1 feat commit)

---

**Total deviations:** 1 auto-fixed (1 missing critical — threat-model-mandated hardening)
**Impact on plan:** Fix is a two-line guard inside the planned helper; no scope creep, no API change.

## Issues Encountered

None. Note: the measured baseline at execution start was **156 passed, 1 skipped** (STATE.md's "148 passed 1 skipped" predates later Phase-4 test additions — recorded actuals used throughout).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- OPS-03 SC1 landed with the route contract fully pinned (D-29 body, 401/403 bytes, null legs, versions self-consistency) — 05-02 (log rotation + registry cap) and 05-03 can build on the green 174+1 baseline.
- 05-04's real-machine live gate can verify /health/details against this SUMMARY's example body and the 401/403 envelope bytes.
- End-of-phase review: the four [ASSUMED] rows above are marked ACCEPT — reviewer can flip any single row with a one-line local change if rejected.

## Self-Check: PASSED

- FOUND: .planning/phases/05-recovery-observability-ops-polish/05-01-SUMMARY.md
- FOUND: api/health.py, tests/test_health_details.py
- FOUND (git log): 871d0ed, 643346a, 837fcd7, 6079be0 — all four task commits present on gsd/phase-1-service-skeleton-health-liveness

---
*Phase: 05-recovery-observability-ops-polish*
*Completed: 2026-09-05*
