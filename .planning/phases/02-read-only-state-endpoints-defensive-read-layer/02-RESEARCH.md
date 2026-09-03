# Phase 2: Read-Only State Endpoints + Defensive Read Layer - Research

**Researched:** 2026-09-03
**Domain:** FastAPI read-only state passthrough + defensive local-file read layer on Windows (single-process uvicorn)
**Confidence:** HIGH

## Summary

Phase 2 adds two route families to the Phase 1 `api/` package with **zero new package dependencies** (machine-verified: fastapi 0.115.14 / starlette 0.46.2 / Python 3.13.1 / pytest 9.1.1 / httpx 0.25.2 already installed): `GET /v1/state/{name}` (verbatim JSON file-body passthrough for a 3-name whitelist, with `X-Data-Mtime` / `X-Data-Age-S` headers) and `GET /health/ready` (stat-only existence/readability check, 200/503, never data-age). The defensive read layer (STA-03) is: per-request `open('rb') → read → fstat → close`, `json.loads(bytes)` validation of the exact bytes read, short retry only on decode errors, and a process-local last-successful-payload cache per name served as 200 with `X-Data-Stale: true` when the file persistently fails to decode — never a bare 500, never a silent success.

Three empirical probes this session materially shaped the design and corrected a training assumption:

1. **All three served files contain CRLF line endings** (785 B / 11.5 KB / 48.4 KB, all valid UTF-8 JSON). Verbatim passthrough (D-01/D-02) therefore requires **binary-mode reads** — a text-mode read would translate CRLF→LF and silently violate the byte-verbatim contract.
2. **On this Windows machine, `os.replace` fails with PermissionError [WinError 5] while any other handle has the target open for reading** (Python `open()` grants read/write share but not `FILE_SHARE_DELETE`). Python's own atomic writer (`scripts/daily/zt_pool.py:72-78`) will fail if the API holds a state file open at the wrong instant — the read layer must open → read → close per request and never hold handles across retries or stream via `FileResponse`. This makes the CONTEXT's "不持长句柄" rule load-bearing, not stylistic.
3. **Torn reads are real**: three writers of the served files (`auction_pool.py:402-404` auction_state, `capture_market_state.py:114-115` market_state, `recalc_seal.py:165-167` + `capture_money_flow.py:62-63` zt_pool_state) truncate-then-write directly (only `zt_pool.save_state` is atomic). A mid-write reader empirically observed partial content → `json.loads` failed. STA-03's retry + last-good-cache fallback is not theoretical defense; it is the only thing standing between consumers and torn JSON during every pipeline run.

A full TestClient prototype of the proposed module (whitelist 404, missing 503 `{"detail": ...}`, verbatim fresh 200 with exact mtime/age headers, torn-then-repaired 200, persistent-torn-with-warm-cache 200 + `X-Data-Stale: true` + cached mtime coherence, cold persistent-torn 503) passed every contract branch on the installed stack.

**Primary recommendation:** One new module `api/state.py` (whitelist map + pure read functions + last-good cache + `APIRouter` with the two routes), registered in `api/main.py` via `app.include_router`. Read files in binary mode, validate with `json.loads(raw)`, derive mtime via `os.fstat` on the same handle, retry decode failures twice with ~20 ms between fresh attempts, fall back to the per-name in-memory last-good payload with `X-Data-Stale: true`. No new packages; new tests in `tests/test_state.py`.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** GET /v1/state/{name} 响应体 = 管线写入的原始 JSON 文件体,逐字节透传,不加工、不封装。新鲜度通过响应头表达:X-Data-Mtime(文件 mtime,Unix epoch 秒,整数)与 X-Data-Age-S(now − mtime,整数秒)。— **Reversibility:** one-way — 一旦外部消费方按 raw body 契约接入,改为 JSON 信封 {meta,data} 会破坏全部既有消费方(ROADMAP SC1 亦字面要求 "raw JSON file body exactly as the pipeline wrote it")。
- **D-02:** 成功响应 Content-Type: application/json;透传时响应体不做任何重格式化(保留原字节,含管线写出的缩进/键序)。
- **D-03:** /v1/state/{name} 仅接受固定三名的显式映射:`market_state` → `data/market_state.json`、`auction_state` → `data/auction_state.json`、`zt_pool_state` → `data/zt_pool_state.json`。未知名一律 404。不做 DATA_DIR 下任意文件名的动态解析——无路径穿越面,Phase 4 分级前持仓/账本/候选天然不可达(SEC-02 精神先行)。— **Reversibility:** costly — 新增服务文件需加映射+测试,但这是有意的窄入口而非缺陷;未来 STA-02/新状态名按 Phase 4 分级政策在同一映射表扩展。
- **D-04:** 错误码分工:未知名 404(客户端错误);已知名但文件缺失/不可读 503(服务端问题,与 /health/ready 同口径)。持续解码失败不回 5xx,而是回退末次成功缓存(STA-03 字面),见 D-05。错误体用 FastAPI 惯例的最小 JSON `{"detail": "..."}`,不含文件路径。
- **D-05:** 读层协议:open → read → close(每次请求完整打开关闭,不持长句柄);JSONDecodeError 短重试(读新的文件快照);持续失败回退进程内末次成功缓存,响应头标 `X-Data-Stale: true`(体仍是合法 JSON = 末次成功载荷,消费方可正常解析)。stale 标记只在回退路径出现,正常路径不发送该头。— **Reversibility:** reversible — 纯内部读策略,消费方契约仅多一个可选响应头。

### Claude's Discretion

