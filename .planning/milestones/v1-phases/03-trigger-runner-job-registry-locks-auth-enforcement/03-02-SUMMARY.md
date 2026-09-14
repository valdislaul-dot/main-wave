---
phase: 03-trigger-runner-job-registry-locks-auth-enforcement
plan: 02
subsystem: api
tags: [auth, x-api-key, fastapi-dependency, trigger-router, job-registry, hmac]

# Dependency graph
requires:
  - phase: 03-01
    provides: "api/jobs.py durable registry + spawn governance (locks_dir/is_running/start_job/read_job/reload_registry, call-time path seams) and scripts/daily/job_lock.py shared single-flight lock — consumed verbatim by api/actions.py"
provides:
  - "Protected HTTP trigger/job surface: api/auth.py require_api_key (router-level, D-10/D-11), api/actions.py (POST /v1/actions/{kind} 202/404/409, GET /v1/jobs/{job_id} 200/404/503, KIND_CMDS D-09 map), api/main.py three-change-site registration + reload_registry boot call"
  - "SEC-01 contract suite (tests/test_auth.py, 8 tests) + ACT-01/02/03 matrix (tests/test_actions.py, 13 tests) — SC1/SC2/SC4 proven in-suite"
affects: [03-03 gui-lock (auth contract consumers), 03-04 live smoke, Phase 4 SEC-02 data-classification (exemption list is documented surface)]

# Actuals (#2632)
actuals:
  tokens: 9528    # chars/4 over realized diff (38,114 chars: 38,036 added / 78 deleted)
  tasks: 3
  commits: 4      # +1 docs metadata commit

tech-stack:
  added: [hmac.compare_digest (request auth), fastapi APIRouter dependencies=[Depends(...)]]
  patterns: ["router-level dependency for structural exemption (never middleware)", "request-only dependency signature — no optional params (no query-param injection)", "call-time module-attr path resolution (DATA_DIR/SCRIPTS_DIR monkeypatch seams)", "fixed-map dispatch: kind -> KIND_CMDS lookup, 404 before any side effect", "accept-time snapshot return from thread-starting call (202 body can't race the worker)"]

key-files:
  created:
    - api/auth.py
    - api/actions.py
    - tests/test_auth.py
    - tests/test_actions.py
  modified:
    - api/main.py
    - api/jobs.py

key-decisions:
  - "start_job must return an accept-time dict(job) snapshot, not the live dict: the worker thread mutates the same dict microseconds after Thread.start, so a live reference lets the 202 body race to running/succeeded against the pinned {status: pending} contract (Rule 1, empirical)"
  - "409 detail object shapes delivered as designed (Open-question 1 resolution): map-hit carries running_job_id; OS-lock-only holder carries no job_id key"
  - "%2F-encoded traversal ids are answered 404 by Starlette's route layer before the handler (uvicorn/httpx decode %2F to literal slashes, {job_id} cannot span segments) — the same gate one layer earlier: 404, zero file access, never 500; handler-level ^[0-9a-f]{32}$ gate pinned for all slash-free malformed ids"
  - "Task 2's tdd RED was structurally satisfied by Task 1: the SEC-01 suite's first run was green because production existed — any red would have meant implementation drift (fix production, never weaken the test)"

patterns-established:
  - "Pattern: auth gate as router-level dependency (actions router only) — /health family and /v1/state stay structurally public; key resolved fresh per request via Phase 1 read_token chain; no sessions, no caches, no shared auth state"
  - "Pattern: spawn command = pure arg-list from KIND_CMDS constants; request body never parsed/echoed/logged — user input structurally cannot reach argv"

requirements-completed: [ACT-01, ACT-02, ACT-03, SEC-01]

