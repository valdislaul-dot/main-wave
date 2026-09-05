---
phase: 04-exposure-hardening-data-classification
plan: 01
subsystem: api
tags: [fastapi, starlette, error-envelope, machine-readable-code, openapi, exception-handler, wr-02, wr-03]

# Dependency graph
requires:
  - phase: 02-read-only-state-endpoints-defensive-read-layer
    provides: "api/state.py raise-site texts + D-04/D-05 wire contract (byte-verbatim detail, path-free bodies) — envelope non-404 details pass these bytes through unchanged"
  - phase: 03-trigger-runner-job-registry-locks-auth-enforcement
    provides: "api/auth.py + api/actions.py raise sites (401/403/404/409 dual-shape/503 texts + WWW-Authenticate challenge) and the raise-server-exceptions TestClient conventions"
provides:
  - "Unified machine-readable error envelope: every 4xx/5xx renders {\"detail\": ..., \"code\": <frozen code>} (key order detail-then-code) across handler-raised, framework route-miss 404/405, framework 422, and unhandled-500 classes — implemented as app-level exception handlers in api/main.py, zero raise-site edits"
  - "Frozen CODE_BY_DETAIL table in api/errors.py complete for the whole phase (incl. 04-03 private/date raise texts frozen today) with shape-keyed 409 split and http_{status} fallback"
  - "Single 404 copy API-wide (\"Not Found\") with per-site codes; tracebacks server-side only; /openapi.json served publicly (docs_url stays None)"
  - "WR-02 hammer + WR-03 dot-segment pin fidelity fixes in tests/test_state.py"
affects: [04-03 (private endpoints consume frozen rows unknown_private_name/private_data_unavailable), 04-04 (date params consume invalid_date_format/date_not_supported), phase-05 ops polish, verify-work, cloud-panel/consumer integration surface]

actuals:
  tokens: 5576   # chars/4 over the realized diff (22302 chars across api/errors.py+api/main.py+tests/test_errors.py+test_state/test_auth/test_actions)
  tasks: 3
  commits: 4

tech-stack:
  added: []
  patterns:
    - "App-level exception-handler envelope: register StarletteHTTPException / RequestValidationError / Exception keys beside the FastAPI() constructor — MRO dispatch makes one HTTPException key cover raise-site fastapi.HTTPException AND framework 404/405; Exception key routes to ServerErrorMiddleware's 500 path"
    - "Frozen text-keyed code table with http_{status} fallback: later raise-site texts can never produce a malformed body, and the table itself is never appended to (T-04-04)"
    - "Server-truth routing pins: raw-ASGI scope call (no httpx transport) for paths whose routing answer differs under client-side URL normalization"

key-files:
  created:
    - api/errors.py - frozen CODE_BY_DETAIL table + _code_for + three exception handlers
    - tests/test_errors.py - six-behavior envelope contract suite (probe routes registered include_in_schema=False)
  modified:
    - api/main.py - openapi_url enabled + three add_exception_handler lines + imports (boot sequence byte-untouched)
    - tests/test_state.py - 5 envelope pins + WR-02 hammer rewrite + WR-03 raw-ASGI pin
    - tests/test_auth.py - 9 envelope pins + docstring shape update
    - tests/test_actions.py - 11 envelope pins (incl. both 409 whole-body shapes)

key-decisions:
  - "Envelope implemented as app-level handlers + text-keyed table (never editing raise sites): the only place a uniform shape can be enforced without touching api/state.py/api/auth.py/api/actions.py — confirmed the [ASSUMED] MRO dispatch empirically"
  - "404 copy unification scoped to the 404 class exactly: 405 framework detail \"Method Not Allowed\" and all non-404 details pass through byte-unchanged with a code sibling (D-04/D-05 wire contract preserved)"
  - "Code table frozen this plan including 04-03/04-04 future raise texts (unknown private name / private data temporarily unavailable / date must be YYYY-MM-DD or YYYYMMDD / date not supported for this action kind) — later plans never append rows"
  - "[ASSUMED] #2 disproved at runtime: starlette ServerErrorMiddleware re-raises after the 500 handler sends (errors.py L184-187), so default TestClient (raise_server_exceptions=True) propagates the exception instead of returning the body — 500-contract assertions use TestClient(raise_server_exceptions=False), which mirrors the real uvicorn wire (uvicorn swallows the re-raise, client receives the envelope body)"
  - "WR-03: replaced the httpx-collapsed 200 dot-segment pin with a raw-ASGI scope call asserting the real-server 404 — the old 200 was a client-side normalization artifact, never exercised server routing"
  - "WR-02: Barrier(2) + 60ms first tear window (> reader 2x20ms retry budget) makes the stale-fallback branch deterministically exercised; stale_hits >= 1 asserted while all other assertions stay branch-agnostic (zero flake)"

