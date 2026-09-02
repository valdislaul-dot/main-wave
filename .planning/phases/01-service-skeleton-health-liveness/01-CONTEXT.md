# Phase 1: Service Skeleton + /health Liveness - Context

**Gathered:** 2026-09-02
**Status:** Ready for planning

## Phase Boundary

The gogo API service exists as a resident FastAPI process on the Windows machine — it boots, auto-starts after reboot, answers liveness probes without ever touching state files, and refuses to start if it would be exposed without a token. Delivers the repo's first pytest suite (TestClient) asserting the /health contract.

**In scope:** HLT-01 (/health always-200, in-memory only), SEC-03 (fail-closed boot: loopback default, non-loopback without token refuses to start), OPS-01 (Windows Task Scheduler autostart via run_api.bat + install_scheduled_task.ps1 convention), OPS-02 (pytest+TestClient seed tests).

**Not this phase:** /health/ready, state endpoints, triggers, token enforcement on requests (SEC-01), data classification policy, Mac launchd plist (Phase 5 parity), log rotation (Phase 5).

**Success criteria** (from ROADMAP.md, must all be TRUE):
1. GET /health returns 200 `{"status":"ok","uptime_seconds":N}` at any hour — never 401/503, never affected by data age.
2. After a Windows reboot the service is running without manual launch and reachable on 127.0.0.1.
3. Starting with a non-loopback bind (e.g. 0.0.0.0) and no API token configured → refuse to start with a clear error.
4. `pytest` passes the repo's first automated tests asserting the /health contract.

## Implementation Decisions