coverage:
  - id: D1
    description: "api/auth.py require_api_key(request) -> str: 401 missing API key + WWW-Authenticate: ApiKey / 403 invalid API key, hmac.compare_digest, read_token reuse (env GOGO_API_TOKEN first, data/api_token.txt second), call-time DATA_DIR token path, request-only signature, fail-closed 403"
    requirement: SEC-01
    verification:
      - kind: unit
        ref: "tests/test_auth.py#test_missing_key_401_post_and_get"
        status: pass
      - kind: unit
        ref: "tests/test_auth.py#test_wrong_key_403_without_challenge"
        status: pass
      - kind: unit
        ref: "tests/test_auth.py#test_env_token_precedence_over_file"
        status: pass
      - kind: unit
        ref: "tests/test_auth.py#test_fail_closed_when_no_token_configured"
        status: pass
      - kind: unit
        ref: "tests/test_auth.py#test_query_param_tamper_cannot_alter_gate"
        status: pass
    human_judgment: false
  - id: D2
    description: "api/actions.py protected router: KIND_CMDS D-09 four-command map, _cmd_for pure arg-list builder, trigger_action 202/404/409 (dual object shapes, whitelist gate before any side effect), get_job ^[0-9a-f]{32}$ gate/404/503/200"
    requirement: ACT-01
    verification:
      - kind: integration
        ref: "tests/test_actions.py#test_all_four_kinds_spawn_fixed_commands"
        status: pass
      - kind: integration
        ref: "tests/test_actions.py#test_trigger_pipeline_lifecycle_to_succeeded"
        status: pass
      - kind: integration
        ref: "tests/test_actions.py#test_409_map_hit_object_shape_and_retrigger_after_terminal"
        status: pass
      - kind: integration
        ref: "tests/test_actions.py#test_409_cross_process_holder_object_shape"
        status: pass
      - kind: integration
        ref: "tests/test_actions.py#test_404_and_503_edges_no_side_effects"
        status: pass
    human_judgment: false
  - id: D3
    description: "ACT-02 lifecycle contract via GET /v1/jobs/{job_id}: pending -> running(+pid) -> succeeded(exit 0)/failed(non-zero exit_code), log_path exposed, UTF-8 emoji log bytes, D-09 argv through the real map"
    requirement: ACT-02
    verification:
      - kind: integration
        ref: "tests/test_actions.py#test_trigger_pipeline_lifecycle_to_succeeded"
        status: pass
      - kind: integration
        ref: "tests/test_actions.py#test_failed_exit_code_surfaces_via_get"
        status: pass
    human_judgment: false
  - id: D4
    description: "SEC-01 key hygiene pinned: token byte absent from job log bytes, child env dump (GOGO_API_TOKEN pop), and every response body; zero registry/lock side effects on 401/403/404"
    requirement: SEC-01
    verification:
      - kind: integration
        ref: "tests/test_auth.py#test_token_never_leaks_to_log_env_or_bodies"
        status: pass
      - kind: unit
        ref: "tests/test_auth.py#test_no_spawn_on_rejection"
        status: pass
    human_judgment: false
  - id: D5
    description: "Public exemption list (D-11): /health, /health/ready, GET /v1/state/{name} answer without a key; unknown state name gets the state router's own 404"
    requirement: SEC-01
    verification:
      - kind: integration
        ref: "tests/test_actions.py#test_public_endpoints_unguarded"
        status: pass
      - kind: integration
        ref: "tests/test_auth.py#test_public_exemptions_no_key_needed"
        status: pass
    human_judgment: false
  - id: D6
    description: "api/main.py three-change-site registration + jobs.reload_registry() boot call placed after the SEC-03/token block and before uvicorn.run (Phase 1 boot ordering byte-for-byte untouched, diff-auditable)"
    verification:
      - kind: other
        ref: "git diff audit 5ce3782..HEAD -- api/main.py: exactly +2 import lines, +1 include_router after state include, +1 reload_registry call between the token block and import uvicorn"
        status: pass
    human_judgment: true
    rationale: "main() 不在套件中执行 (模块级 TestClient(app) 无 boot); reload_registry 行为由 tests/test_jobs.py 单元钉死 (03-01), main() 内调用点位置由 diff 审计确认; 真机 boot smoke 归 03-04"
  - id: D7
    description: "api/jobs.py start_job accept-time snapshot (Rule 1): 202 body deterministically {status: pending}; worker's live dict mutations never race the response"
    verification:
      - kind: integration
        ref: "tests/test_actions.py#test_trigger_pipeline_lifecycle_to_succeeded (202 body pending pin)"
        status: pass
    human_judgment: false
  - id: D8
    description: "Full-suite regression gate + data//logs/ hygiene: python -m pytest -q green across 3 consecutive runs; git status --porcelain -- data/ logs/ shows only pre-existing user pipeline entries"
    verification:
      - kind: other
        ref: "python -m pytest -q -> 92 passed, 1 skipped (x3 runs, 12.2-12.7s each)"
        status: pass
    human_judgment: false

duration: 12min
completed: 2026-09-04
status: complete
---