patterns-established:
  - "Error envelope contract: consumers branch on code, never parse prose; detail bytes remain the human-readable D-04/D-05 surface"
  - "Unified-404 class: handler-raised and framework route-miss 404s byte-identical; semantic difference carried per-site in code"
  - "Raw-ASGI scope harness for server-truth routing pins (WR-03 precedent)"
  - "Thread-hammer fidelity: exception capture list + progress counter + barrier-overlap so a concurrency hammer can never pass vacuously"

requirements-completed: [STA-02, SEC-02]

coverage:
  - id: D1
    description: "Machine-readable error envelope on every 4xx/5xx (401 missing_api_key + challenge header, 403 invalid_api_key, 405 method_not_allowed, 422 validation_error, 500 internal_error) with detail-then-code key order"
    requirement: SEC-02
    verification:
      - kind: unit
        ref: "tests/test_errors.py#test_401_403_envelope_shape_and_challenge_header"
        status: pass
      - kind: unit
        ref: "tests/test_errors.py#test_405_422_500_framework_handlers"
        status: pass
      - kind: unit
        ref: "tests/test_errors.py#test_unmapped_text_fallback_code_and_key_order"
        status: pass
    human_judgment: false
  - id: D2
    description: "Unified 404 copy \"Not Found\" API-wide across handler-raised (unknown_state_name / unknown_action_kind / job_not_found) and framework route-miss (not_found) classes, bytes identical; swept pins in all three pre-existing suites"
    verification:
      - kind: unit
        ref: "tests/test_errors.py#test_404_unified_copy_with_per_site_codes"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_state_unknown_names_404_whitelist_only"
        status: pass
      - kind: unit
        ref: "tests/test_auth.py#test_public_exemptions_no_key_needed"
        status: pass
      - kind: unit
        ref: "tests/test_actions.py#test_unknown_kind_404_no_side_effects"
        status: pass
    human_judgment: false
  - id: D3
    description: "409 dual shapes carry shape-keyed codes (already_running / already_running_other_entry) with the object detail byte-identical; frozen fallback code http_404 for unmapped texts"
    verification:
      - kind: unit
        ref: "tests/test_actions.py#test_409_map_hit_object_shape_and_retrigger_after_terminal"
        status: pass
      - kind: unit
        ref: "tests/test_actions.py#test_409_cross_process_holder_object_shape"
        status: pass
    human_judgment: false
  - id: D4
    description: "Unhandled-exception tracebacks stay server-side (stderr, ASCII marker); 500 body fixed internal_error shape, path-free and token-free; /openapi.json served publicly with the full route family"
    requirement: SEC-02
    verification:
      - kind: unit
        ref: "tests/test_errors.py#test_unhandled_traceback_stays_server_side"
        status: pass
      - kind: unit
        ref: "tests/test_errors.py#test_openapi_schema_served_publicly"
        status: pass
    human_judgment: false
  - id: D5
    description: "WR-02 hammer no longer passes vacuously (writer exceptions asserted empty, progress >= 1, stale branch deterministically exercised); WR-03 dot-segment pin asserts the raw-ASGI server-truth 404 with envelope body"
    verification:
      - kind: unit
        ref: "tests/test_state.py#test_state_live_rewrite_zero_5xx_hammer"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_state_unknown_names_404_whitelist_only"
        status: pass
    human_judgment: false

# Metrics
duration: 16min
completed: 2026-09-04
status: complete
---

# Phase 04 Plan 01: Machine-Readable Error Envelope + OpenAPI + P2 Fidelity Fixes Summary

**Every api/ 4xx/5xx now renders {"detail": ..., "code": <frozen machine code>} via app-level handlers (zero raise-site edits), the 404 copy is unified to "Not Found" API-wide with per-site codes, tracebacks stay server-side, /openapi.json is served publicly, and the WR-02/WR-03 test-fidelity defects are closed**

## Performance

- **Duration:** 16 min
- **Started:** 2026-09-03T20:10:14Z
- **Completed:** 2026-09-03T20:26:14Z
- **Tasks:** 3
- **Files modified:** 6 (2 api/ + 4 tests/)

## Accomplishments

