# Phase 3: Trigger Runner, Job Registry & Locks + Auth Enforcement — Pattern Map

**Mapped:** 2026-09-04
**Files analyzed:** 11 (7 new + 4 modified)
**Analogs found:** 10 / 11 (job_lock.py has no in-repo analog — research Pattern 1 is authoritative)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `api/actions.py` (NEW) | route/controller | request-response + process dispatch | `api/state.py` (Phase 2 router module) | exact |
| `api/auth.py` (NEW) | middleware (FastAPI dependency) | request-response | `api/boot.py` (read_token chain, verbatim reuse) + `api/state.py` (error-body style) | exact reuse |
| `api/jobs.py` (NEW) | service | file-I/O (registry CRUD) + batch (worker thread) | `scripts/daily/zt_pool.py` save_state (atomic write) + `api/state.py` (pure-fn conventions) | role-match |
| `scripts/daily/job_lock.py` (NEW) | utility | file-I/O (cross-process lock) | none in repo (no lock primitive anywhere); partial: `scripts/daily/config.py` import discipline | no analog |
| `tests/test_actions.py` (NEW) | test | request-response | `tests/test_state.py` | exact |
| `tests/test_auth.py` (NEW) | test | request-response | `tests/test_boot.py` (env/token monkeypatch) + `tests/test_health.py` (exemption pins) | exact |
| `tests/test_jobs.py` (NEW) | test | batch + file-I/O | `tests/test_state.py` (pure-fn unit + TestClient integration) | exact |
| `api/main.py` (MOD) | config (route registration + boot) | request-response | itself (2-line include shape L16-18/L34; main() boot L37-77) | exact |
| `scripts/daily/gui_dashboard.py` (MOD) | component (Streamlit GUI) | request-response (sync subprocess) | itself (refresh block L86-92) | exact |
| `.gitignore` (MOD) | config | — | itself (`logs/*` precedent) | exact |
| `tests/conftest.py` (MOD, optional) | config (test fixtures) | — | itself | exact |

## Pattern Assignments

### `api/actions.py` (route, request-response + process dispatch)

**Analog:** `api/state.py` — same role (APIRouter module, contract IDs in docstring, zero import side effects, HTTPException minimal detail, call-time path composition). Copy its skeleton wholesale; swap STATE_FILES whitelist for KIND_CMDS map and the GET handler shape for the POST single-flight gate + GET /v1/jobs/{job_id}.

**Imports + module skeleton** (`api/state.py:19-35`):
```python
import json
import os
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from scripts.daily.config import DATA_DIR  # D-02 路径纪律 (导入链 os/sys/platform)

# D-03 白名单 —— 固定三名显式映射, 未知名 404, 绝无动态路径解析 (无穿越面)。
STATE_FILES = {
    "market_state": "market_state.json",
    "auction_state": "auction_state.json",
    "zt_pool_state": "zt_pool_state.json",
}
_CACHE = {}  # name -> {"raw": bytes, "mtime": int}; 每名一槽, 进程内 (D-05)
router = APIRouter()
```
Replace STATE_FILES with the D-09 map (research Pattern 5, `api/actions.py` KIND_CMDS — single source of truth, 4 kinds, fixed args):
```python
KIND_CMDS = {
    "pipeline":         ("run_pipeline.py",      ("--fast",)),
    "morning-check":    ("morning_check.py",     ("--quick",)),
    "backtest-weights": ("backtest_v4.py",       ()),
    "health-check":     ("data_health_check.py", ()),
}
```
Router-level auth dependency (SEC-01/D-11): `router = APIRouter(dependencies=[Depends(require_api_key)])` — structural exemption: this dependency lives on the NEW router only; /health and /v1/state routers (registered in main.py) never see it. No middleware (HLT-01 purity, `api/main.py:28-31` has zero-dependency /health; SC3).

