---
gsd_state_version: 1.0
current_phase: 5
current_phase_name: Recovery, Observability & Ops Polish
status: executing
stopped_at: Completed 05-02-PLAN.md
last_updated: "2026-09-04T16:57:21.902Z"
last_activity: 2026-09-05
last_activity_desc: Phase 5 execution started
state_head: 498545a63d6d2643b7bae0a206fa3c5ad6a7c276
progress:
  total_phases: 5
  completed_phases: 4
  total_plans: 18
  completed_plans: 16
  percent: 80
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-09-03)

**Core value:** External systems get gogo's live state (health/持仓/温度/market status) and trigger core operations (pipeline/auction/backtest) through one stable HTTP API, without disturbing the existing pipeline.
**Current focus:** Phase 5 — Recovery, Observability & Ops Polish

## Current Position

Phase: 5 (Recovery, Observability & Ops Polish) — EXECUTING
Plan: 3 of 4
Status: Ready to execute
Last activity: 2026-09-05 — Phase 5 execution started

Progress: [████████░░] 80%

## Performance Metrics

**Velocity:**

- Total plans completed: 14
- Average duration: —
- Total execution time: —

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1-5 | TBD | TBD | - |
| 1 | 2 | - | - |
| 02 | 1 | - | - |
| 03 | 4 | - | - |
| 4 | 7 | - | - |

**Recent Trend:**

- Last 5 plans: none
- Trend: —