- /health/ready (HLT-02/Decision E) 按需求字面:3 个白名单文件全部存在且可读 → 200;任一缺失/不可读 → 503;数据新旧不参与判断(夜间/周末/假期永不 503)。就绪检查体保持最小 JSON(与 Phase 1 /health 同风格)。
- stale 兜底不做主动年龄阈值(用户未选该区):仅解码失败触发回退;消费方用 X-Data-Age-S 自行判新旧。
- 末次成功缓存的实现位置(进程内模块级缓存/每名一槽)与短重试次数(2-3 次)由研究/规划按 STA-03 字面选定。
- 读层函数放 api/ 包内新模块(如 api/state.py),沿 D-02 路径纪律从 scripts/daily/config.py 导入路径常量;禁止在 GET 处理器中出现任何 requests/urllib 调用(SC4 grep 审计)。

### Deferred Ideas (OUT OF SCOPE)

- None — discussion stayed within phase scope (todo match count: 0)。未选的两区(stale 年龄阈值、ready 检查集细化)按 ROADMAP/需求字面落入 Claude's Discretion。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HLT-02 | GET /health/ready — stat 状态文件存在性/可读性,仅不可读 503,不看数据新旧 | Readiness convention verified (200/503 semantics matches k8s-style readiness, MEDIUM); stat/`os.access` check design avoids open-handle collisions with pipeline writers (Pitfall 2); whitelist = same 3 files as STA-01 |
| STA-01 | GET /v1/state/{name} 透传 market_state/auction_state/zt_pool_state + X-Data-Mtime/X-Data-Age-S | Byte-verbatim mechanics verified: binary-mode read required (all 3 files CRLF, probe); `json.loads(bytes)` validates without re-serialization (probe); same-handle `os.fstat` mtime coherence (probe); Response content-type/content-length behavior verified on installed starlette 0.46.2 |
| STA-03 | 防御性读层 — 开→读→关、JSONDecodeError 短重试、末次成功缓存回退带 stale 标记 | Torn-read risk empirically confirmed (3 direct-`'w'` writers, probe showed mid-write decode failure); retry+last-good-cache = stale-if-error pattern; Windows handle-sharing probe proves open→read→close discipline protects the pipeline's own os.replace; full TestClient prototype of the protocol passed all branches |

</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Serve state file bodies verbatim | API / Backend | Storage (data/ files) | API tier reads files the pipeline (separate processes) writes; passthrough = read + validate, never transform (D-01) |
| Freshness headers (mtime/age) | API / Backend | Storage | Headers derived from the storage file's real mtime via same-handle `os.fstat` (STA-01) |
| Torn-write defense (retry + last-good cache) | API / Backend | — | In-process read-layer concern (STA-03); pipeline writers are NOT modified in this phase (writer atomicization deferred to Phase 3 discussion) |
| Whitelist enforcement / path-traversal guard | API / Backend | — | Fixed 3-name dict map at the route boundary (D-03); no dynamic path composition |
| Readiness (existence/readability) | API / Backend | Storage | stat-based probe of the same 3 whitelist files (HLT-02); never touches data age |
| Zero-network GET discipline | API / Backend | — | Structural rule: `api/state.py` imports only `scripts.daily.config`; SC4 grep audit + conftest net-block backstop |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | 0.115.14 (installed) | App, routes, `HTTPException` error bodies | Phase 1 pinned; repo requirements.txt `fastapi>=0.115.14` [VERIFIED: pip, machine-verified 2026-09-03] |
| starlette | 0.46.2 (installed) | `Response(content=bytes, media_type="application/json", headers=...)` | Underlies FastAPI; behavior probed this session on the exact installed version |
| python | 3.13.1 (installed) | `json.loads(bytes)`, `os.fstat`, `os.replace` semantics | Repo runtime; all probes run on it |
| pytest + httpx (TestClient) | 9.1.1 / 0.25.2 (installed) | Contract tests | Phase 1 suite conventions (OPS-02), conftest network block |

**No new packages are required for this phase.** Decision: do not add orjson/aiofiles/anyio-streaming/filelock — file sizes are ≤ 48 KB, single user, single process.

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| — (stdlib only: `os`, `json`, `time`) | — | Defensive read layer | Always; STA-03 is a pure-stdlib pattern |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `Response(content=raw_bytes)` | `FileResponse` | FileResponse opens its own handle and streams over the network — holds the file open for the whole client download, which can block the pipeline's `os.replace` on Windows (Pitfall 2). Also bypasses validate/retry/cache. Rejected |
| `Response(content=raw_bytes)` | `PlainTextResponse` / JSONResponse re-encode | Re-encoding destroys verbatim bytes (indent/key order/CRLF); JSONResponse always re-serializes. Rejected |
| Binary `open('rb')` + `json.loads(bytes)` | Text `open('r', encoding='utf-8')` | Text mode applies universal-newline translation on Windows (CRLF→LF) — corrupts the verbatim body (Pitfall 1). Rejected |
| Freshness via `Last-Modified` + `Age` HTTP-standard headers | Custom `X-Data-*` | Custom headers are user-locked (D-01); standard headers can be added later with ETag work (OPS-04, v2). Do not substitute |
| Process-local dict cache | Redis/file-backed cache | Single-process discipline; service restart legitimately cold-starts from files. File-backed cache adds staleness-of-its-own complexity. Rejected |

**Installation:** none. `requirements.txt` unchanged.

## Package Legitimacy Audit

> This phase installs no external packages — the Package Legitimacy Gate protocol is not triggered (fastapi/starlette/httpx/pytest are already installed and pinned by Phase 1, machine-verified above).