**Unknown-input 404 + whitelist-first ordering** (`api/state.py:83-87`) — whitelist lookup precedes any path/argv composition; detail plain string, path-free:
```python
@router.get("/v1/state/{name}")
def get_state_endpoint(name: str):
    """透传白名单状态文件 (D-01..D-05)。白名单查表先于任何路径组合 (D-03)。"""
    if name not in STATE_FILES:
        raise HTTPException(status_code=404, detail="unknown state name")  # D-04
```
Mirror for both routes: unknown kind → 404 before anything else; job_id failing `^[0-9a-f]{32}$` → 404 before `os.path.join` (research anti-pattern: "job_id composed into a path unchecked — gate before composing"). Do NOT copy the read_state_file/get_state defensive-read machinery — jobs.py owns registry reads (open→read→close per GET, no caching).

**409 body shape** (research Open Question 1 — RESOLVED: object detail on BOTH 409 branches; 401/403/404 stay plain-string per D-10):
```python
# claim gate failure, in-memory map hit:
raise HTTPException(409, detail={"message": f"{kind} already running",
                                  "running_job_id": running["job_id"]})
# lock held but map empty (GUI / manual holder): no job_id exists — object detail WITHOUT a running_job_id key
raise HTTPException(409, detail={"message": f"{kind} already running (another entry point)"})
```

**202 immediate return** — handler does only fast bookkeeping (claim + pending file write), returns `{"job_id": ..., "kind": ..., "status": "pending"}` with `status_code=202`, then hands the slow sequence to the worker thread (research Pattern 3; SC3 — never wait on the request path).

### `api/auth.py` (dependency, request-response)

**Analog:** `api/boot.py:30-47` — reuse `read_token` verbatim via import, do not re-implement token loading. Error style from `api/state.py:87/91` (minimal `{"detail": plain-string}`, path-free, D-10).

**Token chain to reuse** (`api/boot.py:30-47`):
```python
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

**Dependency shape** (research Pattern 5; token path resolved INSIDE the function at call time from a module `DATA_DIR` attribute — Phase 2 monkeypatch seam, same spirit as `api/main.py:51` `token_path = os.path.join(DATA_DIR, "api_token.txt")` and `api/state.py:66` call-time join):
```python
import hmac
import os
from fastapi import HTTPException, Request
from api.boot import read_token
from scripts.daily.config import DATA_DIR            # module attr = monkeypatch seam, read at call time

def require_api_key(request: Request) -> str:
    """X-API-Key gate (SEC-01/D-10). Request-only signature — no optional parameters."""
    provided = request.headers.get("X-API-Key")            # header name per REQUIREMENTS.md literal
    if provided is None:
        raise HTTPException(401, detail="missing API key",
                            headers={"WWW-Authenticate": "ApiKey"})   # D-10
    expected = read_token(os.path.join(DATA_DIR, "api_token.txt"))    # env GOGO_API_TOKEN first, file second
    if expected is None or not hmac.compare_digest(expected.encode(), provided.encode()):
        raise HTTPException(403, detail="invalid API key") # D-10: present-but-wrong -> 403
    return provided                                         # validated key string; no handler consumes it
