# Roadmap: gogo API 服务 (main-wave API)

## Overview

Milestone v1 turns gogo's batch pipeline into a resident, queryable HTTP service without modifying any of the 116 existing pipeline files. The API is a shell-boundary wrapper: it reads the JSON state in `data/`/`logs/` verbatim (never a second data source) and launches the existing scripts by subprocess (never importing their modules). Five dependency-driven phases: (1) service skeleton with /health liveness, autostart and fail-closed boot — zero risk on a machine-verified stack; (2) read-only state passthrough with a defensive read layer — the read value ships with zero pipeline risk; (3) the trigger runner with durable jobs, single-flight locks and auth enforcement — all Windows-subprocess risk concentrated and isolated here; (4) data-classification exposure hardening that gates the sensitive 持仓/账本/候选 reads behind tokens; (5) recovery, observability and ops polish. Each phase is independently verifiable and rollback-safe — a stall in phases 3-5 never takes down what earlier phases delivered.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Service Skeleton + /health Liveness** - Resident FastAPI service boots on Windows (autostart on reboot), serves always-200 /health, refuses to boot exposed without a token, seeds repo's first pytest suite (completed 2026-09-03)
- [ ] **Phase 2: Read-Only State Endpoints + Defensive Read Layer** - Market/temperature/zt-pool state served verbatim with freshness headers; half-written files never leak (retry + stale fallback); /health/ready
- [ ] **Phase 3: Trigger Runner, Job Registry & Locks + Auth Enforcement** - POST triggers existing scripts as 202+job_id with durable jobs and single-flight 409s; X-API-Key enforced; event loop never blocked
- [ ] **Phase 4: Exposure Hardening + Data Classification** - 持仓/账本/候选 reads go live token-gated under an explicit classification policy; logs/errors/params/git hardened
- [ ] **Phase 5: Recovery, Observability & Ops Polish** - Auth-gated /health/details, automatic log rotation, completed test suite passing with Win/Mac parity

## Phase Details

### Phase 1: Service Skeleton + /health Liveness

**Goal**: The gogo API service exists as a resident FastAPI process on the Windows machine — it boots, auto-starts after reboot, answers liveness probes without ever touching state files, and refuses to start if it would be exposed without a token.
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: HLT-01, SEC-03, OPS-01, OPS-02
**Success Criteria** (what must be TRUE):

  1. A probe can GET /health at any hour (nights, weekends, holidays) and always receives 200 `{"status":"ok","uptime_seconds":N}` — never 401/503, never affected by data age.
  2. After a Windows reboot the service is running without manual launch (Task Scheduler + run_api.bat) and is reachable on 127.0.0.1.
  3. Starting the service with a non-loopback bind (e.g. 0.0.0.0) and no API token configured makes it refuse to start with a clear error — it never boots reachable-but-unauthenticated.
  4. `pytest` passes the repo's first automated tests (TestClient) asserting the /health contract.

**Plans**: 2/2 plans executed
Plans:
**Wave 1**

- [x] 01-01-PLAN.md — api/ package: /health liveness + fail-closed boot + token at rest + first pytest suite

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02-PLAN.md — Windows autostart: run_api.bat launcher + gogo-api Task Scheduler registration

**Research**: skip — stack machine-verified on this machine (fastapi 0.115.14 / uvicorn 0.51.0 single process / Python 3.13.1); standard liveness + Task Scheduler autostart patterns (install_scheduled_task.ps1 convention); launchd plist for Mac parity.

### Phase 2: Read-Only State Endpoints + Defensive Read Layer

**Goal**: External consumers can read gogo's current market/auction/zt-pool state via HTTP — verbatim file bodies with freshness headers — and never receive a torn or half-written file, even while the pipeline is mid-write.
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: HLT-02, STA-01, STA-03
**Success Criteria** (what must be TRUE):

  1. Consumer GETs /v1/state/market_state (or auction_state/zt_pool_state) and receives the raw JSON file body exactly as the pipeline wrote it, plus X-Data-Mtime and X-Data-Age-S headers derived from the file's real mtime.
  2. During a live pipeline run that is writing state files, repeated GETs of every served file return 0 × 5xx — a half-written JSON is never served; on persistent decode failure the consumer receives the last-good payload explicitly flagged stale, never a silent success or a bare 500.
  3. Consumer GETs /health/ready and receives 200 while all served files exist and are readable; only a missing/unreadable file produces 503. Stale data (night/weekend/holiday) never 503s.
  4. A code audit (grep) proves no GET handler makes an external network call — reads are pure local file reads that open, load and close fast.

**Plans**: 1 plan
Plans:
**Wave 1**

- [x] 02-01-PLAN.md — api/state.py read-only passthrough (verbatim + X-Data-Mtime/Age-S) + defensive read layer (retry/stale fallback) + /health/ready + contract suite

**Research**: skip — no research phase; spec decisions pinned in requirements before coding: Decision A (raw passthrough + X-Data-* headers, recommended, vs envelope) and Decision E (/health purity wording).

