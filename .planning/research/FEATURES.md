# Feature Research

**Domain:** FastAPI HTTP API service layer — load-balancer health checks + read-only status endpoints + operation-trigger endpoints + write-endpoint auth, layered over a JSON-file-backed Python A-share trading system (gogo)
**Researched:** 2026-09-02
**Confidence:** MEDIUM (web sources, cross-checked across 3+ independent references per finding; no official-doc tier available in this run)

## Feature Landscape

### Table Stakes (Users Expect These)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| GET /health — liveness with status + uptime_seconds | LB/consumer probe must exist and be stable; PROJECT.md Active requirement already names it (`status` + `uptime` 秒) | LOW | Bare endpoint: no I/O, no dependency checks, no `response_model` (a validation failure would 422 and non-2xx reads as unhealthy). `include_in_schema=False`. Always 200 while the process serves requests. Body: `{"status":"ok","uptime_seconds":N}` — uptime is informational for humans; LBs key off status code only, never the body |
| Health semantics: 200 = healthy, 503 = cannot serve; never 2xx-with-error-body | LB routing convention (Nginx/Traefik/cloud probes all key off status code) | LOW | LBs do NOT parse health bodies. 500 = checker bug; avoid 4xx on health paths (keep them out of auth/rate-limit middleware — probes must reach them unauthenticated). A body `{"status":"ok"}` is for humans/dashboards only |
| **Data staleness must NEVER 503 /health** | gogo data is stale *by design* on nights/weekends/holidays — a freshness-based 503 would flap the LB out of rotation whenever the pipeline hasn't run yet | LOW (discipline) | Service health ≠ data-pipeline health. Readiness checks only "can this process read the files it serves" (data dir exists/readable, event loop alive). Data age is a *payload* concern (freshness fields), not a probe-status concern. This is the single most important design rule for this domain |
| Read-only status endpoints over existing JSON (market state / temperature / auction summary) | Core value of the API: external consumers get gogo state over HTTP without touching the pipeline | MEDIUM | Read `data/market_state.json` (date/zt_n/max_cons/money_effect — this IS the temperature input), `data/auction_state.json` (current/history), `data/zt_pool_state.json` (`as_of_date`+`last_updated` exist already). No DB, no second data source — read the file the pipeline wrote (Key Decision: 复用现有 JSON) |
| Every status payload carries as-of date + source-file freshness metadata | The 数据引用纪律 culture (data is the only authority; consumers must see how old the data is) — and API convention: honest as-of timestamps, ISO8601 UTC, `null` for known-unset | LOW | gogo files already carry `date`/`as_of_date`/`last_updated`/`created` fields — surface them verbatim in a `meta.freshness` block per source. Do not recompute or "improve" them (推测污染 rule) |
| Stable envelope: `{"data":...}` with `meta` (server_time, freshness); errors never ride on 200 | Consumer contract predictability; partial/degraded data usable → 200 with body flag, not 503 | LOW | Degraded = 200 + explicit `degraded:true`/warning list (market_state.json already has a `warning` field from the 赚钱效应恒0 guard — expose it). 503 only when data is unusable, i.e. file missing/corrupt/unreadable |
| X-API-Key auth on all operation-trigger (write-type) endpoints | PROJECT.md Security constraint: 操作触发接口必须鉴权; repo exposure history (anonymous 200) makes an open trigger endpoint a real remote-code-execution surface | LOW | `fastapi.security.APIKeyHeader(name="X-API-Key")` via `Security()`; key from env var first, then gitignored file (gogo precedent: `data/tushare_token.txt` pattern); no default value; fail fast at startup if key missing; ≥32-char random. 401 when missing (auto_error=False to distinguish), 403 when wrong |
| Trigger endpoints return immediately with a job id; status via polling — never a synchronous long request | Pipeline runs take minutes (scraping with rate-limit sleeps); a sync POST would die on proxy/LB timeouts and block the event loop if done naively | MEDIUM | POST → create job record + launch subprocess → `202` `{"job_id":..., "status":"accepted"}`. `GET /jobs/{job_id}` returns pending/running/succeeded/failed. Do NOT use FastAPI `BackgroundTasks` for this (in-process, lost on restart, exceptions swallowed) |
| **Never `subprocess.run()` in an `async def` handler** | Freezes the whole uvicorn event loop — every request hangs (documented incident class) | LOW (discipline) | Use `Popen` with `DEVNULL` stdio, or `asyncio.create_subprocess_exec` + `await proc.wait()`; or a plain `def` endpoint (threadpool). Mandatory for a service that must keep answering /health while a pipeline runs |
| Operation triggers launch the EXISTING scripts (subprocess), never mutate state directly | Data authority stays with the pipeline; API is a third entry point, not a second writer (Key Decision: 不干扰现有管线) | MEDIUM | `POST /triggers/run_pipeline`, `/triggers/morning_check`, `/triggers/backtest` wrapping `python scripts/daily/...`. No endpoint may write portfolio/candidates JSON itself — dual-writer divergence would break the 定稿机制 |

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Readiness checks probe the REAL served path (file stat of the exact JSONs each endpoint serves) | Fixes the classic "probe green, app broken" disjoint-path anti-pattern; LB only routes to an instance that can actually serve | LOW | Not a stub TCP/HTTP check: stat the state-file registry (existence + readable, ~sub-ms, cached). Never write files from probes; no freshness threshold in the probe |
| Per-source freshness & staleness policy surfaced in every response + a `GET /status/health` style data-pipeline digest | gogo already computes health signals nobody can query: data_health_check 8-item report, market_state warning field, auction snapshot quality guard. Exposing them makes the API "honest status" instead of a mood ring | MEDIUM | Digest endpoint aggregates: state file age per source, expected-write windows (trading day vs weekend — 盘后/T+1 rules), warning fields. Consumers (incl. future cloud panel) decide alerting policy; API reports, doesn't police |
| Single-flight run guard + overlap visibility (409 with running job_id) | Prevent double pipeline runs — pipeline is already scheduled daily (15:30 task); an API-triggered run overlapping the scheduled run would double-scrape and fight over JSON writes | MEDIUM | In-process lock is NOT enough (API restart clears it); use a lock file in `logs/` the same way the scheduled task can check, plus job registry state. Return `409 Conflict {"running_job_id":...}` on overlap |
| Durable file-backed job registry (JSON in `logs/`), re-attachable after API restart | gogo has no DB/broker and shouldn't grow one; a job JSON (id/status/pid/started/completed/exit_code/log tail path) survives restarts and lets a re-started API report on orphaned subprocesses | MEDIUM | Matches repo convention (logs/ gitignored JSON). Subprocess detached via `creationflags=CREATE_NEW_PROCESS_GROUP|DETACHED_PROCESS|CREATE_NO_WINDOW` on Windows (`start_new_session=True` is silently ignored there) so the run outlives an API crash; registry tracks it |
| Portfolio/temperature endpoints behind the SAME auth as write endpoints when bind ≠ 127.0.0.1 | Account data (real positions/P&L) is the most sensitive thing in this repo and the repo history is a known leak concern — read ≠ public when the payload is a trading account | LOW | Split read surface: market-state data public-safe; `portfolio`/`trading_journal`-derived payloads require the API key (or refuse to serve off-localhost). "Read-only = open" is the wrong default given CONCERNS.md |
| `GET /health/details` (auth-gated) for humans | Public probe stays minimal; humans get deps/versions/last-check breakdown | LOW | Two-tier health pattern: minimal public probe vs detailed internal view. P2 |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Celery/Redis task queue for "proper" async jobs | Search results push Celery for long-running work; looks production-grade | New infra on a machine with no container/broker; two machines to keep in sync; single-user system doesn't need queues/retries/multi-worker | `Popen` + durable JSON job registry + poller thread. Revisit only if API gains real concurrency needs |
| /health returning 503 when market data is stale | "If data is old the service is unhealthy" intuition | Night/weekend/holiday staleness is *normal*; LB would flap instances out of rotation for hours daily; conflates pipeline health with service health | Staleness lives in payload `meta.freshness` + the data-pipeline digest endpoint. Service 503s only when it cannot read/serve |
| Direct state-mutation endpoints (POST /portfolio, PATCH /candidates) | "API convenience" | Creates a second writer to files the pipeline owns → divergence; violates data-authority rule and 定稿机制 | Triggers that run the existing scripts; state changes only through pipeline code paths |
| Real-time push/WebSocket streaming of status | "Live" appeal | State files are snapshot-based; push adds connection state, ordering semantics, replay problems for zero users | Polling GETs with `Cache-Control: no-cache`/`max-age` short + ETag; JSON snapshots are small |
| Webhooks/notifications on pipeline completion | Nice automation | Push infra + endpoint exposure + retry semantics for a single consumer that can poll | Job-status polling endpoint |
| Health body exposing internals (paths, hostnames, dependency details, version strings) on the PUBLIC probe | Debugging convenience | Public probe is reachable from anywhere the service is; feeds recon (repo already has exposure history) | `GET /health/details` behind API key |
| Per-client keys / JWT / OAuth / user management | Enterprise auth expectations | Single-user system; key lifecycle overhead; gogo's whole identity model is token files | One strong static API key for write-type + sensitive-read endpoints; rotate manually |
| PUT full-REST CRUD on gogo state resources | REST purity | Half the state is derived/historical JSON not meant for editing | Read-only GETs + operation triggers |

