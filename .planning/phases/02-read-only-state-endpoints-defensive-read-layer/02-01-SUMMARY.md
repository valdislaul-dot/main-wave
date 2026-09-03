---
phase: 02-read-only-state-endpoints-defensive-read-layer
plan: 01
subsystem: api
tags: [fastapi, read-only-passthrough, defensive-read-layer, verbatim-bytes, staleness-headers, readiness, whitelist, windows-file-handles]

# Dependency graph
requires:
  - phase: 01-service-skeleton-health-liveness
    provides: api/ package (FastAPI app, /health, main() boot sequence, DATA_DIR call-time pattern, test suite conventions with autouse net-block)
provides:
  - "GET /v1/state/{market_state|auction_state|zt_pool_state}: raw file bytes verbatim (CRLF preserved) + X-Data-Mtime / X-Data-Age-S freshness headers; X-Data-Stale: true only on last-good-cache fallback"
  - "STA-03 defensive read layer: binary open→read→fstat→close per attempt, json.loads validate-only gate, decode-error short retry (2 x 20 ms), OSError immediate fallback, per-name in-process last-good cache, cold-cache 503 (never bare 500)"
  - "GET /health/ready: stat-only (isfile + os.access) 200/503 for the three whitelist files, never data age, never open()"
  - "D-03 whitelist: unknown names 404 before any path composition (traversal surface structurally absent); path-free 503 details"
  - "tests/test_state.py: 16-test STA-01/STA-03/HLT-02/SC4 contract suite incl. threaded truncate/atomic-rewrite 0x5xx hammer"
  - "Resident service on 127.0.0.1:8000 running the new code (restarted via gogo-api scheduled task, live-probed)"
affects: [03-triggers (writer atomicization discussion, trigger policy), 04-data-classification-hardening (SEC-02 endpoint classification, cache/whitelist seam), verification]

# Actuals (#2632) — pairs with the plan's `estimate` (42000) to calibrate future estimates.
actuals:
  tokens: 4323    # chars/4 over files actually changed (api/state.py + api/main.py delta + tests/test_state.py)
  tasks: 3
  commits: 3

# Tech tracking
tech-stack:
  added: [none - zero new packages (stdlib os/json/time + existing fastapi/starlette)]
  patterns: [APIRouter + include_router (repo first), HTTPException {"detail": ...} error bodies (repo first), Response(content=bytes, media_type=...), same-handle os.fstat mtime, validate-then-serve json.loads gate, stale-if-error last-good cache, monkeypatch-on-DATA_DIR per-test isolation, injected-reader test seam, threaded rewrite hammer]

key-files:
  created: [api/state.py, tests/test_state.py]
  modified: [api/main.py]

key-decisions:
  - "Followed D-01..D-05 locked decisions verbatim: raw byte passthrough (never re-serialize), same-handle fstat mtime, 3-name whitelist with 404 before path composition, 404-client/503-server error split with path-free details, stale marker only on the fallback path"
  - "get_state carries an injectable reader parameter (default read_state_file) as the deterministic test seam; retry constants pinned retries=2, retry_delay=0.02"
  - "api.main.py changed by exactly two lines (import + include_router after /health); boot sequence, SEC-03 ordering, __main__ guard untouched (diff-verified)"
  - "Zero new packages: stdlib-only read layer on the installed fastapi 0.115.14 / starlette 0.46.2 stack"

patterns-established:
  - "api/state.py module: side-effect-free import, DATA_DIR referenced at call time inside functions only (monkeypatch seam), STATE_FILES/_CACHE/router module globals"
  - "Byte-verbatim contract: binary reads, json.loads validate-and-discard, Response media_type='application/json' (no charset, never FileResponse)"
  - "Windows handle discipline: open→read→fstat→close per attempt, no handle across retry sleeps, /health/ready stat-only"

requirements-completed: [HLT-02, STA-01, STA-03]