### Phase 3: Trigger Runner, Job Registry & Locks + Auth Enforcement

**Goal**: Consumers can trigger the existing pipeline/morning-check/backtest/health-check scripts over HTTP — a POST returns 202 + job_id immediately, the unmodified script runs in the background, runs of the same kind never double up, the API never freezes, and nothing spawns without a valid API key.
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: ACT-01, ACT-02, ACT-03, SEC-01
**Success Criteria** (what must be TRUE):

  1. Consumer POSTs /v1/actions/{kind} (pipeline / morning-check / backtest-weights / health-check) with a valid X-API-Key and receives 202 with a job_id immediately; GET /v1/jobs/{job_id} polls pending → running → succeeded/failed and exposes the run's log path. The run is the existing script launched unmodified (arg-list spawn, no shell).
  2. Triggering a kind that is already running — from the API or any other entry point — returns 409 with the running job_id, and two runs of the same kind never write data/ concurrently.
  3. During a full pipeline run, GET /health keeps answering with P95 < 50 ms — background execution never blocks the event loop.
  4. Requests with a missing or wrong X-API-Key receive 401/403 (constant-time comparison) and never spawn a process; keys never appear in any log.
  5. After the API process is killed mid-run and restarted, the durable job registry (logs/api/jobs/) reloads and the interrupted job is queryable in a terminal state — no job is silently lost.

**Plans**: TBD
**Research**: DEEP-RESEARCH PHASE — run `/gsd-plan-phase --research-phase 3`. Verify Windows subprocess governance end-to-end on the real machine: thread+Popen vs create_subprocess_exec (bpo-37381), portalocker/msvcrt lock behavior on this drive, taskkill /F /T tree-kill + CREATE_NO_WINDOW, tasklist PID probes, GBK/UTF-8 output matrix. User sign-off gates (定稿机制) to collect before this phase: writer-side atomicization of the non-atomic write paths (touches pipeline modules — deferable via read-side defense), GUI one-key refresh joining the same lock, liveness of the 15:30 scheduled task (auto_start.bat stale BASE path), trigger default --fast (skips Step9 git push).

### Phase 4: Exposure Hardening + Data Classification

**Goal**: gogo's most sensitive data — 持仓/账本/候选 — is served through token-gated endpoints under an explicit data-classification policy, and the whole exposure surface (bind, logs, errors, params, git) is hardened so the 2026-08-31 privacy red line holds even if the API leaves 127.0.0.1.
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: STA-02, SEC-02
**Success Criteria** (what must be TRUE):

  1. Consumer with a valid key GETs the 持仓/账本/候选 read endpoints and receives raw file bodies + freshness headers like the public endpoints; without a key they get 401/403. Market/temperature endpoints remain open with no key required.
  2. A route-by-route audit shows every endpoint carries exactly its data class's protection — no sensitive route reachable without a token, no public route requiring one; the fail-closed boot check is covered by a test, not just documentation.
  3. Error responses expose no file paths or stack traces (details stay in server logs) and no log line contains an Authorization header or token value.
  4. Trigger date parameters accept only whitelisted formats (YYYY-MM-DD / YYYYMMDD) and reach scripts as argument lists — shell injection attempts are structurally impossible.
  5. Scans confirm data/api_token.txt appears in neither git history nor the sync_cloud whitelist; README documents the API's known limits (single-flight scope, remaining concurrent entry points).

**Plans**: TBD
**Research**: skip — standard security patterns; the phase deliverable includes a PROJECT.md wording revision (data-classification auth clause) requiring user sign-off under 定稿机制.

### Phase 5: Recovery, Observability & Ops Polish

**Goal**: The resident service is operationally sustainable — bounded log growth, human-readable health details behind auth, and a completed automated test suite proving behavior on both machines without network access.
**Mode:** mvp
**Depends on**: Phase 4
**Requirements**: OPS-03
**Success Criteria** (what must be TRUE):

  1. Operator with a valid key GETs /health/details and receives versions/uptime/last-check details; without a key they get 401.
  2. uvicorn and per-run job logs rotate automatically so the API's disk footprint stays bounded through weeks of continuous running with no manual cleanup.
  3. The pytest suite (seeded in Phase 1, grown through Phases 2-5) passes on Windows and Mac with a network-blocking fixture proving no test touches the network.

**Plans**: TBD
**Research**: skip — standard ops/recovery patterns.

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Service Skeleton + /health Liveness | 2/2 | Complete    | 2026-09-03 |
| 2. Read-Only State Endpoints + Defensive Read Layer | 0/TBD | Not started | - |
| 3. Trigger Runner, Job Registry & Locks + Auth Enforcement | 0/TBD | Not started | - |
| 4. Exposure Hardening + Data Classification | 0/TBD | Not started | - |
| 5. Recovery, Observability & Ops Polish | 0/TBD | Not started | - |