### Code Location
- **D-01:** The FastAPI service lives in a new top-level `api/` package (`api/main.py` + submodules), NOT under `scripts/`. Rationale: resident service vs daily batch scripts are different lifecycles; pytest imports work naturally with a package; Phases 2–5 add routes/jobs/auth/classification modules that need room to grow. — **Reversibility:** costly — moving the package later touches imports, tests, run_api.bat, and the scheduled-task action after Phases 2–5 have built on it.
- **D-02:** `api/` imports path constants (`PROJECT_ROOT`, `DATA_DIR`, `LOG_DIR`) from `scripts/daily/config.py` — do NOT copy the per-file `BASE = os.path.dirname(...)` sys.path pattern (ARCHITECTURE.md anti-pattern #1 explicitly forbids it for new modules).

### API Token (SEC-03 boot check dependency)
- **D-03:** Token auto-generated on first start: if `data/api_token.txt` does not exist, the service generates a random token via `secrets` and writes it there. Path is pinned by Phase 4 SC4 (`data/api_token.txt` must appear in neither git history nor the sync_cloud whitelist).
- **D-04:** Read priority: `GOGO_API_TOKEN` env var first, file second — same pattern as the tushare token (`scripts/daily/kline_source.py:26`). The scheduled task uses the file; env override is for manual/test runs.
- **D-05:** After generating, the service logs/prints ONLY "API token generated at data/api_token.txt" — never the value. Reset = delete the file, restart. — **Reversibility:** one-way — a token value that lands in any log can't be un-leaked without rotation, and Phase 4 SC3 audits that no log line contains a token value; breaking this decision means a failed Phase 4 audit.
- **D-06 (non-negotiable, same commit):** `.gitignore` gains `data/api_token.txt` in the SAME commit as the code that creates it. The repo may be public (CONCERNS.md #1: anonymous fetch returned 200) and `sync_cloud.py` auto-commits daily.

### Windows Autostart
- **D-07:** Task Scheduler registration copies the existing convention from `scripts/daily/install_scheduled_task.ps1`: `AtStartup` trigger + 5-min random delay, principal = current user (Interactive, RunLevel Limited), `StartWhenAvailable`, `RestartCount 3` / 10-min interval, `MultipleInstances IgnoreNew`. Distinct task name (not "主升浪每日选股流水线"). Behavior: runs ~5 min after boot when the user is logged in; otherwise waits for logon — accepted tradeoff for a user-attended trading machine (SYSTEM boot task rejected: no user env, expanded privilege surface).
- **D-08:** Default port **8000**, overridable via `GOGO_API_PORT`. The load-balancer probe contract points at `127.0.0.1:8000/health`. — **Reversibility:** one-way — the LB's probe URL is configured against this default; changing it later changes what external consumers configure.
- **D-09:** `run_api.bat` (repo root, OPS-01) locates the repo via `%~dp0` relative path — do NOT copy the hardcoded stale `BASE=C:\Users\Davis\Desktop\主升浪` bug in `scripts/daily/auto_start.bat`.

### Mac Scope
- **D-10:** Phase 1 delivers Windows autostart only. The service code itself must run on Mac (config.py auto-detects PROJECT_ROOT on both ends), but the launchd plist is deferred to Phase 5 (Win/Mac parity).

### Claude's Discretion
- Add `fastapi` / `uvicorn` / `pytest` / `httpx` to `requirements.txt` (currently only akshare/requests/streamlit/tushare — Mac parity requires it; versions machine-verified: fastapi 0.115.14, uvicorn 0.51.0, Python 3.13.1).
- uvicorn single process, programmatic launch from `api/main.py` (run_api.bat calls it directly); startup log to `logs/api/` (gitignored).
- Tests in top-level `tests/` with a network-blocking autouse fixture (pattern proven in vibe-astock, CONCERNS.md positive pattern). Token generation must be test-safe (monkeypatch/override so TestClient runs never touch the real `data/api_token.txt`).
- Token file format/content (e.g. single-line raw key), exact boot-check error message wording for the non-loopback-no-token case, and fail-closed check implementation details — follow SEC-03 literally.
- Port 8000 conflict behavior (clear startup error, not silent fallback).

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Planning docs
- `.planning/ROADMAP.md` — Phase 1 goal, success criteria (4 items), research-skip rationale, phase dependency order
- `.planning/REQUIREMENTS.md` — HLT-01 (/health contract verbatim), SEC-03 (fail-closed boot), OPS-01 (autostart), OPS-02 (pytest); v2 backlog and Out of Scope table
- `.planning/PROJECT.md` — Constraints (Python+FastAPI, reuse data/logs read-only, Win-primary/Mac-compatible, no real-order trading), Key Decisions (auth classification, raw passthrough)

### Codebase maps
- `.planning/codebase/ARCHITECTURE.md` — anti-patterns (path-boilerplate duplication, silent-except culture), "new modules import from config.py" rule, flat-module + lazy-import convention
- `.planning/codebase/STACK.md` — runtime facts (Python 3.13.1, no venv, requirements.txt gaps), Windows automation conventions, `.streamlit`/port 8501
- `.planning/codebase/CONCERNS.md` — repo-visibility risk (possibly public), plaintext-token-at-rest precedent and mitigations, zero-tests status, positive testing patterns to borrow

### Existing code
- `scripts/daily/config.py` — the single path base (`PROJECT_ROOT`/`DATA_DIR`/`LOG_DIR`); api/ must import from it
- `scripts/daily/install_scheduled_task.ps1` — the Task Scheduler convention to copy (triggers/settings/principal)
- `scripts/daily/auto_start.bat` — anti-example only: stale hardcoded BASE path must not be replicated
- `scripts/daily/kline_source.py` §26 — env-var-first-file-second token read pattern
- `.gitignore` — where `data/api_token.txt` must be added (same commit as token code)

## Existing Code Insights

### Reusable Assets
- `scripts/daily/config.py`: `PROJECT_ROOT`/`DATA_DIR`/`LOG_DIR` dual-platform auto-detection — the api/ package's only path dependency.
- `scripts/daily/install_scheduled_task.ps1`: complete Task Scheduler registration pattern (New-ScheduledTaskAction/Trigger/Settings/Principal) to adapt for the API task.
- `vibe-astock/tests/conftest.py` pattern (referenced in CONCERNS.md): network-blocking autouse fixture — the model for the new `tests/` suite.

### Established Patterns
- No package structure exists anywhere in the repo today — `api/` is deliberately the first, justified by pytest import needs; keep it small and importable.
- Plaintext token files under `data/` with `.gitignore` coverage are the accepted secret-handling pattern (tushare/hithink precedents); no `.env` system exists.
- 定稿机制 (CLAUDE.md): trading-mechanism changes need user sign-off — not triggered here (new API surface, no existing mechanism modified).
- Upload rule (2026-08-31): only code + market data go to GitHub; `data/api_token.txt` and `logs/` must never enter git or the `sync_cloud.py` whitelist.
- Single-process discipline: the API is one uvicorn process; the repo has no cross-process locks and the pipeline runs as separate short-lived processes (relevant context for later phases).

### Integration Points
- `run_api.bat` (repo root) → `python -m api.main` style entry; scheduled task action mirrors the ps1's cmd.exe /c wrapper.
- `logs/api/` directory for service startup output; keep stdout free of token values (D-05).
- `requirements.txt` — add the four new deps without disturbing existing pins.
- `tests/` top-level with `conftest.py` network-blocking fixture; pytest must pass on both Win and Mac without network.
- Git commits must stage specific files only (never `git add .`) — the token file must never be staged by accident.

## Specific Ideas

No specific references or examples given by the user beyond the decisions above — open to standard approaches.

## Deferred Ideas

- Mac launchd plist (autostart parity) — Phase 5.
- `/health/details` auth-gated endpoint, log rotation — Phase 5 (OPS-03).
- Anything in REQUIREMENTS.md v2 (job cancel, orphan adoption, ETag, rate limiting, digest aggregation) — future release, explicitly out of scope.
- Discussion stayed within phase scope; no todos were folded (todo match count: 0).

---

*Phase: 1-Service Skeleton + /health Liveness*
*Context gathered: 2026-09-02*
