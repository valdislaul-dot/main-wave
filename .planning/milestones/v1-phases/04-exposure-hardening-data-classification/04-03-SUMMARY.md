---
phase: 04-exposure-hardening-data-classification
plan: 03
subsystem: api
tags: [token-gate, private-namespace, raw-passthrough, candidates, tdd, sc2-audit]

# Dependency graph
requires:
  - phase: 02-read-only-state-endpoints-defensive-read-layer
    provides: "Phase 2 defensive read layer + D-01..D-05 signed wire contract (raw passthrough, same-handle fstat mtime, retry/cache/stale semantics, X-Data-* headers) — 04-03 builds get_private as the documented twin of get_state and reuses read_state_file/StateUnavailable verbatim"
  - phase: 04-exposure-hardening-data-classification (04-02)
    provides: "Ledger write-side atomicity (D-04..D-06 tmp+os.replace) — the private reader's stale-fallback contract rests on D-04's target-keeps-old-content: a torn ledger can never be served as fresh; journal/portfolio files are atomic ledger files"

provides:
  - "Token-gated 机密级 read surface GET /v1/private/{name} (portfolio/journal/candidates) in an isolated /v1/private/* namespace (SEC-02, D-13): router-level require_api_key (same dependency object as actions/jobs), whitelist-before-compose gates (404 unknown name / 422 invalid date / 503 unavailable, frozen 04-01 envelope codes), raw byte-verbatim passthrough with X-Data-Mtime/X-Data-Age-S and stale-flagged fallback"
  - "tests/test_private.py STA-02/SEC-02 contract suite (19 tests) + SC2 route-by-route classification audit and private leak-extension legs in tests/test_auth.py (3 tests extended + 1 new)"

affects: [04-07 (real-machine live gate exercises /v1/private on the atomic ledgers), phase-05 ops polish (auth policy consolidation)]

actuals:
  tokens: 9763   # chars/4 over the realized diff (39,051 chars across api/private.py + api/main.py + tests/test_private.py + tests/test_auth.py)
  tasks: 3
  commits: 4

tech-stack:
  added: []
  patterns:
    - "Router-level Depends(require_api_key) on a dedicated APIRouter -> dependency propagates into every route.dependencies with .dependency identity — the SC2 audit asserts `d.dependency is require_api_key`, never status-code/text reverse-inference"
    - "Documented twin module (get_private mirrors api/state.py get_state: retries=2 on (ValueError, UnicodeDecodeError) only, OSError breaks immediately, warm-cache stale fallback keeps body+mtime version-unified, cold cache -> StateUnavailable) — the state.py signature core is NOT refactored to take a directory argument (04-PATTERNS discretion)"
    - "Raw Response(content=raw, media_type='application/json') for byte passthrough — no charset, no FileResponse (held handles would block pipeline os.replace on Windows)"

key-files:
  created:
    - api/private.py - 机密级私密读端点: PRIVATE_FILES whitelist + candidates rule + _valid_date gate + get_private twin + endpoint (185 lines, module docstring documents D-13..D-16)
    - tests/test_private.py - STA-02/SEC-02 contract suite, 19 tests: gate matrix, byte-verbatim headers, SC1 public-tier untouched, candidates semantics, decoy guards, torn-window stale/cold, injected-reader units
  modified:
    - api/main.py - exactly two lines: import private_router + include_router after state_router (04-01 baseline + 2)
    - tests/test_auth.py - fixture patches api.private.LOG_DIR + clears _CACHE; exemptions test closed-list leg; leak audit extended over all /v1/private shapes; new SC2 audit test (+99/-4)

