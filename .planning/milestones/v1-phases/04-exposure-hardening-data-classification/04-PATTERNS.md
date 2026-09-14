# Phase 4: Exposure Hardening + Data Classification — Pattern Map

**Mapped:** 2026-09-04
**Files analyzed:** 19 (5 new + 12 confirmed modified + 2 optional)
**Analogs found:** 16 / 19 (3 no-analog rows carry authoritative in-repo design docs instead)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `api/private.py` (NEW) | route/controller | request-response + file-I/O (raw passthrough, defensive read) | `api/state.py` (same role, same read layer — only whitelist target dir differs) | exact |
| `api/errors.py` (NEW, discretion) | utility (error-code table + handlers) | request-response | none in api/ (grep: zero `exception_handler`/error-code code); raise-site idiom from `api/auth.py:39-49`; design doc = `02-UI-REVIEW.md` Top-3 items | no analog |
| `tests/test_private.py` (NEW) | test | request-response + file-I/O | `tests/test_state.py` (STA-01 byte/header matrix + autouse isolation + decoy) + `tests/test_auth.py` (gate matrix) | exact |
| `tests/test_trading_journal.py` (NEW) | test | file-I/O (atomic write) | none (no journal test exists today); partial: `tests/test_boot.py` module-attr monkeypatch style | no analog |
| `api/main.py` (MOD) | config (route registration + boot) | request-response | itself (include_router shape L16-20/L36-37; WR-01 branch L56-71) | exact |
| `api/state.py` (MOD) | controller | request-response | itself (raise sites L87/91/114/116; read layer L38-100 is the reuse surface for private.py) | exact |
| `api/auth.py` (MOD) | middleware (FastAPI dependency) | request-response | itself (L39-49 raise sites) | exact |
| `api/actions.py` (MOD) | route/controller | request-response + process dispatch | itself (KIND_CMDS L42-48, `_cmd_for` L51-58, trigger L61-88) | exact |
| `scripts/daily/trading_journal.py` (MOD) | service (persistence) | file-I/O (atomic write, D-04..D-06) | `scripts/daily/zt_pool.py:72-78` (prescribed template); hardened variant `api/jobs.py:59-85` | exact |
| `scripts/daily/run_pipeline.py` (MOD) | CLI batch entry | batch | itself (argv routing L19-21) + `scripts/daily/data_health_check.py:102-110` (--date parse idiom) | role-match |
| `scripts/daily/morning_check.py` (MOD) | CLI batch entry | batch | itself (main L457-482, load_latest_candidates L11-18) + data_health_check --date idiom | role-match |
| `tests/test_state.py` (MOD) | test | file-I/O | itself (WR-02 hammer L273-330; WR-03 dot-segment pin L106-115; error-body pins) | exact |
| `tests/test_auth.py` (MOD) | test | request-response | itself (exemptions L169-183, leak audit L209-254, 401/403 pins) | exact |
| `tests/test_actions.py` (MOD) | test | request-response + process dispatch | itself (argv pin L139-178, 404/503 edges L428-459) | exact |
| `tests/test_boot.py` (MOD) | test | — | itself (case 5 L132-143 SEC-03 refusal; case 7 L162-171 env-satisfies) | exact |
| `tests/conftest.py` (MOD, optional) | config (test fixtures) | — | itself (L31-54 autouse pair) | exact |
| `.planning/PROJECT.md` (MOD) | doc (policy) | — | itself (Constraints/Security L54; Key Decisions L64; footer L98) | exact |
| `README.md` (MOD) | doc (contract) | — | itself (whole file is the stale insert target; no API-contract doc exists in-repo) | role-match |
| `run_api.bat` (MOD, optional) | config (startup path) | — | itself | exact |

## Pattern Assignments

### `api/private.py` (controller, request-response + file-I/O raw passthrough) — NEW

**Analog:** `api/state.py` — same role (APIRouter module, whitelist-before-compose, defensive read layer, raw byte passthrough, freshness headers). Copy its skeleton wholesale; swap the DATA_DIR/STATE_FILES target set for LOG_DIR/private files and add the router-level auth dependency.

