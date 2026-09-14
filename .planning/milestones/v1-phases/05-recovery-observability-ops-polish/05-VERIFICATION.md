---
phase: 05-recovery-observability-ops-polish
verified: 2026-09-05T01:42:12Z
status: passed
score: 10/10 truths verified
behavior_unverified: 0
overrides_applied: 2
overrides:
  - must_have: "05-02 M-A boot dance mechanism (repoint -> rotate -> repoint -> prune inside main(), rotation in-process at boot)"
    reason: "Real-machine gate (05-04 Task 1) live-disproved in-process rotation on the cmd >> launch path: cmd keeps its own deny-share (no FILE_SHARE_WRITE/FILE_SHARE_DELETE) handle copy for the child's whole lifetime, so every in-process open/rename fails (Errno 13 / WinError 32). Superseded by the operator-endorsed M-B adaptation: launcher-side rotation in run_api.bat before python starts + std_streams_on()-branched zero-fd-op in-process block. SC2 intent (bounded console.log, post-boot writes land in the fresh file, one .1 generation) preserved and live-proven at 01:23:31 (console.log.1 static 6,294,297 bytes; fresh console.log 201 bytes holding only the uvicorn boot banner)."
    accepted_by: "Operator (ACCEPT verdict recorded in 05-04-SUMMARY.md, commit b95e9a7)"
    accepted_at: "2026-09-05"
  - must_have: "05-01 uptime wiring mechanism (public uptime_seconds() beside main.py _START + handler-level lazy import from api.main)"
    reason: "Live matrix exposed a __main__/api.main dual-identity fork: `python -m api.main` never registers as api.main in sys.modules, so the lazy from-import re-executed main.py and reset the _START anchor (details uptime recounted from 0, lagged /health by 70s+). Operator-endorsed fix: zero-dependency leaf module api/uptime.py owns _START + uptime_seconds(); main.py and health.py both import it module-level. D-30 intent (both endpoints share one monotonic anchor) preserved — live-verified identical readings (11==11, 13==13) and suite-pinned by the identity test."
    accepted_by: "Operator (ACCEPT verdict recorded in 05-04-SUMMARY.md, commit b95e9a7)"
    accepted_at: "2026-09-05"
gaps: []
deferred: []
decision_coverage:
  honored: 9
  total: 9
  not_honored: []
---

# Phase 5: Recovery, Observability & Ops Polish — Verification Report

**Phase Goal:** The resident service is operationally sustainable — bounded log growth, human-readable health details behind auth, and a completed automated test suite proving behavior on both machines without network access.
**Verified:** 2026-09-05T01:42:12Z
**Status:** passed
**Re-verification:** No — initial verification (no prior 05-VERIFICATION.md existed)

**Mode note:** ROADMAP marks the phase `mode: mvp` with a prose goal (not user-story format) — the milestone-wide pattern carried through Phases 1-4 verifications and accepted at each phase's UAT record (prose-goal goal-backward verification accepted; see 04-VERIFICATION.md). This report verifies goal-backward against the ROADMAP Success Criteria, the OPS-03 requirement, and the four plans' must-haves, mode-agnostic, exactly as Phases 1-4 were closed. The end-of-phase human gate for this phase (05-04, the 03-04/04-07 twin) is already resolved: the operator reviewed all 15 flagged [ASSUMED] rows and the 5 prohibition rows against live evidence and recorded **ACCEPT** + adaptation sign-offs (2026-09-05, commit `b95e9a7`). Nothing in this phase's human-review scope is pending.

## User Flow Coverage (MVP framing — operator walkthrough)

Derived user story (prose-goal phase): «As the operator holding the API token, I want to read live versions/uptime/last-check details in one authenticated call, never hand-clean logs on a service left running for weeks, and run the suite on either machine knowing no test touches the network, so that the resident service is operationally sustainable.»