## Feature Dependencies

```
GET /health (liveness)
    └── (none — deliberately dependency-free)

state-file registry (path list + stat freshness reader)  ← FOUNDATION
    ├──requires──> GET /health readiness semantics (probe real files)
    └──requires──> status endpoints' meta.freshness blocks
                       └──requires──> stable envelope (data/meta)

auth (API key, env-first config)
    ├──requires──> operation-trigger endpoints (POST 202 + job_id)
    ├──requires──> portfolio/sensitive read endpoints (off-localhost)
    └──enhances──> GET /health/details

job registry (durable JSON) + Windows-safe subprocess launcher
    ├──requires──> trigger endpoints (POST /triggers/*)
    ├──requires──> GET /jobs/{job_id} status polling
    └──enhances──> single-flight guard (lock file + registry state)

pipeline digest (data_health_check + warning fields aggregation)
    └──enhances──> status endpoints (degraded flag + per-source freshness)
```

### Dependency Notes

- **State-file registry is the foundation**: freshness/staleness policy is shared by readiness (existence/readability), status `meta.freshness`, and the digest endpoint. Build it once in the first phase; everything else reads from it.
- **Auth must exist before portfolio endpoints ship** if the service binds anything but 127.0.0.1: sensitive-read protection and write protection are the same dependency.
- **Job registry enables the single-flight guard**: "is a run already in progress" must survive API restarts, so the guard reads the registry/lock file, not an in-memory flag.
- **Trigger endpoints require the Windows subprocess launcher first**: launch flags and `taskkill /T /F` tree-kill semantics are the load-bearing part; the HTTP surface is thin on top.
- **Readiness "probe real files" conflicts with "liveness stays bare"**: resolved by endpoint split — `/health` never stats files; the readiness path (`/health/ready`) does, cheaply and cached.