**Module skeleton** (`api/state.py:19-35`; state docstring `:14-17` import-discipline note applies verbatim — import chain must stay fastapi + scripts.daily.config only):
```python
import json
import os
import time

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response

from scripts.daily.config import LOG_DIR   # D-02 路径纪律 —— private 目标在 logs/ 不在 data/
from api.auth import require_api_key
from api.state import read_state_file       # 复用读层原语 (path 参数化, 无 DATA_DIR 耦合)

PRIVATE_FILES = {                           # D-03 白名单形态照抄: 显式映射, 未知名 404
    "portfolio": "portfolio.json",
    "journal": "trading_journal.json",
    # "candidates": 动态文件名 —— 单独解析 (candidates_YYYY-MM-DD.json, 排除 candidates_v* 旧格式)
}
_CACHE = {}                                 # 每 (name[, date]) 一槽 (D-05); 独立于 api.state._CACHE
router = APIRouter(dependencies=[Depends(require_api_key)])   # SEC-02: 机密级命名空间
```
- Path composition at call time from module `LOG_DIR` attr — the monkeypatch seam every Phase 2/3 test relies on (`api/state.py:66` call-time join; `api/main.py:51` same). Never import-time resolve.
- `read_state_file` (`api/state.py:38-49`) is path-parameterized and reusable as-is (open rb → read → same-handle fstat → json.loads validate-only). Import it — do not copy it.
- `get_state` (`api/state.py:56-80`) is **not** reusable as-is: it hard-codes `os.path.join(DATA_DIR, STATE_FILES[name])` (`:66`). private.py needs the identical 20-line retry/cache loop against LOG_DIR — duplicate the shape into `get_private(name, date=None)` with a docstring stating it is the state.py twin targeting logs/. Decision (discretion): do NOT refactor state.py's signed D-01..D-05 core to accept a directory parameter — a read-side duplicate is lower risk than touching the signed module.

**Route shape** (`api/state.py:83-100` verbatim pattern; headers block copy exactly):
```python
@router.get("/v1/private/{name}")
def get_private_endpoint(name: str, date: str = None):
    if name not in PRIVATE_FILES and name != "candidates":
        raise HTTPException(status_code=404, detail="unknown private name")  # 白名单先于一切
    if date is not None and not _DATE_RE.fullmatch(date):
        raise HTTPException(status_code=422, detail="date must be YYYY-MM-DD or YYYYMMDD")  # D-09/SC4
    # candidates: 无参 -> 最新一份 (排除 candidates_v* 前缀); ?date= -> candidates_{YYYY-MM-DD}.json
    # 读层: 缺失/不可读 -> 503 "temporarily unavailable" (冷缓存, 同 D-04); 撕裂 -> 短重试 -> stale 缓存
    headers = {
        "X-Data-Mtime": str(mtime),
        "X-Data-Age-S": str(max(0, int(time.time() - mtime))),
    }
    if kind == "stale":
        headers["X-Data-Stale"] = "true"
    return Response(content=raw, media_type="application/json", headers=headers)  # 永不 FileResponse
```
- Candidate file listing precedent that excludes legacy format: `scripts/daily/auction_pool.py:48-52` / `scripts/daily/morning_check.py:11-18` (`f.startswith('candidates_') and not f.startswith('candidates_v')`, name-sort by date). Real file naming confirmed: `logs/candidates_2026-09-03.json` (dashed). Date normalizes YYYYMMDD → dashed before filename composition.
- Candidate loader functions in scripts load-and-return content (morning_check L17-18); private.py must NOT reuse them (API 不改脚本逻辑、不解析脚本输出 — 数据引用纪律). Only the *selection rule* (prefix filter + date sort) is the pattern to mirror, and file bytes are read through `read_state_file`.
- Decoy guard pins copied from `tests/test_state.py:87-119`: whitelist-out files that really exist must stay unreachable; body never equals decoy content; `str(tmp_path)` never in error bodies (`tests/test_state.py:124-129`).
- Cache warm/stale contract: `get_state` L56-80 twin — stale body must equal last-known-good bytes with the cached real mtime (headers and body always same version), cold cache → 503, never bare 500.

### `api/errors.py` (utility: error-code table + exception handler) — NEW, discretion

**No in-repo analog** — grep of `api/` finds zero `exception_handler` / error-code machinery. The authoritative design source is the user-signed P2 UI-review items (`02-UI-REVIEW.md:27-29`): stable machine-readable `code` field; close the dual-404 grammar gap; machine-readable contract. FastAPI body constraint: `HTTPException` serializes only `{"detail": ...}` — adding a top-level `code` field requires an app-level exception handler (registered in `api/main.py` near app construction or inside `main()`), returning `JSONResponse(status_code=..., content={"detail": <unchanged>, "code": <mapped>})`.