| Step | Expected | Evidence | Status |
|------|----------|----------|--------|
| GET /health/details with valid key | 200 with {versions, uptime_seconds, last_check}, values from the live environment | api/health.py:101-120 (handler); live matrix leg C verbatim in 05-04-SUMMARY (exact D-29 shape, versions 3.13.1/0.51.0/0.115.14, uptime 59, parseable ISOs); suite test_exact_d29_shape + test_versions_self_consistency green | PASS |
| GET /health/details without key / wrong key | 401 missing_api_key + WWW-Authenticate challenge / 403 invalid_api_key, no challenge | api/auth.py:42-48 (pinned bytes, zero diff); suite test_gate_matrix_no_key_401_wrong_key_403_valid_200 green; live matrix legs A/B verbatim in 05-04-SUMMARY | PASS |
| Leave service running for weeks | Disk bounded: registry ≤ 20 terminal pairs, console.log rotates at 5 MiB into one .1 | api/jobs.py:26 PRUNE_CAP=20 (single constant, both prune sites + boot prune); run_api.bat M-B rotation (CRLF+ASCII verified byte-level); suite cap-20 boundary/pair-deletion + rotate threshold/one-generation legs green; live proof 01:23:31 recorded; current machine state corroborates (console.log 405 bytes holding only uvicorn boot banners, no .1, registry 5 terminal pairs) | PASS |
| Run pytest on the real machine | Full suite green; any network-touching test fails by construction | My own run: **193 passed, 1 skipped in 15.80s**; conftest.py:31-48 autouse _no_network fixture guards every test; single skip is the pre-existing env-conditional test_health.py:48 | PASS |
| Run pytest on Mac (cross-machine rollout) | Checklist exists; user executes later and back-fills counts | README.md (local-only, gitignored) Mac 端验证清单 (D-35): git pull → pytest -q → network-blocking proof → token smoke; Win parity counts recorded (189+4 → 193 passed, 1 skip); Mac execution is the operator's post-phase rollout step by design (05-CONTEXT, D-35) | PASS (deliverable delivered; execution deferred to operator) |
| Outcome | "Operationally sustainable" — bounded logs, auth-gated details, machine-portable green suite | All three roadmap SCs verified below on code + suite + live-gate evidence | PASS |

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1: Operator with valid key GETs /health/details and receives versions/uptime/last-check details; without a key 401 — exact D-29 shape, lazy versions, shared uptime anchor, registry+stat-sourced last_check | ✓ VERIFIED | api/health.py (router gate, D-29 assembly, _versions/_latest_succeeded_health_check/_iso); api/uptime.py single anchor shared by main.py /health and health.py; 21-test contract suite green (gate matrix, exact key sets, ISO equality on os.utime-frozen values, uptime anchor/identity pins); live matrix on the real service 401/403/200 verbatim in 05-04-SUMMARY with operator ACCEPT |
| 2 | SC1 null legs: empty/missing/corrupt registry, failed-only or other-kind jobs, missing/unstat-able market_state.json → 200 with null, never 5xx | ✓ VERIFIED | api/health.py:74-98 + 108-112 tolerant scan (listdir OSError → None; per-file (OSError, ValueError) skip; non-dict guard; non-int finished_at guard — WR-03/dict-shape and the 05-01 auto-fix TypeErrror guards); suite null-leg matrix green (test_health_job_null_* x7, test_market_state_mtime_null_* x2) |
| 3 | SC1 envelope purity: zero new raise texts, api/errors.py zero diff, /health stays byte-exact and public, SC2 audit pins /health/details 机密级 with require_api_key dependency-object identity | ✓ VERIFIED | `git diff 25e758e..HEAD -- api/errors.py` = 0 lines; api/auth.py 401/403 bytes unchanged; main.py /health key set {status, uptime_seconds} pinned by suite; tests/test_auth.py:350-378 audit asserts `d.dependency is gate` identity and set-equality — /health/details in expected_secret, public list untouched |
| 4 | SC2 registry bound: PRUNE_CAP = 20 single constant; every terminal transition + boot prune keeps ≤ 20 terminal pairs; swept-interrupted counts toward cap | ✓ VERIFIED | api/jobs.py:26 PRUNE_CAP=20; prune terminal-only/mtime-oldest-first/pair-deletion (.json+.log), dict-shape guard (WR-03); run_job finally-prune (L170) and reload_registry tail-prune (L219) share the constant; log_housekeep.prune_job_logs resolves it at call time; suite cap-20 boundary (25 terminal + 3 inflight → exactly 20 remain, 8 oldest pairs gone from disk), finally-prune leg, corrupt/non-object skip legs — all green; live registry currently 5 terminal pairs ≤ 20 |
| 5 | SC2 console.log rotation: bounded footprint through continuous running — 5 MiB one-generation rotation on the real launch path; failures never block boot | ✓ VERIFIED | M-B launcher rotation in run_api.bat (verified byte-level: CRLF-only, ASCII-only, `%%~zA GTR 5242880` move to .1); api/log_housekeep.py pure primitives (rotate/repoint/std_streams_on/prune, OSError → ascii error, never raise); main.py:108-138 housekeeping block between reload_registry and the uvicorn import, WARNING-not-fatal, zero fd ops under cmd >> (std_streams_on branch); 12-test log_housekeep suite green incl. real-fd subprocess probe + external deny-share holder pin; live proof recorded (console.log.1 static 6,294,297 bytes, fresh console.log 201 bytes with only the uvicorn banner) and independently corroborated by current machine state (console.log 405 bytes = the two post-M-B boot banners only; no .1; no junk) — operator ACCEPT on the M-B adaptation |
| 6 | SC3 Win side: full pytest suite passes on the real machine with the network-blocking fixture proving zero network access | ✓ VERIFIED | My own full run: **193 passed, 1 skipped in 15.80s**; conftest.py autouse _no_network fixture (socket.connect guard, loopback-only exemption) part of every run by construction; single skip identified as the pre-existing env-conditional test_health.py:48 (real token file present); `git status --porcelain -- data/ logs/` empty before and after the run |
| 7 | SC3 Mac leg deliverable: cross-machine verification checklist delivered with parity counts, execution by operator | ✓ VERIFIED (deferred-by-design execution) | README.md (gitignored, local-only) numbered D-35 checklist: git pull → pytest -q (floor 157+, exact Win counts 193+1 recorded in 05-04-SUMMARY) → conftest network-blocking explanation → endpoint smoke with data/api_token.txt token; Mac execution is the operator's post-phase rollout step (05-CONTEXT "Not this phase: Mac 实跑验证本身"; ROADMAP SC3 Win-side + checklist delivery in scope) |
| 8 | D-36: 15:30 scheduled-task question closed with live audit evidence | ✓ VERIFIED | STATE.md [P3→P5] row CLOSED 2026-09-05: name-filtered Get-ScheduledTask enumeration empty (exit 0), control enumeration healthy (201 tasks, only gogo-api relevant, Ready) → confirmed absent, no disable command needed, none issued (D-02); ROADMAP wave/tracker rows cross-reference the record |
| 9 | D-37 + classification mirror: README known-limits deployment note (Ctrl+C lifecycle, no code change) + PROJECT.md 定稿 table /health/details 机密级 row (additive-only) + README endpoint/bounded-log segments | ✓ VERIFIED | README.md four subsections present (部署生命周期注意 D-37 with explicit 不做代码改动 wording; /health/details 鉴权与响应体; 日志有界行为; Mac 端验证清单); git check-ignore README.md exit 0 (never committed); PROJECT.md:65/67 standalone 机密级 row (api/health.py, router-level require_api_key, D-29/D-31 annotation) — additive per 05-03 record |
| 10 | 05-04 human gate: live SC1 matrix + rotation proof + final suite recorded, human-review checklist delivered, operator verdicts recorded | ✓ VERIFIED | 05-04-SUMMARY.md: live evidence verbatim (401/403/200 matrix, rotation byte proof, 189+4 suite counts), 15-row + 5-prohibition checklist, D-36 cross-ref, Mac handoff; commit b95e9a7 records the operator's ACCEPT verdict + adaptation sign-off (2026-09-05); two adaptation commits present (413bf90 M-B, 3e0898b uptime leaf) |

