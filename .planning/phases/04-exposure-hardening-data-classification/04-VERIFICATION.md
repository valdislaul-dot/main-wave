---
phase: 04-exposure-hardening-data-classification
verified: 2026-09-04T12:47:29Z
status: passed
score: 14/14 truths verified
behavior_unverified: 0
overrides_applied: 0
gaps: []
deferred: []
decision_coverage:
  honored: 16
  total: 16
  not_honored: []
---

# Phase 4: Exposure Hardening + Data Classification — Verification Report

**Phase Goal:** gogo's most sensitive data — 持仓/账本/候选 — is served through token-gated endpoints under an explicit data-classification policy, and the whole exposure surface (bind, logs, errors, params, git) is hardened so the 2026-08-31 privacy red line holds even if the API leaves 127.0.0.1.
**Verified:** 2026-09-04T12:47:29Z
**Status:** passed
**Re-verification:** No — initial verification (no prior 04-VERIFICATION.md existed)

**Mode note:** ROADMAP marks the phase `mode: mvp` with a prose goal (not user-story format). This is the milestone-wide pattern carried through Phases 1-3 verifications and accepted at each phase's UAT record (`result: pass` in 01/02/03-UAT.md — prose-goal goal-backward verification accepted). This report verifies goal-backward against the ROADMAP Success Criteria and plan must_haves, mode-agnostic, exactly as Phases 1-3 were closed. The end-of-phase human gate for this phase (04-07, the 03-04 twin) is already resolved: the user reviewed SC1-SC5 against live evidence and recorded **ACCEPT** + the 04-04 session-date sign-off **signed** (2026-09-04, commit `17fd92e`). Nothing in this phase's human-review scope is pending.

## User Flow Coverage (MVP framing — API-consumer walkthrough)