**Packages removed due to [SLOP] verdict:** none (nothing installed)
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```text
                        ┌─────────────────────────────┐
                        │  pipeline processes (sep.)   │
                        │  zt_pool.save_state: tmp+    │
                        │    os.replace (atomic)       │
                        │  auction_pool / market_state │
                        │  / recalc_seal / money_flow: │
                        │    open('w') truncate-write  │
                        └─────────────┬───────────────┘
                                      │ writes
                                      ▼
                        data/market_state.json
                        data/auction_state.json
                        data/zt_pool_state.json     (CRLF UTF-8)
                                      ▲
                                      │ per-request reads
┌─────────────────────────────────────┴────────────────────────────┐
│ uvicorn resident process (api.main)                              │
│                                                                  │
│  GET /health              → in-memory only (Phase 1, untouched)  │
│  GET /health/ready        → stat + os.access × 3 whitelist files │
│  GET /v1/state/{name}     → whitelist dict lookup                │
│        name unknown ────────► 404 {"detail": ...}                │
│        known: path = DATA_DIR + map[name]                        │
│        ┌───────────────────────────────────────────────────┐     │
│        │ api/state.py defensive read layer                 │     │
│        │   attempt ≤ 3 (retries=2, ~20ms apart):            │     │
│        │     open('rb') → read all → fstat → close          │     │
│        │     json.loads(bytes)  (validate only)             │     │
│        │   decode fail → next attempt (fresh snapshot)      │     │
│        │   OSError → fallback immediately                   │     │
│        │   exhausted & cache hit → 200 stale (X-Data-Stale) │     │
│        │   exhausted & no cache → 503 {"detail": ...}       │     │
│        │   success → cache[name] = {raw, mtime}; 200 fresh  │     │
│        └───────────────────────────────────────────────────┘     │
│  200 body = raw bytes verbatim + Content-Type: application/json │
│  + X-Data-Mtime: <epoch s> + X-Data-Age-S: <int s>               │
│  [+ X-Data-Stale: true only on cache fallback]                   │
└──────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure

```
api/
├── __init__.py        # empty (Phase 1)
├── main.py            # + app.include_router(state.router) — one line, no other change
├── boot.py            # untouched (Phase 1)
└── state.py           # NEW: whitelist map, pure read layer, last-good cache, router
tests/
├── conftest.py        # untouched — net-block + env isolation apply automatically
├── test_health.py     # untouched
├── test_boot.py       # untouched
└── test_state.py      # NEW: STA-01/STA-03/HLT-02 contract tests
```

`api/state.py` module-level shape (mirrors `boot.py` purity + `main.py`'s monkeypatchable `DATA_DIR` reference):

```python
# module globals only — import must be side-effect free (no prints, no I/O)
DATA_DIR = DATA_DIR_from_config          # referenced at CALL time so tests can monkeypatch
STATE_FILES = {"market_state": "market_state.json", ...}   # D-03 whitelist, verbatim names
_CACHE = {}                              # per-name one slot: {name: {"raw": bytes, "mtime": int}}
router = APIRouter()
```

Path resolution inside functions (`os.path.join(DATA_DIR, STATE_FILES[name])`) keeps `monkeypatch.setattr(api.state, "DATA_DIR", str(tmp_path))` effective, exactly like `test_boot.py`/`test_health.py` do with `api.main.DATA_DIR`.

### Pattern 1: Whitelist passthrough endpoint (D-03/D-04)

**What:** `/v1/state/{name}` with `name` resolved ONLY through the fixed dict; everything else 404. Error bodies are FastAPI's `HTTPException` → `{"detail": "..."}` (prototype-verified on installed stack); no file path ever appears in a detail string.
**When to use:** any phase that exposes file-backed state by name.

```python
@router.get("/v1/state/{name}")
def state_endpoint(name: str):
    if name not in STATE_FILES:
        raise HTTPException(status_code=404, detail="unknown state name")
    try:
        kind, raw, mtime = get_state(name)
    except StateUnavailable:
        raise HTTPException(status_code=503, detail="state temporarily unavailable")
    headers = {"X-Data-Mtime": str(mtime), "X-Data-Age-S": str(max(0, int(time.time() - mtime)))}
    if kind == "stale":
        headers["X-Data-Stale"] = "true"
    return Response(content=raw, media_type="application/json", headers=headers)
```
[VERIFIED: TestClient prototype on fastapi 0.115.14/starlette 0.46.2 this session — 404/503 bodies, header wire format, stale-header absence on fresh path]

### Pattern 2: Same-handle read + validate (verbatim bytes, STA-01)

**What:** open once in binary, read everything, take mtime from the SAME open handle (`os.fstat`), close, then validate the exact bytes read with `json.loads(bytes)`. No stat-then-read (race between the two system calls can mismatch body and mtime), no re-serialization, no text mode.
**When to use:** every payload read on the fresh path.

```python
def read_state_file(path):
    """open → read → fstat → close. Returns (raw_bytes, mtime_epoch_int)."""
    with open(path, "rb") as f:
        raw = f.read()
        mtime = int(os.fstat(f.fileno()).st_mtime)
    json.loads(raw)          # validation ONLY — never re-serialize (bytes → parsed → discarded)
    return raw, mtime
