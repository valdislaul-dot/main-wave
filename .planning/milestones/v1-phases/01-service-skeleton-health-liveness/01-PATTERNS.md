# Phase 1: Service Skeleton + /health Liveness - Pattern Map

**Mapped:** 2026-09-02
**Files classified:** 11 (9 new, 2 modified)
**Analogs found:** 6 with in-repo analog / 3 with no in-repo analog / 2 self-modified (gitignore, requirements)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `api/__init__.py` | package marker | n/a | none (repo has ZERO `__init__.py` — Glob verified) | no-analog |
| `api/main.py` | app entry (route handler + boot orchestration + uvicorn launch) | request-response (/health) + process boot | `scripts/daily/config.py` (path-constant source, D-02); `scripts/daily/review_recommendations.py:315-316` (entry conventions) | partial (role: entry point; no HTTP/FastAPI code exists anywhere in repo) |
| `api/boot.py` | service (pure boot/token functions) | config/startup | `scripts/daily/kline_source.py:22-39` (env-first-file-second token read, plaintext data/*_token.txt) | role-match |
| `tests/conftest.py` | test fixture (autouse) | n/a | EXTERNAL model: `C:/Users/Davis/vibe-astock/tests/conftest.py` (git-tracked in its own repo, NOT in gogo; endorsed by CONTEXT.md/CONCERNS.md) | no in-repo analog |
| `tests/test_health.py` | test | request-response (TestClient) | none in repo (zero pytest files — `scripts/test_executable.py` is a legacy one-off script, not pytest) | no-analog |
| `tests/test_boot.py` | test | unit (pure functions) | none in repo | no-analog |
| `pytest.ini` | config | n/a | none (no pytest.ini/setup.cfg/pyproject.toml/tox.ini at root — verified) | no-analog |
| `run_api.bat` | launcher (process) | process launch | `scripts/daily/auto_start.bat` (only .bat in repo — keep `cd /d` + `>> log 2>&1` shape, DELETE stale hardcoded BASE at line 7) | role-match (content is half anti-pattern, D-09) |
| `scripts/daily/install_api_task.ps1` | installer (OS task registration) | event-driven (AtStartup trigger) | `scripts/daily/install_scheduled_task.ps1` (tracked, full convention source) | exact |
| `requirements.txt` | config | n/a | self (modify: same `>=floor` style) | self |
| `.gitignore` | config | n/a | self (modify: same style as lines 10-11 token entries) | self |

**Tracked-source gate (#3645):** every analog path above was verified this session via `git ls-files` — all gogo paths are tracked. The one external path (`vibe-astock/tests/conftest.py`) is its own git repo's tracked file, cited only because CONTEXT.md line 73 + CONCERNS.md explicitly name it the model to copy; its full text is quoted below so the planner never needs to open that repo.

## Pattern Assignments

### `api/main.py` (app entry, request-response + boot)

**Analog:** `scripts/daily/config.py` (constants), `scripts/daily/review_recommendations.py` (entry conventions). No FastAPI analog in repo — app/route shape comes from RESEARCH.md Code Example 1.

**Path-constant import (D-02) — copy from `scripts/daily/config.py:5-14`** (only path dependency; api/ adds zero path boilerplate):
```python
# scripts/daily/config.py:5-14  (tracked, quoted verbatim)
# Project root: parent of scripts/daily/
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
DAILY_DIR = os.path.join(DATA_DIR, 'daily_close')
LOG_DIR = os.path.join(PROJECT_ROOT, 'logs')
KLINE_DIR = os.path.join(DATA_DIR, 'kline_data')

# Ensure dirs exist
for d in [DATA_DIR, DAILY_DIR, LOG_DIR, KLINE_DIR]:
    os.makedirs(d, exist_ok=True)
```
Import shape: `from scripts.daily.config import PROJECT_ROOT, DATA_DIR, LOG_DIR`. Importing config.py runs the benign mkdir side effect (acceptable at boot). Token path = `os.path.join(DATA_DIR, 'api_token.txt')`.

**Anti-pattern NOT to copy (ARCHITECTURE.md #1 / D-02):** `scripts/daily/review_recommendations.py:15-16` — the per-file sys.path bootstrap every legacy module uses (also `run_pipeline.py:11`, `zt_pool.py:14`, 10+ more):
```python
# scripts/daily/review_recommendations.py:15-16  — FORBIDDEN in api/ (D-02)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

**Entry guard + stdout convention — copy from `scripts/daily/review_recommendations.py:315-316`** (repo-wide `__main__` convention; keep ALL boot logic + `uvicorn.run` under this guard so `import api.main` stays side-effect-free for TestClient — Pitfall 3):
```python
# scripts/daily/review_recommendations.py:315-316  (tracked)
if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
```
api/main.py variant: guard with `def main() -> None:` then `if __name__ == '__main__': main()` per RESEARCH.md Pattern 1 shape; reconfigure stdout at the top of main() (belt to Pitfall 5 alongside ASCII-only output + `set PYTHONUTF8=1` in the bat).

**App + /health route shape (NO in-repo analog — use RESEARCH.md Code Example 1, lines 358-369; app created at module level, boot NOT):**
```python
# RESEARCH.md Code Example 1 — shape only (fastapi 0.115.14 machine-verified)
import time
from fastapi import FastAPI

_START = time.monotonic()          # module import time == process start for uvicorn.run

app = FastAPI(title="gogo API", docs_url=None, redoc_url=None, openapi_url=None)

@app.get("/health")
def health():
    return {"status": "ok", "uptime_seconds": int(time.monotonic() - _START)}
```
Pins: bare `def` (no auth dependency/middleware this phase — HLT-01 never-401), docs disabled, `time.monotonic()` (never `time.time()`).

**Boot-sequence ordering (SEC-03 vs D-03)** — main() plain Python BEFORE `uvicorn.run`: non-loopback branch evaluates env/file only and `sys.exit(1)` WITHOUT generating; generation happens only on the loopback branch. Full shape in RESEARCH.md Pattern 1 (lines 219-242), `uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)` signature verified on installed 0.51.0.

---

### `api/boot.py` (service, config/startup — pure functions)

**Analog:** `scripts/daily/kline_source.py:22-39` (tracked) — token-at-rest read convention; copy the env-first-file-second shape and single-line-plaintext convention verbatim (D-04), but with explicit `path` params (testable via tmp_path) instead of module-level `BASE`:

**Token read pattern — copy from `scripts/daily/kline_source.py:26-39`:**
```python
# scripts/daily/kline_source.py:26-39  (tracked, quoted verbatim)
def _load_tushare_token():
    """Tushare token: 环境变量 > 配置文件(gitignored)"""
    tok = os.environ.get('TUSHARE_TOKEN', '').strip()
    if tok:
        return tok
    if os.path.exists(TOKEN_PATH):
        try:
            with open(TOKEN_PATH, encoding='utf-8') as f:
                tok = f.read().strip()
                if tok:
                    return tok
        except Exception:
            pass
    return None
```
api/boot.py adaptation (per RESEARCH.md Code Example 3 notes): env name `GOGO_API_TOKEN`; missing token on non-loopback branch = hard error (`sys.exit(1)` in main, not `return None`); read with `encoding='utf-8'`; strip newline; empty file == no token.

**New (no repo analog) — write side D-03/D-05:** `secrets.token_urlsafe(32)` (never `random`/uuid4); write single-line raw key, no trailing content; print ONLY the fixed ASCII sentence `"API token generated at data/api_token.txt"` — never the value (D-05, one-way). Loopback detection: stdlib `ipaddress.ip_address(host).is_loopback` + explicit `localhost` allow (covers 127.0.0.0/8 and ::1; never `host.startswith("127.")`).

**Existing-file-at-rest precedent (same convention family, already gitignored):** `data/tushare_token.txt` and `data/hithink_token.txt` — `.gitignore:10-11`.

---

### `scripts/daily/install_api_task.ps1` (installer, event-driven)

**Analog:** `scripts/daily/install_scheduled_task.ps1` (tracked, read in full). Copy structure lines 12-41; DELETE the stale hardcoded paths (lines 7-9), the Daily-15:30 trigger (lines 20-21), and hardcoded log/manual-test echo lines (50-54). Task name must differ from `主升浪每日选股流水线` (D-07).

**Registration pattern to copy — `scripts/daily/install_scheduled_task.ps1:12-41` (tracked, quoted verbatim):**
```powershell
# Remove existing task if any
try { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue } catch {}

# Create task action
$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$ScriptPath`"" -WorkingDirectory $WorkingDir

# Trigger 1: At system startup (with 5 min delay for network)
$Trigger1 = New-ScheduledTaskTrigger -AtStartup -RandomDelay (New-TimeSpan -Minutes 5)

# Settings: run even if on battery, retry on failure
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew

# Register task for current user
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger1, $Trigger2 `
    -Settings $Settings `
    -Principal $Principal `
    -Description "每日盘后自动下载K线数据并筛选明日涨停候选标的" `
    -Force
```
Phase 1 adaptations (D-07/D-09): `$Trigger1` only (drop `$Trigger2`); action points at `<repo>\run_api.bat`; `$ScriptPath`/`$WorkingDir` derived from `$PSScriptRoot` (ps1 lives in `scripts/daily/` → `$RepoRoot = Split-Path -Parent $PSScriptRoot`) — NEVER the literal `C:\Users\Davis\Desktop\主升浪` (stale-path bug class, D-09; anti-example at lines 7-9 above, `auto_start.bat:7`).

---

### `run_api.bat` (launcher, process launch)

**Analog:** `scripts/daily/auto_start.bat` (tracked — only .bat in repo). Copy the log-redirect + cd discipline; replace the hardcoded-BASE bug with `%~dp0` (D-09).

**Anti-pattern NOT to copy — `scripts/daily/auto_start.bat:7-13` (tracked, quoted verbatim):**
```bat
set BASE=C:\Users\Davis\Desktop\主升浪
set LOG=%BASE%\logs\pipeline.log

echo [%date% %time%] Pipeline starting... >> "%LOG%"

cd /d "%BASE%\scripts\daily"
python run_pipeline.py >> "%LOG%" 2>&1
```
Keep: `cd /d`, `>> log 2>&1` redirect shape. Replace: `set BASE=C:\...` → `cd /d "%~dp0"` (repo root, never hardcode). Research's run_api.bat shape (RESEARCH.md lines 268-274): `@echo off` / `cd /d "%~dp0"` / `if not exist logs\api mkdir logs\api` / `set PYTHONUTF8=1` / `python -m api.main >> logs\api\console.log 2>&1`. `logs/*` already gitignored (`.gitignore:12`), so `logs/api/console.log` needs no new ignore entry (verified `logs/*` covers it; also `logs/*.log` at line 25).

---

### `tests/conftest.py` (test fixture, autouse)

**In-repo analog: none** (repo has zero test files, pytest not installed, no pytest.ini). **External model (endorsed):** `C:/Users/Davis/vibe-astock/tests/conftest.py` — read in full this session; network-blocking autouse fixture at lines 16-23 (tracked in that repo; CONCERNS.md names it the positive pattern to borrow):
```python
# vibe-astock/tests/conftest.py:16-23 (external model, quoted verbatim)
@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def blocked(self, *args, **kwargs):
        raise AssertionError(
            "测试期间不允许出站网络连接 —— 说明有数据源没被 patch，请补上 monkeypatch"
        )

    monkeypatch.setattr(socket.socket, "connect", blocked, raising=False)
```
Phase 1 addition (RESEARCH.md Pattern 3 / Pitfall 3): a second autouse fixture deleting `GOGO_API_TOKEN` / `GOGO_API_HOST` / `GOGO_API_PORT` env vars (`monkeypatch.delenv(..., raising=False)`) so a developer shell never leaks into assertions. Text may stay bilingual (conftest never routes through the bat's GBK redirect) — but ASCII-safe is fine too.

---

### `tests/test_health.py` (test, request-response via TestClient)

**In-repo analog: none** (`scripts/test_executable.py` is a legacy backtest one-off with hardcoded `C:\Users\Davis\Desktop\主升浪` paths — not pytest, not a model; do not cite it). Use RESEARCH.md Code Example 2 (lines 373-392):
```python
# RESEARCH.md Code Example 2 — shape only (official FastAPI testing pattern)
# tests/test_health.py
from fastapi.testclient import TestClient
from api.main import app

client = TestClient(app)           # module-level, no context manager: no lifespan, no boot

def test_health_returns_200_and_ok():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["uptime_seconds"], int)
    assert body["uptime_seconds"] >= 0
```
Pins: imports `api.main` (side-effect-free by construction — boot behind `__main__` guard), never calls `main()`, never touches real `data/api_token.txt` (Pitfall 3 regression: assert the real path is untouched).

---

### `tests/test_boot.py` (test, unit pure functions)

**In-repo analog: none.** Use RESEARCH.md Pattern 1 + Pitfall 2 regression requirement: test SEC-03 refusal via pure `boot_checks(host, token_path)` with `tmp_path` + `monkeypatch.setenv` — non-loopback host + empty tmp_path + no env → refusal, exit code != 0, and NO token file created; loopback default generates (D-03); generated notice text equals the D-05 sentence and contains no token value. Import mechanics: pytest.ini `pythonpath = .` makes `import api.boot` and `import api.main` resolve from repo root (Pitfall 1).

---

### `pytest.ini` (config)

**In-repo analog: none** (verified no pytest.ini/setup.cfg/pyproject.toml/tox.ini at root). Content pinned by RESEARCH.md Pitfall 1 + Validation Architecture: `[pytest]` / `pythonpath = .` / `testpaths = tests` (pytest >= 7 built-in option; floor 8.3). Run command: `python -m pytest -q`.

---

### `api/__init__.py` (package marker)

**In-repo analog: none** (Glob `**/__init__.py` = 0 files — api/ is the repo's first package, D-01). Content: empty. Required so `import api.main` is a regular-package import.

---

### `requirements.txt` (config, MODIFY)

**Analog: self** — current content (4 lines, `>=floor` style):
```
akshare>=1.10.0
requests>=2.28.0
streamlit>=1.28.0
tushare>=1.2.0
```
Append the four lines in the same `name>=floor` style: `fastapi>=0.115.14`, `uvicorn>=0.51.0`, `pytest>=8.3`, `httpx>=0.25.2` (floors machine-verified installed: fastapi 0.115.14, uvicorn 0.51.0, httpx 0.25.2; pytest absent → only fresh install).

---

### `.gitignore` (config, MODIFY)

**Analog: self** — add `data/api_token.txt` in the SAME commit as the generating code (D-06, non-negotiable). Style precedent — existing gitignored plaintext token files at `.gitignore:10-11`:
```
data/tushare_token.txt
data/hithink_token.txt
```
New entry sits beside them: `data/api_token.txt`. Verified absent today (`git check-ignore -v` exit 1 — RESEARCH.md). `logs/*` (line 12) already covers `logs/api/`; no extra entries needed. Belt-and-suspenders: `sync_cloud.py:26-38` explicit allow-list (tracked, verified) enumerates 5 state files + `data/auction/*.json` — the token file can never ride an auto-commit.

## Shared Patterns

### Path constants — single source (D-02)
**Source:** `scripts/daily/config.py:5-14` (quoted above under api/main.py)
**Apply to:** `api/main.py`, `api/boot.py` — import `PROJECT_ROOT`/`DATA_DIR`/`LOG_DIR`; zero per-file `BASE =` computation; zero `sys.path.insert` bootstrap.

### Token at rest: env-first, file-second, plaintext single-line under data/
**Source:** `scripts/daily/kline_source.py:26-39` (quoted above under api/boot.py)
**Apply to:** `api/boot.py` read (`has_token`), generate (`ensure_token` — new, `secrets.token_urlsafe(32)`), D-05 fixed ASCII notice only.

### Entry-point guard + stdout reconfigure
**Source:** `scripts/daily/review_recommendations.py:315-316`
**Apply to:** `api/main.py` — `if __name__ == '__main__':` guard keeps module import side-effect-free (TestClient safety); `sys.stdout.reconfigure(encoding='utf-8')` at main() start (belt to the ASCII-only rule + `PYTHONUTF8=1` in bat for the GBK-redirect hazard, Pitfall 5).

### Windows Task Scheduler registration convention
**Source:** `scripts/daily/install_scheduled_task.ps1:12-41` (quoted above)
**Apply to:** `scripts/daily/install_api_task.ps1` — AtStartup + 5-min RandomDelay, Interactive/Limited principal, StartWhenAvailable, RestartCount 3 / 10-min, MultipleInstances IgnoreNew, idempotent unregister-then-register `-Force`, `cmd.exe /c` action wrapper.

### Launcher .bat shape
**Source:** `scripts/daily/auto_start.bat:10-13` (redirect/cd half) + D-09 fix
**Apply to:** `run_api.bat` — `cd /d "%~dp0"`, `python -m api.main >> logs\api\console.log 2>&1`. Never a literal `BASE=C:\...` (auto_start.bat:7 is the stale-path bug; repo now at `Desktop\gogo`).

### Test network-block + env isolation
**Source:** vibe-astock `tests/conftest.py:16-23` (external, quoted above; tracked in its own repo)
**Apply to:** `tests/conftest.py` for all of `tests/` — plus autouse `monkeypatch.delenv('GOGO_API_TOKEN'|'GOGO_API_HOST'|'GOGO_API_PORT', raising=False)`.

## No Analog Found

Files with no close match in the repo (planner uses RESEARCH.md patterns instead):

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `api/main.py` (app/route layer) | controller/route | request-response | Repo has zero FastAPI/HTTP code (no analog for `app = FastAPI(...)`, `@app.get`, uvicorn). Use RESEARCH.md Code Example 1 + Pattern 1 shape |
| `api/__init__.py` | package marker | n/a | Repo has zero `__init__.py` (Glob verified) — api/ is the first package |
| `tests/conftest.py`, `tests/test_health.py`, `tests/test_boot.py` | test | various | Repo has zero pytest infrastructure; `scripts/test_executable.py` is a legacy one-off, NOT a model (hardcoded stale paths, no fixtures). Use RESEARCH.md Code Examples 2-3, Pattern 3, Validation Architecture |
| `pytest.ini` | config | n/a | No pytest config exists at root (verified) |
| `api/boot.py` (pure-function module shape) | service | config/startup | Legacy modules mix side effects at import; the pure-function-with-explicit-path module is a new shape. Token-read logic copies kline_source.py; boot-check logic per RESEARCH.md Pattern 1 |

## Metadata

**Analog search scope:** repo root recursive (`scripts/`, `scripts/daily/`, root config files) via Glob/Grep/Read; external model dir `C:/Users/Davis/vibe-astock/tests/` (cross-repo, cited by CONTEXT.md); verified no `api/`, `tests/`, `__init__.py`, pytest config, or other `.bat`/`.ps1` files exist anywhere in repo.
**Files scanned:** ~12 analog/infra files read or grepped (config.py, install_scheduled_task.ps1, auto_start.bat, kline_source.py:1-80, sync_cloud.py:1-60, review_recommendations.py:1-40+315-325, .gitignore, requirements.txt, scripts/test_executable.py, vibe-astock/tests/conftest.py; 30+ `__main__` guards and 15 `sys.path.insert` sites located by Grep)
**Tracked-source verification:** `git ls-files` confirmed tracked: config.py, install_scheduled_task.ps1, auto_start.bat, kline_source.py, sync_cloud.py, review_recommendations.py, .gitignore, requirements.txt, scripts/test_executable.py
**Pattern extraction date:** 2026-09-02
