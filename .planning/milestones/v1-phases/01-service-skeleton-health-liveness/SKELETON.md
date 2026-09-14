# Walking Skeleton — gogo API 服务 (main-wave API)

**Phase:** 1
**Generated:** 2026-09-02

## Capability Proven End-to-End

A probe can GET http://127.0.0.1:8000/health on the resident Windows service at any hour and always receive 200 `{"status":"ok","uptime_seconds":N}` — the service boots via `python -m api.main`, auto-starts after reboot via a Task Scheduler task, and refuses to boot on a non-loopback bind when no API token is configured.

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Framework | FastAPI 0.115.14, programmatic `uvicorn.run(app, host, port)` single process | Locked (PROJECT.md): full-Python stack; TestClient in-process testing; no workers ever — one resident process (D-08 single-process discipline) |
| Data layer | None — zero file/DB access on the /health path | HLT-01 contract: pure in-memory uptime from `time.monotonic()`; state-file reads arrive Phase 2 via a defensive read layer, never in Phase 1 |
| Auth approach | Fail-closed boot gate (SEC-03): default bind `127.0.0.1`; non-loopback requires `GOGO_API_TOKEN` env or `data/api_token.txt` (secrets-generated, gitignored) before the socket opens; request auth (X-API-Key) deferred to Phase 3 | Loopback default + no-token refusal = never reachable-but-unauthenticated; token-at-rest convention copied from the tushare precedent (`data/*_token.txt`, env-first-file-second) |
| Deployment target | Resident process on the Windows box: Task Scheduler task `gogo-api` (AtStartup + 5-min random delay, Interactive/Limited principal) → `cmd.exe /c <repo>\run_api.bat` → `python -m api.main`; stdout/stderr → `logs/api/console.log` | Repo convention from `install_scheduled_task.ps1`, minus its stale hardcoded path; Mac launchd plist deferred to Phase 5 (D-10) |
| Directory layout | Top-level `api/` package (`__init__.py`, `main.py`, `boot.py`) + top-level `tests/` + root `pytest.ini`; paths imported from `scripts/daily/config.py` (D-02) | api/ is the repo's first package (pytest import needs + Phases 2-5 room); import mechanics = PEP 420 namespace import of `scripts.daily.config` resolved via repo-root `sys.path` (`python -m api.main`, pytest `pythonpath = .`) |
| Secrets | `data/api_token.txt` (single-line, `secrets.token_urlsafe(32)`), gitignored in the same commit as the generator; env `GOGO_API_TOKEN` overrides file | D-03/D-04/D-05/D-06; repo may be public (CONCERNS.md) and `sync_cloud.py` auto-commits — file can never enter git |

## Stack Touched in Phase 1

- [x] Project scaffold: `api/` package, `pytest.ini`, `tests/` suite with network-blocking autouse fixture (repo's first automated tests), requirements floors added
- [x] Routing — one real route: `GET /health` (in-memory, always 200)
- [ ] Database/state — NONE by design: Phase 1 code never touches `data/` or `logs/` on the request path; state reads are Phase 2's vertical slice
- [ ] UI — NONE: consumers are HTTP probes/scripts; the Streamlit GUI is untouched and out of scope
- [x] Deployment — resident service registered in Windows Task Scheduler (`gogo-api`) with a documented local full-stack run command (`run_api.bat`); real-reboot confirmation is the end-of-phase human check

## Out of Scope (Deferred to Later Slices)

- /health/ready readiness endpoint, state passthrough endpoints, freshness headers (Phase 2)
- X-API-Key request enforcement, job triggers, single-flight locks (Phase 3)
- Data-classification auth on 持仓/账本/候选, error/stack-trace hygiene audits (Phase 4)
- Mac launchd plist, log rotation, auth-gated /health/details (Phase 5)
- Token value rotation UI, CORS, WebSockets, webhooks, queue infra (REQUIREMENTS.md Out of Scope)

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this skeleton without altering its architectural decisions:

- Phase 2: read-only state endpoints + defensive read layer (market/auction/zt-pool verbatim + X-Data-* headers + /health/ready)
- Phase 3: trigger runner with durable jobs + single-flight locks + X-API-Key enforcement
- Phase 4: exposure hardening + data classification (token-gated 持仓/账本/候选)
- Phase 5: recovery, observability & ops polish (details endpoint, rotation, Win/Mac test parity)