```
[VERIFIED: local probe — `json.loads(bytes)` accepts CRLF UTF-8; `os.fstat(f.fileno()).st_mtime` returns the mtime of the exact version read; `json.dumps(parsed)` does NOT reproduce the original bytes]

### Pattern 3: Decode-error retry then last-good cache (STA-03, stale-if-error)

**What:** retries happen ONLY on decode failures (`json.JSONDecodeError` ⊂ `ValueError`, plus `UnicodeDecodeError`) — each attempt is a fresh `read_state_file` (new file snapshot, no held handle between attempts). Any `OSError` (missing/unreadable) skips retries and goes straight to fallback per the STA-03 letter. Fallback = per-name one-slot process cache holding the last successfully read `(raw, mtime)`; served as 200 with `X-Data-Stale: true` and the CACHED mtime (body↔mtime coherence — the age header then honestly describes the served payload). Empty cache (cold start) + exhausted retries → 503 `{"detail": ...}` (D-04's "不可读 503" reading; never a bare 500).

```python
def get_state(name, retries=2, retry_delay=0.02, clock=time.time):
    path = os.path.join(DATA_DIR, STATE_FILES[name])
    for attempt in range(retries + 1):
        try:
            raw, mtime = read_state_file(path)
            _CACHE[name] = {"raw": raw, "mtime": mtime}
            return "fresh", raw, mtime
        except (ValueError, UnicodeDecodeError):
            if attempt < retries:
                time.sleep(retry_delay)          # writer's truncate-write window is ms-scale
        except OSError:
            break                                # missing/unreadable → fallback now
    entry = _CACHE.get(name)
    if entry is not None:
        return "stale", entry["raw"], entry["mtime"]
    raise StateUnavailable
```
[VERIFIED: TestClient prototype — torn-then-repaired 200 fresh; persistent-torn with warm cache 200 + stale:true + cached mtime; cold persistent-torn 503 {"detail": ...}]

**Design note for testability:** make the retry loop deterministic in unit tests by injecting the single-attempt reader as a parameter (`reader=_read_file_once` default) and faking it to fail N times then succeed — no sleeps, no wall-clock races. The end-to-end 0×5xx test (below) then uses a real truncate-rewrite loop.

### Pattern 4: /health/ready — stat only, never open (HLT-02)

**What:** for each of the 3 whitelist files: `os.stat` (existence) + `os.path.isfile` (not a directory) + `os.access(path, os.R_OK)`. All pass → 200 minimal JSON; any failure → 503 `{"detail": ...}`. **Deliberately no `open()`**: an open probe would itself create the exact reader-handle window that blocks a pipeline `os.replace` (Pitfall 2). No data-age, no calendar, no decode checks — stale data never 503s.

```python
@router.get("/health/ready")
def ready():
    for filename in STATE_FILES.values():
        path = os.path.join(DATA_DIR, filename)
        try:
            if not os.path.isfile(path) or not os.access(path, os.R_OK):
                raise HTTPException(status_code=503, detail="state file unavailable")
        except OSError:
            raise HTTPException(status_code=503, detail="state file unavailable")
    return {"status": "ready"}