# Coverage metadata (#1602) — one entry per shipped deliverable.
coverage:
  - id: D1
    description: "api/state.py module: D-03 whitelist map, defensive read layer, GET /v1/state/{name} + GET /health/ready, registered in api/main.py"
    requirement: STA-01
    verification:
      - kind: unit
        ref: "tests/test_state.py#test_state_fresh_body_verbatim_and_exact_headers"
        status: pass
      - kind: other
        ref: "live E2E probe on port 8018: GET /v1/state/market_state 200 verbatim with integer headers, no stale header (urllib assertion poll)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Verbatim byte passthrough incl. CRLF and UTF-8 Chinese content with exact content-type and X-Data-Mtime/X-Data-Age-S headers"
    requirement: STA-01
    verification:
      - kind: unit
        ref: "tests/test_state.py#test_state_fresh_body_verbatim_and_exact_headers"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_state_all_three_names_served_verbatim"
        status: pass
      - kind: other
        ref: "live byte-identity check on 8018 and on the resident 8000 service: response bytes == data/market_state.json bytes, b'\\r\\n' present"
        status: pass
    human_judgment: false
  - id: D3
    description: "Whitelist enforcement: unknown names 404 with pinned detail before path composition; route-non-match shapes 404; dot-segment aliases resolve into the map; decoy non-whitelisted files never served"
    requirement: STA-01
    verification:
      - kind: unit
        ref: "tests/test_state.py#test_state_unknown_names_404_whitelist_only"
        status: pass
      - kind: other
        ref: "live probe: GET /v1/state/portfolio -> 404 {'detail': 'unknown state name'} on 8018 and 8000"
        status: pass
    human_judgment: false
  - id: D4
    description: "Defensive read layer: decode-retry succeeds and warms cache, persistent decode failure serves last-good as stale with cached mtime, OSError skips retries, cold cache 503 with path-free detail"
    requirement: STA-03
    verification:
      - kind: unit
        ref: "tests/test_state.py#test_get_state_decode_retry_succeeds_and_warms_cache"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_get_state_persistent_decode_failure_warm_cache_returns_stale"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_get_state_oserror_skips_retries"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_get_state_persistent_decode_failure_empty_cache_raises"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_state_persistent_torn_warm_cache_serves_stale_flagged"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_state_persistent_torn_cold_cache_503"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_state_missing_file_503_detail_contains_no_path"
        status: pass
    human_judgment: false
  - id: D5
    description: "0 x 5xx under live concurrent rewrites: truncate-writes and atomic os.replace while ~150 GETs run - all 200, all bodies valid JSON, stale bodies equal last-known-good"
    requirement: STA-03
    verification:
      - kind: integration
        ref: "tests/test_state.py#test_state_live_rewrite_zero_5xx_hammer"
        status: pass
    human_judgment: false
  - id: D6
    description: "GET /health/ready: 200 when all three whitelist files present/readable; 503 on missing or directory-typed entry; ancient mtime still 200 (never data age)"
    requirement: HLT-02
    verification:
      - kind: unit
        ref: "tests/test_state.py#test_ready_all_present_200"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_ready_missing_file_503"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_ready_directory_not_readable_503"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_ready_ancient_mtime_still_200"
        status: pass
      - kind: other
        ref: "live probe on resident service: GET /health/ready -> 200 {'status': 'ready'}"
        status: pass
    human_judgment: false
  - id: D7
    description: "SC4 no-network proof: api/*.py import restriction plus in-suite source scan plus standalone grep audit (empty output)"
    requirement: STA-03
    verification:
      - kind: other
        ref: "standalone grep -nE '(requests|urllib|httpx|aiohttp|socket)(\\.|[[:space:]]*import|import)' api/*.py -> no output"
        status: pass
      - kind: unit
        ref: "tests/test_state.py#test_sc4_source_scan_no_network_tokens"
        status: pass
    human_judgment: false
  - id: D8
    description: "Resident service on 127.0.0.1:8000 restarted onto the new code via the gogo-api scheduled task and left Running; /health untouched (Phase 1 purity)"
    requirement: HLT-02
    verification:
      - kind: other
        ref: "live probes on 8000: /v1/state/market_state byte-identical + integer freshness headers + no stale; /v1/state/portfolio 404; /health/ready 200; /health 200 ok; task State=Running, console.log grew with new uvicorn boot"
        status: pass
    human_judgment: false
  - id: D9
    description: "Real-pipeline 0x5xx observation (end-of-phase human check): poll the three /v1/state/{name} endpoints during the user's next natural pipeline run and confirm 0 x 5xx with valid JSON bodies"
    verification: []
    human_judgment: true
    rationale: "Executor must not trigger the real pipeline itself (Phase 3 owns trigger policy); the observation requires the user's own daily 15:00+ run_pipeline.py or GUI one-key refresh, with polling over its duration. Deterministic twin (hammer test D5) already proves the design."

