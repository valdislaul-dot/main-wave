# Phase 2: Read-Only State Endpoints + Defensive Read Layer - Pattern Map

**Mapped:** 2026-09-03
**Files classified:** 3 (1 new module, 1 new test file, 1 modified)
**Analogs found:** 5 with in-repo analog (api/main.py, api/boot.py, tests/test_health.py, tests/test_boot.py, tests/conftest.py — all git-tracked, verified via `git ls-files`) / 2 no-analog aspects (first `APIRouter`+`HTTPException`+`Response` usage in repo; e2e hammer test shape)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `api/state.py` | controller/route (2 handlers) + service (pure read layer + in-process cache) | file-I/O (local defensive read) + request-response | pure-function half: `api/boot.py`; route half: `api/main.py` (route defs); registration: `api/main.py` imports | exact (per half — see Pattern Assignments) |
| `api/main.py` | app entry (MODIFY: register state router) | request-response | self (`api/main.py:10-30` import + app + route region) | self |
| `tests/test_state.py` | test (contract: STA-01/STA-03/HLT-02/SC4) | request-response (TestClient) + unit (injected reader) + integration (hammer) | `tests/test_health.py` (TestClient contract tests); `tests/test_boot.py` (tmp_path + `monkeypatch.setattr(api.<mod>, "DATA_DIR", ...)`) | exact (per test-style half) |