```
[ASSUMED: minimal body `{"status": "ready"}` — discretion zone, mirrors Phase 1 /health style; 200/503 contract verified by prototype]

### Anti-Patterns to Avoid

- **Text-mode file reads on Windows:** universal-newline translation rewrites CRLF→LF; the body stops being verbatim. All three served files are CRLF today. Read `'rb'`, always.
- **Holding the file open while sleeping/retrying or streaming to the client:** on Windows an open read handle makes the pipeline's `os.replace` fail with WinError 5 (probed). Close before the retry sleep; never `FileResponse`.
- **stat-then-read for mtime:** the file can be replaced between the two calls, mismatching header and body. `fstat` the handle you read from.
- **`json.loads` then re-`json.dumps`:** destroys indent/key order/CRLF — the byte contract. Validate and discard the parsed object.
- **Retrying OSError:** STA-03's retry is for torn JSON (decode). Missing/unreadable is deterministic per request; retry only delays the 503.
- **Serving a bare 500 on persistent decode failure:** violates SC2. Cache fallback (200 stale) when warm; 503 with `{"detail": ...}` when cold — both are FastAPI JSON error shapes.
- **Putting age/newest-ness into /health/ready:** HLT-02 letter says stat-only; night/weekend/holiday staleness must never 503 (readiness convention, MEDIUM).
- **Importing network-capable modules into the api package:** `api/state.py` may import `scripts.daily.config` (imports only `os, sys, platform` [VERIFIED: scripts/daily/config.py:2]) — importing anything else from `scripts/daily` (zt_pool, auction_pool, …) drags `requests`/`urllib` into the process and fails the SC4 grep.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Validate JSON without reserializing | Custom parser / partial-parse tricks | `json.loads(raw_bytes)` | Stdlib accepts bytes directly, validates UTF-8 + grammar; parsed object discarded |
| HTTP error bodies | Custom error envelope | `HTTPException(status_code, detail=...)` | FastAPI convention `{"detail": "..."}` (D-04), prototype-verified |
| Raw response with headers | Custom ASGI response class | starlette `Response(content=raw, media_type="application/json", headers=...)` | Content-Type exact `application/json` (no charset for non-text/*), Content-Length auto — both probe-verified on 0.46.2 |
| Last-good cache persistence | Redis/file-backed cache | Process-local dict (one slot per name) | Single-process discipline; restart legitimately cold-starts from files |
| ETag / conditional requests | Cache validators now | (deferred OPS-04, v2) | Not needed until polling volume proves it; `X-Data-Age-S` covers freshness needs |
| Writer-side atomicity | Rewriting pipeline writers | (read-side defense only; Phase 3 sign-off gate) | Phase 2 must not modify any pipeline file; ROADMAP Phase 3 discusses writer atomicization |

**Key insight:** the read layer's job is to make *any* writer behavior — atomic or truncate-write — invisible to consumers. Validate-then-serve with decode-retry + stale-if-error fallback is correct under both, so Phase 2 needs no pipeline changes and no cross-process locks.

## Common Pitfalls

### Pitfall 1: Verbatim contract broken by newline translation
**What goes wrong:** response body differs from the file (CRLF → LF) — subtle for JSON parsers, fatal for byte-exact consumers (D-01 "逐字节透传").
**Why it happens:** `open(path, encoding='utf-8')` on Windows applies universal-newline translation. All three served files are CRLF today [VERIFIED: byte probe of data/*.json].
**How to avoid:** read `'rb'`; validate via `json.loads(raw)`; serve the same bytes.
**Warning signs:** a test comparing `response.content` to fixture bytes fails only on Windows CRLF fixtures; writing fixtures with `Path.write_bytes`.

### Pitfall 2: Reader handle blocks the pipeline's atomic replace (Windows)
**What goes wrong:** pipeline `zt_pool.save_state` (tmp + `os.replace`) raises `PermissionError [WinError 5]`; the state file silently stays stale and a `.tmp` file is left behind.
**Why it happens:** Python `open()` on Windows shares read/write but not delete; `os.replace` needs delete access to the target [VERIFIED: probe — replace failed while a read handle was open, py3.13.1 on this machine].
**How to avoid:** open → read → fstat → close within microseconds per request; close before any sleep; never stream with `FileResponse`; readiness check uses stat/access, not `open()`.
**Warning signs:** `PermissionError` on `os.replace` in pipeline logs; API tests that keep a file handle open across retries.

### Pitfall 3: Body/mtime mismatch (header lies about payload)
**What goes wrong:** `X-Data-Mtime`/`X-Data-Age-S` describe a different file version than the body when the pipeline replaces the file between stat and read.
**How to avoid:** `os.fstat(f.fileno())` on the very handle whose bytes were read (probe-verified); cache the mtime together with the cached bytes so stale responses carry the stale payload's real mtime.
**Warning signs:** age headers that jump backward while bodies stay identical.

### Pitfall 4: "Decode failure" catch is too narrow or too wide
**What goes wrong:** catching only `json.JSONDecodeError` misses `UnicodeDecodeError` (truncation can split a multibyte char); catching `Exception` swallows `OSError` and turns missing files into 200-stale lies.
**How to avoid:** retry on `(ValueError, UnicodeDecodeError)` — `JSONDecodeError` is a `ValueError` subclass; treat `OSError` as the immediate fallback/503 path per STA-03 letter.
**Warning signs:** tests that only exercise ASCII-truncated files; a retry loop that masks a deleted file.

### Pitfall 5: 5xx leakage during live writes
**What goes wrong:** SC2 requires 0×5xx during pipeline writes. A cold-started server (restarted mid-run, empty cache) that catches every attempt inside a truncate-write window is the one residual 503 path.
**Why it happens:** no last-good payload exists yet to fall back to.
**How to avoid:** accept and document the cold-start edge (retry budget makes it improbable: 3 attempts over ~40 ms vs ms-scale write windows); once any read succeeds, the cache is warm for the rest of the process life.
**Warning signs:** 503s only in the first seconds after a service restart that coincides with a pipeline run.

### Pitfall 6: Framework charset assumptions
**What goes wrong:** hand-built `content-type` headers ("application/json; charset=utf-8" or missing) drift from D-02's wire contract.
**Why it happens:** charset is appended only for `text/*` media types; `application/json` gets no charset [VERIFIED: starlette 0.46.2 probe + fastapi docs].
**How to avoid:** pass `media_type="application/json"` to `Response`; never hand-craft the header.
**Warning signs:** content-type assertions in tests that require an exact string.

## Code Examples

### api/state.py skeleton (prototype-validated contract)

```python
"""Phase 2: read-only state passthrough + defensive read layer (STA-01/STA-03/HLT-02).

Import must stay side-effect free. No network-capable imports (SC4).
DATA_DIR is a module global referenced at call time so tests can
monkeypatch.setattr(api.state, "DATA_DIR", str(tmp_path)) — the
test_boot.py/test_health.py pattern.
"""
import os
import time
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from scripts.daily.config import DATA_DIR  # D-02 path discipline (imports only os/sys/platform)

STATE_FILES = {  # D-03 whitelist — unknown names 404, never dynamic path resolution
    "market_state": "market_state.json",
    "auction_state": "auction_state.json",
    "zt_pool_state": "zt_pool_state.json",
}
_CACHE = {}  # name -> {"raw": bytes, "mtime": int}; one slot per name (in-process only)
router = APIRouter()


def read_state_file(path):
    """open -> read -> fstat -> close; validate-only json.loads. Returns (raw, mtime)."""
    with open(path, "rb") as f:
        raw = f.read()
        mtime = int(os.fstat(f.fileno()).st_mtime)
    json.loads(raw)
    return raw, mtime


class StateUnavailable(Exception):
    """File missing/unreadable AND no last-good cache entry."""


def get_state(name, retries=2, retry_delay=0.02):
    """STA-03: decode-error short retry; persistent failure -> last-good cache; else raise."""
    path = os.path.join(DATA_DIR, STATE_FILES[name])
    for attempt in range(retries + 1):
        try:
            raw, mtime = read_state_file(path)
            _CACHE[name] = {"raw": raw, "mtime": mtime}
            return "fresh", raw, mtime
        except (ValueError, UnicodeDecodeError):
            if attempt < retries:
                time.sleep(retry_delay)
        except OSError:
            break
    entry = _CACHE.get(name)
    if entry is not None:
        return "stale", entry["raw"], entry["mtime"]
    raise StateUnavailable


@router.get("/v1/state/{name}")
def get_state_endpoint(name: str):
    if name not in STATE_FILES:
        raise HTTPException(status_code=404, detail="unknown state name")  # D-04
    try:
        kind, raw, mtime = get_state(name)
    except StateUnavailable:
        raise HTTPException(status_code=503, detail="state temporarily unavailable")
    headers = {
        "X-Data-Mtime": str(mtime),                                   # D-01 integer epoch s
        "X-Data-Age-S": str(max(0, int(time.time() - mtime))),        # D-01 integer s, clamp >= 0
    }
    if kind == "stale":
        headers["X-Data-Stale"] = "true"                              # D-05: fallback path only
    return Response(content=raw, media_type="application/json", headers=headers)


@router.get("/health/ready")
def ready():  # HLT-02: stat existence/readability only — never data age, never open()
    for filename in STATE_FILES.values():
        path = os.path.join(DATA_DIR, filename)
        try:
            if not os.path.isfile(path) or not os.access(path, os.R_OK):
                raise HTTPException(status_code=503, detail="state file unavailable")
        except OSError:
            raise HTTPException(status_code=503, detail="state file unavailable")
    return {"status": "ready"}
```

Registration in `api/main.py` (after the `/health` route; do not disturb the `main()` boot sequence):

```python
from api.state import router as state_router
app.include_router(state_router)
```

### Consumer verification (manual smoke)

```bash
curl -s -D - http://127.0.0.1:8000/v1/state/market_state -o /tmp/body.json
# expect: HTTP/1.1 200, content-type: application/json, x-data-mtime: <int>,
#         x-data-age-s: <int>, NO x-data-stale
cmp /tmp/body.json data/market_state.json && echo BYTE-IDENTICAL
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/v1/state/portfolio   # 404
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/health/ready          # 200
```

### SC4 grep audit (must be a plan deliverable — runnable verify command)

```bash
grep -nE "(requests|urllib|httpx|aiohttp|socket)(\.|[[:space:]]*import|import)" api/*.py   # expect: no output
```

### Test shapes for tests/test_state.py (deterministic — no wall-clock races)

1. **Unit, injectable reader:** `get_state(name, reader=fake)` where fake raises `json.JSONDecodeError` on attempts 1..N — assert attempt count, fresh success, cache update, and that `retry_delay=0` makes the test timer-free.
2. **Byte verbatim:** write a CRLF fixture (`Path.write_bytes`), `os.utime` to a fixed epoch, GET, assert `response.content == fixture_bytes` and exact header values.
3. **E2E 0×5xx hammer (SC2):** warm the cache with one GET; then a background thread loops `open('wb')` truncate + partial write + sleep + complete on a fixture file while the test GETs ~200×; assert every response is 200, every body parses as JSON, and any `X-Data-Stale: true` body equals the last known good fixture. (Assertion is timing-independent; passes iff the design is right.)
4. **HLT-02 matrix:** all 3 present → 200; unlink one → 503; make one a directory → 503; set mtime to last year → still 200.
5. **SC4 regression:** read `api/state.py` and `api/main.py` source text; assert no banned network tokens (conftest net-block is the runtime backstop).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Consumers read data/*.json directly (gui_cloud.py `_load`, Streamlit cache TTL 120) | HTTP passthrough with freshness headers | This phase | Consumers can poll for change via X-Data-Mtime/Age-S instead of guessing TTLs |
| Serve stale as default first-request behavior (stale-while-revalidate) | Serve stale ONLY on genuine read failure (stale-if-error) | Web cache/CDN practice (Varnish `beresp.grace`, Cloudflare `stale-if-error`) | Fallback never masks fresh data; the last-good cache is a failure path, not a TTL cache |
| Readiness endpoint checks data freshness | Readiness checks only critical-resource existence; liveness stays trivial | k8s probe convention | /health/ready 503 only on missing/unreadable files; night/weekend/holiday never 503s |

**Deprecated/outdated:**
- None directly; note `Last-Modified`/`Age`/`ETag` conditional-request machinery is the HTTP-standard evolution of the custom `X-Data-*` headers — deferred deliberately (OPS-04, v2, only when polling volume proves it).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Windows handle-sharing finding (reader blocks `os.replace`) generalizes to cross-process (probe was same-process; share modes are enforced per-handle by the OS regardless of process boundary) | Pitfalls 2 | If wrong, collisions are even rarer — design unchanged; short handles remain correct on both models |
| A2 | Pipeline direct-write windows are ms-scale for ≤ 48 KB files, so 2 retries × ~20 ms close most torn reads | Patterns 3 | If a writer stalls mid-write longer than the retry budget, the last-good cache still serves valid JSON — consumers never see torn data, only possibly stale (flagged) |
| A3 | Empty-cache + persistent decode failure → 503 `{"detail": ...}` is the correct STA-03/D-04 reading ("不可读" 503; never bare 500) | Patterns 3 | Planner/executor may prefer 200 with an explicit empty state — would deviate from D-04's 503 for unreadable files |
| A4 | `X-Data-Stale: true` wire value is lowercase "true" exactly as in D-05 | Patterns 1 | Cosmetic; consumers matching case-insensitively unaffected |
| A5 | Negative `X-Data-Age-S` (mtime slightly in the future, clock skew) is clamped to 0 | Patterns 1 | Cosmetic; unclamped negative int would be contract-ambiguous |
| A6 | Error `detail` strings are short ASCII (repo console discipline spirit; D-04 does not fix language) | Patterns 1 | Cosmetic; body is JSON so UTF-8 Chinese would also work |
| A7 | `os.access(path, os.R_OK)` is an honest readability check for HLT-02 without opening the file | Patterns 4 | A file that passes stat+access but fails actual open (exotic ACL/lock) would yield ready=200 then state=503 — rare, self-correcting on next probe |
| A8 | `/health/ready` 200 body `{"status": "ready"}` is an acceptable "最小 JSON" reading | Patterns 4 | Discretion zone — planner picks final wording |

## Open Questions (RESOLVED)

1. **Retry budget numbers** — research recommends `retries=2`, `retry_delay≈0.02–0.05 s` (total worst-case added latency ≈ 40–100 ms, well within polling expectations). No user gate needed (Claude's discretion), but the plan should pin the constants and test them.
   - What we know: torn windows are ms-scale (probe P2); files ≤ 48 KB.
   - What's unclear: none blocking — pick within the range.
   - Recommendation: 2 retries × 0.02 s as the initial constant; revisit if live-run verification ever shows 503s with a warm cache.
   - RESOLVED: 02-01-PLAN.md task 1 pins `retries=2, retry_delay=0.02` in the `get_state` signature (action step 5 and acceptance criteria), and the injected-reader unit tests + rewrite hammer (tasks 2-3) exercise the budget.
2. **Cold-start 503 residual window (SC2 "0×5xx")** — a server restarted mid-write with an empty cache can 503 once.
   - What we know: after any successful read the cache is warm for process life; retry budget makes the window improbable.
   - What's unclear: whether SC2's live-run verification will restart the service mid-run.
   - Recommendation: document in the plan's verification notes; do not complicate the design (no disk cache — restart cold-start from files is a feature).
   - RESOLVED: 02-01-PLAN.md documents the residual in the Flagged Assumptions note and task 3 action step 6 + the end-of-phase human-check, which scope 0×5xx evidence to cache-warm reads (a cold-window 503 is a documented residual, not a failure).
3. **detail wording** — `"unknown state name"` / `"state temporarily unavailable"` / `"state file unavailable"` (no file paths, D-04).
   - Recommendation: ASCII wording above; planner may adjust.
   - RESOLVED: 02-01-PLAN.md pins the exact wording above in task 1's acceptance criteria and live probes plus the 404/503 contract tests (task 2 tests 3-4, 10, 12-13).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Runtime | ✓ | 3.13.1 | — |
| fastapi | App/routes | ✓ | 0.115.14 | — |
| starlette | Response class | ✓ | 0.46.2 | — |
| uvicorn | Resident server | ✓ | 0.51.0 | — |
| pytest | Tests | ✓ | 9.1.1 | — |
| httpx | TestClient | ✓ | 0.25.2 | — |
| data/market_state.json, auction_state.json, zt_pool_state.json | Served payloads | ✓ | CRLF UTF-8 valid JSON, 785 B / 11.5 KB / 48.4 KB | Missing-file behavior is contract-tested (503) |
| Resident API service | Live verification | ✓ | Listening 127.0.0.1:8000 (PID 30968) | Restart via run_api.bat after code change |
| Baseline pytest | Regression gate | ✓ | 18 passed, 1 skipped (0.31 s) | — |

**Missing dependencies with no fallback:** none — the phase installs no new packages and needs no external services.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.1.1 + fastapi TestClient (httpx 0.25.2) |
| Config file | pytest.ini (`pythonpath = .`, `testpaths = tests`) |
| Quick run command | `python -m pytest tests/test_state.py -q` (from repo root) |
| Full suite command | `python -m pytest -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| STA-01 | Verbatim body bytes (CRLF fixture) + exact X-Data-Mtime/X-Data-Age-S headers + content-type application/json | unit (TestClient) | `python -m pytest tests/test_state.py -q` | ❌ Wave 0 |
| STA-01 | Whitelist: 3 names 200; unknown name 404 `{"detail": ...}`; no path traversal surface | unit | same | ❌ Wave 0 |
| STA-03 | Read layer: open/read/close per attempt; decode-error retry (injected reader, timer-free) succeeds; cache updated | unit | same | ❌ Wave 0 |
| STA-03 | Persistent decode failure + warm cache → 200 + `X-Data-Stale: true` + last-good body + cached mtime; no stale header on fresh | unit | same | ❌ Wave 0 |
| STA-03 | Persistent decode failure + empty cache → 503 `{"detail": ...}` (never bare 500) | unit | same | ❌ Wave 0 |
| STA-03 | Missing/unreadable file → 503 (OSError skips retries) | unit | same | ❌ Wave 0 |
| STA-03 | 0×5xx hammer during truncate-rewrite loop (warm cache) — every body valid JSON | integration | same | ❌ Wave 0 |
| HLT-02 | /health/ready: all 3 present → 200; missing / directory → 503; ancient mtime → still 200 | unit | same | ❌ Wave 0 |
| SC4 | Grep audit: no network tokens in api/*.py (source-scan regression test + standalone grep command in plan) | static | `grep -nE "(requests\|urllib\|httpx\|aiohttp\|socket)... api/*.py"` + pytest source-scan | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_state.py -q`
- **Per wave merge:** `python -m pytest -q`
- **Phase gate:** Full suite green before `/gsd-verify-work` (plus manual `curl` smoke and live-run 0×5xx observation per ROADMAP SC2)

### Wave 0 Gaps
- [ ] `tests/test_state.py` — covers STA-01, STA-03, HLT-02, SC4 (all new; no state tests exist today)
- [ ] No framework install needed — pytest/httpx/TestClient verified installed and Phase 1 suite green
- [ ] Existing `tests/conftest.py` autouse fixtures (net-block, env isolation, temproot fix) apply without change — no new fixtures required

## Security Domain

### Applicable ASVS Categories (level 1 per .planning/config.json `security_asvs_level: 1`, `security_enforcement: true`)

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Phase 2 serves public-safe data only; SEC-01 enforcement is Phase 3, SEC-02 classification Phase 4 (traceability table) |
| V3 Session Management | no | No sessions in the API design |
| V4 Access Control | no-by-design (this phase) | Endpoints deliberately public (market/temperature/zt-pool only); whitelist is the boundary; STA-02 sensitive reads are Phase 4 token-gated |
| V5 Input Validation | yes | `{name}` path param resolved ONLY through the fixed 3-entry dict → 404; no `os.path.join` with user input, no dynamic filename — path traversal structurally impossible (D-03) |
| V6 Cryptography | no | No secrets handled in this phase's request path (token logic untouched from Phase 1) |

### Known Threat Patterns for FastAPI local-file passthrough

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via `{name}` (`../../logs/portfolio.json`) | Information disclosure | Fixed whitelist map (D-03); prototype-verified 404 for unknown names |
| Torn/half-written JSON served as fresh | Tampering | Validate-then-serve: `json.loads(bytes)` gate; decode retry; last-good cache with `X-Data-Stale: true` (STA-03) |
| Local file disclosure through error bodies | Information disclosure | D-04: minimal `{"detail": ...}` never contains file paths |
| Unbounded read of huge files (memory DoS) | Denial of service | Served files are bounded producer-owned state (≤ 48 KB today); single-user loopback service |
| Outbound network call from a GET handler (SSRF/leak) | Elevation of privilege / Info disclosure | Structural: `api/state.py` imports only `scripts.daily.config`; SC4 grep audit command + source-scan pytest + conftest runtime net-block (three independent layers) |
| Response header injection | Tampering | Header values derive from integers (`str(mtime)`, `str(age)`) — no user or file-controlled strings enter headers |

## Sources

### Primary (HIGH confidence)
- [VERIFIED: local probe, this machine] starlette 0.46.2 / fastapi 0.115.14 behavior — `Response(content=bytes, media_type="application/json")` → content-type `application/json` (no charset), Content-Length auto-set; `json.loads(bytes)` accepts CRLF UTF-8; re-serialization does not reproduce original bytes
- [VERIFIED: local probe, this machine, py3.13.1] Windows file semantics — `os.replace` PermissionError WinError 5 while a read handle is open; direct `'w'` truncate-write torn reads observed (decode ValueError); `os.fstat(f.fileno()).st_mtime` returns mtime of the exact file version read
- [VERIFIED: local probe, this machine] Full TestClient design prototype — every STA-01/STA-03/HLT-02 contract branch (verbatim, 404/503, stale fallback, cold 503, ready 503 paths)
- [VERIFIED: in-repo] writer patterns — `scripts/daily/zt_pool.py:72-78` (`tmp = STATE_PATH + '.tmp'` + `json.dump(...)` + `os.replace(tmp, STATE_PATH)`); direct writers `scripts/daily/auction_pool.py:402-404`, `scripts/daily/capture_market_state.py:114-115`, `scripts/daily/recalc_seal.py:165-167`, `scripts/daily/capture_money_flow.py:62-63` (all `with open(..., 'w', encoding='utf-8') as f:` + `json.dump(state, f, ensure_ascii=False, indent=2)`)
- [VERIFIED: in-repo] file facts — data/market_state.json (785 B), auction_state.json (11 572 B), zt_pool_state.json (48 392 B): all CRLF, valid JSON; `scripts/daily/config.py:2` imports only `os, sys, platform`; `api/main.py:16` DATA_DIR import pattern; pytest baseline 18 passed / 1 skipped
- [CITED: fastapi.tiangolo.com/advanced/custom-response/] `Response(content, media_type, headers)` usage; Content-Length auto; charset appended for text types only (corroborates local probe)

### Secondary (MEDIUM confidence)
- [CITED: kubernetes.io v1-33 liveness/readiness probe docs + Tyk/Kong/Serverpod health docs via WebSearch 2026-09-03] readiness 200/503 convention; readiness checks dependencies, never freshness; liveness stays trivial — matches HLT-02 letter
- [VERIFIED: local probe + fastapi docs] same as above where cross-checked

### Tertiary (LOW confidence)
- [ASSUMED: WebSearch synthesis 2026-09-03 — Varnish/Cloudflare stale-if-error, TOCTOU cache bug reports] serve-stale-only-on-failure (stale-if-error) layering; stat-keyed cache entries; no single authoritative pattern document exists for the defensive-read domain

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new packages; all versions machine-verified this session
- Architecture: HIGH — read-layer protocol and route contract fully prototyped with TestClient against the installed stack; writer behaviors probed empirically
- Pitfalls: HIGH for Windows file-semantics pitfalls (probed); MEDIUM for retry-budget and readiness-body discretion items

**Research date:** 2026-09-03
**Valid until:** 2026-10-03 (stack is stable and pinned; no fast-moving dependencies)