## MVP Definition

### Launch With (v1)

- [ ] `GET /health` — liveness: `{"status":"ok","uptime_seconds":N}`, always 200, no deps, out of auth (PROJECT.md Active requirement)
- [ ] Readiness semantics behind `/health` split or `/health/ready`: stat state-file registry (existence/readability only), 503 only when files unreadable — **never on data age**
- [ ] Read-only status endpoints: market state (temperature inputs), auction summary, pool state — reading existing JSON verbatim with `meta.freshness` (as-of date from the file itself)
- [ ] Stable envelope: `data` + `meta`, degraded/warning fields surfaced, never 2xx-with-error-body
- [ ] X-API-Key auth dependency (env-first, gitignored file fallback, fail-fast) applied to all trigger endpoints — required by PROJECT.md Security constraint
- [ ] Trigger endpoints `POST /triggers/run_pipeline` (+morning_check, +backtest) → `202 {job_id, status}` via `Popen` (never `subprocess.run` in async handler), and `GET /jobs/{job_id}` status polling
- [ ] Job registry persisted as JSON in `logs/` (gitignored, matches repo convention)
- [ ] No direct state-mutation endpoints — triggers only launch existing scripts

### Add After Validation (v1.x)

- [ ] Portfolio/temperature read endpoints — behind the SAME API-key auth (or localhost-only); trigger: first deployment that isn't localhost, or first external consumer
- [ ] Single-flight guard returning `409 {"running_job_id":...}` + lock file that also coordinates with the scheduled 15:30 task — trigger: first observed double-run or first overlap scare
- [ ] Pipeline digest endpoint aggregating data_health_check + warning fields + per-source expected freshness — trigger: external consumer asks "is today's data complete?"
- [ ] `GET /health/details` auth-gated detailed health — trigger: anyone debugging remotely