**Tracked-source gate (#3645):** every analog path in this file was verified tracked this session via `git ls-files -- api/ tests/ scripts/daily/config.py scripts/daily/zt_pool.py` — all print. The three served payload files (`data/market_state.json`, `data/auction_state.json`, `data/zt_pool_state.json`) are also git-tracked and present on disk (785 B / 11 572 B / 48 392 B — matches RESEARCH probes). Grep-verified: `fastapi` is imported ONLY by `api/main.py` and `tests/test_health.py` — no `APIRouter`/`include_router`/`HTTPException`/`fastapi.responses.Response` exists anywhere in the repo yet; those shapes come from 02-RESEARCH.md Patterns 1-4 (prototype-verified on the installed stack), quoted below where they are the only source.

## Pattern Assignments

### `api/state.py` (NEW — controller + service, file-I/O + request-response)

**Two halves, two analogs:** pure read functions + cache = `api/boot.py`; route handlers + module layout = `api/main.py`. Registration pattern = `api/main.py` import region. Wholesale code shape (functions, retry loop, exception class, route bodies) is prototype-verified in 02-RESEARCH.md §Code Examples lines 319-406 — planner MUST copy that as the skeleton; the excerpts below are the repo-native conventions to graft onto it.

**Module docstring / no-side-effect import discipline — copy from `api/main.py:1-9`** (tracked, quoted verbatim):
```python
"""api 包入口: FastAPI app + GET /health + main() 启动序列 (HLT-01, SEC-03, D-03/D-05/D-08)。

模块导入必须无副作用 (Pitfall 3): 不启动、不绑定端口、不写 data/api_token.txt ——
app 与 /health 路由在模块层创建, 启动逻辑全部在 main() 内, 由 __main__ 守卫调用,
这样测试 (TestClient) 可以安全地 import api.main。

路径常量来自 scripts/daily/config.py (D-02), 本模块不计算 BASE、不做 sys.path 操作。
所有控制台文本保持 ASCII-only (Pitfall 5: bat 重定向到 GBK 控制台/日志不得炸编码)。
"""
```
Pins for state.py: same docstring conventions (Chinese, pins requirement IDs `STA-01/STA-03/HLT-02`, D-numbers, zero `BASE` computation, ASCII-only text); import must stay side-effect free — `scripts.daily.config` import runs benign `os.makedirs` (config.py:13-14) which is acceptable, but state.py itself must do no I/O at import.

**Import block pattern — copy from `api/main.py:10-24`** (tracked, quoted verbatim):
```python
import os
import sys
import time

from fastapi import FastAPI

from scripts.daily.config import DATA_DIR
from api.boot import ensure_token, has_token, is_loopback

# uptime 锚点: 模块导入时刻 (对 uvicorn.run 即进程启动时刻)。
# 用 monotonic —— 免疫 NTP/手动改钟导致的墙钟跳变 (T-01-04)。
_START = time.monotonic()

# docs/openapi 关闭 (discretion)。无中间件、无路由依赖 (HLT-01 纯度, Pitfall 6)。
app = FastAPI(title="gogo API", docs_url=None, redoc_url=None, openapi_url=None)
```
state.py adaptation: `from fastapi import APIRouter, HTTPException` + `from fastapi.responses import Response` (repo firsts — RESEARCH.md Code Example, verified on fastapi 0.115.14 / starlette 0.46.2); `from scripts.daily.config import DATA_DIR` verbatim (D-02; config.py imports only `os, sys, platform` — config.py:2, SC4-safe); NEVER import anything else from `scripts/daily` (zt_pool/auction_pool/... drag `requests`/`urllib` into the process and fail the SC4 grep — RESEARCH.md Anti-Patterns). Module globals at state.py top: `STATE_FILES` whitelist dict (D-03), `_CACHE = {}` one slot per name (D-05), `router = APIRouter()`.

**Call-time module-global reference (monkeypatch-ability) — copy from `api/main.py:16` + `tests/test_boot.py:119`:** `DATA_DIR` is imported into the module namespace and referenced INSIDE functions at call time (never bound into a constant at import, never used to compute another module-level path), so tests can `monkeypatch.setattr(api.state, "DATA_DIR", str(tmp_path))`. Same for path resolution inside functions: `os.path.join(DATA_DIR, STATE_FILES[name])` — never a precomputed module-level `STATE_PATH`. This exact mechanism is proven by `test_boot.py:119` (`monkeypatch.setattr(api.main, "DATA_DIR", str(tmp_path))`).

**Route handler shape — copy from `api/main.py:27-30`** (tracked; the repo's only route-definition precedent):
```python
@app.get("/health")
def health():
    """探活 (HLT-01): 纯内存返回, 不读文件、不碰网络、不依赖交易日历 —— 任何时刻恒 200。"""
    return {"status": "ok", "uptime_seconds": int(time.monotonic() - _START)}
```
state.py adaptation: replace `@app.get` with `@router.get("/v1/state/{name}")` and `@router.get("/health/ready")` (repo's first APIRouter — RESEARCH.md Pattern 1 lines 179-194 and Pattern 4 lines 243-254 hold the full handler bodies); keep bare `def`, Chinese docstring, no auth dependency/middleware (Phase 2 public by design, RESEARCH.md Security Domain V4 no-by-design).

**Pure-function read layer style — copy from `api/boot.py:14-27` + `api/boot.py:30-47`** (tracked, quoted verbatim):
```python
def is_loopback(host: str) -> bool:
    """host 是否为回环地址。

    bare "localhost"(不区分大小写) 直接判定为回环; 其余交给
    ipaddress.ip_address(host).is_loopback (覆盖 127.0.0.0/8 与 ::1)。
    无法解析的字符串(含空串)按 fail-closed 返回 False —— 视为非回环,
    从而触发 token 要求。禁止字符串前缀检查 (host.startswith("127."))。
    """
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def read_token(token_path: str):
    """读取 token: GOGO_API_TOKEN 环境变量优先, 文件其次 (D-04, 同 tushare 惯例)。

    环境值先 strip, 非空才生效; 文件以 utf-8 读取并 strip。
    空环境值 / 空文件 / 文件读取失败均视为"无 token" (返回 None)。
    """
    tok = os.environ.get("GOGO_API_TOKEN", "").strip()
    if tok:
        return tok
    if os.path.exists(token_path):
        try:
            with open(token_path, encoding="utf-8") as f:
                tok = f.read().strip()
                if tok:
                    return tok
        except Exception:
            pass
    return None
```
Pins for state.py read functions (`read_state_file`, `get_state`): every function depends only on explicit params + module globals referenced at call time; zero console output anywhere in the module (boot.py prints nothing — the D-05 print discipline lives in main.py; state.py must never print); narrow `except` clauses (boot.py's blanket `except Exception: pass` in read_token is a token-read convenience — DO NOT copy that swallow style into the read layer: RESEARCH.md Pitfall 4 pins retry on `(ValueError, UnicodeDecodeError)`, immediate fallback on `OSError`).

**Error-body convention — NO in-repo analog (first HTTPException in repo).** D-04 pins FastAPI convention `HTTPException(status_code=404, detail="unknown state name")` / `503 detail="state temporarily unavailable"` / `"state file unavailable"` — minimal `{"detail": "..."}`, never a file path, never a bare 500. RESEARCH.md Pattern 1 lines 179-194 (prototype-verified on fastapi 0.115.14) is the shape source.

**Whitelist guard — RESEARCH.md Pattern 1 (D-03/D-04):** unknown `{name}` never reaches path composition; fixed dict lookup → 404. Header values derive only from integers (`str(mtime)`, `str(age)`) — no user/file-controlled strings enter headers (RESEARCH.md Security: header injection structurally impossible).

**Writer behavior the read layer defends against (context for tests) — `scripts/daily/zt_pool.py:72-78`** (tracked, quoted verbatim — atomic writer):
```python
def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    state['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    tmp = STATE_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)
```
Three direct truncate-writers also exist (auction_pool.py:402-404 → auction_state, capture_market_state.py:114-115 → market_state, recalc_seal.py:165-167 + capture_money_flow.py:62-63 → zt_pool_state) — RESEARCH.md §Sources probed mid-write torn reads against them. The read layer is tested against BOTH writer styles but NEVER modifies any pipeline file (Phase 2 boundary; RESEARCH.md Don't Hand-Roll row 7).

**Core module skeleton (only source for the full shape):** 02-RESEARCH.md §Code Examples lines 321-406 — `read_state_file` (open 'rb' → read → `os.fstat(f.fileno()).st_mtime` → close → `json.loads(raw)` validate-only), `StateUnavailable` exception class, `get_state(name, retries=2, retry_delay=0.02)` retry/cache loop, both route handlers, plus the testability design note (inject single-attempt reader as param `reader=_read_file_once` for timer-free unit tests).

---

### `api/main.py` (MODIFIED — one import + one registration line)

**Analog: self** — current file read in full (74 lines, tracked). Two edits only, per 02-RESEARCH.md §Code Examples lines 408-413:

**Registration — insert after the `/health` route block** (`api/main.py:30`), before `def main()` at line 33:
```python
from api.state import router as state_router   # module-level import beside api.boot import (line 17 style)
app.include_router(state_router)
```
Pins: import placement matches the existing `from api.boot import ...` at `api/main.py:17` (module-level, after the `scripts.daily.config` import); registration happens at module level next to the `/health` route — app/routes at module level is the established Phase 1 pattern (`api/main.py:23-30`), `main()` boot sequence (lines 33-69: stdout reconfigure → env parse → SEC-03 checks → lazy uvicorn import → `uvicorn.run`) stays untouched. Nothing in the route registration touches token/boot ordering.

**No change to:** module docstring (may append `+ include_router(state_router)` note if desired, but the import-side-effect-free property must hold — `api.state` import chain is `fastapi` + `scripts.daily.config`, both already imported here); `if __name__ == "__main__":` guard at lines 72-73.

---

### `tests/test_state.py` (NEW — STA-01/STA-03/HLT-02/SC4 contract tests)

**TestClient contract-test shape — copy from `tests/test_health.py:1-37`** (tracked, quoted verbatim):
```python
"""HLT-01 /health 契约测试: 恒 200 + 精确 body + monotonic uptime + 导入无副作用。

全文件不发任何 Authorization 头 —— /health 必须裸请求也 200 (Pitfall 6:
未来任何鉴权中间件必须豁免 /health; 任何断言 /health 401 的测试都违背 HLT-01)。
"""
import os

import pytest
from fastapi.testclient import TestClient

import api.main
from api.main import app
from scripts.daily.config import DATA_DIR

client = TestClient(app)  # 模块级, 无 context manager: 无 lifespan, 无 boot

# 真实 token 路径在本次测试会话开始(模块导入)前是否已存在 ——
# 该测试只 pin "模块导入不创建文件" 的无副作用性, 与生产文件是否在位无关:
# Task 1 的 E2E 回环启动后真实文件可能合法存在 (本机), 全新检出则不存在。
_TOKEN_PATH = os.path.join(DATA_DIR, "api_token.txt")
_TOKEN_EXISTED_AT_IMPORT = os.path.exists(_TOKEN_PATH)


def test_health_returns_200_and_ok():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["uptime_seconds"], int)
    assert body["uptime_seconds"] >= 0


def test_health_body_has_exact_keys_and_json_type():
    response = client.get("/health")
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body.keys()) == {"status", "uptime_seconds"}
```
test_state.py adaptation: module-level `client = TestClient(app)` imports `api.main` (which now registers state routes — one import covers both route families); **CRITICAL data-isolation pin**: `test_state.py` MUST monkeypatch `api.state.DATA_DIR` to `tmp_path` per test — the module-level `client` hits real files otherwise (the real `data/*.json` exist and are git-tracked). The `test_health.py` module-level `DATA_DIR` import at line 13 is only for the no-side-effect probe; state tests need `import api.state` + `monkeypatch.setattr(api.state, "DATA_DIR", str(tmp_path))` BEFORE each GET. Response-header assertions style (`response.headers["content-type"].startswith(...)`, `set(body.keys()) == {...}`) is the house style to copy for `X-Data-Mtime` / `X-Data-Age-S` / `X-Data-Stale` and `{"detail": ...}` error-body assertions. Fixture files: `tmp_path / "market_state.json"` written with `write_bytes` (CRLF fixture — `Path.write_bytes`, per RESEARCH.md Pitfall 1 warning sign) + `os.utime(path, (ts, ts))` for deterministic mtime.

**tmp_path + monkeypatch DATA_DIR units — copy from `tests/test_boot.py:43-54, 117-119`** (tracked, quoted verbatim):
```python
def test_read_token_env_wins_over_file(monkeypatch, tmp_path):
    token_file = tmp_path / "api_token.txt"
    token_file.write_text("file-key", encoding="utf-8")
    monkeypatch.setenv("GOGO_API_TOKEN", "env-key")
    assert read_token(str(token_file)) == "env-key"


def test_loopback_boot_prints_only_notice_and_creates_token(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("GOGO_API_TOKEN", raising=False)
    monkeypatch.setattr(api.main, "DATA_DIR", str(tmp_path))
    _patch_uvicorn_run(monkeypatch)
    api.main.main()  # 不得抛 SystemExit
```
Pins for the unit half of test_state.py: `tmp_path` + `monkeypatch` only (never touch real `data/`); `monkeypatch.setattr(api.state, "DATA_DIR", str(tmp_path))` is the mechanism (mirror of `api.main.DATA_DIR` at test_boot.py:119/136/166); injected-reader fake for retry tests (`get_state(name, reader=fake)` where fake raises `json.JSONDecodeError` N times then succeeds, `retry_delay=0`) keeps tests timer-free (RESEARCH.md §Test shapes 1-5, lines 432-438 — the five test shapes ARE the test plan: verbatim CRLF + exact headers, whitelist 404 matrix, injected-reader retry, warm-cache stale fallback, cold 503, OSError-no-retry, ready matrix incl. ancient-mtime-still-200, SC4 source scan).

**No new fixtures in conftest.py** — the autouse `_no_network` (conftest.py:31-48) and `_clean_env` (51-55) apply automatically (RESEARCH.md Wave 0 Gaps). No analog needed for the e2e 0×5xx hammer test (background-thread truncate-rewrite loop while GETting ~200×) — it is the repo's first threading test; shape in RESEARCH.md §Test shapes item 3 (assertions timing-independent: every response 200, every body parses, stale bodies equal last-known-good fixture).

## Shared Patterns

### Side-effect-free module import + call-time module globals (monkeypatch seam)
**Source:** `api/main.py:1-9, 16, 27-30` + `tests/test_boot.py:119`
**Apply to:** `api/state.py` (module level holds only constants/app/router/`_CACHE`; zero prints, zero I/O at import), `api/main.py` (registration adds no import side effects — `api.state` chain is fastapi + config, both already imported). Regression-test convention: `test_health.py:46-52` proves import creates no file — test_state.py should analogously prove `import api.state` does no file I/O.

### Path constants single source (D-02)
**Source:** `scripts/daily/config.py:5-7` (`DATA_DIR = os.path.join(PROJECT_ROOT, 'data')`) consumed at `api/main.py:16`
**Apply to:** `api/state.py` — `from scripts.daily.config import DATA_DIR` only; zero per-module `BASE` computation, zero `sys.path.insert` bootstrap (ARCHITECTURE.md anti-pattern #1; Phase 1 D-02 pins it).

### Data-reference discipline (raw passthrough)
**Source:** CLAUDE.md 数据引用纪律 + D-01/D-02 (CONTEXT.md:23-25)
**Apply to:** `api/state.py` — serve file bytes verbatim (binary read; `json.loads` validate-only, parsed object discarded — never re-`json.dumps`, never text-mode read which rewrites CRLF→LF on Windows).

### Zero-network GET discipline (three independent layers)
**Source:** `tests/conftest.py:31-48` (runtime net-block autouse) + RESEARCH.md SC4 grep + module import restriction
**Apply to:** `api/state.py` (imports only `scripts.daily.config`; no requests/urllib/httpx/aiohttp/socket anywhere in api/*.py), `tests/test_state.py` (SC4 source-scan regression test reading `api/state.py` + `api/main.py` text, asserting no banned tokens). Runnable audit command (plan deliverable): `grep -nE "(requests|urllib|httpx|aiohttp|socket)(\.|[[:space:]]*import|import)" api/*.py` → no output.

### Minimal JSON error bodies (D-04)
**Source:** No repo analog (Phase 1 has zero error routes) — RESEARCH.md Pattern 1 (prototype-verified `{"detail": "..."}` via `HTTPException` on fastapi 0.115.14)
**Apply to:** `api/state.py` both handlers — 404 unknown name (client error) vs 503 missing/unreadable (server condition, same 503 vocabulary as /health/ready); persistent decode failure NEVER 5xx (200 stale with `X-Data-Stale: true`, or 503 cold); detail strings never contain file paths.

### Windows file-handle discipline
**Source:** `scripts/daily/zt_pool.py:72-78` (atomic writer the reader must not block) + RESEARCH.md Pitfall 2 (probe: open read handle → `os.replace` fails WinError 5)
**Apply to:** `api/state.py` — open → read → fstat → close per attempt (no held handles across retry sleeps, no `FileResponse` streaming, readiness uses stat/access never `open()`).

## No Analog Found

| File / Aspect | Role | Data Flow | Reason |
|---------------|------|-----------|--------|
| `api/state.py` route layer (`APIRouter`, `HTTPException`, `fastapi.responses.Response`) | controller/route | request-response | Grep-verified: repo has zero `APIRouter`/`include_router`/`HTTPException`/`Response` usage; `api/main.py:24-30` registers via bare `@app.get`. Handler bodies MUST come from 02-RESEARCH.md Patterns 1-4 (lines 179-254) + Code Example skeleton (lines 319-406) — prototype-verified on installed fastapi 0.115.14 / starlette 0.46.2 |
| `tests/test_state.py` e2e 0×5xx hammer | test (integration, threaded writer) | event-driven (background writer) | Repo's first threading test; no analog. Shape: RESEARCH.md §Test shapes item 3 (warm cache, background `open('wb')` truncate + partial write + sleep + complete loop, ~200 GETs, timing-independent assertions) |
| `tests/test_state.py` SC4 source-scan test | test (static) | n/a | No source-scan test exists in repo (Phase 1 suite is 18 tests, contract+unit only) |

## Metadata

**Analog search scope:** `api/` (all 3 files read in full), `tests/` (all 4 files read in full), `scripts/daily/config.py` (read in full), `scripts/daily/zt_pool.py:55-94` (save_state atomic writer), `.planning/phases/01-*/01-CONTEXT.md` + `01-PATTERNS.md` (Phase 1 conventions), `pytest.ini`, repo-wide grep for fastapi/APIRouter/include_router usage.
**Files scanned:** 11 (api/main.py, api/boot.py, api/__init__.py, tests/test_health.py, tests/test_boot.py, tests/conftest.py, scripts/daily/config.py, scripts/daily/zt_pool.py:55-94, pytest.ini, 01-CONTEXT.md, 01-PATTERNS.md) + state-file existence/size checks
**Tracked-source verification:** `git ls-files` confirmed tracked: api/main.py, api/boot.py, api/__init__.py, tests/conftest.py, tests/test_boot.py, tests/test_health.py, scripts/daily/config.py, scripts/daily/zt_pool.py, data/market_state.json, data/auction_state.json, data/zt_pool_state.json
**Pattern extraction date:** 2026-09-03