# Phase 03 Plan 02: X-API-Key gate + protected trigger/job HTTP surface — Summary

Protected HTTP surface delivered on the 03-01 execution core: `api/auth.py` request-only `require_api_key` dependency (401 missing + `WWW-Authenticate: ApiKey` / 403 wrong, `hmac.compare_digest`, Phase 1 `read_token` chain reuse, fail-closed no-token) gating `api/actions.py`'s router — `POST /v1/actions/{kind}` → 202 `{job_id, kind, status: pending}` immediately / 404 unknown kind before any side effect / 409 dual object shapes (map-hit with `running_job_id`, OS-lock-only holder without) — and `GET /v1/jobs/{job_id}` → 200 full record / 404 / 503. All four kinds spawn their exact D-09 fixed commands (arg-list, no shell, request body never parsed). `api/main.py` gained exactly three change-sites incl. the `jobs.reload_registry()` boot call after the SEC-03 token block; full suite 92 passed / 1 skipped across 3 consecutive runs with data/ and logs/ untouched. SC1/SC2/SC4 proven in-suite.

## Performance
- Duration: 12 min (2026-09-03T17:17:10Z -> 17:29Z) / Tasks: 3 (1 tracer TDD + 2 auto) / Commits: 4 + 1 docs metadata
- Files modified: 6 (3 new api/test modules pair-wise, api/main.py 3 change-sites, api/jobs.py 1-line semantic fix)
- Full suite: 92 passed, 1 skipped — 3 consecutive green runs (was 71/1 after 03-01; +21 new tests: 13 actions + 8 auth)

## Accomplishments
- **HTTP contract as built** (pinned byte strings):
  - `POST /v1/actions/{kind}` (X-API-Key required): **202** `{"job_id": "<32-hex>", "kind": "<kind>", "status": "pending"}` | **404** `{"detail": "unknown action kind"}` | **409** `{"detail": {"message": "<kind> already running", "running_job_id": "<32-hex>"}}` (in-memory claim) or `{"detail": {"message": "<kind> already running (another entry point)"}}` (OS lock held by GUI/manual — no `running_job_id` key) | **401** `{"detail": "missing API key"}` + `WWW-Authenticate: ApiKey` | **403** `{"detail": "invalid API key"}` (no challenge header on 403).
  - `GET /v1/jobs/{job_id}` (X-API-Key required): **200** full registry record (status/pid/exit_code/log_path/cmd/timestamps) | **404** `{"detail": "job not found"}` (unknown or non-`^[0-9a-f]{32}$` id — gate before any path join) | **503** `{"detail": "job temporarily unavailable"}` (unreadable/corrupt file) | 401/403 as above.
  - Public surface untouched: `/health`, `/health/ready`, `GET /v1/state/{name}` answer keyless (router-level dependency = structural exemption, never middleware).