### Future Consideration (v2+)

- [ ] Job cancellation (`POST /jobs/{id}/cancel` via `taskkill /T /F`) — Windows process-tree kill semantics need care; single-flight already prevents the worst case; add only if a runaway run actually happens
- [ ] Per-key rate limiting on trigger endpoints — trigger: the service leaves localhost
- [ ] ETag/304 conditional GETs on status endpoints — trigger: polling volume or payload size becomes measurable
- [ ] Re-attach/orphan adoption on API restart (registry shows `running` with dead pid → mark `orphaned`, offer cleanup) — trigger: first API crash mid-run

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| GET /health liveness (status+uptime) | HIGH (LB requirement) | LOW | P1 |
| Staleness-never-503s discipline | HIGH (prevents LB flapping every night/weekend) | LOW | P1 |
| Read-only status endpoints (market/auction/pool) | HIGH (core value) | MEDIUM | P1 |
| meta.freshness + as-of in every payload | HIGH (数据引用纪律) | LOW | P1 |
| X-API-Key on triggers (env-first, fail-fast) | HIGH (security constraint) | LOW | P1 |
| Trigger endpoints: POST 202 + job_id + GET /jobs/{id} | HIGH (core value) | MEDIUM | P1 |
| Windows-safe subprocess launcher (flags, no event-loop blocking) | HIGH (correctness) | MEDIUM | P1 |
| Job registry durable JSON in logs/ | MEDIUM | LOW | P1 |
| Portfolio endpoints behind auth / localhost-only | HIGH (account-data sensitivity) | LOW | P1 (if not localhost) / P2 |
| Single-flight guard + 409 overlap | MEDIUM | MEDIUM | P2 |
| Pipeline digest endpoint | MEDIUM | MEDIUM | P2 |
| /health/details auth-gated | LOW | LOW | P2 |
| Cancel endpoint | LOW | MEDIUM | P3 |
| ETag/304 | LOW | LOW | P3 |
| Rate limiting | LOW (localhost) | LOW | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

## Competitor Feature Analysis

| Feature | Spring Boot Actuator | Kubernetes-style probes | Typical Express `/health` | Our Approach |
|---------|----------------------|-------------------------|---------------------------|--------------|
| Health paths | `/actuator/health`, liveness+readiness split | `/livez`, `/readyz` (empty body, status-code only) | Single `/health` `{status, uptime}` | `/health` liveness (req. `status`+`uptime`) + readiness via file-stat registry, 503 only when unreadable |
| Body consumption | Humans/aggregators (code-based) | None — status code only | None | Status code for LB; JSON for humans; `include_in_schema=False` |
| Dependency checks | Rich per-component registry | Readiness probes | None typically | File-stat registry (existence/readability), cached, parallel — never freshness-gated |
| Degraded state | `UP`/`DOWN`/`OUT_OF_SERVICE` | Not modeled (binary) | Not modeled | 200 + `degraded` flags/warning fields from existing gogo health guards |
| Staleness | n/a | n/a | n/a | In `meta.freshness` per source + digest endpoint — never in probe status (gogo data goes stale by design on non-trading days) |
| Write-op protection | Spring Security (heavy) | n/a (internal) | middleware | `APIKeyHeader` + env-first key file, per gogo token convention |