key-decisions:
  - "?date= is candidates-only semantics: legal dates against portfolio/journal are ignored and serve the fixed file (fixed files use the (name, None) cache slot); compact YYYYMMDD normalizes to dashed before filename composition"
  - "Date gate = whitelist regex + generic month 1-12 / day 1-31 semantic range (so 2026-13-99 -> 422); per-calendar validity (e.g. 2026-02-31) is explicitly NOT in whitelist semantics — 'missing file' then answers 503, matching plan Task 2's gate text"
  - "Candidates selection rule mirrors morning_check.py:11-18 by rule only (startswith candidates_ AND NOT candidates_v*, sort by filename date part, newest) — the endpoint never imports or reruns script logic; file bytes still go through read_state_file"
  - "Dot-segment literal paths (/v1/private/../portfolio) cannot route-match the 3-segment {name} pattern — framework 404 (not_found envelope) fires before any handler, the true server answer pinned via raw-ASGI scope call (WR-03 family); httpx collapses '..' pre-transport so TestClient answers are client artifacts, not server truth"

patterns-established:
  - "Whitelist-before-compose gate ordering: unknown name 404 beats invalid date 422 (name gate first); auth dependency beats both (no-key on unknown name -> 401, whitelist membership never leaks to unauthenticated callers)"
  - "Decoy guard: whitelist-out files that really exist under the served directory are seeded in tests and asserted unreachable (body never equals decoy bytes, str(tmp_path) and backslash never appear in error bodies)"
  - "Torn-window determinism: injected reader units (retry_delay=0, fake reader) pin the twin semantics at function level; HTTP-level legs pin the wire behavior (stale-flagged 200 with cached mtime, cold 503 envelope, never bare 500)"

requirements-completed: [STA-02, SEC-02]

coverage:
  - id: D1
    description: "GET /v1/private/{portfolio,journal,candidates} 机密级 token-gated raw passthrough with X-Data-Mtime/X-Data-Age-S; whitelist-before-compose gates in frozen envelopes; candidates D-14 semantics; torn-window stale/503 (D-05 twin semantics)"
    requirement: STA-02
    verification:
      - kind: unit
        ref: "tests/test_private.py#test_gate_matrix_no_key_401_wrong_key_403_valid_200"
        status: pass
      - kind: unit
        ref: "tests/test_private.py#test_raw_bytes_verbatim_and_exact_fresh_headers"
        status: pass
      - kind: unit
        ref: "tests/test_private.py#test_candidates_no_param_serves_newest_excluding_legacy"
        status: pass
      - kind: unit
        ref: "tests/test_private.py#test_candidates_invalid_date_422_missing_file_503"
        status: pass
      - kind: unit
        ref: "tests/test_private.py#test_get_private_persistent_decode_warm_cache_stale"
        status: pass
      - kind: unit
        ref: "tests/test_private.py#test_private_torn_file_warm_cache_serves_stale_flagged"
        status: pass
      - kind: unit
        ref: "python -m pytest -q (131 passed, 1 skipped — full-suite regression gate)"
        status: pass
    human_judgment: false
  - id: D2
    description: "SC2 route-by-route classification audit: every APIRoute classified secret (require_api_key identity present) or public (absent), set-equality non-vacuous over real routes, unclassified routes fail; /probe/* infra and /openapi.json framework route carved with shape assertions"
    requirement: SEC-02
    verification:
      - kind: unit
        ref: "tests/test_auth.py#test_sc2_route_by_route_classification_audit"
        status: pass
      - kind: unit
        ref: "tests/test_auth.py#test_public_exemptions_no_key_needed (closed-list leg: /v1/private/portfolio no-key -> 401)"
        status: pass
      - kind: unit
        ref: "tests/test_auth.py#test_token_never_leaks_to_log_env_or_bodies (all /v1/private response shapes byte-audited)"
        status: pass
    human_judgment: false
  - id: D3
    description: "Suite data isolation — real logs//data/ never touched; decoy/error bodies never contain paths or token bytes (SC3)"
    requirement: SEC-02
    verification:
      - kind: unit
        ref: "git status --porcelain -- data/ logs/ (empty after every task stage)"
        status: pass
      - kind: unit
        ref: "tests/test_private.py#test_unknown_names_404_decoy_unreachable_no_paths"
        status: pass
      - kind: unit
        ref: "tests/test_private.py RED run (1 error during collection — ModuleNotFoundError api.private, designed TDD evidence)"
        status: pass
    human_judgment: false