- **Auth dependency resolution chain**: header `X-API-Key` → missing → 401+challenge (compare skipped); else `expected = read_token(os.path.join(DATA_DIR, "api_token.txt"))` resolved at call time from module attr — `GOGO_API_TOKEN` env first (strip, non-empty), `data/api_token.txt` second (utf-8, strip), failure → None → fail-closed 403; `hmac.compare_digest(expected.encode(), provided.encode())`; success returns the validated key string. Request-only signature: no optional params → no `?token_path=` query-param injection (pinned by a decoy-file test).
- **Trigger dispatch**: `KIND_CMDS` (D-09 verbatim): pipeline → `run_pipeline.py --fast`, morning-check → `morning_check.py --quick`, backtest-weights → `backtest_v4.py` (no args), health-check → `data_health_check.py` (no args). `_cmd_for` builds `[sys.executable, <SCRIPTS_DIR>/daily/<script>, *args]` — arg-list only; the request body is never parsed, echoed, or logged (zero-parameter surface per D-09). Kind whitelist lookup precedes lock/claim/spawn — unknown kinds leave the registry and lock dirs empty.
- **Single-flight on the wire**: OS byte-range lock acquired before the in-memory claim consult; both 409 shapes proven, including a real cross-process holder (child process holding `job_lock.py`'s lock → 409 another-entry-point; kill → OS auto-release → 202 through the full HTTP path) and re-trigger after terminal.
- **Key hygiene (mechanical half of SC4)**: `run_job` pops `GOGO_API_TOKEN` from the spawn env copy; grep-audit test asserts the secret byte appears in neither job log bytes, the child's dumped environment, nor any response body seen during a live trigger.
- **Rule 1 fix in the 03-01 core**: `api/jobs.py start_job` now returns an accept-time `dict(job)` snapshot — see Decisions.
- **main() insertion points** (pre-edit line numbers of api/main.py): top imports after `from api.state import router as state_router` (line 18); `app.include_router(actions_router)` immediately after `app.include_router(state_router)` (line 34); `jobs.reload_registry()` after the SEC-03/token if/else block (ends line 68) and before the `# 惰性导入`/`import uvicorn` (lines 70-71). Phase 1 boot ordering (fail-closed check before token generation, `access_log=False`) untouched — diff-verified against 03-01's base.

## Task Commits
1. **Task 1 (tracer, tdd): trigger contract suite RED** - `56e14d6` (test: 4 tracer behaviors — 202 lifecycle/argv pin, 401/403 wiring, unknown-kind 404, public surface)
2. **Task 1 GREEN: auth + actions + main registration** - `d8a2599` (feat: api/auth.py + api/actions.py + main.py 3 change-sites + jobs.py snapshot fix). Tracer gate: verify re-run end-to-end post-commit — pass, expanded to Task 2.
3. **Task 2 (auto, tdd): SEC-01 auth contract suite** - `a4b095b` (test: 8 behaviors; first-run green — production from Task 1, no drift)
4. **Task 3 (auto): ACT-01/02/03 full matrix** - `613d004` (test: four-kind argv pins, failed exit surfacing, 409 matrix incl. cross-process holder + re-trigger, 404/503 edges)
**Plan metadata:** pending docs commit.
TDD Gate Compliance: Task 1 RED/GREEN commits present in order (`test(03-02)` 56e14d6 before `feat(03-02)` d8a2599). Task 2's RED phase was structurally empty by design — production code existed from Task 1 (plan letter: "any red here means the Task 1 implementation actually drifted"); its single `test(03-02)` commit documents the first-run-green confirmation. No `refactor(03-02)` commits — no cleanup was needed beyond the folded test-side template fix.

## Files Created/Modified
- `api/auth.py` (new, 54 lines) — `require_api_key(request: Request) -> str`; module docstring names SEC-01/D-10/D-11/Pattern 5; imports hmac/os/fastapi + `api.boot.read_token` + `scripts.daily.config.DATA_DIR` (module attr, used only inside the function); zero import side effects, ASCII-only console text (none), nothing logged.
- `api/actions.py` (new, 151 lines) — `router = APIRouter(dependencies=[Depends(require_api_key)])`; `SCRIPTS_DIR` (module attr, call-time read — test seam); `KIND_CMDS` (D-09 verbatim); `_cmd_for(kind)` arg-list builder; `trigger_action(kind)` (202/404/409); `get_job(job_id)` (regex gate → 404/503/200); module docstring names ACT-01/02/03 + SEC-01 + OQ1 shapes.
- `api/main.py` (+8 lines, 3 change-sites at the pinned positions — see main() insertion points above).
- `api/jobs.py` (2 lines changed + docstring) — `start_job` returns `snapshot = dict(job)` before `Thread.start`; public interface unchanged.
- `tests/test_actions.py` (new, 460 lines) — 13 tests: tracer four behaviors + full matrix; helpers: autouse tmp isolation (jobs/auth/state DATA_DIR+LOG_DIR seams, `_claims`/`_CACHE` cleared), `write_token`, `fake_script_tree` (real-named fakes under tmp `scripts/daily/`, KIND_CMDS name pin), GET poll helpers tolerant of the transient 503 replace-collision window, cross-process lock-holder child.
- `tests/test_auth.py` (new, 289 lines) — 8 SEC-01 tests incl. env-precedence, fail-closed, no-spawn-on-rejection, token-absence audit over log/env-dump/bodies, `?token_path=` tamper pin.

## Decisions Made
1. **start_job returns an accept-time snapshot (Rule 1, empirical):** the 202 contract pins `status: pending`, but `start_job` handed the response path a live dict that the worker thread mutates to `running` microseconds after `Thread.start` — under scheduler timing the 202 body raced to `running`. `snapshot = dict(job)` after `claim` (whose file write is the durable accept) makes the response deterministic and honest: it describes exactly the persisted pending record. Interface unchanged; all 03-01 consumers (test_jobs.py, 13 tests) stayed green untouched. (api/jobs.py, folded into d8a2599.)
2. **409 object shapes as designed (OQ1):** map-hit `{"message": ..., "running_job_id": ...}` / OS-lock-only `{"message": "...(another entry point)"}` without the key — mirrored byte-exact in tests.
3. **Encoded-traversal ids die at the route layer:** uvicorn/httpx decode `%2F` into literal slashes before routing, so `..%2F..%2Fdata%2Fapi_token` never matches `{job_id}` — Starlette answers 404 (generic body) with zero handler work. Security outcome identical to the handler gate (404, no path join, no file access, never 500) — T-03-11 satisfied one layer earlier. Tests assert route-layer 404 for that family and the handler's pinned `job not found` body for every slash-free malformed id (short, 31-hex, uppercase 32-hex, 33-hex, dot-segment is httpx-normalized away — same family).
4. **Task 2 committed as a single test commit:** its tdd RED was satisfied structurally (Task 1 delivered the code); first-run green is the no-drift confirmation the plan asked for. Fix-production-never-weaken-the-test held — no production change was needed.

## Deviations from Plan
1. [Rule 1 - Bug] start_job live-dict race corrupts the 202 body — Found during: Task 1 GREEN verification (intermittent `{"status": "running"}` in the 202 response vs the pinned `pending`) | Issue: worker thread mutated the same dict returned to the response path immediately after Thread.start | Fix: return `dict(job)` accept-time snapshot from `start_job` (semantics unchanged, docstring updated) | Files modified: api/jobs.py | Verification: 202-body pending pin green across 3 consecutive full-suite runs | Commit: d8a2599.
2. [Test-side iteration - Bug] fake-script template mis-substituted — Found during: Task 1 RED development | Issue: `.format(sleep=sleep)` parsed the fake body's literal `{'argv': ...}` dict braces (KeyError), then `.replace("{sleep}")` missed the actual `{sleep!r}` placeholder leaving a SyntaxError in the spawned child (rc=1) | Fix: `.replace("{sleep!r}", repr(sleep))` | Files modified: tests/test_actions.py | Verification: suite green | Commit: folded into the RED commit 56e14d6.
3. [Test adaptation - transport reality] %2F-traversal and literal-dot job_ids never reach the handler — Found during: Task 3 verification | Issue: httpx/uvicorn decode `%2F` to `/` and normalize `..` segments before routing, so those shapes get Starlette's route-level 404 (generic body) rather than the handler's pinned `job not found` — same gate one layer earlier, still 404 + zero file access + never 500 | Fix: test asserts route-layer 404 + zero side effects for the encoded-traversal family, and the exact pinned body for all slash-free malformed ids (plus uppercase/33-hex strengthening) | Files modified: tests/test_actions.py | Verification: full matrix green | Commit: 613d004.

**Total deviations:** 3 (1 Rule 1 production fix in the 03-01 core, 2 test-side). **Impact:** the Rule 1 fix is a one-line semantic tightening that keeps the 03-01 public interface identical while making the pinned 202 contract deterministic; test-side items adapt the suite to transport-layer behavior without weakening any security assertion.

## Issues Encountered
- None beyond the deviations above — no auth gates, no flaky runs across 3 consecutive full-suite executions.

## User Setup Required
None - no external service configuration required. (Token for HTTP consumers is the existing Phase 1 `data/api_token.txt` or `GOGO_API_TOKEN` env; nothing new to configure.)

## Next Phase Readiness
- 03-03 (GUI lock join) consumes `scripts/daily/job_lock.py` unchanged; the 409-another-entry-point shape it will see from the API is pinned in this plan's tests.
- 03-04 (live smoke) restarts the resident API — `main()` now runs `jobs.reload_registry()` in the boot sequence; the live uvicorn run can be exercised with the real token against `/v1/actions/health-check` and the SC1-SC5 manual matrix; SC4's real-machine console.log grep completes the leak audit (suite covers the mechanical half).
- The exemption list (/health, /health/ready, GET /v1/state/{name}) is now the documented public surface that Phase 4 SEC-02 data-classification tiers build around (D-11).
- Phase 4 SC4 date-whitelist parameters extend the zero-parameter trigger surface — KIND_CMDS + `_cmd_for` structure keeps backward compatibility (fixed args stay appendable).

## Self-Check: PASSED
