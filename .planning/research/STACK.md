# Stack Research

**Domain:** FastAPI HTTP API service layer (health check + read-only JSON state + subprocess-triggered operations) inside an existing Python A-share trading system
**Project:** gogo (主升浪) — Win 端为主 / Mac 端同步, no Docker, existing Streamlit GUI
**Researched:** 2026-09-02
**Confidence:** HIGH for core choices (machine-verified), MEDIUM for ecosystem-consensus choices

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended | Conf. |
|------------|---------|---------|-----------------|-------|
| Python | 3.13.1 (machine) | Runtime | Whole 27.5k-LOC trading system already runs on it; FastAPI 0.115+/0.141+ both require >=3.10, satisfied | HIGH |
| FastAPI | >=0.115.14 (installed baseline; latest stable 0.141.1) | HTTP framework | Project-level decision (all-Python, no Node). Async-native (needed to `await` subprocesses without blocking), built-in OpenAPI `/docs` for debugging, Pydantic response models give a stable typed JSON contract for consumers. **Do not force-upgrade** past what the shared interpreter tolerates (see Version Compatibility) — 0.115.x is fully sufficient for a health/status/trigger API | HIGH |
| Uvicorn | >=0.51.0 (installed; latest 0.52.4) | ASGI server | The standard FastAPI server. **One single process** — never `--workers` on Windows (spawn re-imports the app module: deadlock risk, known `_subprocess.py` stdin bugs). A single event-loop process is far more than enough for LB-scale probing + JSON reads. Plain `uvicorn`, not `uvicorn[standard]` (uvloop is Unix-only; extras are unnecessary weight) | HIGH |
| Pydantic v2 | 2.13.4 (installed) | Response models / validation | FastAPI-native; used only for thin response schemas over existing JSON state — do **not** re-architect `data/`/`logs/` state into a database or ORM layer | HIGH |

### Supporting Libraries

| Library | Version | Purpose | When to Use | Conf. |
|---------|---------|---------|-------------|-------|
| Starlette | 0.46.2 (installed) | Transitive (FastAPI dep) | Never import directly except `starlette.testclient` / `app.state` patterns — comes free with FastAPI | HIGH |
| httpx | 0.25.2 (installed) | TestClient transport | Required by Starlette's TestClient; already present. Dev-only | HIGH |
| pytest | 9.1.1 (latest) | API test seed | The repo has **zero automated tests** (CONCERNS.md). The API layer is the natural first seed: pure endpoints over fixture JSON, TestClient, no network. Optional pytest-asyncio only when testing the subprocess runner directly | MEDIUM |
| stdlib only: `asyncio.subprocess`, `secrets`/`hmac`, `json`, `time`, `sys` | — | Operation triggers, auth compare, JSON reads | The entire trigger/run-manager/auth surface needs **no third-party code** (see Patterns below) | HIGH |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `uvicorn main:app --reload` | Dev hot-reload | watchfiles 1.2.0 already installed; never use `--reload` or `--workers` in production on Windows |
| Windows Task Scheduler (existing `install_scheduled_task.ps1` convention) | Auto-start API at boot/logon | Register a "主升浪API服务" task: action `python -m uvicorn api.main:app --host 127.0.0.1 --port 8001`, WorkingDirectory = repo, `-RestartCount 3 -RestartInterval 10min -MultipleInstances IgnoreNew` (pattern already proven in the repo). Adequate for a single-user desktop; API process death is detected by Task Scheduler restart-on-failure | MEDIUM |
| NSSM (only if needed) | True Windows service | Upgrade path if the machine must run headless/session-independent with guaranteed crash recovery + log rotation. Register `python.exe -m uvicorn ...` + `AppDirectory`. Not required for phase 1 | MEDIUM |
| launchd plist (Mac 端) | Auto-start on secondary machine | `RunAtLoad` + `KeepAlive=true`, same code, same command | MEDIUM |

## Installation

```bash
# Additions to requirements.txt (project convention is unpinned >= floors)
fastapi>=0.115.14
uvicorn>=0.51.0

# Dev only (optional, machine already has httpx 0.25.2)
pytest>=9.1.1
```

No venv required — the machine's shared interpreter already carries the compatible stack (verified 2026-09-02). The API process must run under the **same** interpreter the pipeline scripts use, because operation triggers spawn `sys.executable`. If a future dependency conflict appears, use a venv with `--system-site-packages` rather than isolating — subprocess triggers need the pipeline's deps.