# Metrics
duration: 9min
completed: 2026-09-03
status: complete
---

# Phase 2 Plan 1: Read-only State Passthrough + Defensive Read Layer Summary

**Raw-byte-verbatim GET /v1/state/{name} for the 3-name whitelist with X-Data-Mtime/X-Data-Age-S freshness headers, a stale-if-error defensive read layer (decode retry + last-good cache), stat-only /health/ready, a 16-test contract suite with a threaded 0x5xx rewrite hammer, and the resident 127.0.0.1:8000 service live on the new code — zero new packages**

## Performance

- **Duration:** 9 min
- **Started:** 2026-09-03T11:56:55Z
- **Completed:** 2026-09-03T12:05:55Z
- **Tasks:** 3
- **Files modified:** 3 (1 created module, 1 modified, 1 created test file)

## Accomplishments
- STA-01/D-01/D-02 wire contract live and tested: served bytes are byte-identical to the pipeline-written files (CRLF and UTF-8 survive — binary reads, json.loads validate-and-discard, never re-serialize), content-type exactly `application/json`, X-Data-Mtime from the very handle read, X-Data-Age-S non-negative, no X-Data-Stale on the fresh path.
- STA-03/D-05 defensive read layer delivered: per-attempt binary open→read→fstat→close (no handle across retry sleeps or streaming), 2 x 20 ms decode-error retries on fresh snapshots, OSError immediate fallback, per-name in-process last-good cache served 200 + `X-Data-Stale: true` with the cached payload's own mtime, cold-cache 503 `{"detail": "state temporarily unavailable"}` — a torn body can never be labeled fresh, never a bare 500.
- D-03/D-04 whitelist + error contract: the fixed 3-name dict lookup runs before any path composition (traversal structurally impossible); unknown route-matching names 404 with the pinned detail; route-non-match shapes 404 before the handler; dot-segment URLs normalize into the whitelist; error details never contain file paths.
- HLT-02 /health/ready: stat-only (isfile + os.access) existence/readability over the same three files, 200 `{"status": "ready"}` / 503 `"state file unavailable"`, never data age (ancient-mtime test), never open().
- SC4 no-network discipline enforced three ways: import restriction, standalone grep audit (empty output, recorded below), in-suite source-scan regression.
- SC2/STA-03 integration proof: the threaded truncate/atomic-rewrite hammer (repo's first threading test) — 150 GETs against both real writer styles, 0 x 5xx, every body valid JSON, stale bodies equal last-known-good.
- Resident service restarted onto the new code via the gogo-api scheduled task and left Running; live probes on 127.0.0.1:8000 all passed.
- Full pytest suite green: 34 passed, 1 skipped (Phase 1's 18 + Phase 2's 16), offline, zero real-data touch.

## Task Commits

Each task was committed atomically:

1. **Task 1: api/state.py defensive read layer + routes, registered, live-probed E2E** - `f388461` (feat)
2. **Task 2: tests/test_state.py STA-01/STA-03/HLT-02/SC4 contract suite** - `7fb7e26` (test)
3. **Task 3: 0x5xx truncate/atomic-rewrite hammer + full-suite gate + SC4 audit + resident-service restart** - `ea2ea7a` (test)

**Plan metadata:** pending (docs: complete plan — next commit)

## Files Created/Modified
- `api/state.py` - New module: D-03 STATE_FILES whitelist, _CACHE last-good slots, router; read_state_file (binary open→read→fstat→close + validate-only json.loads), StateUnavailable, get_state (retry/cache/fallback with injectable reader), get_state_endpoint (GET /v1/state/{name}), ready (GET /health/ready)
- `api/main.py` - Exactly two added lines: `from api.state import router as state_router` and `app.include_router(state_router)` after the /health route; boot sequence, SEC-03 checks, __main__ guard byte-identical otherwise
- `tests/test_state.py` - 16-test contract suite with autouse DATA_DIR→tmp_path + _CACHE-clear fixture (real data/ never touched; git porcelain over data/ unchanged)

## Decisions Made
- All five locked decisions (D-01..D-05) implemented verbatim per CONTEXT — no user re-ask needed (discuss-phase sign-off already recorded).
- Retry constants pinned as planned: `retries=2`, `retry_delay=0.02` (~40 ms worst-case added latency).
- `get_state` exposes `reader=read_state_file` injection seam; unit tests run timer-free with `retry_delay=0`.
- api/main.py kept to the strict two-line change for diff-verifiable purity.
- Zero new packages; stdlib-only read layer (os/json/time) on the installed fastapi/starlette stack.

## Deviations from Plan

None - plan executed exactly as written.

### Auto-fixed Issues

None.

---

**Total deviations:** 0 auto-fixed
**Impact on plan:** None.

## Issues Encountered
- None during execution. One environmental note: the Phase 1 resident service instance (PID 30968) had already been stopped (Ctrl+C in console.log) before Task 1 — port 8000 was free, so Task 3's kill step was a no-op and the scheduled-task restart was clean. All 16 new tests passed on first run; no reds required investigation.

## Real-Pipeline 0x5xx Observation — USER ACTION (end-of-phase human check)

**Status: handed off — outcome slot open (recorded 2026-09-03).**

The deterministic in-suite twin (hammer test) passes; the real-writer confirmation requires the user's next natural pipeline run. **The executor must NOT trigger the real pipeline itself (Phase 3 owns trigger policy).**

**Action:** during the next natural pipeline run (daily 15:00+ `run_pipeline.py`, a GUI one-key refresh, or any run rewriting `data/market_state.json` / `data/auction_state.json` / `data/zt_pool_state.json`), poll all three endpoints for the run's duration and confirm **0 x 5xx** with every body valid JSON:

```bash
for i in $(seq 1 200); do
  for n in market_state auction_state zt_pool_state; do
    python -c "import urllib.request,json,sys; r=urllib.request.urlopen('http://127.0.0.1:8000/v1/state/$n'); json.loads(r.read()); sys.exit(0 if r.status==200 else 1)"
  done
  sleep 0.2
done
```

**Caveat:** the observation counts from the first successful read onward (cache warm); a cold-start 503 in the very first write-window collision after a service restart is the documented residual (RESEARCH open question 2), not a failure. Record the observed outcome (passed / what was observed instead) here for end-of-phase verification harvest.

## SC4 Audit Evidence (recorded)

Standalone command run from the repo root after all commits: `grep -nE "(requests|urllib|httpx|aiohttp|socket)(\.|[[:space:]]*import|import)" api/*.py` → **no output** ("SC4 audit clean"). In-suite twin `test_sc4_source_scan_no_network_tokens` passes.

## Live-Probe Results (recorded)

- Port 8018 E2E (Task 1): fresh 200 verbatim (CRLF present, byte-identical), content-type `application/json`, integer x-data-mtime/x-data-age-s, no x-data-stale; `/v1/state/portfolio` 404 with pinned detail; `/health/ready` 200 ready; `/health` 200 ok; probe process terminated, port released.
- Resident service 127.0.0.1:8000 (Task 3): `/v1/state/market_state` body byte-identical to `data/market_state.json`, integer freshness headers, no stale header; `/v1/state/portfolio` 404 pinned detail; `/health/ready` 200 ready; `/health` 200 ok. Scheduled task `gogo-api` State=Running, LastTaskResult=267009 (SCHED_S_TASK_RUNNING), console.log grew 13→16 lines with the new boot (uvicorn on 127.0.0.1:8000, PID 20184). **Service left running.**

## Next Phase Readiness
- Phase 2 scope fully delivered on the Phase 1 api/ package; ready for `/gsd-verify-work` after the real-pipeline observation is recorded.
- Phase 3 (triggers/trigger runner) builds on this module's whitelist/cache seam and owns the pipeline-run trigger policy; Phase 4 (STA-02/SEC-02) extends the same STATE_FILES map under the data-classification policy.
- No blockers; requirements HLT-02, STA-01, STA-03 marked complete in REQUIREMENTS.md.

---
*Phase: 02-read-only-state-endpoints-defensive-read-layer*
*Completed: 2026-09-03*

## Self-Check: PASSED

- FOUND: api/state.py, tests/test_state.py, 02-01-SUMMARY.md
- FOUND: commits f388461 (feat), 7fb7e26 (test), ea2ea7a (test)