# Metrics
duration: 14min
completed: 2026-09-04
status: complete
---

# Phase 04 Plan 03: Private /v1/private/* Token-Gated Read Surface Summary

**The 机密级 data tier (portfolio/journal/candidates) now has an isolated token-gated read surface — GET /v1/private/{name} with router-level require_api_key, whitelist-before-compose gates in the frozen 04-01 envelope codes, raw byte-verbatim passthrough with X-Data-Mtime/X-Data-Age-S freshness headers and a D-05 stale-flagged fallback — delivered TDD (RED import-error proof, then GREEN), extended into the full STA-02 matrix (candidates D-14 semantics, decoy guards, torn-window units), and pinned by an SC2 route-by-route classification audit that fails on any future unclassified route**

## Performance

- **Duration:** 14 min (window from 04-02 completion 04:32:28+08:00 to last task commit 04:47:00+08:00)
- **Started:** 2026-09-04 (after 04-02 close)
- **Completed:** 2026-09-04
- **Tasks:** 3 (1 tracer TDD RED+GREEN, 2 test-matrix auto)
- **Files modified:** 4 (1 api/ created + 1 api/ two-line + 2 tests/)

## Accomplishments

- **TDD RED evidence (Task 1):** tests/test_private.py ran red against the absent module — `ModuleNotFoundError: No module named 'api.private'` (1 error during collection) — the designed proof that the contract suite exists before any implementation. GREEN then built api/private.py + the two-line api/main.py include, 4/4 tracer tests passing. The tracer feedback gate (#3299) then re-ran the automated verify end-to-end: file suite 4 passed, hygiene empty — verified, expansion proceeds.
- **STA-02 matrix (Task 2) green on first run — zero drift:** the full matrix (candidates selection incl. candidates_v* legacy decoys, both date formats, 422/503 error legs, decoy/unreachability guards, injected-reader torn-window units) passed 19/19 against the Task 1 implementation without a single production change — the 03-02 no-drift precedent: production code preceded the suite, first-run green proves the matrix behaviors were already implemented correctly.
- **Gate ordering pinned:** unknown name 404 beats invalid date 422 (whitelist-before-compose); auth dependency beats both — no-key on an unknown name answers 401, so whitelist membership never leaks to unauthenticated callers.
- **Candidates semantics (D-14):** no `?date=` serves the newest `candidates_*.json` excluding `candidates_v*` legacy (rule mirror of morning_check.py:11-18, endpoint never runs script logic); `?date=YYYY-MM-DD` and `?date=YYYYMMDD` normalize to the same exact file with its real mtime/age headers; well-formed-but-missing -> 503; empty logs/ -> 503.
- **Torn-window contract (D-05 twin):** warm cache serves stale-flagged 200 with the cached body and cached mtime (version-unified); cold cache answers the 503 envelope, never a bare 500; injected-reader units pin retries=2 on (ValueError, UnicodeDecodeError) only, OSError breaks immediately (no retry), success warms the (name, date) slot.
- **SC2 audit (Task 3):** route-by-route classification with dependency identity (`d.dependency is require_api_key`), set-equality non-vacuity over the six real routes, hard failure on unclassified routes, /probe/* test-infra and /openapi.json framework route carved with shape assertions (probe absence tolerated when the file runs alone). Exemption list closed: /v1/private/portfolio without a key -> 401.
- **Leak audit extended:** every /v1/private response shape (200 verbatim bytes for portfolio/candidates, 401/403/404/422/503 error bodies) byte-audited against the secret token; journal deliberately absent for the cold-503 leg.
- **Full-suite regression:** 131 passed, 1 skipped in 12.95s (04-02 baseline 111 + 20 new); `git status --porcelain -- data/ logs/` empty after every stage.

## Wire Contract (GET /v1/private/{name})

| Case | Status | Envelope (04-01 frozen) |
|------|--------|--------------------------|
| No X-API-Key | 401 | {"detail": "missing API key", "code": "missing_api_key"} + `WWW-Authenticate: ApiKey` |
| Wrong key | 403 | {"detail": "invalid API key", "code": "invalid_api_key"} (no challenge) |
| portfolio/journal/candidates, fresh | 200 | raw bytes verbatim; content-type application/json (no charset); X-Data-Mtime (same-handle fstat), X-Data-Age-S (clamped ≥0); no X-Data-Stale |
| Torn file, warm cache | 200 | body = last-successful bytes, X-Data-Mtime = cached mtime, `X-Data-Stale: true` |
| Name not in whitelist | 404 | {"detail": "Not Found", "code": "unknown_private_name"} (never composes a path) |
| ?date= malformed / month-day out of range | 422 | {"detail": "date must be YYYY-MM-DD or YYYYMMDD", "code": "invalid_date_format"} |
| File missing / unreadable / cold cache | 503 | {"detail": "private data temporarily unavailable", "code": "private_data_unavailable"} |
| Dot-segment literal (../) | 404 | framework {"detail": "Not Found", "code": "not_found"} — {name} cannot cross segments, handler never runs |

Error bodies never contain paths (no tmp_path, no backslash); the 200 body is the exact file byte stream (CRLF/中文 verbatim, never re-serialized).

## get_private vs get_state (documented twin, not a refactor)

Same retry policy (ValueError/UnicodeDecodeError x2, OSError immediate break), same stale/cold fallback shape, same read_state_file primitive — differing only in target LOG_DIR and the (name[, date]) cache slot keying. api/state.py's signature core was deliberately NOT refactored to accept a directory parameter (04-PATTERNS discretion: twin duplication risk < touching a signed module); api/state.py received zero code changes this plan.

## Route Inventory Audited (SC2)

- **Secret (require_api_key identity present):** `/v1/private/{name}`, `/v1/actions/{kind}`, `/v1/jobs/{job_id}`
- **Public (identity absent):** `/health`, `/health/ready`, `/v1/state/{name}`
- **Framework/infra:** `/openapi.json` (pure starlette Route — asserted the only one); `/probe/*` (test_errors.py registration, include_in_schema=False)

## Task Commits

Each task was committed atomically:

1. **Task 1 RED (tracer, tdd): private read contract suite** — `27f0ca9` (test; collection error by design — module absent)
2. **Task 1 GREEN (tracer, tdd): token-gated /v1/private read surface** — `443b9e8` (feat; api/private.py + api/main.py +2 lines; 4/4 green)
3. **Task 2: full STA-02 private matrix** — `13fe27a` (test; 19/19 green first run — no-drift proof)
4. **Task 3: SC2 route-by-route classification audit + private leak extension** — `c95880b` (test; 131 passed full suite)

**Plan metadata:** pending final docs commit.

## Files Created/Modified

- `api/private.py` - created; PRIVATE_FILES whitelist (portfolio→portfolio.json, journal→trading_journal.json), _DATE_RE + month/day semantic gate, _resolve_filename/_latest_candidates_file (candidates D-14 rule), get_private twin (injectable reader seam, retries=2/retry_delay=0.02), endpoint returning raw Response with X-Data-* headers; module docstring documents D-13..D-16, import discipline (no network imports, SC4), twin-documentation of get_state
- `api/main.py` - modified; exactly two lines (import private_router after actions_router import; include_router(private_router) after state_router) — Phase 1 /health purity and SEC-03 boot ordering untouched
- `tests/test_private.py` - created; 19 tests in five sections (gate matrix, raw headers, SC1 public tier, candidates semantics, whitelist/decoys/torn-window, injected-reader units); autouse fixture patches api.private.LOG_DIR + api.auth/api.state DATA_DIR to tmp_path subtree, clears both caches, write_token helper; _asgi_get raw-scope helper (WR-03 family)
- `tests/test_auth.py` - modified; fixture gains api.private.LOG_DIR patch + _CACHE clear; exemptions test gains closed-list leg; leak audit extended over all /v1/private shapes; new SC2 audit test

## Decisions Made

See key-decisions frontmatter. No user decision was required — no checkpoints in this plan; all must-have truths verified by the suite:
- whitelist gate precedes every path composition (Truth 1) — 404/422/503 order pins + decoy guards
- bytes verbatim with exact headers, stale only on fallback (Truth 2) — byte pins + header pins
- candidates rule = script rule mirror (Truth 3) — latest/legacy/date-format tests
- cold/unreadable never bare 500 (Truth 4) — torn cold-503 legs + injected-reader raises
- /v1/private/* isolated namespace, no public leakage (Truth 5) — SC1 untouched test + SC2 audit
- suite never touches real logs//data/ (Truth 6) — hygiene gate empty after every stage

## Deviations from Plan

None in implementation — the plan executed exactly as written; api/private.py satisfied the full matrix on first run. Two test-side notes recorded (both truth-pinning, no production impact):

1. **Dot-segment expectation refined to server truth (Rule 3 family, /probe WR-03 precedent):** the plan expected 404 unknown_private_name for `/v1/private/../portfolio`, but the literal path cannot route-match the 3-segment `{name}` pattern — starlette answers framework 404 (code not_found) before any handler, and httpx collapses `..` pre-transport so TestClient answers are client artifacts. The test pins the raw-ASGI scope truth (404, zero handler runs, envelope not_found) — the functional guarantee (404 before any path composition, whitelist never sees the traversal) is identical and stronger-pinned.
2. **Generic month/day gate scope:** the plan's gate text ("month 1-12 / day 1-31 semantic check") is implemented as the generic range; per-calendar validity (e.g. 2026-02-31) is out of whitelist semantics and answers 503 as a missing file. Test list asserts the generic-range boundaries (13月/00月/00日 -> 422) with a code comment naming the non-goal.

## Issues Encountered

- **ModuleNotFoundError during RED (designed, not a defect):** the Task 1 tracer suite ran against the not-yet-existing api/private.py — this IS the RED evidence the plan's TDD gate requires; GREEN implementation resolved it to 4/4.
- Two test-authoring corrections caught before running (test-shape bugs, not product bugs): `2026-02-31` was initially in the 422 list (would 503 under the generic-range gate) and `..` as a TestClient path (httpx collapses it) — both fixed in-file before the suite ran; the committed suite passed first run.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **04-07 real-machine live gate can exercise /v1/private against the atomic ledgers** (04-02 write side + this read side: a torn ledger can never be served as fresh, and the warm-cache stale fallback is the documented degradation path)
- **SC2 drift guard is permanent:** any future route added outside the secret/public sets fails the audit — new tiers must extend the classification explicitly
- Full suite: 131 passed, 1 skipped; `git status --porcelain -- data/ logs/` empty throughout

---
*Phase: 04-exposure-hardening-data-classification*
*Completed: 2026-09-04*

## Self-Check: PASSED

Files verified present: api/private.py (private read endpoint, 185 lines), tests/test_private.py (19 tests), tests/test_auth.py (SC2 audit + leak extension), .planning/phases/04-exposure-hardening-data-classification/04-03-SUMMARY.md. Commits verified in git log: 27f0ca9 (RED), 443b9e8 (GREEN feat), 13fe27a (STA-02 matrix), c95880b (SC2 audit). Full suite 131 passed, 1 skipped; data/ and logs/ untouched (hygiene empty after every stage).