**Auth / secret plumbing (zero new deps):**
- Token source: env var `GOGO_API_TOKEN` first, then untracked `data/api_token.txt` — the exact pattern `kline_source.py` already uses for the Tushare token. Never commit, never whitelist in `sync_cloud.py`.
- Compare with `secrets.compare_digest` (constant-time). Built-in `fastapi.security.APIKeyHeader(name="X-API-Key")` dependency on every write endpoint → 401 + `WWW-Authenticate: APIKey` when missing/absent (machine-verified on 0.115.14).

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| FastAPI | Flask / Quart | Already decided at project level (all-Python). Flask is sync WSGI — you would lose native `await subprocess`; Quart adds nothing over FastAPI's ecosystem |
| Single uvicorn process | gunicorn + uvicorn workers | Unix-only deployment (Mac/Linux server). **Not available on Windows** — gunicorn is not Windows-supported |
| Single uvicorn process | Hypercorn | Only if you need HTTP/2 or Windows multi-process without spawn pitfalls — unneeded at this scale |
| `asyncio.create_task` runner | Celery / RQ + Redis / RabbitMQ | Distributed task queue only if operations must outlive the API process across machines. One machine, single-flight → massive overkill |
| Static API key (APIKeyHeader) | JWT / OAuth2 password flow / session cookies | Multi-user, per-user audit, token expiry/refresh needs. Single-user local API → JWT is ceremony without security benefit; OAuth2 form flow would also drag in `python-multipart` |
| Task Scheduler first | NSSM service wrapper | Machine runs headless / user never logs in / crash-recovery SLA stricter than Task Scheduler's restart-on-failure |
| Direct JSON reads of `data/`/`logs/` | SQLite/DB + SQLAlchemy | Second data source would violate the project's hard rule (不引入第二数据源). The JSON files ARE the database |
| Stdlib `asyncio.subprocess` | `background_tasks`/threading | FastAPI `BackgroundTasks` is same-process, after-response only — it cannot survive API restarts and gives no run-status tracking; `threading` blocks on GIL-free waits but adds lifecycle code for nothing |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `uvicorn --workers` on Windows | Multiprocessing **spawn** re-imports the app module — deadlock/`AttributeError` reports with heavy module init; reloader kills whole console groups via `CTRL_C_EVENT` | One uvicorn process; multiple separate processes behind the LB only if ever needed |
| `gunicorn` | Unix-only; does not run on Windows | uvicorn directly |
| Celery / Redis / RQ | Distributed queue infra for a 1-machine single-flight job | `asyncio.Lock` + `asyncio.create_task` + in-memory run registry (JSON persisted to `data/api_runs.json` for restart visibility) |
| JWT (`pyjwt`/`python-jose`) + `passlib` | Single static key; nothing to expire/refresh; more attack surface, more deps | `APIKeyHeader` + `secrets.compare_digest` |
| `python-multipart` | Only needed for `OAuth2PasswordRequestForm` (form parsing) — not needed for header/bearer schemes | Skip entirely |
| `pydantic-settings` | Project already has `scripts/daily/config.py` auto-path detection + env-first/token-file convention | Reuse `config.py`; read env var then `data/api_token.txt` |
| SQLAlchemy / SQLite / any ORM | Second data source = data-drift risk the project explicitly forbids | `json.load` over state files with small Pydantic response models |
| `uvicorn[standard]` extras | uvloop is Unix-only; httptools/websockets unneeded for JSON API; python-dotenv conflicts with the env-first pattern | plain `uvicorn` |
| `BackgroundTasks` for operation triggers | Same-process, runs after response, no status/registry, lost on restart | Managed `asyncio.Task` + single-flight lock + run record |
| `win32serviceutil` (pywin32 service) | Most code to maintain for auto-start | Task Scheduler (phase 1) → NSSM (if needed) |
| Docker / containerization | Project constraint (no Docker today); desktop Win deployment | Native scheduled task / service wrapper |
| Importing pipeline modules (`run_pipeline`, `scoring`, …) inside the API process | Heavy module-level init (pandas/akshare) slows startup, blocks spawn, and couples API uptime to trading-code health | Subprocess isolation — the API never imports trading code; it only spawns `python scripts/daily/xxx.py` exactly like the scheduled task does |

## Stack Patterns by Variant

**If the API and a pinned third-party stack share the interpreter (this machine: vibe-astock/langgraph ecosystem carries fastapi 0.115.x):**
- Stay on `fastapi>=0.115.14,<0.116` unless the other pin is lifted. Feature needs here (health + JSON + API-key + subprocess) are satisfied by 0.115.x — the already-installed 0.115.14 was smoke-tested 2026-09-02 on Python 3.13.1 (health 200, APIKeyHeader 401/200, TestClient OK).