Design facts the planner must reconcile (all pinned today):
- Every existing raise site + detail text (raise sites stay unchanged if the mapping is text-keyed; only main.py gains a handler + errors.py a table):
  - 401 `missing API key` + WWW-Authenticate (api/auth.py:41-43) → code e.g. `missing_api_key`
  - 403 `invalid API key` (api/auth.py:48) → `invalid_api_key`
  - 404 `unknown state name` (api/state.py:87); 503 `state temporarily unavailable` (:91); 503 `state file unavailable` (:114/:116)
  - 404 `unknown action kind` (api/actions.py:70); 404 `job not found` (:100/:106); 503 `job temporarily unavailable` (:104); 409 object details `{"message": ..., "running_job_id": ...}` and `{"message": ...}` (:76-86)
  - Framework-generated: route-miss 404 `Not Found`, 405, validation 422 (starlette default body), unhandled-500
- Dual-404 gap (02-UI-REVIEW:28, live-confirmed): handler 404 `{"detail":"unknown state name"}` vs framework 404 `{"detail":"Not Found"}` — 04-CONTEXT L35 signs a single unified 404 copy ("404 文案单一定稿"). Recommended: one 404 wording API-wide + per-site `code` values carry the semantic difference (code table distinguishes unknown-state/unknown-action/job-not-found/route-miss), plus a catch-all 404 handler so the framework class also returns the unified body. 409 stays object-detail (`{"message": ..., "running_job_id": ...}`, 03-RESEARCH Open Question 1 RESOLVED); code rides as the sibling top-level field via the handler.
- Body-shape precedent for the handler's JSONResponse: `api/state.py:98-100` (`Response(content=..., media_type=...)`), import `JSONResponse` from `fastapi.responses` (same import family).
- 4xx/5xx detail must never contain paths/tokens (SC3) — handler maps text→code by table lookup; unknown text falls back to a status-class code, never echoes `exc.detail` internals beyond the standard body.
- **Pin-update sweep is mandatory**: every error-body pin below changes shape to include the code field — tests/test_state.py:102,127,204,214,225,238; tests/test_auth.py:113,118,127,143,162,187,192,202(no),223 + `test_actions` equivalents; tests/test_actions.py:202,412-413,432,436,444,459. Also add: unhandled-exception handler → body path-free + traceback stays server-side (console.log) — test pins `"Traceback" not in r.text` precedent at tests/test_actions.py:450.

### `api/main.py` (config: route registration + boot) — MOD

**Existing two-line include shape** (`api/main.py:16-20` imports + `:36-37` registration) — Phase 4 adds the private router the same way (03-PATTERNS precedent):
```python
from api.private import router as private_router        # beside L18-20
...
app.include_router(private_router)                      # beside L36-37 (机密级: 自带 auth 依赖)
```
- `/health` (L30-33) and the app constructor (L27) untouched except the error-handler registration lines (`app.add_exception_handler(...)` beside L27 — same module-level wiring region as `app.include_router`).
- `docs_url=None, redoc_url=None, openapi_url=None` (L27) — openapi is currently **disabled**; the P2 UI-review item 3 (02-UI-REVIEW:29) and 04-CONTEXT "openapi schema 同步更新" require re-enabling `openapi_url` (docs_url may stay None) OR an in-repo contract doc. This is a planner decision; if enabled, route docstrings (private/actions/state) are the schema source and must document the code field + date formats.
- **WR-01 / D-12 boot change** — non-loopback branch, exact current shape (`api/main.py:56-71`):
```python
    if not is_loopback(host):
        # SEC-03: 非回环绑定必须有已配置 token, 否则拒绝启动 (exit non-zero)。
        # 只评估 env/file 状态 —— 本分支绝不调用 ensure_token。
        if not has_token(token_path):
            print(
                f"ERROR: refusing to bind {host} without an API token. "
                "Set GOGO_API_TOKEN or create data/api_token.txt",
                file=sys.stderr,
            )
            sys.exit(1)
```
D-12 change: gate on **env token only** (file must no longer satisfy — WR-01: the auto-generated file makes file-presence indistinguishable from deliberate exposure). Suggested shape: `if not os.environ.get("GOGO_API_TOKEN", "").strip(): refuse` + a console **warning** (ASCII-only, stderr, never echoes the token) whenever binding non-loopback. Branch order stays: env parse → SEC-03 fail-closed check → (loopback) ensure_token → reload_registry (L76) → uvicorn.run (L81) — Phase 1 boot ordering diff-auditable (04-CONTEXT integration points). Fail-closed boot check must have test coverage (SC2) — see test_boot.py below.