- Frozen `CODE_BY_DETAIL` table in api/errors.py — 14 text-keyed rows (401/403, four 404-origin texts + framework "Not Found", 405 "Method Not Allowed", 503 family, 04-03/04-04 private + date texts frozen today) plus shape-keyed 409 split (`already_running` / `already_running_other_entry`); unknown texts fall back to `http_{status}`
- Three app-level handlers in api/main.py beside the FastAPI() constructor: StarletteHTTPException key (MRO-covers fastapi.HTTPException raise sites AND framework route-miss 404 / method-miss 405), RequestValidationError key (422), Exception key (routes to ServerErrorMiddleware -> fixed 500 body, traceback.print_exc to stderr only, ASCII marker)
- Unified 404 copy: exact body bytes `{"detail": "Not Found", "code": "unknown_state_name"}` etc. — detail bytes identical across handler and framework classes; non-404 details byte-identical to their pinned D-04/D-05 texts with only the code sibling added
- openapi_url="/openapi.json" (docs_url/redoc_url stay None); GET /openapi.json is public (200 without a key), schema covers /health, /health/ready, /v1/state/{name}, /v1/actions/{kind}, /v1/jobs/{job_id}
- WR-02 hammer fidelity: writer-thread exceptions captured and asserted empty, per-iteration progress asserted >= 1, Barrier(2) + 60ms first tear window deterministically exercises the x-data-stale fallback branch (stale_hits >= 1), all pre-existing assertions kept branch-agnostic
- WR-03 dot-segment pin: literal path `/v1/state/market_state/../auction_state` now asserted via raw-ASGI scope call to return the real-server 404 envelope (code not_found); the old 200-on-collapsed-path assertion (httpx client-side artifact) is gone

## Final Code Table (api/errors.py CODE_BY_DETAIL, frozen)

| detail text (raise-site byte) | code | class |
|---|---|---|
| `missing API key` | `missing_api_key` | 401 (auth) |
| `invalid API key` | `invalid_api_key` | 403 (auth) |
| `unknown state name` | `unknown_state_name` | 404 (state handler) |
| `unknown action kind` | `unknown_action_kind` | 404 (actions handler) |
| `job not found` | `job_not_found` | 404 (jobs handler) |
| `unknown private name` | `unknown_private_name` | 404 (04-03 raise text, frozen today) |
| `Not Found` | `not_found` | 404 (framework route-miss; the unified copy text — only this row) |
| `Method Not Allowed` | `method_not_allowed` | 405 (framework method-miss, detail passes through unchanged) |
| `state temporarily unavailable` | `state_temporarily_unavailable` | 503 |
| `state file unavailable` | `state_file_unavailable` | 503 |
| `private data temporarily unavailable` | `private_data_unavailable` | 503 (04-03 text, frozen today) |
| `job temporarily unavailable` | `job_temporarily_unavailable` | 503 |
| `date must be YYYY-MM-DD or YYYYMMDD` | `invalid_date_format` | 422 (04-03/04-04 text, frozen today) |
| `date not supported for this action kind` | `date_not_supported` | 400/422 (04-04 text, frozen today) |
| dict detail with `message` + `running_job_id` | `already_running` | 409 shape-keyed |
| dict detail with `message` only | `already_running_other_entry` | 409 shape-keyed |
| any other detail | `http_{status_code}` | fallback |

## Handler Registration (api/main.py)

Pre-edit region: L14 `from fastapi import FastAPI` (imports block), L26 stale comment, L27 `app = FastAPI(title="gogo API", docs_url=None, redoc_url=None, openapi_url=None)` — the L27 wiring region named in 04-PATTERNS. Added exactly:

- imports beside the existing ones: `fastapi.exceptions.RequestValidationError`, `starlette.exceptions.HTTPException as StarletteHTTPException`, the three handlers from `api.errors`
- on the FastAPI() call: `openapi_url=None` -> `openapi_url="/openapi.json"` (docs_url/redoc_url unchanged)
- three `app.add_exception_handler(...)` lines directly after the constructor, before the include_router lines
- L26 comment refreshed (openapi now on; docs interactive UI still off per CLI-only)
- include_router lines, /health, and the whole main() boot sequence byte-untouched

## Task Commits

Each task was committed atomically:

1. **Task 1 (TDD): envelope contract suite + implementation** — `7aa98e1` (test RED, 6 behaviors red for the designed reasons: no code field, openapi disabled) + `b0ec583` (feat GREEN)
2. **Task 2: pin sweep to the code-field envelope** — `aea1a02` (test)
3. **Task 3: WR-02 hammer + WR-03 raw-ASGI pin** — `2ea9acb` (test)

**Plan metadata:** pending final docs commit.

## Files Created/Modified

- `api/errors.py` - frozen code table + `_code_for` + `http_exception_handler` / `validation_error_handler` / `unhandled_exception_handler`; zero import side effects; ASCII-only console text
- `api/main.py` - import lines + openapi_url change + 3 add_exception_handler lines + comment refresh (L27 wiring region)
- `tests/test_errors.py` - 6-test envelope contract suite; three probe routes registered on the shared app (include_in_schema=False); autouse tmp isolation mirroring sibling suites; `client_no_raise` for the 500-path assertions
- `tests/test_state.py` - 5 envelope pins (L102/127/204/225/238 equivalents), WR-02 hammer rewrite (errors/progress/Barrier/60ms window/stale_hits), WR-03 leg (c) replaced by `_asgi_get` raw-ASGI 404 pin, `import asyncio`
- `tests/test_auth.py` - 9 envelope pins + docstring shape update (challenge-header assertions untouched)
- `tests/test_actions.py` - 11 envelope pins incl. both 409 whole-body equality shapes with code siblings; `running_job_id`-not-in-detail and %2F status-only pins untouched