**If a fresh install on the Mac side (no version conflicts):**
- Use latest stable: fastapi 0.141.1 + uvicorn 0.52.4 (both require Python >=3.10; fastapi 0.141.1 pairs starlette>=0.46.0 + pydantic>=2.9.0 — all satisfied by the versions proven on the Win side).

**If the load balancer needs readiness semantics beyond liveness:**
- Keep `GET /health` = pure liveness (200 `{"status":"ok","uptime":N}`); add `GET /ready` later that 503s when `data/market_state.json` is missing or stale for a trading day (cache check result 2-10 s so probe floods do not touch disk constantly). Probes key off HTTP status codes, not bodies.

**If the API must listen beyond loopback (LAN/cloud):**
- Only with explicit user decision — repo visibility is **suspected public** (CONCERNS.md: anonymous HTTP 200 on 2026-09-02), so default bind `127.0.0.1` and treat any exposure as hostile: require the API key on write ops (mandatory) and consider it on state endpoints that reveal positions/账目. Prefer a reverse proxy with TLS over raw `0.0.0.0` uvicorn.

**Port choice:**
- Default `8001` (configurable via env `GOGO_API_PORT`). Avoids Streamlit 8501 (GUI) and other dev-server defaults on the machine.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| fastapi 0.115.14 | Python 3.13.1, starlette 0.46.2, pydantic 2.13.4, uvicorn 0.51.0, httpx 0.25.2 | **Machine-verified 2026-09-02**: smoke test of /health + APIKeyHeader 401/200 + TestClient passed |
| fastapi 0.141.1 (latest, PyPI 2026-09-02) | Python >=3.10; requires starlette>=0.46.0, pydantic>=2.9.0, typing-extensions>=4.8.0 | Installed starlette 0.46.2 / pydantic 2.13.4 satisfy the constraints — upgrade is possible if nothing else pins `<0.116` |
| uvicorn 0.51.0 (installed) / 0.52.4 (latest) | Python >=3.10 | Plain uvicorn has no extra deps beyond click/h11 |
| pytest 9.1.1 (latest) | Python >=3.10 | Dev-only |
| APIKeyHeader / HTTPBearer | No `python-multipart` needed | Only `OAuth2PasswordRequestForm` requires multipart — avoid that scheme |
| Python 3.13 (Win) vs Mac-side Python | Code identical | Config auto-detects platform (`config.py` IS_MAC/IS_WIN) — do not hardcode paths in the API package |

## Sources

- PyPI JSON metadata (2026-09-02 fetch): fastapi latest 0.141.1 / requires_python >=3.10 / starlette>=0.46.0 + pydantic>=2.9.0 — HIGH (official registry, cross-checked against installed env)
- PyPI JSON metadata: uvicorn latest 0.52.4 / requires_python >=3.10 — HIGH
- PyPI JSON metadata: pytest latest 9.1.1 — HIGH
- https://fastapi.tiangolo.com/reference/security/ — built-in APIKeyHeader/HTTPBearer/Basic schemes, dependency pattern, 401 behavior — HIGH (official docs)
- https://fastapi.tiangolo.com/tutorial/background-tasks/ — BackgroundTasks is same-process/after-response; docs point to Celery for heavy work — HIGH (official docs)
- https://pypi.org/project/uvicorn/ + GitHub issue/discussion reports (open-webui #23476, uvicorn #2263) — `--workers` on Windows = multiprocessing spawn hazards; run single process — MEDIUM (community consensus, multiple corroborating reports)
- WebSearch 2026-09-02: health-endpoint conventions (liveness vs readiness split, 200/503 semantics, `{"status","uptime"}` body shape, probe intervals 5-10 s) — MEDIUM (multiple independent sources: 137foundry, ASOasis, Plane docs, dev.to)
- WebSearch 2026-09-02: NSSM vs Windows Task Scheduler for uvicorn services — MEDIUM (multiple community guides, consistent)
- Local empirical verification on 2026-09-02: pip list (fastapi 0.115.14, starlette 0.46.2, pydantic 2.13.4, uvicorn 0.51.0, httpx 0.25.2, watchfiles 1.2.0), Python 3.13.1, functional smoke test — HIGH
- Project grounding: `Desktop/gogo/.planning/PROJECT.md`, `.planning/codebase/CONCERNS.md`, `scripts/daily/config.py`, `install_scheduled_task.ps1`, `requirements.txt` — HIGH (local audit)

---
*Stack research for: gogo FastAPI HTTP API service layer (health + state + subprocess-triggered ops)*
*Researched: 2026-09-02 — verified against live PyPI and machine environment, not training data*