**Score:** 10/10 truths verified (0 present-but-behavior-unverified)

### Deferred Items

None — no truth failure is addressed by a later milestone phase (Phase 5 is the milestone's final phase). The Mac-side suite execution (SC3) is a user-executed rollout step, not a deferred phase item; its deliverable (the D-35 checklist) is verified in truth 7.

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `api/health.py` | Router-level require_api_key gate + GET /health/details D-29 assembly + tolerant helpers | ✓ VERIFIED | 120 lines; `router = APIRouter(dependencies=[Depends(require_api_key)])` (health.py:41, same dependency object as private/actions); _versions/_latest_succeeded_health_check/_iso; zero console output; module import side-effect-free |
| `api/main.py` | uptime via shared anchor; /health unchanged; health_router include; housekeeping block between reload_registry and uvicorn import | ✓ VERIFIED | uptime_seconds imported from api/uptime (L22); /health L48-51 byte-unchanged contract; health_router include L57; housekeeping block L108-138 (std_streams_on branch, WARNING-not-fatal); lazy uvicorn import L141 |
| `api/uptime.py` | Zero-dependency leaf anchor (_START + uptime_seconds) | ✓ VERIFIED | New post-live-fix module (3e0898b); imports time only; docstring records the __main__/api.main dual-identity rationale |
| `api/log_housekeep.py` | Pure-function primitives: rotate_console_log / repoint_std_streams / std_streams_on / prune_job_logs | ✓ VERIFIED | 5 MiB constant; call-time path/cap resolution via api.jobs attrs; OSError → ascii error, never raises, no prints; release_std_handles removed (EBADF crash source) |
| `api/jobs.py` | PRUNE_CAP = 20 single constant; prune/reload tolerance + dict-shape guards | ✓ VERIFIED | PRUNE_CAP=20 (L26); terminal-only mtime-oldest-first prune with .json+.log pair deletion; guards at reload L214, prune L241; OSError/ValueError per-file tolerance |
| `run_api.bat` | M-B launcher rotation before python start | ✓ VERIFIED | CRLF-only (0 lone LF), ASCII-only (0 non-ASCII bytes), `for %%A ... if %%~zA GTR 5242880 move /y` to .1; comment cross-references MAX_CONSOLE_LOG_BYTES |
| `tests/test_health_details.py` | Full SC1 contract suite with isolated fixtures | ✓ VERIFIED | 21 active tests, 0 skipped; autouse tmp_path isolation (health DATA_DIR + jobs LOG_DIR + auth DATA_DIR + write_token); frozen os.utime ISO equality; null matrix; fail-closed; leak hygiene; identity pin |
| `tests/test_auth.py` | SC2 audit covers /health/details with dependency-object identity | ✓ VERIFIED | expected_secret includes "/health/details"; `_gated` asserts identity `is require_api_key`; set-equality non-vacuity; docstring updated (per-path D-11 enumeration, 机密级) |
| `tests/test_log_housekeep.py` | Primitive suite incl. real-fd and Windows-share probes | ✓ VERIFIED | 12 active tests; threshold/.1-overwrite/no-op/OSError legs; prune delegation + call-time cap; subprocess fd probe; std_streams_on inherit probe; external deny-share holder pin |
| `tests/test_jobs.py` | Cap-20 rewrite + tolerance legs | ✓ VERIFIED | test_reload_sweep_prune_cap_keeps_20_newest_terminal (25+3 seed → 20 remain, 8 pairs gone), finally-prune leg, corrupt + non-object skip legs |
| `tests/test_boot.py` | LOG_DIR/jobs-LOG_DIR patches + repoint no-op (WR-04) on all main()-calling tests | ✓ VERIFIED | All full-boot tests patch api.main.LOG_DIR + api.jobs.LOG_DIR → tmp and call _noop_repoint; loopback err=="" pins success-silence |
| `README.md` | D-37 note + /health/details contract + bounded-log facts + Mac checklist | ✓ VERIFIED | Local-only (git check-ignore exit 0); four subsections read and matched against as-built 05-01/05-02 facts |
| `.planning/PROJECT.md` | 机密级 /health/details classification row | ✓ VERIFIED (warning: Active list stale — see Anti-Patterns W2) | Row at L65 + D-29/D-31 annotation L67 |
| `.planning/STATE.md` | [P3→P5] D-36 close-out with audit evidence | ✓ VERIFIED | Row closed 2026-09-05 with command + empty result + control enumeration |
| `05-04-SUMMARY.md` | Phase gate record + operator verdicts | ✓ VERIFIED | Live evidence verbatim; verdict section "ACCEPT — all 15 flagged rows, 5 prohibition rows verified" |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | -- | ------ | ------- |
| api/health.py | api/auth.py | require_api_key imported once, attached at router level | WIRED | health.py:37/41; SC2 audit asserts live-route dependency identity; no middleware/app-level gate anywhere in main.py |
| api/health.py | uptime anchor | module-level import of api/uptime.uptime_seconds | WIRED | health.py:38; main.py:22 same import; identity pin test green; live equal readings recorded |
| api/health.py | jobs registry | jobs_dir() + read_job() scan (kind health-check + succeeded, max finished_at) | WIRED | health.py:66-98; read-only (no registry mutation); live health_job ISO from registry in matrix leg C |
| api/health.py | data/market_state.json | os.stat at call time via config DATA_DIR, OSError → null | WIRED | health.py:109-112; live parseable mtime in matrix leg C |
| api/main.py | log_housekeep | housekeeping block between reload_registry (L106) and lazy uvicorn import (L141) | WIRED | main.py:108-138; paths derived from main's LOG_DIR attr (single test seam); prune base explicit |
| log_housekeep.prune_job_logs | api/jobs.prune + PRUNE_CAP | cap resolved at call time (single source) | WIRED | log_housekeep.py:104-116 |
| run_api.bat | console.log rotation | M-B pre-python move at >5 MiB | WIRED | Byte-verified bat; live-proven 01:23:31 |
| tests/* | app under test | module-level TestClient(app) with isolated tmp seams | WIRED | Real app routes exercised; real data/ logs/ zero-touch (hygiene empty pre/post suite) |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| /health/details | versions.python/uvicorn/fastapi | sys.version + importlib.metadata.version at request time | Yes — live env values; self-consistency test would red on hardcoded strings; PackageNotFoundError → "unknown" documented fallback | ✓ FLOWING |
| /health/details | uptime_seconds | api/uptime.py monotonic anchor (module import time) | Yes — shared with /health; live equality observed | ✓ FLOWING |
| /health/details | last_check.health_job | logs/api/jobs registry read_job scan | Yes — live ISO from real registry | ✓ FLOWING |
| /health/details | last_check.market_state_mtime | os.stat(data/market_state.json) | Yes — live parseable ISO | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Full suite green (all phase behaviors incl. gate matrix, null legs, cap boundary, rotation primitives, SC2 audit) | `python -m pytest -q` | 193 passed, 1 skipped in 15.80s | ✓ PASS |
| Skip is the known env-conditional one, not a phase regression | `python -m pytest tests/test_health.py -q -rs` | 3 passed, 1 skipped — test_health.py:48 "real token file existed before the session" | ✓ PASS |
| data/logs hygiene after suite | `git status --porcelain -- data/ logs/` | empty | ✓ PASS |
| Frozen envelope zero diff across the phase | `git diff 25e758e..HEAD -- api/errors.py` | 0 lines | ✓ PASS |
| M-B launcher format + threshold | byte-level scan of run_api.bat | 0 lone LF, 0 non-ASCII, GTR 5242880 present | ✓ PASS |
| Live service probes (/health, /health/details no-key) | curl 127.0.0.1:8000 | connection refused — service currently stopped (task LastTaskResult 0xC000013A, Ctrl+C exit after the gate; D-37-consistent). Live matrix evidence stands from the recorded 05-04 gate run + operator ACCEPT; behavioral coverage from the suite | ? NOT-RERUN (environment state, not a defect — see Notes) |

### Probe Execution

No probe scripts declared by any 05-xx plan and no `scripts/*/tests/probe-*.sh` files exist in the repo — Step 7c SKIPPED (nothing to run). The 05-04 gate's inline probes (registry non-terminal scan, shape assertion one-liners) were executed at the gate with outputs recorded in 05-04-SUMMARY.md; the current registry scan (5 terminal / 0 non-terminal) re-confirms the precondition state.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| OPS-03 | 05-01, 05-02, 05-03, 05-04 | 日志轮转 + 鉴权版 GET /health/details | ✓ SATISFIED | Auth-gated details endpoint (05-01, live-verified 05-04); rotation half: PRUNE_CAP 20 + M-B console rotation (05-02, live-proven 05-04); classification/doc/audit records (05-03); REQUIREMENTS.md marks [x] and table row "OPS-03 \| Phase 5 \| Complete" |

No orphaned requirements: REQUIREMENTS.md maps exactly one ID (OPS-03) to Phase 5, and all four plans claim it. v2 rows (OPS-04/05/06, ACT-04/05) are explicitly out-of-scope/excluded in every plan — not orphans.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `.planning/ROADMAP.md` | 152, 184 | Tracker lag: Phase-5 header "**Plans**: 3/4 plans executed" and Progress row "3/4 \| In Progress" while all four wave entries are [x] and STATE.md records 18/18 plans complete | ⚠️ Warning | Doc-only. ROADMAP is internally inconsistent (its own wave checkboxes contradict the Progress row). No plan or success criterion requires this count; recommend fixing at milestone close-out alongside the phase→Complete transition |
| `.planning/PROJECT.md` | 33-34 | "### Active" section still lists both Phase-5 deliverables unchecked ("日志轮转 + 鉴权版 /health/details（OPS-03）" and "双机测试套件全绿") while the delivered-items pattern used for Phases 1-4 was not applied | ⚠️ Warning | Doc-only tracker staleness; the classification row 05-03 added is present and correct; features are built and verified. Recommend flipping/moving both items at milestone close-out |
| README.md (local-only) | 日志有界行为 section | Boot-bound rotation caveat (review IN-03: an un-restarted long-lived session grows console.log past threshold by design) is not stated explicitly | ℹ️ Info | Operator-accepted limitation recorded in 05-REVIEW.md; README states rotation happens at boot, which implies the caveat; optional wording addition |
| `api/health.py`, `api/log_housekeep.py`, `api/jobs.py` scans | — | Debt-marker scan (TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER), stub scan, disabled-test scan on all phase files | ℹ️ Info | Clean — no markers, no stub patterns, no skipped/disabled tests in requirement-linked files (the "skips" grep hits are test names, not skip markers) |

### Test Quality Audit

| Test File | Linked Req | Active | Skipped | Circular | Assertion Level | Verdict |
| --------- | ---------- | ------ | ------- | -------- | ---------------- | ------- |
| tests/test_health_details.py | OPS-03 | 21 | 0 | No | Value + behavioral (exact key sets, ISO equality on frozen values, multi-leg matrix) | PASS |
| tests/test_auth.py | OPS-03 | (audit) | 0 | No | Value (set equality + dependency-object identity) | PASS |
| tests/test_log_housekeep.py | OPS-03 | 12 | 0 | No | Value + behavioral (subprocess real-fd probe, deny-share holder) | PASS |
| tests/test_jobs.py | OPS-03 | cap legs | 0 | No | Value (exact 20-remain boundary, pair deletion on disk) | PASS |
| tests/test_boot.py | OPS-03 | main()-calling | 0 | No | Behavioral (boot ordering, refusal exits, err=="" pins) | PASS |

**Disabled tests on requirements:** 0. **Circular patterns:** 0 — the versions self-consistency leg computes expected values in-test via importlib.metadata against the live environment (deliberate anti-hardcode pin: an endpoint hardcoding versions would fail red) and ISO expectations are computed from frozen os.utime values via the spec'd expression — both are wiring proofs, not same-system output capture. **Insufficient assertions:** 0.

### Prohibition Verification

All prohibition rows across the four plans are judgment-tier. The operator's end-of-phase gate explicitly verified the five 05-04 gate prohibitions and accepted the phase (ACCEPT verdict, 05-04-SUMMARY.md). Codebase evidence for the plan-level rows, verified by this report:

| Prohibition (plan) | Disposition | Evidence |
| ------------------ | ----------- | -------- |
| 05-01: require_api_key reused as router-level dependency, never middleware/app-level, no second token loader | ✓ VERIFIED | health.py:41 `APIRouter(dependencies=[Depends(require_api_key)])`; main.py declares no middleware; SC2 audit asserts identity on the live route |
| 05-01: frozen 04-01 envelope must not grow | ✓ VERIFIED | `git diff 25e758e..HEAD -- api/errors.py` = 0 lines; zero new raise texts (handler raises nothing; only auth's existing raises) |
| 05-01: version strings not hardcoded | ✓ VERIFIED | health.py:44-58 reads sys.version + importlib.metadata.version; suite self-consistency leg green |
| 05-01: /health/details pure read, tolerant of corrupt registry with null, never 5xx | ✓ VERIFIED | health.py code read (zero writes/spawn/network; scan tolerant incl. non-dict and non-int guards); null-leg suite green |
| 05-01: D-11 public list stays per-path; /health stays pure | ✓ VERIFIED | test_auth.py expected_public unchanged {/health, /health/ready, /v1/state/{name}}; docstring wording updated |
| 05-02: rotation block runs between reload_registry and the uvicorn import, never before SEC-03 checks | ✓ VERIFIED | main.py: SEC-03 block L77-101 → reload_registry L106 → housekeeping L108-138 → lazy import uvicorn L141 |
| 05-02: in-process repoint/rotate ordering (as written) | ✓ VERIFIED-BY-ADAPTATION (operator ACCEPT) | Live-disproven on the real cmd >> path; M-B launcher rotation + std_streams_on branch replaces it; intent (post-boot writes land in the fresh file, never .1) live-proven and operator-endorsed (commit 413bf90 + b95e9a7) |
| 05-02: rotation/prune failures never block boot | ✓ VERIFIED | Primitives return errors, never raise (suite OSError legs); main() prints at most one ASCII WARNING and continues; SEC-03 fatal-exit paths untouched |
| 05-02: log_housekeep purity (no prints, no import side effects, call-time path params) | ✓ VERIFIED | log_housekeep.py code read (no console output; os.path.join at call time); boot tests' err=="" pins; no stdout/stderr wrapper rebuilds |
| 05-02: suite never touches the real console.log/registry | ✓ VERIFIED | Autouse tmp_path fixtures across test_health_details/test_jobs/test_log_housekeep/test_boot; subprocess probes target tmp files only; hygiene empty before/after my full-suite run |
| 05-03: README.md never committed/staged | ✓ VERIFIED | `git check-ignore README.md` exit 0; README absent from all phase commits (git log shows docs commits scoped to .planning only) |
| 05-03: D-36 disable action never executed by the agent | ✓ VERIFIED | STATE.md record: enumeration empty → confirmed absent → no disable command needed, none issued |
| 05-03: no code changes in the docs plan; docs describe as-built facts | ✓ VERIFIED | 05-03 commits are docs-only (ea58d8c + metadata); README facts cross-checked against 05-01/05-02 as-built code by this report |
| 05-03: D-37 recorded with NO code change (no watchdog/relaunch logic) | ✓ VERIFIED | README wording "有意不做代码改动——无守护进程、无自动重启逻辑"; no such code exists |
| 05-04 (5 rows): no restart mid-job/auction-window; restart via real task only; no suite touch of real logs; adapt-and-record on contradiction; token never in outputs | ✓ VERIFIED (operator gate + this report) | Precondition scan outputs recorded (zero non-terminal before every stop/start; Saturday run); all boots via Start-ScheduledTask with orphan taskkill recovery; isolation fixtures + hygiene; adaptation commits 413bf90/3e0898b both re-proven and re-suite'd; no token material appears in any SUMMARY/record read by this report |

### Human Verification Required

None pending — the end-of-phase human gate was discharged in-phase: the operator reviewed the live matrix transcript, rotation evidence, D-36 record and all flagged [ASSUMED] rows, recording **ACCEPT** for all 15 rows and verifying all 5 prohibition rows (2026-09-05, commit `b95e9a7`, verdict section in 05-04-SUMMARY.md). No ⚠️ PRESENT_BEHAVIOR_UNVERIFIED truths remain: every behavior-dependent claim (auth gate bytes, null-leg 200s, cap boundary, rotation ordering under the real launch path, stream re-point landing) is exercised either by the suite or by the recorded real-machine gate with operator sign-off.

### Decision Coverage

| Decision | Honored | Evidence |
| -------- | ------- | -------- |
| D-29 (details content contract) | ✓ | health.py D-29 dict + exact-shape suite + live matrix body |
| D-30 (data sources: versions lazy, uptime anchor, registry + stat) | ✓ | health.py/uptime.py/main.py; realized as api/uptime.py leaf after the live-found fork (operator-endorsed adaptation) |
| D-31 (auth split, frozen envelope) | ✓ | auth.py reuse; errors.py zero diff; suite pins 401/403 bytes |
| D-32 (console rotation 5 MiB → .1 one generation) | ✓ | run_api.bat M-B + log_housekeep; live-proven (mechanism adapted M-A→M-B, operator ACCEPT) |
| D-33 (registry cap 20) | ✓ | jobs.py PRUNE_CAP=20 + boundary suite |
| D-34 (pure-function log_housekeep module, boot-sequence call) | ✓ | log_housekeep.py + main.py block position |
| D-35 (Mac verification checklist; execution by user) | ✓ | README checklist delivered; parity counts recorded; rollout pending operator execution by design |
| D-36 (15:30 task confirm → record / hand off) | ✓ | STATE.md closed row with live audit evidence |
| D-37 (P2 Ctrl+C lifecycle → README note, zero code change) | ✓ | README deployment-lifecycle section |

### Notes for the Operator (non-blocking observations)

1. **Service currently stopped.** The gogo-api scheduled task's last run ended with LastTaskResult 0xC000013A (Ctrl+C exit) after the 05-04 gate left it Running — exactly the D-37 documented lifecycle characteristic (console.log shows the ^C after the pid-32532 boot banners). Start it again with `Start-ScheduledTask -TaskName gogo-api` when the resident service is wanted; the M-B rotation and fresh-file stream landing were already proven on the last real boot (01:23:31 / 01:28:16 banners in the current console.log corroborate).
2. **Mac rollout (D-35)** remains for the operator to execute and back-fill per the README checklist; parity baseline recorded: 193 passed, 1 env-conditional skip.
3. **Doc tracker lag** (ROADMAP Progress "3/4 In Progress", PROJECT.md "### Active" unchecked Phase-5 items): recommend fixing during milestone close-out; no code or gate record is affected.

## Gaps Summary

No gaps. All three ROADMAP success criteria and the OPS-03 requirement are achieved on code, suite, and live-gate evidence: the auth-gated /health/details contract (SC1), the bounded-footprint rotation + cap mechanisms with a real-machine proof (SC2), and the green 193+1 suite under the autouse network-blocking fixture with the Mac checklist delivered (SC3). The two live-disproven plan mechanisms (M-A dance, lazy-import uptime anchor) were adapted in-place with recorded evidence and operator sign-off — the overriding decisions are documented in the frontmatter above.

---

_Verified: 2026-09-05T01:42:12Z_
_Verifier: Claude (gsd-verifier)_