```
⚠ **Do NOT copy an optional `token_path` parameter into this signature.** FastAPI would surface it as an attacker-controllable `token_path` query parameter — a caller could redirect token resolution at an arbitrary file whose contents then feed the compare. 03-02 prohibition #2 pins the request-only shape; the auth suite asserts `?token_path=<anything>` cannot change the 401/403/202 outcome (a decoy-file key stays 403). Fail-closed (no token configured → 403, never 200). Token value never logged, never echoed in detail (grep-audit test pins it). Missing-header path returns straight 401 — no compare on that branch.

### `api/jobs.py` (service, file-I/O registry + batch worker thread)

**Analog 1 — atomic transition writer:** `scripts/daily/zt_pool.py:72-78` (in-repo canonical atomic write, research-probed os.replace-over-existing on NTFS):
```python
def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    state['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    tmp = STATE_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)
```
Registry variant (research Pattern 2 — tmp in same dir, pid-suffixed to avoid cross-thread collision):
```python
def write_job(jobs_dir, job):                       # atomic: tmp + os.replace (same dir = same volume)
    tmp = os.path.join(jobs_dir, f".{job['job_id']}.tmp-{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(jobs_dir, job["job_id"] + ".json"))
```

**Analog 2 — read-side handle discipline:** `api/state.py:45-49` (open→read→fstat→close; every registry GET reads the whole file fresh, never holds a handle — the WinError-5 note at `api/state.py:62-63` applies verbatim: "Windows 上打开的读句柄会让管线的 os.replace 撞 WinError 5"):
```python
def read_state_file(path):
    """open('rb') -> read 全部 -> 同一句柄 fstat -> close; 返回 (raw, mtime)。...
    """
    with open(path, "rb") as f:
        raw = f.read()
        mtime = int(os.fstat(f.fileno()).st_mtime)
    json.loads(raw)  # validate only —— 解析结果丢弃, 永不回写
    return raw, mtime
```

**Pure-function + injectable-seam conventions** (from `api/boot.py:9-11` docstring "每个函数只依赖显式传入的路径参数与环境变量, 不计算路径常量、不做控制台输出" and `api/state.py:56` — injectable `reader=read_state_file` parameter is the deterministic unit-test seam model): all jobs.py functions take `jobs_dir`/`lock_dir`/script paths as explicit parameters or read module attrs at call time (monkeypatch seam, e.g. `reload_registry(jobs_dir)`, `JOBS_DIR`/`LOCK_DIR` module attrs). No module-level I/O at import.

**Worker-thread spawn shape** (research Pattern 3, probes V1/V4 — no in-repo background-execution analog; sync subprocess precedent is the GUI at `gui_dashboard.py:88-90`, sys.executable + arg list + cwd):
```python
def _run_job(job):
    log_path = os.path.join(JOBS_DIR, job["job_id"] + ".log")
    job["log_path"], job["status"] = log_path, "running"          # atomic write
    env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"     # V1 finding — mandatory
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0 # V4 finding
    try:
        with open(log_path, "wb", buffering=0) as fh:
            proc = subprocess.Popen(job["cmd"], cwd=PROJECT_ROOT, env=env,
                                    stdout=fh, stderr=subprocess.STDOUT,
                                    creationflags=flags)
        job["pid"] = proc.pid                                     # atomic write
        job["exit_code"] = proc.wait()
        job["status"] = "succeeded" if proc.exit_code == 0 else "failed"
    except Exception as e:                                        # spawn failure -> failed, no crash
        job["status"], job["exit_code"] = "failed", None
    job["finished_at"] = int(time.time())                         # atomic write; release lock; clear map
```
`threading.Thread(target=..., daemon=True)` per job — event loop untouched (SC3). `job["cmd"] = [sys.executable, <abs script path>, *kind_args]`, never `shell=True`. cwd=PROJECT_ROOT from `scripts/daily/config.py:5`.

**Reload sweep (SC5)** — research Example 3, pure function over `jobs_dir`, deterministic `interrupted` marking, prune cap 500 terminal-only pairs.

### `scripts/daily/job_lock.py` (utility, cross-process lock) — NO ANALOG

No lock primitive (msvcrt/fcntl/portalocker) exists anywhere in the repo — confirmed by grep. Research Pattern 1 skeleton is the authoritative, machine-verified source (probe V2: empty-file lock OK, same-process re-entrancy denied, cross-process errno 13, locked byte unreadable by others → content-free lock files, taskkill → OS auto-release → no stale-lock protocol). Copy from `03-RESEARCH.md` Pattern 1 verbatim, not from any repo file.

Import-shape constraints from two consumers:
- API side: `from scripts.daily.job_lock import acquire` — import chain must stay os/sys/platform-only (config.py:2 discipline; module must not import pipeline modules, per `api/state.py:14-17` SC4 note "只允许 import fastapi 与 scripts.daily.config").
- GUI side: `gui_dashboard.py:14` does `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` then plain `import morning_check as mc` (L16) — so GUI imports job_lock as a top-level module name. Keep job_lock free of any `scripts.`-prefixed import (works both ways); msvcrt/fcntl ImportError split per research Pattern 1.
- Path constants: DATA_DIR comes from config via each caller (research: lock files at `data/locks/{kind}.lock`); dirs created at acquire time (never at import — config.py:13-14 import-time makedirs is NOT the pattern to copy here; job_lock must be side-effect-free on import per api/__init__ discipline).

### `api/main.py` (MOD) — two-line include + one-line reload

**Existing two-line include shape** (`api/main.py:16-18` import block + `:34` registration) — Phase 3 adds the actions router the same way:
```python
from api.state import router as state_router          # L18 (existing)
...
app.include_router(state_router)                       # L34 (existing)
```
New lines: `from api.actions import router as actions_router` beside L18; `app.include_router(actions_router)` beside L34. Do not touch `/health` (L28-31) or the app constructor (L25).

**Reload call placement** — one line inside `main()` AFTER the SEC-03/token block (L53-68) and BEFORE `import uvicorn` (L71); boot ordering and diff-auditability preserved (D-12: SEC-03 check-before-token-generation sequence at L53-68 is Phase 1 payload — do not reorder):
```python
    else:
        # D-03: 回环/默认分支, 首次启动自动生成 token (写入 data/api_token.txt)。
        # D-05: 生成后只打印这一句固定 ASCII 提示, 绝不打印 token 值。
        if not has_token(token_path):
            ensure_token(token_path)
            print("API token generated at data/api_token.txt")

    # <-- NEW: reload_registry() call lands here (after token block, before uvicorn import)

    # 惰性导入: 测试 import api.main 时无需 uvicorn 依赖, 也不触发任何绑定。
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)  # L73: access_log=False 已在
```
Reload must be a directly-callable function in api/jobs.py, NOT a FastAPI lifespan hook — the existing test convention is module-level `TestClient(app)` without a context manager (`tests/test_state.py:31`, `tests/test_health.py:15`), so boot-time behavior lives in `main()` or plain functions. `main()` keeps `sys.stdout.reconfigure(encoding="utf-8")` (L43) — console stays ASCII-only in new code.

### `scripts/daily/gui_dashboard.py` (MOD, D-01) — lock check in refresh

**Existing refresh block** (`gui_dashboard.py:86-92`) — keep the direct-subprocess form; wrap with lock acquire + finally release:
```python
if c3.button("🔄 刷新数据", width='stretch'):
    with st.spinner("拉涨停池+评分(轻量)..."):
        r = subprocess.run(
            [sys.executable, 'scripts/daily/run_pipeline.py', '--fast'],
            cwd=BASE, capture_output=True, text=True, timeout=180)
        st.success("完成!" if r.returncode == 0 else f"部分失败(见日志)")
    st.rerun()
```
D-01 change: before `subprocess.run`, `fh = job_lock.acquire("pipeline", <locks_dir>)`; if None → `st.warning("管线运行中(API job 或 GUI),刷新已禁用")` and skip the run; else run and release in `finally` (research Pitfall 7: streamlit `timeout=180` raises TimeoutExpired and leaves the child alive — a finally-release keeps the lock from stranding; on timeout warn that a pipeline may still be running). Import shape: `import job_lock` (top-level, same mechanism as L16 `import morning_check as mc` after L14 sys.path.insert). Lock file path joins BASE/data/locks — same as API side (D-03 same-machine scope; gitignore the dir; Mac parity via fcntl split inside job_lock).

### `.gitignore` (MOD) — one line

`logs/*` already ignores `logs/api/jobs/` (registry + job logs, no new entry needed). Add `data/locks/` (lock files — content-free but must never reach git/sync_cloud whitelist, D-03 discipline). Precedent: existing `data/api_token.txt` line in `.gitignore`.

### `tests/test_actions.py`, `tests/test_auth.py`, `tests/test_jobs.py` (NEW)

**Analog:** `tests/test_state.py` (integration + pure-fn unit in one file) / `tests/test_boot.py` (env/token monkeypatch) / `tests/test_health.py` (public-endpoint exemption pins).

**Module-level TestClient, no context manager** (`tests/test_state.py:27-31`):
```python
import api.main  # noqa: F401  (注册 state 路由 —— 一次 import 覆盖两个路由族)
import api.state
from api.main import app

client = TestClient(app)  # 模块级, 无 context manager: 无 lifespan, 无 boot
```

**Per-file autouse isolation fixture** (`tests/test_state.py:34-39`) — pattern to replicate for each api module attr under test (api.actions/jobs/auth module attrs: JOBS_DIR, LOCK_DIR, DATA_DIR, KIND script paths; plus map/thread state cleanup between tests):
```python
@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path, monkeypatch):
    """每个测试前: DATA_DIR -> tmp_path (monkeypatch 缝) + 清空 _CACHE。"""
    monkeypatch.setattr(api.state, "DATA_DIR", str(tmp_path))
    api.state._CACHE.clear()
    return tmp_path
```

**Global fixtures come free** (`tests/conftest.py`): `_no_network` autouse (L31-48) and `_clean_env` autouse (L51-54 — deletes GOGO_API_TOKEN/GOGO_API_HOST/GOGO_API_PORT so auth tests are deterministic). Optional conftest addition per research Wave 0: tmp token-file writer helper + JOBS_DIR/LOCK_DIR monkeypatch helpers.

**Auth-test shapes** (`tests/test_boot.py:43-47` env/file token fixture precedent; `tests/test_health.py:24-31` bare-request 200 pins):
```python
token_file = tmp_path / "api_token.txt"
token_file.write_text("file-key", encoding="utf-8")
monkeypatch.setenv("GOGO_API_TOKEN", "env-key")  # or delenv for file-only cases
```
Exemption pins copy `tests/test_health.py:1-5` docstring stance — /health, /health/ready, /v1/state/{name} must answer bare (no header) 200; any test asserting they 401 violates HLT-01/D-11. Decoy-guard + no-path-in-body assertions copy `tests/test_state.py:87-119` (404 matrix with real decoy files present) and `:124-129` (`assert str(tmp_path) not in response.text`).

**Fake-script spawn tests** (research Example 4 — fake scripts written into tmp_path at test time, KIND script paths monkeypatched to them; no real pipeline ever runs, network autouse-blocked):
```python
FAKE = "import json,sys,time;json.dump(sys.argv[1:],open(sys.argv[1],'w'));time.sleep(0.2);sys.exit(int(sys.argv[2]))"
```
Pin: argv == [fake_script, '--fast'] proves arg-list spawn without shell; 409 on overlap carries running_job_id; 401/403 spawn nothing (assert jobs dir stays empty); token value absent from job log + console log bytes (grep audit, SEC-01). Cross-process lock test spawns a real child python holding job_lock (research V2 probe shape). Pure-fn registry tests (reload sweep → interrupted, prune cap) take tmp_path jobs_dir with hand-written fixture JSONs, mirroring `tests/test_state.py:134-177` injected-reader unit style.

## Shared Patterns

### Path discipline — config.py only, call-time module-attr resolution
**Source:** `scripts/daily/config.py:5-9` (PROJECT_ROOT/DATA_DIR/LOG_DIR), `api/state.py:66` (`os.path.join(DATA_DIR, STATE_FILES[name])` at call time), `api/main.py:51` (token_path joined in main()).
**Apply to:** all new api modules. Never compute BASE, never sys.path surgery in api/; import paths from `scripts.daily.config` (import chain os/sys/platform only — `api/state.py:26` comment). Module attrs read at call time = the monkeypatch seam every Phase 2/3 test relies on.

### Minimal JSON error bodies, path-free, decision-tagged
**Source:** `api/state.py:87,91,114,116` (`detail="unknown state name"` / `"state temporarily unavailable"`); pins in `tests/test_state.py:124-129`.
**Apply to:** all actions/auth endpoints. Plain-string details for 401/403/404/503 (D-10); object details ONLY on 409 (research Open Question 1 — RESOLVED): the map-hit branch carries `{"message": ..., "running_job_id": ...}`, the lock-held branch carries `{"message": ...}` with no `running_job_id` key. Detail never contains token value or file paths.

### Atomic writes — tmp + os.replace
**Source:** `scripts/daily/zt_pool.py:72-78` (save_state), research-probed os.replace-over-existing on NTFS.
**Apply to:** api/jobs.py registry transitions (every status change), never `open('w')` truncate on a mutable single-point file.

### Read-handle discipline — open→read→close, never hold across awaits
**Source:** `api/state.py:45-49` + WinError-5 note at `:62-63`.
**Apply to:** GET /v1/jobs/{job_id} registry reads (api/jobs.py). A held read handle blocks the pipeline writer's os.replace — same failure class the Phase 2 layer defends against.

### Import side-effect freedom + ASCII console
**Source:** `api/state.py:14-17` docstring; `api/main.py:8` (Pitfall 5: bat 重定向 GBK 控制台), `api/boot.py:9-11`.
**Apply to:** api/auth.py, api/actions.py, api/jobs.py, scripts/daily/job_lock.py — module import never spawns threads, writes files, binds ports, or prints; job_lock creates dirs at acquire time, not import.

### Test conventions — module-level TestClient, autouse isolation, zero network
**Source:** `tests/conftest.py:31-54`, `tests/test_state.py:31-39`, `tests/test_health.py:15`.
**Apply to:** all three new test files. Module-level `TestClient(app)` (no lifespan — boot behavior lives in main(), not lifespan hooks); per-file autouse fixture redirects module DATA_DIR/JOBS_DIR/LOCK_DIR to tmp_path and clears in-memory state; fake scripts in tmp_path; no real pipelines, no network.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `scripts/daily/job_lock.py` | utility | file-I/O (cross-process lock) | Zero lock code exists in repo (grep: no msvcrt/fcntl/portalocker/lockf anywhere). Research Pattern 1 (`03-RESEARCH.md` §Architecture Patterns) is the authoritative skeleton — machine-verified this session (probe V2) — copy verbatim; repo provides only import-shape constraints (config.py:2 chain; gui_dashboard.py:14-16 top-level import mechanism) |
| `api/jobs.py` worker-thread governance (subset) | service | batch (background Popen) | No background-execution code exists in api/ (single-threaded batch repo per ARCHITECTURE.md). Partial analog: `gui_dashboard.py:88-90` sync `subprocess.run` arg-list shape. Thread+Popen recipe comes from research Patterns 2-3 (probes V1/V4) |

## Metadata

**Analog search scope:** `api/`, `tests/`, `scripts/daily/` (git-tracked files only; verified via `git ls-files` — all named analogs tracked)
**Files scanned:** 11 source analogs read in full or targeted range: api/main.py, api/boot.py, api/state.py, tests/conftest.py, tests/test_state.py, tests/test_health.py, tests/test_boot.py, scripts/daily/config.py, scripts/daily/zt_pool.py (L55-94), scripts/daily/gui_dashboard.py (L1-130), scripts/daily/run_pipeline.py (L1-40)
**Repo facts confirmed:** no `__init__.py` in scripts/ (namespace packages, `pythonpath=.`); `logs/api/jobs/` exists and is covered by `.gitignore` `logs/*`; `data/locks/` does not exist yet (needs new gitignore line); uvicorn `access_log=False` already at api/main.py:73; /health (api/main.py:28-31) has zero dependencies — structural auth exemption point
**Pattern extraction date:** 2026-09-04
