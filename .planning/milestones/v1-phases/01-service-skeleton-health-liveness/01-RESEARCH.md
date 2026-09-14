# Phase 1: Service Skeleton + /health Liveness - Research

**Researched:** 2026-09-02
**Domain:** FastAPI resident service on Windows 11 + Task Scheduler autostart + fail-closed boot + first pytest suite
**Confidence:** HIGH (stack machine-verified this session; every locked decision cross-checked against live repo files)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Code Location**
- **D-01:** The FastAPI service lives in a new top-level `api/` package (`api/main.py` + submodules), NOT under `scripts/`. Rationale: resident service vs daily batch scripts are different lifecycles; pytest imports work naturally with a package; Phases 2–5 add routes/jobs/auth/classification modules that need room to grow. — **Reversibility:** costly — moving the package later touches imports, tests, run_api.bat, and the scheduled-task action after Phases 2–5 have built on it.
- **D-02:** `api/` imports path constants (`PROJECT_ROOT`, `DATA_DIR`, `LOG_DIR`) from `scripts/daily/config.py` — do NOT copy the per-file `BASE = os.path.dirname(...)` sys.path pattern (ARCHITECTURE.md anti-pattern #1 explicitly forbids it for new modules).

**API Token (SEC-03 boot check dependency)**
- **D-03:** Token auto-generated on first start: if `data/api_token.txt` does not exist, the service generates a random token via `secrets` and writes it there. Path is pinned by Phase 4 SC4 (`data/api_token.txt` must appear in neither git history nor the sync_cloud whitelist).
- **D-04:** Read priority: `GOGO_API_TOKEN` env var first, file second — same pattern as the tushare token (`scripts/daily/kline_source.py:26`). The scheduled task uses the file; env override is for manual/test runs.
- **D-05:** After generating, the service logs/prints ONLY "API token generated at data/api_token.txt" — never the value. Reset = delete the file, restart. — **Reversibility:** one-way — a token value that lands in any log can't be un-leaked without rotation, and Phase 4 SC3 audits that no log line contains a token value; breaking this decision means a failed Phase 4 audit.
- **D-06 (non-negotiable, same commit):** `.gitignore` gains `data/api_token.txt` in the SAME commit as the code that creates it. The repo may be public (CONCERNS.md #1: anonymous fetch returned 200) and `sync_cloud.py` auto-commits daily.

**Windows Autostart**
- **D-07:** Task Scheduler registration copies the existing convention from `scripts/daily/install_scheduled_task.ps1`: `AtStartup` trigger + 5-min random delay, principal = current user (Interactive, RunLevel Limited), `StartWhenAvailable`, `RestartCount 3` / 10-min interval, `MultipleInstances IgnoreNew`. Distinct task name (not "主升浪每日选股流水线"). Behavior: runs ~5 min after boot when the user is logged in; otherwise waits for logon — accepted tradeoff for a user-attended trading machine (SYSTEM boot task rejected: no user env, expanded privilege surface).
- **D-08:** Default port **8000**, overridable via `GOGO_API_PORT`. The load-balancer probe contract points at `127.0.0.1:8000/health`. — **Reversibility:** one-way — the LB's probe URL is configured against this default; changing it later changes what external consumers configure.
- **D-09:** `run_api.bat` (repo root, OPS-01) locates the repo via `%~dp0` relative path — do NOT copy the hardcoded stale `BASE=C:\Users\Davis\Desktop\主升浪` bug in `scripts/daily/auto_start.bat`.

**Mac Scope**
- **D-10:** Phase 1 delivers Windows autostart only. The service code itself must run on Mac (config.py auto-detects PROJECT_ROOT on both ends), but the launchd plist is deferred to Phase 5 (Win/Mac parity).

### Claude's Discretion
- Add `fastapi` / `uvicorn` / `pytest` / `httpx` to `requirements.txt` (currently only akshare/requests/streamlit/tushare — Mac parity requires it; versions machine-verified: fastapi 0.115.14, uvicorn 0.51.0, Python 3.13.1).
- uvicorn single process, programmatic launch from `api/main.py` (run_api.bat calls it directly); startup log to `logs/api/` (gitignored).
- Tests in top-level `tests/` with a network-blocking autouse fixture (pattern proven in vibe-astock, CONCERNS.md positive pattern). Token generation must be test-safe (monkeypatch/override so TestClient runs never touch the real `data/api_token.txt`).
- Token file format/content (e.g. single-line raw key), exact boot-check error message wording for the non-loopback-no-token case, and fail-closed check implementation details — follow SEC-03 literally.
- Port 8000 conflict behavior (clear startup error, not silent fallback).

### Deferred Ideas (OUT OF SCOPE)
- Mac launchd plist (autostart parity) — Phase 5.
- `/health/details` auth-gated endpoint, log rotation — Phase 5 (OPS-03).
- Anything in REQUIREMENTS.md v2 (job cancel, orphan adoption, ETag, rate limiting, digest aggregation) — future release, explicitly out of scope.
- Discussion stayed within phase scope; no todos were folded (todo match count: 0).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| HLT-01 | GET /health 探活——纯内存返回 `{"status":"ok","uptime_seconds":N}`，永远 200，不受鉴权拦截，数据过期绝不 503 ([VERIFIED: .planning/REQUIREMENTS.md:12]) | Code Example 1 (in-memory monotonic uptime, zero file/network deps, no auth middleware in this phase — SEC-01 request enforcement is Phase 3); tests map in Validation Architecture |
| SEC-03 | 默认绑 127.0.0.1，非回环无 token 拒绝启动（fail-closed） ([VERIFIED: .planning/REQUIREMENTS.md:31]) | Pattern 1 (boot check runs BEFORE uvicorn.run binds; ordering vs D-03 generation spelled out); ipaddress stdlib loopback detection; boot logic isolated in pure functions so it is testable without TestClient |
| OPS-01 | Windows 任务计划程序开机自启（run_api.bat，沿用 install_scheduled_task.ps1 惯例） ([VERIFIED: .planning/REQUIREMENTS.md:35]) | Pattern 2 (ps1 conventions quoted from live file + the stale-path anti-pattern to avoid + machine fact: no gogo task currently registered; port 8000 free) |
| OPS-02 | pytest+TestClient 种子测试（仓库首套自动化测试） ([VERIFIED: .planning/REQUIREMENTS.md:36]) | Import-mechanics finding (namespace package + pytest pythonpath), vibe-astock network-blocking conftest model, Code Example 2, Validation Architecture section |

All four requirements map 1:1 to the phase's locked decisions. No research found any conflict between the four; the only cross-cutting subtlety is SEC-03-vs-D-03 ordering (see Pattern 1).
</phase_requirements>

## Summary

Phase 1 is a greenfield, zero-risk-to-pipeline phase: a new top-level `api/` package (the repo's first package — `[VERIFIED: Glob **/__init__.py found 0 files in repo]`), a `/health` route that computes uptime from `time.monotonic()` captured at import time and touches nothing on disk, a fail-closed boot sequence in `api/main.py` that refuses non-loopback binds without a token, and the repo's first pytest suite in a new top-level `tests/`. The full stack was re-verified on this machine this session: Python 3.13.1, fastapi 0.115.14, uvicorn 0.51.0, starlette 0.46.2, httpx 0.25.2 all import cleanly; **pytest is NOT installed** — the single environment gap, trivially closed by `pip install "pytest>=8.3"` (PyPI latest 9.1.1, `requires_python >=3.10` — compatible with 3.13.1).

The two structural findings a planner must design around: (1) **import mechanics** — the repo has zero `__init__.py` files, so `import scripts.daily.config` (mandated by D-02) resolves only via PEP 420 namespace packages, which works when the repo root is on `sys.path` (verified live this session: `PROJECT_ROOT = C:\Users\Davis\Desktop\gogo`); production entry must therefore be `python -m api.main` from the repo root (run_api.bat `cd /d "%~dp0"`), and pytest needs `pythonpath = .` in a root `pytest.ini` (or a root conftest). (2) **SEC-03 check ordering vs D-03 token generation** — the fail-closed refusal must be evaluated on env-var/file state BEFORE any auto-generation would run, and the generation branch must never fire on the non-loopback path; otherwise "no token configured" can never occur and the refusal becomes dead code. Loopback default boot: env → file → else generate via `secrets` and print exactly the D-05 sentence.

OPS-01 facts verified on this machine: no `主升浪每日选股流水线` task and no gogo/API task is currently registered in Task Scheduler (200 tasks total; only two unrelated CJK OEM tasks) — Phase 1 registers a fresh, distinct task; port 8000 currently has no listener (free for D-08); user `Davis` is the scheduled-task principal. The existing `install_scheduled_task.ps1`/`auto_start.bat` pair both hardcode the stale `C:\Users\Davis\Desktop\主升浪` path — the new installer must derive repo paths from `$PSScriptRoot` and `%~dp0` (D-09). `data/api_token.txt` is absent and NOT yet covered by `.gitignore` (`git check-ignore -v` exit 1) — D-06's same-commit gitignore addition is confirmed necessary; `logs/` is already fully ignored (`logs/*`), so `logs/api/` needs no new gitignore entry; `sync_cloud.py` uses an explicit allow-list, so the token file cannot ride an auto-commit.

**Primary recommendation:** Build `api/` as {`__init__.py`, `main.py` (FastAPI app + `/health` + `main()` boot), `boot.py` (pure token/bind functions)}, launch programmatically with `uvicorn.run(app, host, port)` where host defaults to `127.0.0.1` and port to 8000 (env-overridable `GOGO_API_HOST`/`GOGO_API_PORT`), and gate pytest imports with `pytest.ini` (`pythonpath = .`, `testpaths = tests`). Add the four deps to requirements.txt with the machine-verified floors. Write the Task Scheduler installer as a new `scripts/daily/install_api_task.ps1` that derives paths from `$PSScriptRoot` (never hardcoded).

## Project Constraints (from CLAUDE.md)

Directives in the repo CLAUDE.md that Phase 1 must honor (repo file is gitignored but present; content read this session via project context):

- **Upload rule (2026-08-31, user-fixed):** only code + market data go to GitHub. 持仓/账目/logs/、CLAUDE.md/CONTEXT.md/README、资料、memory、setup are never uploaded (gitignored). `data/api_token.txt` must join this protected set — D-06 implements it via `.gitignore` in the same commit as the generating code; `logs/api/*` is already covered by the existing `logs/*` ignore rule.
- **Never `git add .`:** commits must stage specific files (CONTEXT.md "Integration Points": "Git commits must stage specific files only (never `git add .`)"). D-06's protection is belt: the sync_cloud explicit allow-list is the suspenders (verified `[VERIFIED: scripts/daily/sync_cloud.py:26-38]` — the whitelist enumerates exactly 5 state files + `data/auction/*.json`, so `data/api_token.txt` can never be auto-added).
- **定稿机制 (2026-08-25):** trading-mechanism changes need explicit user sign-off. CONTEXT.md already ruled this is NOT triggered — new API surface, no existing mechanism modified. No sign-off gate needed in Phase 1.
- **Git pull discipline (2026-09-02, user-fixed):** do not `git pull`/push unless the user explicitly asks. Phase execution and the scheduled-task install must not assume a fetch from origin.
- **No venv / direct pip:** repo convention is global-site-packages Python + `pip install -r requirements.txt` (STACK.md). The environment audit below confirms the same interpreter hosts all deps.
- **Encoding discipline:** Windows GBK console; existing CLI entries self-reconfigure stdout. For the API, keep console/log text ASCII-only in `api/` (D-05's notice and the SEC-03 refusal message are ASCII) so cmd redirection into `logs/api/console.log` can never raise UnicodeEncodeError; optionally set `PYTHONUTF8=1` in run_api.bat.
- **Time rule (`date +"%H:%M"` before operations)** is a trading-console rule; it does not gate service code, but note the `/health` probe must answer identically on trading and non-trading days (HLT-01) — the design (no trading-calendar dependency anywhere in Phase 1 code) honors this by construction.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| /health liveness (200, in-memory) | API process (FastAPI app) | — | Pure in-memory: monotonic uptime at request time; no disk, no network, no auth middleware in Phase 1 — nothing that could 401/503 or vary with data age |
| Fail-closed boot (SEC-03) | API process (boot code) | — | Runs in `main()` BEFORE `uvicorn.run()` binds the socket; no framework hook (lifespan) can refuse a bind that `uvicorn.run` has already started — the check must precede it in plain Python |
| Token at rest (D-03/D-04/D-05) | API process (boot code) | Filesystem tier (`data/api_token.txt`) | Generation/read is a boot-time side effect; kept out of request handlers; env-first-file-second mirrors the tushare precedent |
| Uptime tracking | API process | — | `time.monotonic()` start constant captured at module import |
| Autostart after reboot (OPS-01) | OS tier (Windows Task Scheduler) | API process (run_api.bat → python -m api.main) | OS-owned: AtStartup trigger + Interactive principal; the service itself only needs to be launchable idempotently from a bat |
| Startup log capture | OS redirect (bat `>>`) | — | run_api.bat redirects stdout/stderr into `logs/api/console.log` (already gitignored); rotation is Phase 5 (OPS-03) |
| First automated tests (OPS-02) | Test tier (pytest + TestClient) | API process (app import) | Top-level `tests/`; TestClient exercises the ASGI app in-process; boot-check pure functions tested directly with tmp_path/monkeypatch |

## Standard Stack

### Core
| Library | Version (machine) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastapi | 0.115.14 (floor `>=0.115.14`) | Web framework; /health route; app object | Locked by PROJECT.md decision (Python+FastAPI, whole stack Python). Imported successfully this session `[VERIFIED: live import]`. PyPI latest 0.141.1, `requires_python >=3.10` — the API surface used (TestClient, lifespan, @app.get) is stable across both |
| uvicorn | 0.51.0 (floor `>=0.51.0`) | ASGI server, single process | Locked discretion ("uvicorn single process, programmatic launch"). `uvicorn.run(app, host=..., port=...)` signature machine-verified `[VERIFIED: inspect of installed uvicorn 0.51.0]`. PyPI latest 0.52.4 |
| pytest | not installed → install latest (9.1.1) or `>=8.3` | Test runner | OPS-02 first suite. PyPI `requires_python >=3.10` `[VERIFIED: pypi.org JSON]` — runs on Python 3.13.1. Do NOT run `unittest` — TestClient + pytest is the documented FastAPI pairing |
| httpx | 0.25.2 (floor `>=0.25.2`) | TestClient transport | `TestClient` (starlette) requires httpx `[CITED: fastapi.tiangolo.com/tutorial/testing/]`; already installed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| starlette | 0.46.2 (transitive) | TestClient lives here; ASGI layer | Never imported directly; exists because fastapi depends on it. Version compatible with fastapi 0.115.14 and httpx 0.25.2 `[VERIFIED: live import]` |
| anyio | 4.14.2 (transitive) | TestClient event-loop backend | Never imported directly |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| fastapi + uvicorn | Flask + waitress / Node Express | Rejected by locked decision: gogo is a full-Python stack; Flask lacks typed routes/TestClient parity; Express rejected in REQUIREMENTS.md Out of Scope |
| `uvicorn.run()` programmatic | `uvicorn api.main:app` CLI in bat | Locked discretion says programmatic from `api/main.py`; keeps SEC-03 boot check and env resolution in one Python file, testable; CLI form would split logic between bat and Python |
| `time.monotonic()` | `time.time()` process start | monotonic is immune to wall-clock jumps (NTP, manual clock change) — uptime must never go backwards or jump |
| Root `conftest.py` for sys.path | `pytest.ini` `pythonpath = .` | Both work; `pytest.ini` is explicit, documented in-file config and also hosts `testpaths`; a root conftest is invisible magic. Chosen: `pytest.ini` |

**Installation:**
```bash
pip install "fastapi>=0.115.14" "uvicorn>=0.51.0" "pytest>=8.3" "httpx>=0.25.2"
# or, following the repo's single-file convention: add the four lines to requirements.txt (floors as above), then:
pip install -r requirements.txt
```

**Version verification:** (run before finalizing the plan)
```bash
python -c "import fastapi, uvicorn, httpx; print(fastapi.__version__, uvicorn.__version__, httpx.__version__)"
python -c "import pytest; print(pytest.__version__)"   # fails today — pytest not yet installed
```

## Package Legitimacy Audit

> Gate run 2026-09-02 via `gsd-tools package-legitimacy check --ecosystem pypi` + PyPI JSON API + live imports.

| Package | Registry | Latest release | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| fastapi | PyPI | 0.141.1 (2026-07-29) | unknown to seam | github.com/fastapi/fastapi `[VERIFIED: pypi.org JSON]` | SUS* | Approved — machine-verified (see below) |
| uvicorn | PyPI | 0.52.4 (2026-08-19) | unknown to seam | github.com/Kludex/uvicorn `[VERIFIED: pypi.org JSON]` | SUS* | Approved — machine-verified (see below) |
| pytest | PyPI | 9.1.1 (2026-06-19) | unknown to seam | github.com/pytest-dev/pytest `[VERIFIED: pypi.org JSON]` | SUS* | Approved — canonical dev tool |
| httpx | PyPI | 0.28.1 (2024-12-06) | unknown to seam | github.com/encode/httpx `[VERIFIED: pypi.org JSON]` | SUS* | Approved — machine-verified (see below) |

\* **SUS reasons are seam data-source gaps, not risk signals:** the seam reports `unknown-downloads` for every PyPI package (it has no PyPI download-count source) and uvicorn additionally shows `too-new` because `publishedAt` is the date of its *latest release* upload (2026-08-19), not the package's age. None of fastapi/uvicorn/pytest/httpx is new, low-download, or repo-less: all four `exists: true`, `deprecated: false`, `postinstall: null`, with canonical maintainer repos declared on PyPI (uvicorn's repo moved from encode/ to its current maintainer Kludex — the PyPI-declared URL is the authoritative current one).

**Verification already performed at research time (satisfies the "verify before using" intent — no extra checkpoint:human-verify needed):**
1. fastapi 0.115.14, uvicorn 0.51.0, httpx 0.25.2 are installed in the machine's global site-packages and were **imported successfully this session** — byte-for-byte the versions CONTEXT.md locked. Installing the `>=` floors therefore upgrades nothing on this box.
2. pytest is the only fresh install; it is the standard Python test runner, declared for `requires_python >=3.10` `[VERIFIED: pypi.org JSON]`, no postinstall, canonical repo. Its first invocation (`pytest -q` on the seeded suite) is an inherent smoke test.
3. All four were also cross-checked against official documentation (fastapi.tiangolo.com) and PyPI authoritative metadata.

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none with real risk signals (see note above — planner does NOT need checkpoints for these four)

## Architecture Patterns

### System Architecture Diagram

Flow of a boot and of one probe request (conceptual tiers, not file listings):

```text
[Windows Task Scheduler]            [Probe: GET http://127.0.0.1:8000/health]
  AtStartup + 5-min random delay          │ (any hour, any day)
  (Interactive, user Davis)               ▼
        │                        [FastAPI app — api/main.py]
        ▼                        GET /health → {"status":"ok","uptime_seconds":N}
[run_api.bat (repo root)]                 │ computed from time.monotonic() − START
  cd /d "%~dp0"                           │ NO file read, NO network, NO auth gate
  python -m api.main                      ▼
        │                       200 always (never 401/503)
        ▼
[api/main.py main() boot sequence]
  1. host = GOGO_API_HOST or "127.0.0.1"   (D-08 default; port 8000)
  2. SEC-03 check BEFORE any bind:
     non-loopback + (no GOGO_API_TOKEN env AND no data/api_token.txt)
        → clear error to stderr/log, sys.exit(1)   [never generates in this branch]
  3. loopback default: env → file → else generate via secrets,
     write data/api_token.txt, print ONLY "API token generated at data/api_token.txt"
  4. uvicorn.run(app, host=host, port=port)   (single process)
        │
        ▼
[stdout/stderr → run_api.bat >> logs/api/console.log]
[data/api_token.txt — .gitignore entry added in the SAME commit (D-06)]

[tests/ — pytest + TestClient]
  imports api.main app in-process (no boot, no socket, no token file touch);
  network-blocking autouse fixture; pure boot functions tested with tmp_path
```

Traceability of the primary use case (probe): Task Scheduler (or manual) → bat → boot check → uvicorn binds 127.0.0.1:8000 → any /health request returns 200 in-memory. Nothing in the request path touches `data/`, `logs/`, the network, or the calendar — that is exactly HLT-01's "at any hour, never affected by data age".

### Recommended Project Structure

```
api/                          # NEW — repo's first package (D-01)
├── __init__.py               # empty (required — api/ is a regular package)
├── main.py                   # FastAPI app, GET /health, main() boot sequence, uvicorn.run
└── boot.py                   # PURE functions: is_loopback(host), read_token(path),
                              #   ensure_token(path) (D-03/D-04/D-05), boot_checks(host, token)
                              #   → unit-testable without TestClient or sockets
tests/                        # NEW — top-level (Claude's discretion)
├── conftest.py               # autouse network-block fixture (vibe-astock model) + env isolation
├── test_health.py            # HLT-01: 200, exact body, monotonic uptime
└── test_boot.py              # SEC-03: refuse non-loopback w/o token; loopback default generates
                              #   (tmp_path); D-05: notice text carries no token value
pytest.ini                    # NEW: pythonpath = . / testpaths = tests (import mechanics)
run_api.bat                   # NEW at repo root (D-09): %~dp0, python -m api.main >> logs/api/console.log
scripts/daily/install_api_task.ps1   # NEW: Task Scheduler installer, paths from $PSScriptRoot
requirements.txt              # ADD: fastapi>=0.115.14, uvicorn>=0.51.0, pytest>=8.3, httpx>=0.25.2
.gitignore                    # ADD: data/api_token.txt (same commit as token code — D-06)
```

### Pattern 1: Fail-closed boot check that runs BEFORE the socket binds

**What:** SEC-03's refusal is not a framework concern — no FastAPI hook (middleware, lifespan) exists "before the server binds". The check is plain Python at the top of `main()`, evaluated on env/file state before generation can mask it.

**When to use:** every start path (bat, task, manual) funnels through `python -m api.main` → `main()` → check → `uvicorn.run`.

**Critical ordering (SEC-03 vs D-03):** the non-loopback branch must test "token configured?" = `GOGO_API_TOKEN` env set OR `data/api_token.txt` exists-and-nonempty, and on failure must exit WITHOUT generating. If generation ran first, a bare `0.0.0.0` start would always "have" a token and the refusal branch would be unreachable — silently violating success criterion 3. Token generation (D-03) happens only on the loopback/default branch when env is unset and the file is missing.

**Loopback detection:** stdlib `ipaddress.ip_address(host).is_loopback` covers `127.0.0.1` and `::1`; treat bare `localhost` as loopback via explicit allow. Everything else (`0.0.0.0`, LAN IP, hostname) is non-loopback → token required.

**Exit contract:** non-zero exit (`sys.exit(1)`), message to stderr AND the startup log; Task Scheduler's `RestartCount 3 / 10-min` then retries 3 times and stops, leaving `LastTaskResult = 1` — visible, diagnosable, no silent reachable-unauthenticated state (matches success criterion 3 wording "clear error").

**Example (shape — exact wording is Claude's discretion):**
```python
# api/main.py — boot sequence; every line below follows a locked decision
import os, sys
from fastapi import FastAPI
from scripts.daily.config import PROJECT_ROOT      # D-02 (namespace import, see Pitfall 1)
from api.boot import ensure_token, has_token, is_loopback  # pure helpers in api/boot.py

app = FastAPI(title="gogo API", docs_url=None, redoc_url=None, openapi_url=None)

def main() -> None:
    host = os.environ.get("GOGO_API_HOST", "127.0.0.1")      # D-08 default loopback
    port = int(os.environ.get("GOGO_API_PORT", "8000"))      # D-08
    token_path = os.path.join(PROJECT_ROOT, "data", "api_token.txt")
    if not is_loopback(host):
        if not has_token(token_path):                        # env first, file second
            print(f"ERROR: refusing to bind {host} without an API token. "
                  f"Set GOGO_API_TOKEN or create data/api_token.txt", file=sys.stderr)
            sys.exit(1)                                      # NO generation on this branch
    else:
        ensure_token(token_path)                             # D-03 generation; prints D-05 notice
    import uvicorn                                          # lazy import keeps boot importable in tests
    uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)
```
(uvicorn.run params `app/host/port/log_level/access_log` confirmed present in installed 0.51.0 `[VERIFIED: inspect]`.)

### Pattern 2: Task Scheduler autostart — the repo's own convention, minus the stale path

**What:** register a Windows task that runs `cmd.exe /c "<repo>\run_api.bat"` at startup, for the interactive user, with restart/missed-start settings. Source: the live convention in `scripts/daily/install_scheduled_task.ps1:17-33`, quoted verbatim `[VERIFIED: read this session]`:

```powershell
# Trigger 1: At system startup (with 5 min delay for network)
$Trigger1 = New-ScheduledTaskTrigger -AtStartup -RandomDelay (New-TimeSpan -Minutes 5)
...
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
```

**Phase 1 adaptation (D-07):** only the AtStartup trigger (no 15:30 daily trigger — that belonged to the pipeline task); task name distinct from "主升浪每日选股流水线" (machine fact: neither that task nor any gogo/API task is currently registered — 200 tasks audited, only two unrelated CJK OEM tasks `[VERIFIED: Get-ScheduledTask this session]`).

**When to use:** the new `scripts/daily/install_api_task.ps1` MUST derive `$RepoRoot = Split-Path -Parent $PSScriptRoot` (ps1 lives in scripts/daily → repo root) and build the action from it — never a hardcoded path. The existing ps1 hardcodes `C:\Users\Davis\Desktop\主升浪` (line 8) and `auto_start.bat` hardcodes the same stale path (line 7) — both are the anti-example D-09 forbids replicating; the repo now lives at `C:\Users\Davis\Desktop\gogo` `[VERIFIED: config.py PROJECT_ROOT probe]`.

**run_api.bat shape (D-09):**
```bat
@echo off
cd /d "%~dp0"                    REM %~dp0 = repo root; never hardcode BASE
if not exist logs\api mkdir logs\api
set PYTHONUTF8=1
python -m api.main >> logs\api\console.log 2>&1
```

**When to use:** every boot path. Note the task action wraps this in `cmd.exe /c "..."` per the ps1 convention (`New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c ..."`), and `WorkingDirectory` = repo root so `python -m api.main` resolves.

### Pattern 3: Tests that never touch real state (test-safety)

**What:** (a) boot/token logic lives in `api/boot.py` pure functions taking explicit paths — unit tests pass `tmp_path` and `monkeypatch.setenv("GOGO_API_TOKEN", ...)`; (b) `TestClient(app)` tests import the app object without ever invoking `main()` (guard everything boot-ish behind `if __name__ == "__main__": main()`), so no test run can read/create the real `data/api_token.txt`; (c) an autouse network-block fixture makes any accidental outbound call fail loudly — the proven vibe-astock model `[VERIFIED: read C:\Users\Davis\vibe-astock\tests\conftest.py:16-23]`:

```python
@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def blocked(self, *args, **kwargs):
        raise AssertionError("test attempted an outbound network connection — patch the data source")
    monkeypatch.setattr(socket.socket, "connect", blocked, raising=False)
```

**When to use:** all tests in this suite; extend the same conftest with an autouse env-cleanup fixture (`monkeypatch.delenv("GOGO_API_TOKEN", raising=False)` etc.) so host/port/token env vars from a developer's shell never leak into assertions.

### Anti-Patterns to Avoid
- **Boot check inside uvicorn/framework hooks:** too late — the socket may already be bound or the semantics hidden; keep it in plain `main()` before `uvicorn.run`. (Also: `@app.on_event("startup")` is deprecated — `[CITED: fastapi.tiangolo.com/advanced/events/]` — and irrelevant here because the SEC-03 refusal must precede binding, not follow it.)
- **Auto-generating the token on the non-loopback branch:** makes SEC-03's refusal unreachable (see Pattern 1 ordering).
- **Importing `api.main` runs boot side effects:** keep `main()` and `uvicorn.run` under `if __name__ == "__main__"`; module import must stay side-effect-free apart from `app = FastAPI(...)`.
- **Hardcoding paths in run_api.bat / the installer ps1:** the stale-`主升浪` bug class that already bit `auto_start.bat` and `install_scheduled_task.ps1` (both still contain it today).
- **Reimplementing token reading:** copy the env-first-file-second shape from `kline_source.py` (quote below in Code Examples); do not invent a different precedence or a `.env` system (none exists in the repo).
- **`time.time()` for uptime:** wall clock jumps backwards (NTP); `time.monotonic()` is the standard for uptime counters.
- **Logging the token value anywhere** (including debug logs and access logs): D-05 is one-way; Phase 4 SC3 audits log lines.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP framework, routing, JSON serialization | Raw `http.server` / socket server | FastAPI (0.115.14) | ASGI ecosystem, TestClient for free, typed routes for Phases 2-5; locked decision |
| ASGI server / process lifecycle | Hand-written event loop server | uvicorn (0.51.0) | Battle-tested single-process server; programmatic `uvicorn.run` |
| Random token generation | `random` module, uuid4, timestamps | `secrets.token_urlsafe(32)` (stdlib) | `random` is not cryptographically secure; uuid4's randomness is not guaranteed CSPRNG-grade; `secrets` is the stdlib answer — never hand-roll crypto |
| Loopback detection | String prefix hacks (`host.startswith("127.")`) | `ipaddress.ip_address(host).is_loopback` (stdlib) | Handles 127.0.0.0/8, ::1 correctly; prefix hacks miss `::1` and accept invalid strings |
| Uptime tracking | `time.time()` deltas | `time.monotonic()` (stdlib) | Immune to wall-clock changes |
| Test HTTP client | Raw sockets against a live server | starlette `TestClient` (via httpx) | In-process ASGI calls: no port, no subprocess, no network; the documented FastAPI pattern `[CITED: fastapi.tiangolo.com/tutorial/testing/]` |
| Windows task registration | Manual taskschd.msc clicking / schtasks.exe string parsing | PowerShell `ScheduledTasks` module (New-ScheduledTaskAction/Trigger/Settings/Principal/Register) | Repo convention; declarative; idempotent with `-Force`; machine has the module working `[VERIFIED: Get-ScheduledTask this session]` |

**Key insight:** every "hard" piece of this phase — server, framework, token entropy, loopback math, task registration — has a stdlib or repo-convention answer. The only genuinely custom logic is the SEC-03 branch ordering and the D-03/D-05 generation policy, which is why they are isolated into pure functions in `api/boot.py` where tests can pin them.

## Common Pitfalls

### Pitfall 1: `import scripts.daily.config` breaks under pytest or from the wrong cwd
**What goes wrong:** repo has zero `__init__.py` files (verified `[VERIFIED: Glob]`), so `scripts.daily.config` resolves only as a PEP 420 namespace package — which requires the repo root to be on `sys.path`. Running `python api/main.py` directly (script mode) puts `api/` on the path, not the root → `ModuleNotFoundError`. Bare `pytest` from the root inserts only `tests/`, not the root → same failure in the suite.
**Why it happens:** D-02 mandates importing from `scripts/daily/config.py`, but the repo has never used package imports (flat-dir + per-file sys.path was the old way, now forbidden for new modules).
**How to avoid:** production entry is always `python -m api.main` from the repo root (run_api.bat does `cd /d "%~dp0"`); tests get a root `pytest.ini` with `pythonpath = .` and `testpaths = tests` (pytest >= 7 built-in option — floor is 8.3 anyway). Verified working this session from the repo root: `python -c "import scripts.daily.config"` → PROJECT_ROOT correct.
**Warning signs:** `ModuleNotFoundError: No module named 'scripts'` in a task log or pytest output.

### Pitfall 2: SEC-03 refusal never fires because token generation ran first
**What goes wrong:** the service boots on 0.0.0.0, auto-creates the token file (D-03), and starts — "no token configured" can never be true, so the fail-closed promise is silently dead while the tests for it (if any) still pass because they test the branch functions in isolation.
**Why it happens:** D-03 (generate on first start) and SEC-03 (refuse without token) look compatible until you order them; generation first makes refusal unreachable.
**How to avoid:** the non-loopback branch evaluates configured-ness on env + existing file ONLY and exits before any generation; generation is exclusive to the loopback/default branch. Add a regression test asserting that calling the boot check with a non-loopback host and an empty tmp_path creates NO file.
**Warning signs:** code review shows `ensure_token()` called before the SEC-03 `if`.

### Pitfall 3: TestClient runs touch the real `data/api_token.txt`
**What goes wrong:** first test run creates a real token in the live repo data dir (and a later D-06-less commit could stage it); or tests depend on a token that exists on Win but not on Mac → suite is machine-dependent.
**Why it happens:** token logic at import time or in lifespan, or boot code not guarded by `__main__`.
**How to avoid:** module import side-effect-free; boot guarded; `api/boot.py` takes explicit paths/env; conftest env-cleanup; tests assert the real path was untouched (tmp_path isolation).
**Warning signs:** `data/api_token.txt` appears in `git status` after running the tests.

### Pitfall 4: Task registered with the stale repo path (the 主升浪 bug class)
**What goes wrong:** task boots a nonexistent `C:\Users\Davis\Desktop\主升浪\run_api.bat` → LastTaskResult failure at every reboot; service never comes up; success criterion 2 fails silently.
**Why it happens:** copying `install_scheduled_task.ps1` / `auto_start.bat` verbatim — both still hardcode the pre-rename path (`install_scheduled_task.ps1:8`, `auto_start.bat:7` `[VERIFIED: read this session]`); the repo moved to `Desktop\gogo`.
**How to avoid:** new ps1 derives paths from `$PSScriptRoot`; bat uses `%~dp0`; installer echoes the resolved paths for visual confirmation; verification step runs the task once manually (`Start-ScheduledTask`) and probes `127.0.0.1:8000/health`.
**Warning signs:** ps1 contains the literal `Desktop\主升浪` anywhere.

### Pitfall 5: Encoding crash when the bat redirects stdout to a file
**What goes wrong:** python printing non-ASCII to redirected (non-console) stdout on a GBK-locale Windows box can raise UnicodeEncodeError — the service dies after boot with a cryptic log.
**Why it happens:** cmd redirection changes stdout encoding from the UTF-8 console mode to the ANSI code page.
**How to avoid:** keep all `api/` console output ASCII-only (D-05 notice and SEC-03 error are ASCII by construction) and/or `set PYTHONUTF8=1` in run_api.bat before launching.
**Warning signs:** console.log ends with `UnicodeEncodeError: 'gbk' codec can't encode character`.

### Pitfall 6: `/health` accidentally coupled to files or auth
**What goes wrong:** a later-phase dev adds a middleware/dependency "just in case" and the probe starts returning 401/503; or the handler stats a state file for "freshness" and nights/weekends change behavior.
**Why it happens:** liveness endpoints drift into readiness semantics.
**How to avoid:** in this phase the app has NO middleware and NO dependencies — the route is a bare `def health()` returning the in-memory dict; the OPS-02 test pins `200` + exact body + no headers required. Any future middleware must exempt `/health` (Phase 3's auth work is explicitly out of this phase's scope).
**Warning signs:** test asserts a 401 for /health without a key — that contradicts HLT-01; flag it in review.

## Code Examples

Verified patterns from official sources and the live repo:

### 1. In-memory /health with monotonic uptime (HLT-01 contract)
```python
import time
from fastapi import FastAPI

_START = time.monotonic()          # module import time == process start for uvicorn.run

app = FastAPI(title="gogo API", docs_url=None, redoc_url=None, openapi_url=None)

@app.get("/health")
def health():
    return {"status": "ok", "uptime_seconds": int(time.monotonic() - _START)}
```
Response is exactly `{"status":"ok","uptime_seconds":N}` — 200 always, no middleware, no file access, no auth dependency (SEC-01 request enforcement arrives in Phase 3).

### 2. TestClient + pytest seed tests (OPS-02)
```python
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

def test_health_uptime_never_decreases():
    first = client.get("/health").json()["uptime_seconds"]
    second = client.get("/health").json()["uptime_seconds"]
    assert second >= first
```
Source: FastAPI official testing docs — plain `def` tests, synchronous `client.get`, standard `assert` `[CITED: fastapi.tiangolo.com/tutorial/testing/]`.

### 3. Token read precedence — the repo's own pattern to copy (D-04)
`scripts/daily/kline_source.py:26-39` quoted verbatim `[VERIFIED: read this session]`:
```python
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
The api equivalent differs in two deliberate ways: on the non-loopback branch a missing token is a HARD error (`sys.exit(1)`) rather than `return None`, and the write side (`secrets.token_urlsafe(32)`, single-line file, D-05 notice only) is new — but the env-first-file-second read shape and the single-line plaintext convention are copied verbatim.

### 4. Path constants — the single source (D-02)
`scripts/daily/config.py:5-14` quoted verbatim `[VERIFIED: read this session]` — api/ imports these and adds no path code of its own:
```python
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
Importing config.py has a benign side effect (dirs ensured) — acceptable at boot; LOG_DIR already exists and `logs/api/` is created by run_api.bat or the service.

### 5. Task Scheduler convention (OPS-01) — the live source
Quoted above in Pattern 2 from `scripts/daily/install_scheduled_task.ps1:17-33` `[VERIFIED]`. The Phase 1 installer keeps: AtStartup + 5-min RandomDelay, StartWhenAvailable, RestartCount 3 / 10-min, MultipleInstances IgnoreNew, Principal = current user Interactive Limited. It drops the Daily-15:30 trigger and replaces hardcoded paths with `$PSScriptRoot`-derived ones.

### 6. Programmatic uvicorn launch (installed-version-verified)
`uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)` — signature confirmed on the installed 0.51.0 `[VERIFIED: inspect.signature(uvicorn.run) this session]` (params include `app, host, port, workers, log_level, access_log, timeout_graceful_shutdown`, ...). Single process: never pass `workers` (default single). `access_log=False` keeps LB probe traffic out of the console log; if per-request logs are wanted later, flip it in Phase 5 with rotation.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Flat scripts with per-file `sys.path` bootstrap + `BASE =` 3-level up-search (anti-pattern #1, all 40+ scripts/daily modules) | New modules import `PROJECT_ROOT/DATA_DIR/LOG_DIR` from `scripts/daily/config.py`; `api/` is a real package | This phase (ARCHITECTURE.md mandate, D-02) | api/ code contains zero path boilerplate; pytest imports work; Phases 2-5 build on the same pattern |
| `@app.on_event("startup")` | `lifespan=` param (async context manager) | FastAPI docs now label on_event "Alternative Events (deprecated)" `[CITED: fastapi.tiangolo.com/advanced/events/]` | Phase 1 doesn't need either (boot logic precedes uvicorn.run); Phase 2+ should use lifespan if startup work is needed |
| Repo has zero automated tests (27.5k LOC) | First pytest suite in top-level `tests/` with network-blocking autouse fixture | This phase (OPS-02; CONCERNS.md zero-tests concern) | Regression safety for the whole API milestone; pattern proven in vibe-astock |
| Plaintext secrets as gitignored `data/*_token.txt` files, env-first read (tushare/hithink precedents) | Same convention extended to the API token (`data/api_token.txt`) | This phase (D-03/D-04/D-05/D-06) | No `.env` system introduced; consistent secret handling; D-05/D-06 close the leak paths Phase 4 audits |
| Windows autostart via hardcoded-path bat/ps1 (stale `主升浪` path — currently broken on this box; task not even registered) | Paths derived from `%~dp0` / `$PSScriptRoot`; distinct API task registered | This phase (D-07/D-09) | Success criterion 2 becomes true and stays true across future renames |

**Deprecated/outdated:**
- `@app.on_event("startup"/"shutdown")`: deprecated in favor of `lifespan`; don't seed new code with it.
- Hardcoded `BASE=C:\Users\Davis\Desktop\主升浪` in `auto_start.bat`/`install_scheduled_task.ps1`: stale since the repo lives at `Desktop\gogo`; never replicate (D-09).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Registering a Scheduled Task for the current user (Interactive, RunLevel Limited) does not require elevation on this machine | Pattern 2 | The existing ps1 header says "以管理员身份运行此脚本" — may be legacy caution. Mitigation: attempt without elevation; on access-denied, run once elevated. Low risk either way |
| A2 | `StartWhenAvailable` makes a missed AtStartup trigger fire at the next user logon, delivering D-07's "otherwise waits for logon" | Pattern 2 / D-07 | If Windows instead drops the missed trigger, the service stays down until manual start or next reboot. Mitigation: verification step covers both a manual `Start-ScheduledTask` run and a real reboot; add a `-Logon` trigger only if the wait behavior is observed to fail |
| A3 | Disabling `/docs`/`/openapi.json` (docs_url=None) is the right default | Code Example 1 | Purely discretionary (no locked decision); if the user wants interactive docs for manual probing, re-enable — no contract impact |
| A4 | Task-name charset: a CJK task name (e.g. "gogo API 服务") displays correctly in taskschd.msc | Pattern 2 | Existing CJK task names exist on this box, but console listing of them mojibakes in GBK; if the name must round-trip through scripts/greps, an ASCII name ("gogo-api") is safer — planner choice, flag for user only if it matters |
| A5 | Python is resolvable as `python` in the scheduled task's environment | run_api.bat shape | Interactive-logon tasks inherit the user env, where `python` resolves (pip 25.0.1 lives in the user AppData install `[VERIFIED]`); if the task ever runs under a different principal this breaks — verification step catches it |

## Open Questions (RESOLVED)

1. **Does the LB probe (D-08's "load-balancer probe contract") exist today, and does it require the service to answer before user logon?** — RESOLVED (2026-09-03): proceeded per D-07 (logon-gated), adopted in 01-02 flagged assumption A2 with the end-of-phase reboot human-check fallback.
   - What we know: the contract points at `127.0.0.1:8000/health`; D-07 accepts "waits for logon" for a user-attended machine; no probe consumer was named in CONTEXT.md.
   - What's unclear: whether some external system already polls and would alarm during the no-logon window.
   - Recommendation: proceed per D-07 (logon-gated). If a real LB appears, revisit with a SYSTEM-level task decision (explicitly rejected in D-07 for this machine).
2. **Should the SEC-03 refusal message text be user-facing Chinese or ASCII English?** — RESOLVED (2026-09-03): ASCII English, adopted in 01-01 Task 1's stderr wording (names the bound host + GOGO_API_TOKEN remedy).
   - What we know: D-05's success notice wording is pinned verbatim and ASCII; the refusal wording is Claude's discretion.
   - What's unclear: user preference for error text language.
   - Recommendation: ASCII English (encoding safety in bat-redirected logs, Pitfall 5); wording shown in Pattern 1 as a starting point.

## Environment Availability

> Phase has real external dependencies (OS Task Scheduler, ports, packages) — audited live 2026-09-02.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | whole phase | ✓ | 3.13.1 (C:\Users\Davis\AppData\Local\Programs\Python\Python313) | — |
| fastapi | HLT-01 app | ✓ | 0.115.14 (import OK) | — |
| uvicorn | server | ✓ | 0.51.0 (import OK) | — |
| httpx | TestClient transport | ✓ | 0.25.2 (import OK) | — |
| starlette / anyio / pydantic | transitive | ✓ | 0.46.2 / 4.14.2 / 2.13.4 | — |
| **pytest** | OPS-02 suite | ✗ | — | Install `pytest>=8.3` via pip (PyPI latest 9.1.1, `requires_python >=3.10` — 3.13.1 OK). Only missing piece |
| Port 8000 | D-08 default bind | ✓ | no listener (netstat clean) | GOGO_API_PORT override if a future process claims it; Phase 1 must print a clear error on bind failure (Claude's discretion) |
| PowerShell ScheduledTasks module | OPS-01 installer | ✓ | works (200 tasks enumerated) | schtasks.exe as last resort |
| Task Scheduler state | OPS-01 | ✓ | no gogo/API task registered yet — fresh registration | — |
| Windows user context | task principal | ✓ | Davis (interactive) | — |
| cmd.exe + `%~dp0` | run_api.bat | ✓ | standard | — |
| Network (PyPI) | pytest install only | ✓ | pip reached PyPI JSON this session | vendored wheel or Mac-side copy — not expected |

**Missing dependencies with no fallback:**
- pytest — not installed; the plan must include an install step (single `pip install "pytest>=8.3"` or via requirements.txt) before any test task runs. It is the only gap between this machine and the whole phase being runnable.

**Missing dependencies with fallback:**
- None beyond pytest.

**Step 2.6 note:** no Runtime State Inventory section — this is a greenfield phase (no rename/refactor/migration), per the protocol the section is omitted.

## Validation Architecture

`workflow.nyquist_validation: true` in `.planning/config.json` — section required. The repo has NO existing test infrastructure (zero test files, no pytest.ini, pytest not installed `[VERIFIED]`), so Wave 0 must build it from scratch.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >= 8.3 (PyPI latest 9.1.1) via TestClient (starlette 0.46.2) |
| Config file | `pytest.ini` (NEW at repo root: `[pytest]` / `pythonpath = .` / `testpaths = tests`) — required for import mechanics, Pitfall 1 |
| Quick run command | `python -m pytest -q` |
| Full suite command | `python -m pytest` (same suite — 2 test files in Phase 1) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| HLT-01 | GET /health → 200, `{"status":"ok","uptime_seconds":int}`; no auth header needed; uptime non-decreasing | unit (TestClient) | `python -m pytest tests/test_health.py -q` | ❌ Wave 0 — new |
| SEC-03 | non-loopback host + no env token + no token file → refusal, exit != 0, and NO token file created | unit (pure boot fn, tmp_path) | `python -m pytest tests/test_boot.py -q` | ❌ Wave 0 — new |
| SEC-03 | non-loopback + token present (env or file) → no refusal; loopback default → token generated (D-03), notice text equals D-05 sentence and contains no token value | unit (pure boot fn, tmp_path + monkeypatch) | `python -m pytest tests/test_boot.py -q` | ❌ Wave 0 — new |
| OPS-02 | the suite itself runs green with zero network access (autouse blocker) | infra | `python -m pytest -q` | ❌ Wave 0 — new |
| OPS-01 | task registered; service reachable at 127.0.0.1:8000/health after `Start-ScheduledTask` | manual-only (cannot assert OS Task Scheduler from pytest) | `Start-ScheduledTask -TaskName "gogo API 服务"` then `curl http://127.0.0.1:8000/health`; reboot test is a user action | n/a — plan verification step |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/<affected file> -q`
- **Per wave merge:** `python -m pytest -q`
- **Phase gate:** full suite green (plus the manual OPS-01 reboot check) before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `pip install "pytest>=8.3"` — no pytest on the machine today (audited)
- [ ] `pytest.ini` — root config with `pythonpath = .`, `testpaths = tests` (import mechanics)
- [ ] `tests/conftest.py` — autouse network-block fixture (vibe-astock model, quoted in Pattern 3) + env-isolation fixture
- [ ] `tests/test_health.py` — HLT-01 contract tests
- [ ] `tests/test_boot.py` — SEC-03/D-03/D-05 pure-function tests

## Security Domain

`workflow.security_enforcement: true`, ASVS level 1 (`.planning/config.json`) — section required.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | partial | No request auth this phase (SEC-01 is Phase 3 — /health must return 200 with NO key, HLT-01). What IS in scope: token at rest — generation via `secrets.token_urlsafe(32)` (never `random`), env-first-file-second read per the tushare precedent, plaintext single-line file under `data/` matching repo convention |
| V3 Session Management | no | Stateless API; no sessions by design |
| V4 Access Control | partial | Fail-closed bind gate (SEC-03): default `127.0.0.1`; non-loopback bind requires a configured token before the socket ever opens. Access control on requests arrives Phase 3 (SEC-01 constant-time compare) |
| V5 Input Validation | no | Phase 1 has zero request inputs (no path/query/body params on /health) |
| V6 Cryptography | yes | `secrets` module only (CSPRNG); no hand-rolled crypto, no storage of plaintext passwords (single-user token file is the accepted repo pattern) |
| V14 Configuration | yes | `.gitignore` gains `data/api_token.txt` in the same commit as the generator (D-06); docs/openapi disabled on the app (discretionary, see A3); bind + port env-overridable with loopback default |

### Known Threat Patterns for the Phase 1 stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Token value leaked via log/print (one-way — rotation required to recover) | Information Disclosure | D-05: after generation print ONLY the fixed ASCII sentence "API token generated at data/api_token.txt"; never log env values, headers, or the file content; no access-log of request bodies exists (GET /health carries none). Phase 4 SC3 audits log lines |
| Token file accidentally committed (repo possibly public — CONCERNS.md #1) | Tampering / Information Disclosure | D-06 same-commit `.gitignore` entry `data/api_token.txt` (verified absent today — `git check-ignore -v` exit 1); commit discipline = stage specific files, never `git add .`; sync_cloud explicit allow-list cannot add it `[VERIFIED: sync_cloud.py:26-38]` |
| Service booted reachable-but-unauthenticated on a non-loopback bind | Elevation / Spoofing | SEC-03 boot refusal before bind, exit non-zero with clear stderr message (Pattern 1 ordering — generation must not precede the check); loopback default (D-08) |
| Uptime/health manipulated by wall-clock changes | Tampering (minor) | `time.monotonic()` — not NTP/clock settable |
| Unbounded console log growth (LB probes every N seconds) | DoS (disk) | `access_log=False` on uvicorn.run; log rotation is explicitly Phase 5 (OPS-03) — bounded only by reboots until then, accepted |
| Port 8000 conflict with an impostor service | Spoofing | Bind failure surfaces uvicorn's clear error (discretion: print host/port context); D-08 pins the contract port — an impostor is a Phase 4+ concern (mutual auth out of scope) |

**Scope note:** request-path auth (SEC-01), data-classification enforcement (SEC-02), error/stack-trace hygiene and audit scans are Phase 3/4 requirements — Phase 1 must NOT bolt a key check onto /health, which would break HLT-01's "never 401".

## Sources

### Primary (HIGH confidence — verified this session)
- **Live machine probes** — Python 3.13.1; imports of fastapi 0.115.14 / uvicorn 0.51.0 / starlette 0.46.2 / httpx 0.25.2 / anyio 4.14.2 / pydantic 2.13.4; pytest ABSENT; port 8000 free; user Davis; 200 scheduled tasks with no gogo task; `pip 25.0.1`.
- **PyPI JSON API (pypi.org/pypi/{pkg}/json)** — fastapi 0.141.1 / uvicorn 0.52.4 / pytest 9.1.1 / httpx 0.28.1 latest versions, `requires_python` constraints, declared source repos, no deprecation/postinstall.
- **gsd-tools `package-legitimacy check --ecosystem pypi`** — 4/4 exist with canonical repos; SUS only for `unknown-downloads`/`too-new` seam data gaps.
- **In-repo files read in full this session** — `scripts/daily/config.py` (lines 5-14 quoted), `scripts/daily/install_scheduled_task.ps1` (lines 17-33 quoted), `scripts/daily/auto_start.bat` (stale path at line 7), `scripts/daily/kline_source.py` (lines 26-39 quoted), `scripts/daily/sync_cloud.py` (lines 26-38 quoted), `.gitignore` (no api_token entry — check-ignore exit 1), `requirements.txt`, `.planning/*` (REQUIREMENTS/ROADMAP/PROJECT/STATE/config.json), `01-CONTEXT.md`.
- **Namespace-import probe** — `python -c "import scripts.daily.config"` from repo root returned correct PROJECT_ROOT (PEP 420 path).
- **Installed-module inspection** — `inspect.signature(uvicorn.run)` on 0.51.0.
- **vibe-astock tests/conftest.py** (lines 16-23) — network-blocking autouse fixture model.

### Secondary (MEDIUM confidence)
- [FastAPI Testing docs](https://fastapi.tiangolo.com/tutorial/testing/) — TestClient + pytest pattern (Code Example 2).
- [FastAPI Lifespan Events](https://fastapi.tiangolo.com/advanced/events/) — lifespan pattern; on_event deprecated.
- PyPI-declared repo for uvicorn (github.com/Kludex/uvicorn — post-encode maintainer transfer; declared by package metadata).

### Tertiary (LOW confidence)
- None — no findings rest on unverified web search.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — machine-verified imports, versions match CONTEXT.md lock, PyPI metadata cross-checked.
- Architecture: HIGH — every pattern traced to a locked decision (D-01..D-10) or a verified repo file; only discretionary details (A1-A5) are flagged.
- Pitfalls: HIGH — six pitfalls, each rooted in a live repo fact or documented FastAPI/uvicorn behavior; import-mechanics and SEC-03-ordering pitfalls verified by direct probe.

**Research date:** 2026-09-02
**Valid until:** 2026-10-02 (stable stdlib + pinned floors; fast-moving risk is low — floors are machine-verified and already installed; pytest floor 8.3 well below current 9.1.1)