Local precedent to inspect during implementation (in-workspace, not upstream): vibe-astock's FastAPI `server.py` + its test-suite pattern (network-blocking autouse fixture) — the only other FastAPI service in the workspace, useful for house conventions.

## Sources

- API Health Check Endpoints guide — https://apistatuscheck.com/blog/api-health-check-endpoint-guide (web, MEDIUM)
- Health check endpoint worth trusting — https://137foundry.com/articles/web-application-health-check-endpoint-worth-trusting (web, MEDIUM)
- /healthz patterns — https://dev.to/velprove/api-health-check-patterns-what-healthz-should-return-ln8 (web, MEDIUM)
- REST health endpoint design — https://asoasis.tech/articles/2026-04-07-0253-rest-api-health-check-endpoint-design/ (web, MEDIUM)
- FastAPI Production Guide: Health Checks — https://patrykgolabek.dev/guides/fastapi-production/health-checks/ (web, MEDIUM)
- FastAPI health check patterns / liveness-vs-readiness — https://www.index.dev/blog/how-to-implement-health-check-in-python (web, MEDIUM); https://theneuralbase.com/fastapi-for-ml/learn/advanced/health-check-and-readiness-probes/ (web, MEDIUM)
- Stale-data status codes — https://stackoverflow.com/questions/7880280/what-http-status-code-should-i-use-for-a-get-request-that-may-return-stale-data (web, MEDIUM); 200 vs 503 partial failure — https://stackoverflow.com/questions/31549831/ (web, MEDIUM)
- Response envelope/JSON design — https://jsonic.io/guides/rest-api-json-response ; https://jsonparser.ai/blog/json/rest-api-json-design/ (web, MEDIUM)
- REST response standardization — https://asoasis.tech/articles/2026-04-25-0253-rest-api-response-format-standardization/ (web, MEDIUM)
- Long-running jobs / subprocess from HTTP — https://stackoverflow.com/questions/79512845/ (web, MEDIUM); hoosh batch API model — https://github.com/MacCracken/hoosh/blob/2.4.6/CHANGELOG.md (web, LOW)
- FastAPI BackgroundTasks limits — https://github.com/fastapi/fastapi/discussions/7930 (web, MEDIUM); https://sudoteach.com/blog/fastapi-backgroundtasks (web, LOW)
- Async subprocess in Python — https://blog.est.im/2024/stdout-11 (web, LOW); event-loop freeze incident — https://zenn.dev/76hata/articles/fastapi-async-def-subprocess-freeze-fix (web, MEDIUM)
- FastAPI APIKeyHeader/security — https://github.com/fastapi/fastapi/pull/14370 (web, MEDIUM); https://fastapi.tiangolo.com/ru/reference/security/ (web, MEDIUM)
- Health-check anti-patterns — https://cloudnativenow.com/contributed-content/when-healthy-isnt-healthy-rethinking-kubernetes-health-checks-for-real-world-systems/ (web, MEDIUM); HAProxy UP-but-broken — https://www.netdata.cloud/guides/haproxy/haproxy-health-check-green-app-broken/ (web, MEDIUM); liveness vs readiness restart loops — https://dev.to/apikumo/liveness-vs-readiness-health-check-endpoints-that-wont-restart-loop-your-service-4bba (web, MEDIUM)
- Windows Popen detach flags — https://stackoverflow.com/questions/79512845/ ; https://github.com/NousResearch/hermes-agent (web, MEDIUM); `start_new_session` POSIX-only (cpython docs semantics, web, MEDIUM)

---
*Feature research for: gogo FastAPI API service layer (health/status/trigger/auth)*
*Researched: 2026-09-02*