User story (derived, prose-goal phase): «As the API consumer (the user's own trading session), I want the 持仓/账本/候选 read endpoints to require my token and the exposure surface to be hardened, so that the 2026-08-31 privacy red line holds even if the API leaves 127.0.0.1.»

| Step | Expected | Evidence | Status |
|------|----------|----------|--------|
| Request /v1/private/portfolio, journal, candidates without a key | 401 `missing_api_key` + `WWW-Authenticate: ApiKey`, no data served | api/auth.py:39-43 (missing-header 401 + challenge); 04-07 live matrix rows 5, 13 (401 on wire); suite test_gate_matrix / test_missing_key_401 | ✓ |
| Request with a wrong key | 403 `invalid_api_key`, no data served | api/auth.py:44-48 (compare_digest fail 403); 04-07 live row 6 (403 on wire) | ✓ |
| Request with the real key | 200 with raw byte-identical file body + X-Data-Mtime/X-Data-Age-S; market/temperature/health stay open with no key | api/private.py:157-185 (raw Response + headers); api/state.py routes unguarded; 04-07 live rows 7-10 (byte-identical to the real logs/ files, wire headers present) + rows 1-4 (public 200s); suite test_raw_bytes_verbatim_and_exact_fresh_headers et al. | ✓ |
| Browse the private surface with an unknown name or a bad date | 404 `Not Found`/`unknown_private_name`, 422 `invalid_date_format` — path-free envelope bodies | api/private.py:165-172 (whitelist-before-compose); 04-07 live rows 11-12; suite unknown-name/date matrix | ✓ |
| Boot posture change (someone binds 0.0.0.0) | Refusal unless GOGO_API_TOKEN env is set; loud ASCII warning, token never echoed | api/main.py:74-92 (env-only satisfier, D-12); 04-07 assumption row (a) loopback bind TRUE — the D-12 gate held live; suite boot cases 8/9 | ✓ |
| Verify the token file never leaks (git / upload whitelist / logs) | Scans empty; README documents the API's known limits | My SC5 re-runs (git history 0 hits; sync_cloud whitelist clean; .gitignore L12); README.md:69-105 known-limits; 04-07 Task 2 scan re-runs | ✓ |
| Outcome: privacy red line holds even off-loopback | All six steps above true simultaneously, endpoint-by-endpoint | SC2 route audit + live matrix + SC5 scans — all green | ✓ |

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | GET /v1/private/{name} for portfolio/journal/candidates is served ONLY through the token gate: no key → 401 `{"detail":"missing API key","code":"missing_api_key"}` + WWW-Authenticate: ApiKey; wrong key → 403 `{"detail":"invalid API key","code":"invalid_api_key"}`; the router carries `APIRouter(dependencies=[Depends(require_api_key)])` in a namespace structurally isolated from public /v1/state/* (D-13..D-15, SC1) | ✓ VERIFIED | api/private.py:55 (router-level gate), api/auth.py:33-49 (401/403 contract); api/main.py:53 (private include). In-suite: tests/test_private.py gate matrix + test_unknown_name_no_key_still_401_gate_first; my full-suite run green (below). Live: 04-07 matrix rows 5-6 (401 + challenge header, 403 byte-exact) |
| 2 | With a valid key the responses replicate the STA-01 contract: raw file bytes verbatim (never re-serialized, D-01), media_type application/json without charset, X-Data-Mtime + X-Data-Age-S from the real file mtime; stale-cache fallback serves last-good bytes flagged X-Data-Stale: true; cold cache on missing/unreadable data → 503 `private_data_unavailable`, never a bare 500 (D-16, SC1) | ✓ VERIFIED | api/private.py:173-185 (Response(content=raw), stale header only on fallback path), :113-154 (get_private retry/cache twin of api/state.py get_state). In-suite behavioral: test_private_torn_file_warm_cache_serves_stale_flagged / test_private_torn_cold_cache_503 / test_private_missing_file_cold_cache_503 / test_get_private_persistent_decode_warm_cache_stale (torn-window injection over the real endpoint) — all passed. Live: 04-07 rows 7-9 byte-IDENTICAL to logs/portfolio.json (603 B), logs/trading_journal.json (22,703 B), logs/candidates_2026-09-03.json with x-data-mtime/x-data-age-s on the wire, no X-Data-Stale |
| 3 | candidates semantics follow the in-repo rule: no ?date= → newest candidates_*.json excluding the candidates_v3_* legacy prefix; ?date=YYYY-MM-DD or YYYYMMDD serves that dated file (compact normalized to dashed); invalid date → 422 `invalid_date_format`; well-formed date with no matching file → 503; unknown name → 404 `unknown_private_name` before any path composition; whitelist-out files stay unreachable (D-14, whitelist-before-compose) | ✓ VERIFIED | api/private.py:45-48 (PRIVATE_FILES), :52-72 (_DATE_RE + _valid_date semantic gate), :81-110 (candidates rule mirroring morning_check.py selection, legacy exclusion), :165-172 (name gate before date gate before compose). In-suite: test_candidates_* 5-leg suite + test_unknown_names_404_decoy_unreachable_no_paths (decoy candidates_v3_* unreachable, no path text in bodies). Live: 04-07 rows 10-12 (compact-format 200 byte-identical; unknown name 404; `?date=2026-99-99` → 422 on the wire) |
| 4 | The two ledger writers are atomic: save_portfolio/save_journal serialize to a same-directory .tmp sibling then os.replace — a reader can never observe a truncated/half-written ledger; wire behavior byte-identical for every caller (same paths, same dump options, no last_updated/schema injection); a crash between tmp write and replace never loses the last committed content; success leaves no .tmp residue (D-04..D-06, STA-02 read go-live precondition) | ✓ VERIFIED | scripts/daily/trading_journal.py:47-63 (_replace_retry), :65-73 (save_portfolio), :83-89 (save_journal) — tmp + os.replace only, no os.rename, no schema field added; record_hold_valuation and other write paths untouched (scope fence). In-suite behavioral: replace-failure injection keeps previous target content byte-for-byte (test suite in tests/test_trading_journal.py — passed in my run); zero .tmp residue pinned. Git: trading_journal.py phase-4 commits touch only the two savers + record_sell (WR-02/06/07 review-fix, separately reviewed) |
| 5 | A route-by-route audit (test) proves every APIRoute carries exactly its tier's protection: require_api_key present on /v1/private/*, /v1/actions/*, /v1/jobs/*; absent on /health, /health/ready, /v1/state/*; /openapi.json joins the public tier — no sensitive route reachable without a token, no public route requiring one; the audit asserts dependency identity on the actual route objects, never satisfiable by documentation alone (SC2) | ✓ VERIFIED | tests/test_auth.py::test_sc2_route_by_route_classification_audit — dependency-identity assertion (`d.dependency is require_api_key`), set-equality over every classified route, unclassified-route hard failure, probe/openapi exemptions asserted by shape. **Named-test run: 5/5 passed** including this one (0.42 s). Full suite green |
| 6 | The fail-closed boot check is hardened and test-covered (WR-01/D-12): a non-loopback bind (e.g. 0.0.0.0) is refused unless the env var GOGO_API_TOKEN is set — the auto-generated file data/api_token.txt no longer satisfies the check; refusal exits non-zero BEFORE any token generation/file creation/uvicorn.run, with an ASCII error naming the host and env var; env-authorized non-loopback boots print an ASCII warning never echoing the token; the loopback default posture (auto-generate file token) is byte-unchanged (SC2, SEC-03 ordering) | ✓ VERIFIED | api/main.py:74-92 (non-loopback branch reads os.environ directly — file structurally irrelevant), :93-98 (loopback branch untouched: has_token/ensure_token), :103 (reload_registry), :108 (uvicorn.run). api/boot.py has_token/read_token/is_loopback unchanged. In-suite behavioral: tests/test_boot.py cases 8/9 (file-token-only → SystemExit + no file rewrite + uvicorn recorder empty; env-token → proceeds + warning without token echo in capsys out AND err) + case 5 unchanged; **named-test run passed**. Live: 04-07 restart through the real scheduled task booted the loopback posture with the file token intact — assumption rows (a)/(b) TRUE, the D-12 gate never weakened |
| 7 | Every 4xx/5xx across the api/ surface carries the unified body shape `{"detail": ..., "code": <stable machine code>}` with key order detail-then-code — 401 missing_api_key, 403 invalid_api_key, 404 family (unknown_state_name / unknown_action_kind / job_not_found / unknown_private_name / not_found), dual-shape 409 (already_running / already_running_other_entry), 503 family, framework 405 method_not_allowed, framework 422 validation_error, unhandled-500 internal_error — implemented by app-level exception handlers registered in api/main.py beside the constructor, never by editing raise sites (D-19) | ✓ VERIFIED | api/errors.py:32-52 (frozen CODE_BY_DETAIL incl. all 04-03/04-04 texts), :59-70 (_code_for text/shape-keyed with http_{status} fallback), :73-108 (three handlers); api/main.py:41-43 (registrations). 404 copy single-sourced to "Not Found" with semantic difference in code (:81-84). In-suite: tests/test_errors.py 6-leg envelope suite (incl. unmapped-text fallback pin and key-order pin); error-body pins swept across test_state/test_auth/test_actions. Live: 04-07 rows 5-6, 11-13 byte-exact envelope bodies |
| 8 | No error response or console/log line exposes file paths, stack traces, the token value, or exception internals: tracebacks go to server-side stderr only; error bodies are table-mapped fixed text; the token byte appears in no response body, no job log, no child env, no captured output across the whole protected surface (SC3) | ✓ VERIFIED | api/errors.py:97-108 (unhandled-500 prints traceback to stderr server-side only, fixed ASCII body); private/state/auth raise texts are fixed whitelist strings (grep-verified: no path interpolation into any body); api/main.py:108 access_log=False (uvicorn default does not log headers; disabled entirely). In-suite behavioral: tests/test_errors.py::test_unhandled_traceback_stays_server_side ("Traceback" not in r.text), tests/test_state.py path-absence pins, tests/test_auth.py::test_token_never_leaks_to_log_env_or_bodies — extended over all /v1/private shapes (200/401/403/404/422/503 bodies in the audit set, job log bytes, child env dump, GOGO_API_TOKEN key popped) — passed. Live: 04-07 token-in-console scan False over logs/api/console.log; every captured probe line audited |
| 9 | Trigger date parameters accept only the whitelisted formats (YYYY-MM-DD / YYYYMMDD) for pipeline and morning-check: gate order is kind-404 first → format/calendar 422 `invalid_date_format` → capability 422 `date_not_supported` (backtest-weights/health-check stay zero-param) → one normalized `--date=YYYY-MM-DD` token appended at the END of the fixed arg-list — a shell-injection attempt dies at the 422 before argv exists; no 422/404 ever spawns (D-26..D-28, SC4) | ✓ VERIFIED | api/actions.py:85-98 (four-gate order), :59-68 (_cmd_for arg-list append after fixed args), KIND_CMDS :51-56 (fixed commands, date-capable set). In-suite: tests/test_actions.py fake-script argv pins (recorded cmd ending [--fast, --date=2026-09-03]), invalid-format matrix → 422 + registry-stillness, zero-param kinds + date → 422, unknown kind + date → 404. Live: 04-07 row 12 (`?date=2026-99-99` → 422 on the wire) |
| 10 | The date validation is single-sourced in scripts/daily/date_args.py (whitelist regex + real calendar parse + argv resolution), pure stdlib with zero import side effects; both run_pipeline.py (fast mode) and morning_check.py (main) resolve --date and refuse a format-valid but non-session date with a clear ASCII message + exit 2 BEFORE any capture/file write/network call — a live run can never be labeled under a wrong session date; no token = pre-Phase-4 byte-identical behavior (SC4, fail-loud) | ✓ VERIFIED | scripts/daily/date_args.py (whole file — imports re/sys/datetime only, purity pinned by test_import_purity_no_side_effects); run_pipeline.py:54-67 (gate before Step 1); morning_check.py:459-473 (gate before load_latest_candidates/load_portfolio/capture). In-suite behavioral: tests/test_date_args.py subprocess refusal pins (past/invalid date → exit 2, zero data//logs/ writes, stderr message) — passed in my run. Human: 04-04 session-date fail-loud semantics **signed off** by the user at the 04-07 gate (2026-09-04) |
| 11 | SC5 scans: data/api_token.txt appears in neither git history nor the sync_cloud upload whitelist; .gitignore covers token + logs; README documents the API's known limits (single-flight scope, the 409 envelope codes, residual concurrent entry points: Mac crontab 无锁 / 手动 CLI / GUI 弃用 2026-09-04) and the boot posture | ✓ VERIFIED | **My own scan runs**: `git log --all --name-only` → 0 occurrences of api_token.txt in any commit; scripts/daily/sync_cloud.py:27-37 explicit file list contains only market-data snapshots (no token, no locks, no registry); .gitignore:12 `data/api_token.txt`, :14 `logs/*`, :27 `logs/*.log`, and README.md itself :30. README.md:69-105 endpoint inventory + known-limits + 启动姿态; 04-07 Task 2 re-ran the same set on the real repo (all PASS) |
| 12 | PROJECT.md Constraints/Security carries the two-tier data-classification table (公开级 /health /health/ready /v1/state/* /openapi.json — no key | 机密级 /v1/private/* + POST /v1/actions/* + GET /v1/jobs/* — X-API-Key required) with router-source grep column, the 定稿 stamp (2026-09-02 用户确认 + Phase 4 定稿 2026-09-04), and the 2026-08-31 privacy-red-line pointer; every endpoint string in the table and in README is byte-verified against the actual route decorators; docs claim only implemented limits (SEC-02 documentation requirement, SC5) | ✓ VERIFIED | .planning/PROJECT.md:56-61 (定稿 line + two-tier table). Cross-checked each row against the code: /health + /openapi.json (api/main.py:36,46), /v1/state/* + /health/ready (api/state.py:83,103), /v1/private/* (api/private.py:157), POST /v1/actions/* + GET /v1/jobs/* (api/actions.py:71,129) — all gated/un-gated exactly as documented; README known-limits claims match api/actions.py 409 raise sites byte-for-byte. README.md UTF-8 without BOM (byte-checked), gitignored local file per the 2026-08-31 user rule (04-06 deviation documented and accepted) |
| 13 | The review-fix pass (04-REVIEW-FIX.md, iteration 3) is real: WR-06 (run_pipeline --sell documented form crashed with IndexError) fixed by aligning the docstring to the real 3-arg NAME CODE PRICE form + guard tightened to `len(sys.argv) >= 5`; WR-07 (refused sell reported success) fixed end-to-end — record_sell returns None on all three refusal paths, run_pipeline exits 1 on None, contract pinned by new tests; fix scope confined to the sell bookkeeping CLI path, no 定稿机制 module touched | ✓ VERIFIED | Commits c2f24f0 + 39f2fdc present; code verified: run_pipeline.py:40-46 (guard >= 5 + `is None → sys.exit(1)`), trading_journal.py record_sell refusal paths return None (docstring states contract); git diff c2f24f0~1..39f2fdc = exactly scripts/daily/run_pipeline.py, scripts/daily/trading_journal.py, tests/test_trading_journal.py. In-suite: 11 test_trading_journal tests incl. new WR-07 pin test_record_sell_refusal_returns_none_no_match_and_legacy — **named-test run passed**; review-fix worktree record: 157 passed, 0 failed |
| 14 | Hygiene and live-gate truth: the full suite is green with zero failures (my run: 156 passed + 1 environment-conditional skip — test_health.py:48 skips because the real token file exists from the live boot, the documented skip), data/ and logs/ untouched by the suite (git status before/after identical, no .tmp residue), no debt markers in any phase-modified file; the real machine served the hardened API through the scheduled-task restart with the SC1-SC5 live matrix recorded and the user's ACCEPT verdict + session-date sign-off on file | ✓ VERIFIED | My full-suite run `python -m pytest -q` → 156 passed, 1 skipped in 17.61 s (0 failures); git status --porcelain -- data/ logs/ identical to the pre-run snapshot (2 pre-existing real-capture items, unchanged); debt-marker scan over all phase files: zero TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER; 04-07-SUMMARY.md live matrix + verdict block (ACCEPT, 2026-09-04, commit 17fd92e); service left running loopback on 127.0.0.1:8000 |

**Score:** 14/14 truths verified (0 present-but-behavior-unverified — every behavior-dependent truth above carries in-suite behavioral tests that passed in my full run and/or live-machine evidence from the user-accepted 04-07 gate)

### Deferred Items

None — no truth failed and no gap is addressed by a later milestone phase. (Phase 5 covers OPS-03 log rotation + /health/details — out of this phase's scope by design, recorded in ROADMAP as Phase 5 work, not a gap here.)

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | ----------- | ------ | ------- |
| `api/errors.py` | Frozen text-keyed code table + three app-level handlers | ✓ VERIFIED | 109 lines; CODE_BY_DETAIL complete incl. 04-03/04-04 texts; _code_for text/shape-keyed with http_{status} fallback; handlers map without paths/tokens; pure module |
| `api/private.py` | Token-gated private read router + candidates rule + read-layer twin | ✓ VERIFIED | 186 lines; router-level auth; whitelist-before-compose; raw Response + X-Data-* headers; stale/cold semantics |
| `api/main.py` | Handler registrations + openapi_url + private include + SEC-03 env-only boot branch | ✓ VERIFIED | All four regions present in their wave-ordered places; boot order preserved; access_log=False |
| `api/actions.py` | Date-param four-gate extension + arg-list append + WR-05 lock-fd close | ✓ VERIFIED | Gates ordered kind→format→capability→spawn; token built from parsed date object |
| `scripts/daily/date_args.py` | Pure single-source validator | ✓ VERIFIED | 74 lines; DATE_RE/parse_date/resolve_date_arg/format_token; stdlib-only imports |
| `scripts/daily/run_pipeline.py` | Fast-mode session-date gate + WR-06/07 sell fixes + WR-04 warn-loud | ✓ VERIFIED | Date gate before Step 1; --sell 3-arg guard + None→exit 1 |
| `scripts/daily/morning_check.py` | main() session-date gate before data loads | ✓ VERIFIED | Gate at main() top before load_latest_candidates/load_portfolio/capture |
| `scripts/daily/trading_journal.py` | Atomic save_portfolio/save_journal + refusal-None record_sell | ✓ VERIFIED | tmp + os.replace (+4x10ms PermissionError retry); no schema mutation; same-dir same-volume |
| `tests/test_private.py` | STA-02/SEC-02 contract suite | ✓ VERIFIED | 21 tests: gate matrix, byte-verbatim headers, candidates semantics, decoy guards, torn/stale/cold injection units |
| `tests/test_auth.py` | SC2 route-by-route audit + leak-audit extension | ✓ VERIFIED | Dependency-identity audit; leak audit over all private shapes |
| `tests/test_boot.py` | WR-01/D-12 regression cases 8/9 | ✓ VERIFIED | File-token refusal + env-token warning, capsys both-streams token-absence |
| `tests/test_errors.py` | Envelope contract suite | ✓ VERIFIED | 6-leg suite incl. 405/422/500 handlers, fallback code, traceback-stays-server-side, openapi public |
| `tests/test_date_args.py` | Validator matrix + script refusal subprocess pins | ✓ VERIFIED | Both formats, calendar rejects, ambiguity, purity, exit-2 refusal pins |
| `.planning/PROJECT.md` | 定稿 classification table | ✓ VERIFIED | Two-tier table + 定稿 stamp + red-line pointer + grep-source column |
| `README.md` | Known-limits + endpoint inventory + boot posture | ✓ VERIFIED | Local-only (gitignored per user rule), no BOM, claims byte-checked against code |
| `.gitignore` | Token/log coverage | ✓ VERIFIED | L12 data/api_token.txt, L14 logs/*, L27 logs/*.log |

### Key Link Verification

| From | To | Via | Status |
| ---- | --- | --- | ------ |
| api/private.py router | api/auth.py require_api_key | `APIRouter(dependencies=[Depends(require_api_key)])` — same dependency object as actions/jobs (api/private.py:55; identity asserted by SC2 audit) | ✓ WIRED |
| api/private.py read layer | api/state.py read core | `from api.state import StateUnavailable, read_state_file` reused as-is (path-parameterized); get_private is the documented twin — state.py signature core NOT refactored (state.py last touched Phase 2, git-verified) | ✓ WIRED |
| api/private.py | scripts/daily/config.py LOG_DIR | Imported once, joined at call time (monkeypatch seam); import chain fastapi + api.* + scripts.daily.config only, zero network capability | ✓ WIRED |
| api/actions.py date gate | scripts/daily/date_args.py | `date_args.parse_date` single-source import — API gate, script gates and tests consume one regex + one calendar check (api/actions.py:90) | ✓ WIRED |
| Appended date token | Script argv routing | `_cmd_for(kind, extra_args=(f"--date={parsed:%Y-%m-%d}",))` — appended after fixed args; scripts parse argv via resolve_date_arg (run_pipeline.py:58, morning_check.py:463) | ✓ WIRED |
| Exception handlers | app construction | `app.add_exception_handler(...)` x3 at api/main.py:41-43 beside FastAPI() constructor — module-level TestClient suites exercise the real envelope | ✓ WIRED |
| Envelope code mapping | raise sites | Text-keyed CODE_BY_DETAIL + shape-keyed 409 — raise sites in state/auth/actions carry original details (raise sites never edited for the envelope; state.py/auth.py git history ends in Phases 2/3) | ✓ WIRED |
| Non-loopback boot gate | env GOGO_API_TOKEN | main() reads os.environ.get directly on the non-loopback branch — file-token path structurally irrelevant (api/main.py:79); loopback branch still uses api/boot.py has_token/ensure_token | ✓ WIRED |
| PROJECT.md classification table | the implementing routers | Endpoint strings byte-identical to route decorators (grep-verified row by row); router-source column maps table → code | ✓ WIRED |
| 04-07 live matrix | the running service | http://127.0.0.1:8000 probes with the real data/api_token.txt in X-API-Key only; 13-row matrix recorded; user ACCEPT | ✓ WIRED |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| GET /v1/private/portfolio | raw bytes | read_state_file(LOG_DIR/portfolio.json) real file read → open→read→fstat→close | Byte-identity proven live vs logs/portfolio.json (603 B, row 7) | ✓ FLOWING |
| GET /v1/private/journal | raw bytes | read_state_file(LOG_DIR/trading_journal.json) | Byte-identity proven live vs logs/trading_journal.json (22,703 B, row 8) | ✓ FLOWING |
| GET /v1/private/candidates | raw bytes | _latest_candidates_file() listdir → newest candidates_*.json (legacy excluded) → read_state_file | Byte-identity proven live vs logs/candidates_2026-09-03.json (row 9); ?date=20260903 → same file (row 10) | ✓ FLOWING |
| X-Data-Mtime/X-Data-Age-S | ints | Same read handle fstat (D-01); age clamped non-negative | Wire values present and correct (row 7: mtime 1788400301, age 70552) | ✓ FLOWING |
| Date token → job argv | string | date object normalized `--date=%Y-%m-%d` (never raw query string) | Fake-script argv pins record [..., --fast, --date=2026-09-03]; live 422 gate on the wire (row 12) | ✓ FLOWING |

### Behavioral Spot-Checks (executed by the verifier, 2026-09-04 20:35-20:47 local)

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Full suite | `python -m pytest -q` | 156 passed, 1 skipped in 17.61 s (0 failures; skip = documented env-conditional test_health.py:48 — real token file exists from the live boot) | ✓ PASS |
| SC2 route-by-route classification audit | `pytest tests/test_auth.py::test_sc2_route_by_route_classification_audit` | 1 passed | ✓ PASS |
| WR-01 file-token refusal regression | `pytest tests/test_boot.py::test_non_loopback_file_token_only_refuses_without_uvicorn` | 1 passed | ✓ PASS |
| Private gate matrix (401/403/200) | `pytest tests/test_private.py::test_gate_matrix_no_key_401_wrong_key_403_valid_200` | 1 passed | ✓ PASS |
| Unified-404 envelope pin | `pytest tests/test_errors.py::test_404_unified_copy_with_per_site_codes` | 1 passed | ✓ PASS |
| WR-07 refusal-None pin | `pytest tests/test_trading_journal.py::test_record_sell_refusal_returns_none_no_match_and_legacy` | 1 passed | ✓ PASS |
| SC5 scan 1 — token in git history | `git log --all --name-only | grep api_token` | 0 occurrences across all commits | ✓ PASS |
| SC5 scan 2 — sync_cloud whitelist | read scripts/daily/sync_cloud.py:27-37 | Explicit file list = market snapshots only; no token/locks/registry | ✓ PASS |
| SC5 scan 3 — .gitignore | `git check-ignore -v data/api_token.txt` | .gitignore:12 data/api_token.txt | ✓ PASS |
| data/logs hygiene through suite run | `git status --porcelain -- data/ logs/` before/after | Identical snapshot (2 pre-existing real-capture items from earlier today; suite added zero changes); no logs/*.tmp residue | ✓ PASS |
| Debt markers | grep TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER over all 10 phase-modified files | Zero matches | ✓ PASS |
| Live gate | 04-07-SUMMARY.md (restart + 13-row matrix + assumption rows + suite + verdict) | All rows PASS; user ACCEPT + sign-off recorded (commit 17fd92e) | ✓ PASS |

### Probe Execution

No probe scripts exist in this phase (Step 7c): PLAN/SUMMARY files reference no `probe-*.sh`, and no conventional `scripts/*/tests/probe-*.sh` files exist in the repo (find scan empty). The phase's runnable checks are the pytest suite and the live HTTP matrix, both executed above — probe execution N/A.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| STA-02 | 04-01..04-05, 04-07 | 持仓/账本/候选读取接口（数据分级：token 保护） | ✓ SATISFIED | Truths 1-4 + live matrix rows 5-10: token-gated /v1/private/* raw reads byte-identical with freshness headers over atomic ledgers; REQUIREMENTS.md traceability row marks Phase 4 Complete |
| SEC-02 | 04-01..04-07 | 数据分级鉴权——行情/温度放开，持仓/账本/候选/触发一律 token | ✓ SATISFIED | Truths 5-12: SC2 route audit, D-12 boot gate, error/log hygiene, date whitelist, SC5 scans, PROJECT.md 定稿 classification table; REQUIREMENTS.md row marks Phase 4 Complete |

No orphaned requirements: the union of requirement IDs across all seven plans ({STA-02, SEC-02}) equals exactly the phase's ROADMAP requirement set. No plan declares an ID outside the phase, and every phase requirement is claimed by at least one plan.

### Decision Coverage

All 16 trackable CONTEXT.md `<decisions>` entries (D-13..D-28) are honored by shipped artifacts — `gsd-tools query check.decision-coverage-verify` returned `{total: 16, honored: 16, not_honored: []}`. Verified independently: D-13 namespace isolation (api/private.py router), D-14 candidates semantics (truth 3), D-15 401/403 split (truth 1), D-16 raw + headers contract (truth 2), D-17/D-04..D-06 atomicity (truth 4), D-18 WR-02/WR-03 fidelity fixes (tests/test_state.py — hammer rewrite with exception capture + progress counter + overlap, raw-ASGI dot-segment 404 pin), D-19 envelope (truth 7), D-20 openapi + README limits (truths 7, 11), D-21 log hardening + audit rule (truth 8 + test_token_never_leaks extension), D-22/D-12 WR-01 boot fix (truth 6), D-23..D-25 classification table (truth 12), D-26..D-28 date whitelist (truths 9-10).

### Test Quality Audit

| Test File | Linked Req | Active | Skipped | Circular | Assertion Level | Verdict |
|-----------|-----------|--------|---------|----------|-----------------|---------|
| tests/test_private.py | STA-02/SEC-02 | 21 | 0 | No | Behavioral (torn-window injection, byte-identity, header-exact, decoy unreachability) | ✓ Adequate |
| tests/test_auth.py | SEC-02 | 12+ | 0 | No | Behavioral (dependency-identity audit, token-absence over bodies/logs/env) | ✓ Adequate |
| tests/test_boot.py | SEC-02 | 17 | 0 | No | Behavioral (SystemExit code, no-side-effect triple-pin, capsys both-streams) | ✓ Adequate |
| tests/test_errors.py | SEC-02 | 6 | 0 | No | Behavioral (byte-exact envelope shapes, traceback-server-side, key order) | ✓ Adequate |
| tests/test_date_args.py | SEC-02 | 10+ | 0 | No | Behavioral (subprocess exit-2 refusal with zero-write diff pins) | ✓ Adequate |
| tests/test_trading_journal.py | STA-02 | 11 | 0 | No | Behavioral (replace-failure keeps old content, refusal-None contract) | ✓ Adequate |
| tests/test_actions.py | STA-02/SEC-02 | ~25 | 0 | No | Behavioral (fake-script argv pins, registry stillness on rejection) | ✓ Adequate |

**Disabled tests on requirements:** 0 (the only skip in the suite is the documented environment-conditional `test_health.py:48`, which is not a requirement-linked disabled test — it runs and passes in environments without a pre-existing real token file, as recorded by the review-fix worktree run: 157 passed).
**Circular patterns detected:** 0 — no test writes expected-value fixtures; expected bytes come from real files under tmp monkeypatched seams or literal contracts.
**Insufficient assertions:** 0 — every requirement-linked test reaches value/behavioral-level assertion.

### Prohibitions (negative must-haves — 34 across the 7 plans, all judgment-tier, resolved by direct code/git/behavioral evidence)

| Plan | Prohibition (family) | Resolution evidence | Verdict |
| ---- | -------------------- | ------------------- | ------- |
| 04-01 (6) | Raise sites never edited for the envelope (state/auth/actions keep exact details) | git: api/state.py last touched Phase 2, api/auth.py Phase 3, api/actions.py Phase 4 edits are date-param additions (pre-frozen texts) + WR-05 fd-close only; errors.py maps text/shape-keyed | ✓ Not violated |
| 04-01 | Non-404 detail bytes byte-identical; 404 copy scoped to the 404 class | errors.py:81-84 unifies only status 404; body pins sweep keeps byte-equalities (suite green) | ✓ Not violated |
| 04-01 | No error body/console line ever contains path/token/exception internals | Handlers fixed-text table-mapped; traceback only to server stderr; tests pin "Traceback" not in r.text, str(tmp_path) not in bodies, token-absence audit | ✓ Not violated |
| 04-01 | Pin sweep must not weaken assertions | WR-02 hammer strengthened (exception capture + progress >= 1 + overlap); current pins assert full envelope bytes | ✓ Not violated |
| 04-01 | main.py changes confined to constructor wiring region | Layout verified: handlers beside constructor, includes below, boot block/main() order preserved and pinned by tests | ✓ Not violated |
| 04-01 | WR-02/WR-03 test-fidelity only, no production change | git: phase-4 api/ changes = none for these; fixes live in tests/test_state.py only | ✓ Not violated |
| 04-02 (4) | Only save_portfolio/save_journal change; other write paths untouched | trading_journal.py phase-4 diff = two savers (+ record_sell via later review-fix, separately reviewed); record_hold_valuation truncate-write untouched | ✓ Not violated |
| 04-02 | No schema mutation / no last_updated injection; same bytes/paths | saver code verified: same dump options, no field added | ✓ Not violated |
| 04-02 | Suite never writes real logs/ | Module-global monkeypatch seams; my full-suite run left data/ logs/ identical to pre-run snapshot | ✓ Not violated |
| 04-02 | Windows atomicity semantics: same-dir tmp, os.replace only (never os.rename) | Code verified: `.tmp` sibling + os.replace (+ PermissionError retry); no os.rename anywhere in the savers | ✓ Not violated |
| 04-03 (6) | Raw passthrough D-01: verbatim bytes, no json round-trip, no FileResponse, no charset | Response(content=raw, media_type="application/json") verified; no FileResponse import | ✓ Not violated |
| 04-03 | state.py signed core not refactored to take a directory | state.py zero phase-4 changes (git); get_private is a documented twin | ✓ Not violated |
| 04-03 | Whitelist-before-compose: unknown name 404 / invalid date 422 before any path work | private.py:165-172 order verified; decoy pins prove unreachability; no filesystem touch on unknown names | ✓ Not violated |
| 04-03 | No external network; import chain discipline | private.py imports = os/re/time/fastapi/api.auth/api.state/scripts.daily.config; no script loader imported; conftest _no_network autouse guards the suite | ✓ Not violated |
| 04-03 | Envelope codes from frozen 04-01 table; no errors.py edits in 04-03 | git: errors.py created in 04-01, no later phase-4 edits (frozen table comment in place); private.py raises only frozen texts | ✓ Not violated |
| 04-03 | Audit asserts dependency presence on actual route objects, not docs | test_sc2 asserts `d.dependency is require_api_key` over app.routes with set equality | ✓ Not violated |
| 04-04 (5) | Only regex+calendar-validated dates reach argv; token from parsed date object, never raw string | actions.py:96 builds f"--date={parsed:%Y-%m-%d}"; parse_date calendar-validates; shell=False structural | ✓ Not violated |
| 04-04 | backtest-weights/health-check stay zero-parameter | actions.py:93-94 capability gate → 422 before spawn; KIND_CMDS fixed args unchanged | ✓ Not violated |
| 04-04 | Script refusal precedes every capture/write/network; exits non-zero with ASCII message | run_pipeline.py:54-67 and morning_check.py:459-473 gates verified at main() top before any data load/capture; exit 2; subprocess pins assert zero side effects | ✓ Not violated |
| 04-04 | date_args.py pure stdlib, zero import side effects | Imports = re/sys/datetime only; purity pin passed | ✓ Not violated |
| 04-04 | No duplicate date regex anywhere | All three consumers import date_args (verified by import lines); no second regex in actions/run_pipeline/morning_check | ✓ Not violated |
| 04-05 (5) | Non-loopback gate env-only; file token must NOT satisfy it | main.py:79 reads os.environ.get only on the non-loopback branch; regression test 8 pins file-token refusal | ✓ Not violated |
| 04-05 | SEC-03 ordering locked: fail-closed check before ensure_token/file creation; loopback branch byte-identical | Code order verified; refusal path creates nothing (tests pin no file + uvicorn never called); loopback branch unchanged | ✓ Not violated |
| 04-05 | Warning/error ASCII-only, never token value or file paths | Message text verified (names host + env var only); capsys pin asserts token absent from out AND err | ✓ Not violated |
| 04-05 | main() changes confined to SEC-03 branch region | Region layout verified; boot order preserved and pinned | ✓ Not violated |
| 04-05 | Pre-existing pinned guarantees kept (refusal creates no file, names host + env var) | Tests 8/9 keep and extend the pins; suite green | ✓ Not violated |
| 04-06 (4) | Table must not misclassify any endpoint; 机密级 rows name exactly the three families | Table rows byte-verified against route decorators (truth 12); no row mislabeled | ✓ Not violated |
| 04-06 | Docs must not claim limits the code does not implement | README claims only per-kind single-flight + two 409 codes + residual entry points (all verified against code); no rate-limit/ETag claims | ✓ Not violated |
| 04-06 | No encoding risk: UTF-8, no BOM | README byte-checked: UTF-8, starts 0x23, no BOM | ✓ Not violated |
| 04-06 | Docs-only diff; suite stays green | git: 04-06 commits touch PROJECT.md (+ summary) only; suite green in my run | ✓ Not violated |
| 04-07 (4) | No real pipeline/morning-check ever triggered live | 04-07 evidence: registry count 10 → 10 across all probes; only POST was no-auth 401; zero data/ writes | ✓ Not violated |
| 04-07 | Token value never in captured output or SUMMARY | 04-07 records token-in-SUMMARY False, token-in-console False; I read the SUMMARY in full — no token value present | ✓ Not violated |
| 04-07 | Contradiction with flagged assumptions → gate HALTS, never weakens D-12 | Assumption rows (a)/(b)/(c) recorded TRUE; D-12 gate held (loopback launcher never triggered it); no weakening | ✓ Not violated |
| 04-07 | Hygiene: data/ logs/ empty after tasks; service left running | Recorded empty; service left running and healthy (/health 200 at close) | ✓ Not violated |

Resolution note (autonomous-verifier honesty): all 34 prohibition verdicts above are the verifier's judgment resolutions grounded in direct byte-level code/git/test evidence (not SUMMARY claims). The end-of-phase human review that would normally confirm judgment-tier items has already occurred — the user's 04-07 ACCEPT verdict + session-date sign-off (2026-09-04) covered SC1-SC5 against live evidence; no prohibition family is flagged for further review.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | None found | — | — |

Scans over all phase-modified files (api/errors.py, api/private.py, api/main.py, api/actions.py, scripts/daily/date_args.py, run_pipeline.py, morning_check.py, trading_journal.py, PROJECT.md, README.md, tests/*): zero TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER markers; zero empty/stub implementations; zero hardcoded-empty data paths; zero console.log-only implementations. The four 04-REVIEW.md info findings (IN-01..IN-04) were declared out of fix scope by the review-fix record (fix_scope: critical_warning) — they are cosmetic (duplicate import os, legacy positions:null, docstring drift, comment drift), none affects phase contracts, and none is a debt marker.

### Human Verification Required

None pending — the phase's end-of-phase human gate is already resolved by the user's recorded verdict:

1. **SC1-SC5 acceptance walkthrough (04-07 end-of-phase gate, 03-04 twin)** — Verdict: **ACCEPT** (2026-09-04). The user reviewed all five success criteria against the live-machine evidence (restart record, 13-row matrix, SC5 scan re-runs, assumption-truth rows, full suite output) and accepted. Recorded in 04-07-SUMMARY.md, committed `17fd92e`.
2. **04-04 fail-loud session-date semantics sign-off** — **signed** (2026-09-04): run_pipeline.py/morning_check.py refusing format-valid non-session --date with ASCII message + exit 2 before any capture/write/network is accepted by the user; the API date param is deliberately inert for non-today dates until richer historical semantics are defined. Same verdict record.
3. **MVP user-story format decision (milestone-wide carried item)** — resolved at each prior phase's UAT record (`result: pass` in 01/02/03-UAT.md): prose-goal goal-backward verification accepted for the milestone's mvp-mode phases. This report follows that accepted pattern (see Mode note at top).

### Gaps Summary

No gaps. No must-have truth failed (14/14 verified), no artifact is missing/stub/orphaned/hollow, no key link is broken, all data flows trace to real ledger files with live byte-identity, no blocker anti-pattern or unresolved debt marker exists, and all 34 prohibitions across the seven plans are verified not-violated by direct code/git/behavioral evidence. Both phase requirements (STA-02, SEC-02) are satisfied with code, in-suite behavioral, live-machine, and user-accepted evidence; the plan-claim requirement union exactly equals the phase requirement set (no orphans). Decision coverage 16/16 honored.

All five ROADMAP success criteria carry evidence beyond symbol presence: SC1 by in-suite behavioral tests (gate matrix, byte-verbatim headers, torn/stale/cold injection) plus the user-accepted live matrix rows 7-10 (byte-identical bodies + wire headers); SC2 by the dependency-identity route audit test plus the D-12 boot regression tests (both in my green full-suite run) plus the live loopback boot observation; SC3 by the traceback-server-side pins, the token leak-audit over all /v1/private shapes and job logs, and the live console.log token scan; SC4 by the argv-delivery pins, the subprocess exit-2 refusal pins, and the live 422 row; SC5 by my own scan re-runs (git history / sync_cloud / .gitignore) plus the README known-limits document byte-checked against the code.

Status is therefore `passed`: every truth verified, no human item pending (the end-of-phase gate verdict ACCEPT + date-gate sign-off are on file), and no deferred gap. Phase 4 goal achieved — the sensitive data surface is token-gated under the documented classification policy with the bind/logs/errors/params/git exposure surface hardened, on the real machine.

---

_Verified: 2026-09-04T12:47:29Z_
_Verifier: Claude (gsd-verifier)_