## Swept Pin-Site List

- test_state.py: 404 x3 in whitelist loop (unknown_state_name), 503 state temporarily unavailable x2, 503 state file unavailable x2
- test_auth.py: 401 missing_api_key x2 (POST + GET legs), 403 invalid_api_key x4 (wrong key / env-precedence / fail-closed / query-tamper), 404 unknown_state_name (exemption audit), 401 query-tamper
- test_actions.py: 401, 403, 404 unknown_action_kind x2, 404 unknown_state_name (public-exemptions), 409 already_running whole body, 409 already_running_other_entry whole body (+ not-in-detail), 404 job_not_found x3, 503 job_temporarily_unavailable

## Decisions Made

See key-decisions frontmatter. No user decision was required — the four [ASSUMED] dispatches were resolved from installed-source reading plus empirical probes (all three handler routes confirmed: MRO starlette-key coverage, ServerErrorMiddleware 500 path, openapi rendering).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test fidelity] [ASSUMED] #2 disproved: 500-path contract assertions route through a no-raise TestClient**
- **Found during:** Task 1 GREEN (envelope suite implementation)
- **Issue:** The plan assumed a registered Exception handler makes TestClient return the 500 JSON body. Installed-source reading (starlette/middleware/errors.py L184-187) proved ServerErrorMiddleware **always re-raises** after the handler sends, and starlette/testclient.py L338-340 propagates app exceptions when raise_server_exceptions=True — the default client would raise `RuntimeError: probe-boom-envelope` instead of returning the envelope body, erroring the 500-path tests forever
- **Fix:** 500-path assertions (unhandled-exception legs of two tests) use a module-level `TestClient(app, raise_server_exceptions=False)` — mirrors the real uvicorn wire, where the server swallows the re-raise after logging and the client receives the fixed internal_error body. Contract unchanged: bodies asserted, never raised exceptions
- **Files modified:** tests/test_errors.py (client_no_raise + two request sites)
- **Verification:** 6/6 envelope tests green; full suite green
- **Committed in:** 7aa98e1 (amended into the RED commit so the RED suite file is exactly the committed suite)

**2. [Rule 1 - Correctness] Stale L26 comment contradicted the enabled openapi_url**
- **Found during:** Task 1 GREEN (api/main.py wiring)
- **Issue:** `# docs/openapi 关闭 (discretion)...` described the pre-change state; leaving it would misdocument the new public /openapi.json surface (04-03 SC2 audits it)
- **Fix:** Refreshed the comment to state openapi public-read-only + docs interactive UI off (CLI-only)
- **Files modified:** api/main.py
- **Committed in:** b0ec583

---

**Total deviations:** 2 auto-fixed (both Rule 1)
**Impact on plan:** Both necessary for test correctness and accurate documentation. No production behavior change beyond the plan's contract; no scope creep.

## Issues Encountered

- The plan's three [ASSUMED] dispatch facts were resolved without a runtime fallback being needed: (1) starlette-keyed registration MRO-covers fastapi.HTTPException raise sites and framework 404/405 as predicted; (2) Exception key routes to ServerErrorMiddleware (500 sent, then re-raised for server logging — the re-raise is what broke default TestClient, see deviation 1); (3) /openapi.json rendered cleanly from existing docstrings with zero route edits
- RED phase note: today's pre-envelope route-miss 404s are JSON `{"detail":"Not Found"}` (not plain text), and the framework 405 detail is "Method Not Allowed" (phrase-sourced) — both rows frozen in the table accordingly

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 04-03 (private endpoints) and 04-04 (date params) consume already-frozen table rows — raise sites there need zero api/errors.py changes
- Wire contract for consumers: branch on `code`; 404 vocabulary is one copy with per-site codes; /openapi.json is the self-describing surface
- WR-02/WR-03 fidelity defects closed; hammer and raw-ASGI harness are reusable patterns for future concurrency/routing pins
- Full suite: 107 passed, 1 skipped (101 baseline + 6 envelope tests); `git status --porcelain -- data/ logs/` empty throughout

---
*Phase: 04-exposure-hardening-data-classification*
*Completed: 2026-09-04*

## Self-Check: PASSED

Files verified present: api/errors.py, api/main.py, tests/test_errors.py, tests/test_state.py, tests/test_auth.py, tests/test_actions.py, 04-01-SUMMARY.md. Commits verified in git log: 7aa98e1, b0ec583, aea1a02, 2ea9acb. Full suite 107 passed, 1 skipped; data/ and logs/ untouched.