### `api/state.py` / `api/auth.py` / `api/actions.py` (MOD)

- `api/state.py` — only the error-body shape changes if the text-keyed handler design is adopted (raise sites L87/91/114/116 unchanged); if the unified-404 copy is implemented by changing raise-site texts, the two 404/503 wording pins change here. Read layer (L38-100) and `/health/ready` (L103-117) otherwise untouched. `read_state_file` becomes an exported reuse surface for api/private.py (add it to the module docstring's contract note).
- `api/auth.py` — raise sites L39-49 unchanged except body shape via handler; do NOT touch the request-only signature rule (`:15-18` docstring, prohibition #2) or the D-10 401+WWW-Authenticate/403 split. The same dependency gates the new private router — zero new auth code (04-CONTEXT reusable assets).
- `api/actions.py` — date-parameter extension (D-09/SC4). Current whitelist-first trigger (`:61-88`):
```python
@router.post("/v1/actions/{kind}", status_code=202)
def trigger_action(kind: str):
    entry = KIND_CMDS.get(kind)
    if entry is None:
        raise HTTPException(404, detail="unknown action kind")  # T-03-10 门
    cmd = _cmd_for(kind)
    ...
```
Extension points: optional `date` (query param — request body stays undeclared per D-09 zero-param body) accepted only for kinds `pipeline` / `morning-check`; whitelist regex `^(?:\d{4}-\d{2}-\d{2}|\d{8})$` checked **before** `_cmd_for`; invalid format → 422 + detail naming the two whitelisted formats (CONTEXT: "非法格式 → 422 + detail 说明白名单格式"); passing a date to `backtest-weights` / `health-check` → 422 (zero-param kinds unchanged); appended as a single arg-list token `f"--date={date}"` at the END of the fixed args (`_cmd_for` gains an extra-args parameter — constants + validated date only; request data still can never reach argv unvalidated; shell=False structurally). `KIND_CMDS` (L42-48) stays the single source of truth.

### `scripts/daily/trading_journal.py` (service, file-I/O) — MOD, D-04..D-06 (STA-02 precondition)

**Current non-atomic writers** (`trading_journal.py:45-47` and `:57-59`):
```python
def save_portfolio(pf):
    with open(PORTFOLIO_FILE, 'w', encoding='utf-8') as f:
        json.dump(pf, f, ensure_ascii=False, indent=2)

def save_journal(journal):
    with open(JOURNAL_FILE, 'w', encoding='utf-8') as f:
        json.dump(journal, f, ensure_ascii=False, indent=2)
```
**Prescribed template** (D-05: 照 zt_pool 模式) — `scripts/daily/zt_pool.py:72-78`:
```python
def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    state['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    tmp = STATE_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)
```
Journal variant: `tmp = PORTFOLIO_FILE + '.tmp'` (same dir = same volume), `os.replace(tmp, PORTFOLIO_FILE)`; identical for JOURNAL_FILE. No last_updated injection (schema is user's ledger — do not mutate). Scope is exactly these two functions (D-05: no logs/ sweep; `record_hold_valuation`'s `daily_valuations.json` truncate-write at L191-198 stays untouched). Hardened variant exists if read-collision retry is wanted: `api/jobs.py:59-85` (`write_job` — pid-suffixed tmp + 4x10ms PermissionError retry) — optional, not required (private read handles are open→read→close µs windows).
- Test seam facts: `PORTFOLIO_FILE`/`JOURNAL_FILE` are module globals read at call time (L11-12) → monkeypatch seam; module import has side effect `os.makedirs(LOG_DIR, exist_ok=True)` (L14) — harmless (logs/ exists), do not copy this into api/ modules.

### `scripts/daily/run_pipeline.py` + `scripts/daily/morning_check.py` (CLI batch) — MOD, SC4 script side

API-side append reaches scripts as `[..., "--fast", "--date=YYYY-MM-DD"]` / `[..., "--quick", "--date=..."]` (CONTEXT literal single-token form). Neither script parses it today:
- `run_pipeline.py:19-21`: `fast_mode = '--fast' in sys.argv`; `if len(sys.argv) > 1 and sys.argv[1] != '--fast':` routes argv[1] as a command (`--status/--buy/--sell/--value`) — the date token MUST come after `--fast` (argv[2:]), never as argv[1], or it hits the usage branch. Note: in fast mode argv[2:] is currently ignored — silent no-op until a parse is added.
- `morning_check.py:457-482`: `main()` reads `quick = '--quick' in sys.argv` (L459), `data = load_latest_candidates()` (L460), header date `datetime.now()` (L465), quick-mode auction snapshot path `data/auction/YYYY-MM-DD.json` from `datetime.now()` (L472); prev-pool selection delegates to the shared `zt_pool.get_prev_pool_file()` (L427-428).
- In-repo `--date` parse idiom (space-separated) — `scripts/daily/data_health_check.py:102-110`:
```python
    args = sys.argv[1:]
    if '--date' in args:
        i = args.index('--date')
        today = args[i + 1] if len(args) > i + 1 else datetime.now().strftime('%Y-%m-%d')
    else:
        today = datetime.now().strftime('%Y-%m-%d')
```
Phase 4 appends the single token `--date=<date>` per CONTEXT literal — script-side parse should accept that token form (`next((a.split("=", 1)[1] for a in argv if a.startswith("--date=")), None)`), or the API appends two tokens `["--date", date]` to match the in-repo idiom. Planner decision; both reach argv as arg-list (SC4 satisfied either way).
- Shared prev-file selection MUST go through `zt_pool.get_prev_pool_file(ref_date)` (`zt_pool.py:56-69` — it already takes ref_date; CLAUDE.md 2026-09-01 rule: no hand-written filters).
- Scope caution for the planner: full historical re-run semantics (what a `--date=D` pipeline/morning-check must recompute vs capture) is NOT user-specified beyond format whitelist + arg-list delivery (SC4). If scripts only *accept* the token, the feature is inert; if they rerun capture against a past date, semantics cascade into every step module (each computes `datetime.now()` internally). Recommend a pure parse helper per script (unit-testable, e.g. `resolve_date_arg(argv)` validating the whitelist regex) and an explicit planner decision on date semantics scoped to file *selection* (candidates/auction snapshot/prev-pool), leaving capture steps live-only or fail-loud when date != today.

### Test files (MOD)

**`tests/test_state.py`** — two P2-review fixes + error-body pins:
- **WR-02 hammer fix** (`tests/test_state.py:273-330`; defect spec `02-REVIEW.md:43-47`): `writer_loop` (L290-315) swallows any non-OSError exception (thread dies silently → test passes vacuously as a static-file smoke test; the `x-data-stale` branch L325-326 never exercised). Fix: capture thread exceptions into a shared list and assert empty after join; add a per-iteration `progress` counter asserted >= 1; add a barrier or initial writer sleep so GETs overlap a real torn window.
- **WR-03 dot-segment pin fix** (`tests/test_state.py:111-115`; spec `02-REVIEW.md:49-53`): class (c) asserts `/v1/state/market_state/../auction_state` → 200, which is an httpx/TestClient URL-normalization artifact — live uvicorn (curl `--path-as-is`) returns framework 404; the handler never runs. The 200 pin misdocuments the wire contract. Fix: assert the server truth — a raw-ASGI-scope request (build scope dict with the un-normalized path, call `app(scope, receive, send)` via asyncio, capture response) returns 404; plus a comment that the TestClient 200 variant exists only because httpx collapses `..` pre-transport. Note the repo convention that class (b) encoded shapes (`..%2F..`) assert status-only 404 (L106-109) and `tests/test_actions.py:440-450` already documents the same httpx caveat — mirror that comment.
- Error-body pins (L102/127/204/214/225/238) updated to the new code-field shape from `api/errors.py`.

**`tests/test_auth.py`** — add the SC2 route-by-route classification audit + error pins + leak-audit extension:
- Audit shape: iterate `app.routes`; for each `APIRoute` assert dependency presence equals the classification table — 公开级 (`/health`, `/health/ready`, `/v1/state/*`): no `require_api_key` in `route.dependencies`; 机密级 (`/v1/private/*`, `/v1/actions/*`, `/v1/jobs/*`): `require_api_key` present. Depends objects expose `.dependency`. Existing exemption pins to extend: L169-183 (`test_public_exemptions_no_key_needed`) gains the private-route 401-without-key leg.
- Error-body pins L113/118/127/143/162/187/192/223 updated.
- Leak-audit extension (SC3): the existing byte-absence audit (L209-254) covers job logs + child env + response bodies; add /v1/private requests into the body collection and (optionally) a console.log audit test — real subprocess precedent at `tests/test_actions.py:383-423` (spawn child, read its stdout) and capsys pattern at `tests/test_boot.py:117-127`.
- 401/403 unchanged texts (D-10) unless the unified-404 decision touches them (it should not — 404 only).

**`tests/test_actions.py`** — date-param contract (fake-script argv pins, L139-178 pattern):
- Valid `?date=2026-09-03` and `?date=20260903` on pipeline/morning-check → 202; fake-script recorded argv (L173-175 pattern) == `[fake_script, "--fast", "--date=2026-09-03"]` (or two-token variant) — proves arg-list delivery; registry `cmd` pin L170-172 extended.
- Invalid formats (`2026/09/03`, `2026093`, `abc`, `2026-13-99`) → 422, no spawn (registry dir stays empty — `_registry_files() == []` pattern L203).
- date on `backtest-weights`/`health-check` → 422 (zero-param kinds).
- Error-body pins L202/412-413/432/436/444/459 updated.

**`tests/test_boot.py`** — WR-01 fail-closed boot coverage (case 5/7 analogs, L132-171):
- Existing: non-loopback + no token → SystemExit, no file created (L132-143); env token satisfies (L162-171). New required cases: non-loopback + **file token present but env absent** → refuse (the WR-01 regression: today `has_token` passes on the auto-generated file — D-12 makes env the only satisfier); non-loopback + env token → proceeds + **console warning** printed (capsys, ASCII, token value absent from output — L117-127 notice-purity pattern).
- `_patch_uvicorn_run` helper L22-25 reused verbatim.

### `tests/test_private.py` (NEW) — contract suite for STA-02/SEC-02/SC2/SC3

Copy `tests/test_state.py` scaffolding wholesale: module docstring pinning data isolation; module-level `TestClient(app)` (L27-31); autouse fixture monkeypatching `api.private.LOG_DIR` (and `api.state.DATA_DIR` for the public-side assertions) to tmp_path + clearing `_CACHE` (L34-39 shape); `_write_*` fixtures writing `logs/portfolio.json`, `logs/trading_journal.json`, `logs/candidates_2026-09-03.json` + a `candidates_v3_...` decoy file (legacy-format exclusion pin).
Cases (each maps to a success criterion):
- Gate: no key → 401 + WWW-Authenticate (auth matrix from `tests/test_auth.py:110-128`); wrong key → 403; market/temperature endpoints (`/v1/state/*`, `/health`) stay open with no key (SC1) — exemptions block L169-183 shape.
- Raw passthrough + exact freshness headers per name (SC1) — byte-verbatim assertions from `tests/test_state.py:52-63`; portfolio/journal bodies contain UTF-8 Chinese + CRLF fixture (Pitfall 1).
- candidates no-param → latest; `?date=` both whitelist formats → dated file; legacy `candidates_v3_*` never selected; unknown date file → 503 (read-layer unavailability, D-04 semantics); invalid date → 422 with format detail.
- Unknown name → 404 + decoy guard (whitelist-out files unreachable, L87-119 shape) + `str(tmp_path)` not in error bodies (L124-129).
- Freshness of the *data-versioning contract*: torn-window behavior via injected-reader unit tests (L134-176 shape) — `get_private(name, date=None, retries=..., reader=...)` keeps the injectable-reader seam.
- SC2 audit (or in test_auth.py — single home): route-by-route classification table assertion.

### `tests/test_trading_journal.py` (NEW)

Atomic-write unit tests for the two changed functions; no direct analog — borrow `tests/test_boot.py` module-attr monkeypatch style (L43-47 pattern: point module globals at tmp_path). Cases: `save_portfolio`/`save_journal` produce valid JSON at target with no `.tmp` residue; torn/crash simulation (kill between tmp write and replace is not directly possible — instead assert content lands only via replace: after a simulated failure the target keeps the previous good content — pre-write old content, monkeypatch `os.replace` to raise once, assert target unchanged and tmp cleaned or tolerated). Round-trip through `load_portfolio`/`load_journal` (L31-54 unchanged).

### Docs (MOD)

**`.planning/PROJECT.md`** — the data-classification policy lands in the Constraints/Security clause (L54) per 04-CONTEXT: two-level table 数据类别 → 端点 → 保护级别 — 公开级 (`/health`, `/health/ready`, `GET /v1/state/*` 行情温度): 无 key; 机密级 (`GET /v1/private/*` 持仓/账本/候选 + 全部 `POST /v1/actions/*` + `GET /v1/jobs/*`): X-API-Key. Version note: "2026-09-02 用户确认 + Phase 4 定稿 2026-09-04", linked to the privacy red line (2026-08-31, decision row L64) and the 定稿 marker 「改动需用户确认」. Table formatting is discretion; markdown table matching the Key Decisions table style (L58-78). Also flip Active rows L31-32 at transition and update the L98 footer.
**`README.md`** — add the API 已知限制 section (SC5 hard requirement): single-flight scope (same-kind overlap → 409; GUI lock join code retained), remaining concurrent entry points (Mac crontab 无锁 — two-machine serial convention; manual CLI; GUI deprecated 2026-09-04), loopback-only default bind + env-forced-token rule for non-loopback, plus a reference to the PROJECT.md classification table and the endpoint list. README is stale v2-era (whole file is 71 lines, predates the API) — the section is additive at the end.

### `tests/conftest.py` + `run_api.bat` (MOD, optional)

- conftest: existing autouse pair (L31-54) covers Phase 4 needs (`_clean_env` deletes GOGO_API_TOKEN so boot tests are deterministic). Optional additions only: a tmp token-file writer helper (already duplicated in test_auth.py L55-59 — could centralize) or a LOG_DIR seam helper for test_private. Not required.
- run_api.bat: startup stays loopback-default (`api/main.py:48` D-08), so the D-12 env-forced-token change needs no bat edit for the default posture. If the Task Scheduler task ever binds non-loopback, GOGO_API_TOKEN must be supplied in the task env — a bat-side comment/passthrough is the only optional repo change (04-CONTEXT integration points: "WR-01 修复改动启动路径"). Keep `set PYTHONUTF8=1` (L4) untouched.

## Shared Patterns

### Token gate + structural public/private split (SEC-02)
**Source:** `api/auth.py:33-49` (`require_api_key`), router attach precedent `api/actions.py:36`.
**Apply to:** new `api/private.py` router (`APIRouter(dependencies=[Depends(require_api_key)])`); `api/main.py` include. Never middleware, never app-level dependency — public surface structurally untouched. 401 missing + WWW-Authenticate / 403 wrong, fail-closed when no token. Classification is a route-property assertion (SC2 test) + PROJECT.md table + README reference — three mirrors of one table.

### Defensive raw read layer + freshness headers (STA-01/STA-03 contract, D-01)
**Source:** `api/state.py:38-100` (read_state_file importable; get_state twin in private.py; headers L92-100; media_type JSON no charset; never FileResponse — held handles block os.replace, WinError 5 note L62-63).
**Apply to:** `api/private.py` — byte-level passthrough, never re-serialize; stale body == cached mtime version; cold 503; no bare 500.

### Whitelist-before-compose + path-free errors
**Source:** `api/state.py:86-91`, `api/actions.py:99-107` regex gate; decoy pins `tests/test_state.py:87-119`.
**Apply to:** private name whitelist, candidates date→filename composition, actions date whitelist, job_id gate. User input never composes a path or argv before a whitelist/regex gate; error bodies never contain paths (D-04, SC3).

### Unified error envelope with machine-readable codes
**Source:** P2 UI-review items (`02-UI-REVIEW.md:27-29`, user sign-off in 04-CONTEXT L35); raise-site inventory listed under api/errors.py above; JSONResponse precedent `api/state.py:98-100`.
**Apply to:** all 4xx/5xx across api/ (state/auth/actions/private + framework 404/422/500). Detail copy single-sourced per status class; code field machine-readable, path-free; tracebacks server-side only (SC3). Error-body pins in test_state/test_auth/test_actions all updated in the same wave.

### Atomic writes — tmp + os.replace
**Source:** `scripts/daily/zt_pool.py:72-78` (prescribed D-05 template); hardened retry variant `api/jobs.py:59-85`.
**Apply to:** `trading_journal.py` save_portfolio/save_journal only (D-04..D-06; bound as STA-02 go-live precondition — wave ordering: journal atomicity lands before private endpoints deploy).

### Date whitelist + arg-list delivery (D-09 extension, SC4)
**Source:** whitelist regex shape from `api/actions.py` kind gate; in-repo parse idiom `data_health_check.py:102-110`; shared prev-pool selector `zt_pool.py:56-69` (mandatory, no hand-written filters).
**Apply to:** POST /v1/actions date param (pipeline/morning-check only, 422 otherwise), GET /v1/private/candidates `?date=`, script-side `--date=` parse in run_pipeline/morning_check. Validation precedes argv append; shell=False structurally.

### Test conventions
**Source:** `tests/conftest.py:31-54` (autouse no-network + clean-env); module-level TestClient without context manager (`tests/test_state.py:27-31`); per-file autouse tmp isolation + in-memory state clearing (L34-39); fake-script trees (`tests/test_auth.py:62-84`); capsys console pins (`tests/test_boot.py:117-127`); raw-ASGI-scope request for server-truth routing pins (WR-03 fix).
**Apply to:** test_private.py (new), test_trading_journal.py (new), and every modified suite. Tests never touch real data//logs/; fake scripts never hit network; job workers always waited to terminal to avoid cross-test residue (`wait_terminal` test_auth L91-105).

### ASCII console + import side-effect freedom + config path discipline
**Source:** `api/state.py:14-17`; `api/main.py:8`; `api/boot.py:3-7`; `scripts/daily/config.py:5-9`.
**Apply to:** api/errors.py, api/private.py (module import never binds/handles/spawns/prints; LOG_DIR/DATA_DIR read at call time = monkeypatch seam); all new console text ASCII-only (WR-01 warning included); no token value ever printed/logged (D-05).

### SC5 scans (verification + optional audit pins)
**Verified this mapping session (facts for the plan):** `data/api_token.txt` absent from git history (`git log --all -- data/api_token.txt` empty); absent from the sync_cloud whitelist (`scripts/daily/sync_cloud.py:27-37` — explicit list of data/*.json + data/auction glob only); `.gitignore` L12-14 covers api_token/locks/logs. Optional in-suite audit pins: source-scan pattern `tests/test_state.py:261-268` (read module/file source text, assert banned content absent) extended to assert `sync_cloud.py` source contains no `api_token` token; the git-history check stays a phase-gate shell command (not a pytest).

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `api/errors.py` | utility | request-response | Zero exception-handler / error-code machinery exists in api/ (grep-verified). Design source is the user-signed P2 UI-review items (`02-UI-REVIEW.md:27-29`): `code` field shape `{"detail": ..., "code": ...}`; dual-404 unification via catch-all handler; raise sites stay minimal-JSON. If the planner folds the handler into api/main.py instead of a new module, main.py L27 wiring region is the insertion point |
| `tests/test_trading_journal.py` | test | file-I/O | No journal test exists anywhere in tests/. Scaffold from tests/test_state.py (autouse isolation) + tests/test_boot.py (module-attr monkeypatch); atomic-write assertions borrow the zt_pool.py:72-78 shape as the oracle |
| README API/known-limits section | doc | — | README.md is a stale v2-era strategy doc with zero API content; no API-contract doc exists in-repo (openapi disabled at api/main.py:27). Content comes from 04-CONTEXT SC5 wording + PROJECT.md classification table, not from any file analog |

## Metadata

**Analog search scope:** `api/` (all 7 modules read in full), `tests/` (conftest + 7 suites read), `scripts/daily/` (zt_pool L55-115, trading_journal full, run_pipeline full, morning_check L1-120 + L400-500, data_health_check L95-124, config full, sync_cloud L20-74), `.planning/` (PROJECT.md full, 02-REVIEW.md WR-01..03 + IN items, 02-UI-REVIEW Top-3, 03-RESEARCH/03-PATTERNS for conventions), root (README full, run_api.bat, .gitignore)
**Files scanned:** 26
**Tracked-source gate (#3645):** every named analog verified git-tracked (`git ls-files` non-empty for api/*, tests/*, run_api.bat, .gitignore, .planning/PROJECT.md, README.md, scripts/daily/*.py named above)
**Repo facts confirmed:** `logs/portfolio.json` + `logs/trading_journal.json` + `logs/candidates_YYYY-MM-DD.json` exist on disk (gitignored, untracked); legacy `candidates_v3_*.json` also present (must be excluded); `data/api_token.txt` not in git history nor sync_cloud whitelist; openapi/docs disabled at api/main.py:27; `api/auth.py` uses request-only signature (prohibition #2); error bodies are plain-string detail everywhere with a single 409 object-detail exception; no date-validation helper exists anywhere in scripts/ (grep-verified); run_pipeline.py argv[1] doubles as command dispatcher (date token must follow `--fast`)
**Pattern extraction date:** 2026-09-04