*Updated after each plan completion*
**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 01 P01-01 | 8min | 3 tasks | 9 files |
| Phase 01 P01-02 | 9min | 3 tasks | 2 files |
| Phase 02 P01 | 9 min | 3 tasks | 3 files |
| Phase 03 P01 | 11 | 3 tasks | 4 files |
| Phase 03 P02 | 12 | 3 tasks | 6 files |
| Phase 03 P03 | 6 | 2 tasks | 1 files |
| Phase 03 P04 | 17 | 3 tasks | 1 files |
| Phase 04 P01 | 16 | 3 tasks | 6 files |
| Phase 04-exposure-hardening-data-classification P02 | 3 min | 2 tasks | 2 files |
| Phase 04 P03 | 14 | 3 tasks | 4 files |
| Phase 04-exposure-hardening-data-classification P04 | 13min | 3 tasks | 6 files |
| Phase 04-exposure-hardening-data-classification P05 | 6min | 2 tasks | 2 files |
| Phase 04 P06 | 20 min | 2 tasks | 2 files |
| Phase 04-exposure-hardening-data-classification P04-07 | 6min | 3 tasks | 1 files |
| Phase 05 P01 | 6 | 3 tasks | 4 files |
| Phase 05 P02 | 10 | 3 tasks | 6 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap] Research 5-phase structure adopted (skeleton/health → read-only state → trigger runner/jobs/locks → data classification/hardening → ops polish); auth scaffold P1, enforcement P3, full policy P4.
- [Roadmap] STA-02 (持仓/账本/候选 reads, token-gated) delivered in Phase 4 with the data-classification policy, not Phase 2 — Phase 2 stays public-safe only.
- [Roadmap] Decision A (raw passthrough + X-Data-Mtime/X-Data-Age-S headers) — implemented in Phase 2 (D-01/D-02/D-05), wire contract is the consumer integration surface.
- [P3/P4] Data-classified auth confirmed 2026-09-02 (market/temperature open; 持仓/账本/候选/trigger token) — PROJECT.md wording revision pending in Phase 4 (定稿机制).
- [Phase 1]: Phase 1 /health probe path is pure in-memory (monotonic uptime, no middleware/deps); any future auth must exempt /health (OPS-02 suite pins it)
- [Phase 1]: Installer runs ELEVATED on this machine: non-elevated Register-ScheduledTask is denied (0x80070005) - RESEARCH assumption A1 disproven; header updated
- [Phase 1]: Boot-trigger delay delivered as fixed Delay=PT5M not RandomDelay: PS 5.1 -RandomDelay silently dropped for AtStartup triggers (CIM class lacks the property; XML schema rejects it - legacy convention task never had it either)
- [Phase 1]: SEC-03 boot check runs BEFORE any token generation (Pitfall-2); token at rest = data/api_token.txt (secrets, env-first-file-second, gitignored same-commit); -ExecutionTimeLimit PT0S so the resident service outlives the 3-day default
- [Phase 1]: Repo's first test suite: pytest.ini pythonpath=. + tests/ (18 passed, 1 skipped, autouse network-block); import mechanics require `python -m api.main` from repo root
- [Phase 02]: Followed D-01..D-05 locked decisions verbatim: raw byte passthrough (never re-serialize), same-handle fstat mtime, 3-name whitelist with 404 before path composition, 404-client/503-server error split with path-free details, stale marker only on the fallback path — Discuss-phase sign-off carried; wire contract (byte-verbatim + X-Data-* headers) is the consumer integration surface
- [Phase 02]: get_state carries an injectable reader parameter (default read_state_file) as the deterministic test seam; retry constants pinned retries=2, retry_delay=0.02 — Timer-free unit tests via fake reader + retry_delay=0; RESEARCH design note line 237
- [Phase 02]: api.main.py changed by exactly two lines (import + include_router after /health); boot sequence, SEC-03 ordering, __main__ guard untouched (diff-verified) — Phase 1 /health purity and SEC-03 fail-closed ordering are load-bearing; minimal-diff registration keeps the diff check trivially auditable
- [Phase 02]: Zero new packages: stdlib-only defensive read layer on the installed fastapi 0.115.14 / starlette 0.46.2 stack — File sizes <= 48 KB single-user loopback service; package-legitimacy gate not triggered
- [Phase 03]: [P3 03-01] write_job 重试 os.replace (4x10ms, WinError-5 读碰撞): 轮询读者绝不把迁移打成失败/不滞留 worker —— 实测 Windows 结论
- [Phase 03]: [P3 03-01] run_job finally 每步隔离守卫: 终态写/释放/关锁/prune 各自独立, 磁盘级写失败绝不跳过硬释放
- [Phase 03]: [P3 03-01] TestClient /health 延迟测试先预热 2 请求再计时 (框架暖启动不算延迟信号; 50ms p95 断言不变; 实测 p95=3.12ms)
- [Phase 03]: start_job 返回接受时刻 dict(job) 快照而非活引用: worker 线程在 Thread.start 后立即把同一 dict 迁成 running, 活引用会让 202 响应体竞态出现 running/succeeded (Rule 1 实测修复, api/jobs.py)
- [Phase 03]: 409 双形态按 OQ1 定稿: 内存 claim 命中带 running_job_id, OS 锁独占(另一入口)不带 job_id 键
- [Phase 03]: %2F 编码穿越 id 由 Starlette 路由层 404 拦截 (uvicorn/httpx 解码 %2F 成字面斜杠, {job_id} 无法跨段) — 同一闸门更早一层: 404、零文件访问、永不 500; handler 级 ^[0-9a-f]{32}$ 闸门钉全部无斜杠畸形 id
- [Phase 03]: Task 2 tdd RED 结构性满足于 Task 1: 生产代码先于套件存在, 首跑全绿即无漂移证明 (修生产不弱化测试纪律保持)
- [Phase 03]: [P3 03-03] st.rerun 置于 try/except/finally 之后并加 done 门控: 计划自身结构门要求 finally/fd.close/TimeoutExpired 文本先于分支内首个 st.rerun, 且超时路径无条件 rerun 会抹掉必须的「管线可能仍在运行」警告 — 释放保证不变 (finally 全路径关锁, gui_dashboard.py)
- [Phase 03]: [P3 03-03] 超时路径不 st.stop(): 让本次运行完整渲染 (警告留在面板顶, 按钮下方区块照常显示); TimeoutExpired 子进程可能存活 (probe V4), 清理归 v2 ACT-04
- [Phase 03]: [P3 03-04] 真机重启路径 = Start-ScheduledTask 'gogo-api'(需免沙箱启动): 沙箱化启动的实例在调用收尾时收到 Ctrl+C 死亡 (LastTaskResult 0xC000013A), 免沙箱后常驻 (0x41301 running); boot 期 reload_registry 在 /health 200 后数秒内把被杀 pipeline job 标为 interrupted —— main() 装载的真机证明 (03-02 wiring)
- [Phase 03]: [P3 03-04] 实况 SC2/SC3/SC5 全过: 409 携带 running_job_id 逐字节吻合; /health p95=17.14ms (120 样本, 真管线运行中, 界 50ms); taskkill /F /T 35864 树杀 (Step 1.5 运行中被杀) → 重启 → interrupted+finished_at+部分日志 753B 留存 → job_lock.acquire 即时成功 (OS 自动释放经真崩溃验证) → 新 health-check 触发成功
- [Phase 03]: [P3 03-04] 真管线运行会写 tracked data 文件 (data/official_check.json + data/zt_pool_state.json, 01:53 拉 09-03 收盘池 42 只官方校验一致) —— 设计内职能, 与既有 data/historical_zt_pool.json 用户运行修改同类; 不 stage 不还原
- [Phase 03]: [P3 03-04] 快 kind (health-check 全程 1.0s) 也命中实况 409+running_job_id —— 计划容忍的竞态分支在本机未触发; D-02 复确认 verify-only (201 任务仅 gogo-api 匹配, 无提权命令)
- [Phase 03]: GUI (streamlit gui_dashboard.py) 弃用——始终使用 CLI (run_pipeline.py / morning_check.py) 运行本项目 — 2026-09-04 用户拍板: 放弃 GUI 面板, 日常盘后/竞价全部走 CLI。影响: 03-03 锁接入代码保留(API 仍共用同一锁文件); 03-UAT GUI 3 项作废; Phase 4 范围剔除 GUI 修复(WR-05/IN-01); Mac GUI 对等验证取消; gogo CLAUDE.md 实盘操作段后续可清理 GUI 行
- [Phase 4]: Envelope via app-level handlers + frozen text-keyed code table, zero raise-site edits (StarletteHTTPException key MRO-covers raise-site + framework 404/405; Exception key -> ServerErrorMiddleware 500)
- [Phase 4]: 404 copy unified to Not Found API-wide; non-404 details byte-identical + code sibling; 405 framework detail passes through (only the 404 class is unified)
- [Phase 4]: Code table frozen incl. 04-03/04-04 texts (unknown_private_name/private_data_unavailable/invalid_date_format/date_not_supported); unknown texts fall back http_{status}; later plans never append rows
- [Phase 4]: [ASSUMED]#2 disproved: ServerErrorMiddleware re-raises after 500 handler sends -> 500-path pins use TestClient(raise_server_exceptions=False) mirroring real uvicorn wire (04-01 deviation 1)
- [Phase 4]: WR-03 pin = raw-ASGI scope call (server truth 404); httpx-collapsed 200 was a client artifact. WR-02 hammer: exception capture + progress + Barrier/60ms window -> stale branch deterministically exercised
- [Phase 4]: openapi_url=/openapi.json public read-only (docs/redoc stay None); schema renders from existing docstrings, zero route edits
- [Phase 4]: save_portfolio/save_journal atomic via same-dir .tmp + os.replace (D-04..D-06): byte-identical output (text-mode open semantics incl. Windows CRLF kept), zero schema mutation, module-global seam preserved; failure-path .tmp residue tolerated per zt_pool template, target-keeps-old-content is the load-bearing invariant (Test 3/4 pinned)
- [Phase 4]: [P4 04-03] Private tier = router-level Depends(require_api_key) on a dedicated /v1/private/* namespace (SEC-02, D-13) — same dependency object as actions/jobs; SC2 audit asserts dependency identity (route.dependencies[].dependency is require_api_key) per route, set-equality non-vacuous, unclassified new routes fail the audit
- [Phase 4]: [P4 04-03] get_private = documented twin of api/state.py get_state (retries=2 on ValueError/UnicodeDecodeError only, OSError immediate break, warm-cache stale fallback body+mtime version-unified, cold -> StateUnavailable) targeting LOG_DIR with (name[, date]) cache slots; state.py signature core NOT refactored to take a directory argument (04-PATTERNS discretion)
- [Phase 4]: [P4 04-03] ?date= is candidates-only semantics: legal dates against fixed files (portfolio/journal) are ignored and serve the fixed file from the (name, None) slot; YYYYMMDD normalizes to dashed before filename composition; date gate = whitelist regex + generic month 1-12/day 1-31 range (2026-13-99 -> 422), per-calendar validity (02-31) out of whitelist semantics -> 503 missing file
- [Phase 4]: [P4 04-03] Candidates selection mirrors morning_check.py:11-18 by rule only (candidates_ AND NOT candidates_v*, filename date part sort, newest) — endpoint never imports or reruns script logic; file bytes still go through read_state_file
- [Phase 4]: [P4 04-03] Dot-segment literal paths (/v1/private/../portfolio) cannot route-match the 3-segment {name} pattern — framework 404 (not_found envelope) fires before any handler, zero file access; pinned via raw-ASGI scope call (WR-03 family; httpx collapses '..' pre-transport so TestClient answers are client artifacts)
- [Phase 4]: date_args.py single-source validator consumed by API gate, script gates and tests — no duplicated regex anywhere (T-04-15); argv token always built from a parsed date object (T-04-13)
- [Phase 4]: Script session-date gates share ASCII refusal substring 'session date' on stderr with exit 2 before any capture/file write/network; subprocess pins spawn only past/invalid dates (never today — child bypasses conftest network patch)
- [Phase 4]: P4 04-05: refusal message retains case-5 pinned substrings (host via {host}, GOGO_API_TOKEN) and drops the old remedy naming data/api_token.txt — env-var-only + file-token-not-accepted, no paths beyond the host; case 5 needed zero assertion deltas
- [Phase 4]: P4 04-05: D-12 warning goes to stderr (not stdout) — case 7's stdout-only pin survives byte-unchanged; comment appended explaining why
- [Phase 4]: P4 04-05: main() docstring paragraph refreshed from 'env+file 现存状态' to env-only WR-01/D-12 semantics (old text documented the buggy behavior — Rule 1 stale-doc fix)
- [Phase 4]: P4 04-05: file-token refusal test seeds sentinel file and asserts bytes unchanged + uvicorn.run never called (recorder fake) — pins refusal precedes ensure_token/uvicorn without file-creation races
- [Phase 04]: README.md content written local-only, NOT committed: repo CLAUDE.md + .gitignore (2026-08-31 用户定) keep 项目说明 (README/CLAUDE/CONTEXT) 不上传 GitHub; plan task-2 commit step waived (CLAUDE.md precedence) — SC5 documented-limits satisfied on the local file the 04-07 gate reads
- [Phase 04]: README single-flight wording scoped to byte-checked facts (api/actions.py raise sites): per-kind lock, same-API overlap 409 already_running + running_job_id; other-entry hold already_running_other_entry no job_id — no invented locks/rate-limits/ETags in docs
- [Phase 4]: [P4 04-07] 真机重启路径 = Start-ScheduledTask 'gogo-api' 免沙箱 (03-04 环境事实复确认): /health 200 ~2s, bind 127.0.0.1:8000 pid 30508, loopback 姿态 + 文件 token 原样 —— D-12 门从未触发(无 launcher 绑非回环)也从未被削弱
- [Phase 4]: [P4 04-07] 实况矩阵 13 行全过且零偏差: 私密读 200 字节级一致 + x-data-mtime/x-data-age-s (h11 线上小写头名, 大写 dict 查询得 None —— 后续 live gate 用 http.client getheaders 读线上真值); 401+WWW-Authenticate/403/404 unknown_private_name/date 422 信封与套件预测逐字节吻合; 唯一 POST = 无 auth 401 探针, 注册表 10->10 零 spawn (禁真跑禁令守住)
- [Phase 4]: [P4 04-07] 假设-truth 行 (a) 启动路径绑回环 (b) 无文件-token 非回环消费者 (c) 任务名 gogo-api —— 真机全 TRUE; SC5 三扫描复跑与 04-06 基线逐字节同; 全套件 148 passed 1 skipped; 服务留 RUNNING 待用户下一交易日
- [Phase 4]: [P4 04-07] Phase 4 人类门 (03-04 孪生): SC1-SC5 证据映射表 + 04-04 fail-loud session-date 语义签认在 SUMMARY 底部待用户裁决 (ACCEPT/DELTA) —— end-of-phase 收割, executor 不代答
- [Phase 5]: [05-01] market_state.json missing/unreadable -> market_state_mtime null (200-with-null, never 5xx) — ASSUMED row ACCEPT
- [Phase 5]: [05-01] uptime wiring = public uptime_seconds() in api/main.py + handler-level lazy import in route (module-level import would circular-fail) — ASSUMED row ACCEPT
- [Phase 5]: [05-01] newest succeeded health-check = max finished_at among kind health-check + status succeeded registry jsons — ASSUMED row ACCEPT
- [Phase 5]: [05-01] ISO output = datetime.fromtimestamp(value, timezone.utc).isoformat(), suite asserts frozen-value equality — ASSUMED row ACCEPT
- [Phase 5]: [05-01] Registry located via api.jobs.jobs_dir() single source; DATA_DIR on health module only (no duplicated path logic, zero unused imports)
- [Phase 5]: [05-01] importlib.metadata imported as module attribute (not from-import) to keep versions-fallback monkeypatch seam
- [Phase 5]: Cap-20 boundary seed: 25 terminal + 3 inflight -> reload_registry sweeps inflight to interrupted (in-place rewrite = newest mtimes) then tail-prune deletes the 8 oldest terminal pairs -> exactly 20 .json (17 newest terminal + 3 interrupted); interrupted counts toward the cap
- [Phase 5]: Windows two-repoint dance order repoint -> rotate -> repoint is the only working order (cmd >> inherited handle lacks FILE_SHARE_DELETE, machine-verified 2026-09-04); uniform dance even under threshold; live proof deferred to the 05-04 gate
- [Phase 5]: log_housekeep is zero-config pure-function: defaults (console.log path, registry dir, cap) resolve via api.jobs module attrs at call time - one LOG_DIR monkeypatch isolates the whole module; primitives never raise and never print
- [Phase 5]: Boot failure discipline: first-repoint error still attempts rotate; at most ONE ascii WARNING to stderr; never exit/raise on housekeeping failure - SEC-03 fatal-exit paths untouched
- [Phase 5]: Boot-test isolation via a single api.main.LOG_DIR patch: every path the housekeeping block touches derives from main's own LOG_DIR attr (never module-default bare calls, which would dup2 the real logs tree onto pytest fds)

### Pending Todos

- *(none — Phase 4 planning next)*

### Blockers/Concerns

- [P4] PROJECT.md security-clause wording revision requires user sign-off (定稿机制).
- [P3→P5] 15:30 定时任务疑似失效（likely defunct）——GUI 已弃用（2026-09-04），无 GUI 并发跑者；API/CLI 由同一锁文件仲裁；任务存废待 Phase 5 ops polish 确认
- [P2] REVIEW.md WR-01: token gate 为存在性检查且自开启——非回环绑定只查 token 存在，回环默认运行会自动生成 token，误配 0.0.0.0 时静默服务 LAN。修复需 env 强制 token + 控制台警告，属 Phase 3/4 鉴权加固范围
- [P2] REVIEW.md WR-02/WR-03 + UI-audit 3 项优先级修复（机器可读错误码、双 404 文案归一、openapi/README 契约）——涉及 D-01/D-04 定稿决策，采纳需用户确认
- [P2] 会话清理现象：交互会话启动的服务实例随会话结束收到 Ctrl+C（2026-09-03 晚 4 次 ^C 观察，LastTaskResult 0xC000013A）；AtStartup 自启路径不受影响——部署生命周期关注项，记入 Phase 5 ops polish
- [P1] REVIEW.md WR-01: SEC-03 是启动时意图检查，token 文件存在后 0.0.0.0 绑定不再拒绝——按请求鉴权是 Phase 3/4 范围，Phase 1 契约内不违反
- [P1] REVIEW.md WR-02/WR-03/WR-04 非阻塞加固项（端口范围校验、$ErrorActionPreference='Stop'、config.py 导入副作用）— 记入后续阶段硬化清单

## Deferred Items

Items acknowledged and deferred at milestone close, most recent first:

| Category | Item | Status | Deferred At | Milestone |
|----------|------|--------|-------------|-----------|
| *(none — v2 backlog tracked in REQUIREMENTS.md)* | | | | |

## Session Continuity

Last session: 2026-09-04T16:57:21.350Z
Stopped at: Completed 05-02-PLAN.md
Resume file: None
