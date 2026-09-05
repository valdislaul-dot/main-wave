# Phase 5: Recovery, Observability & Ops Polish - Context

**Gathered:** 2026-09-04
**Status:** Ready for planning

<domain>
## Phase Boundary

常驻服务的运维可持续性收尾：日志增长有界、鉴权版健康详情、双机测试套件证明——里程碑最后一个阶段。

**In scope:** OPS-03（日志轮转 + 鉴权版 GET /health/details）、15:30 定时任务存废确认（[P3→P5] 遗留闭环）、P2 会话清理现象记录（README known-limits 部署注意）、Mac 端测试验证步骤清单交付。

**Not this phase:** ETag/限流/管线 digest 聚合接口（v2 OPS-04/05/06）、job 取消/孤儿收养（v2 ACT-04/05）、Mac 实跑验证本身（跨机 rollout 步骤，用户执行后回填）、进程守护/崩溃重启（超出里程碑范围）。

**Success criteria** (from ROADMAP.md, must all be TRUE):
1. Operator with a valid key GETs /health/details and receives versions/uptime/last-check details; without a key they get 401.
2. uvicorn and per-run job logs rotate automatically so the API's disk footprint stays bounded through weeks of continuous running with no manual cleanup.
3. The pytest suite (seeded in Phase 1, grown through Phases 2-5) passes on Windows and Mac with a network-blocking fixture proving no test touches the network.
</domain>

<decisions>
## Implementation Decisions

### /health/details 内容契约（OPS-03/SC1）
- **D-29:** 返回字段：`{"versions": {"python","uvicorn","fastapi"}, "uptime_seconds": N, "last_check": {"health_job": <最近 health-check job 完成时间 ISO 或 null>, "market_state_mtime": <data/market_state.json mtime ISO>}}`。
- **D-30:** 数据来源：versions 从 sys.version + importlib.metadata 惰性读（不硬编码）；uptime 复用 /health 的模块导入锚点（api/main.py:30）；last_check 读 jobs registry 最近 succeeded 的 health-check job + os.stat(market_state.json)。
- **D-31:** 鉴权与错误：机密级（Phase 4 分级表定稿）X-API-Key 必填；401/403 沿用 D-10 分工；错误体走 04-01 冻结信封（code 表已有行或按冻结规则新增——若需新增行，表已声明冻结，先查 04-01 是否已含 health/details 相关文案）。

### 日志轮转机制（SC2）
- **D-32:** console.log 轮转：boot 时 size-check——main() 启动时（SEC-03 检查后、uvicorn.run 前）若 logs/api/console.log > 5MB 则重命名为 console.log.1 再新开（保留一份历史）。Windows 无 logrotate，常驻服务 boot 检查最简单可靠。
- **D-33:** job logs/registry 上限：保留最近 N=20 个 job 的 .json+.log 对，启动时 prune 更旧的（registry 上限设计 Phase 3 起即为承诺，本阶段落地）。
- **D-34:** 轮转逻辑落位：独立纯函数模块（如 `api/log_housekeep.py`），boot 序列内调用，纯函数可测、boot 顺序 diff 可审计（沿 api/boot.py 纯函数惯例）。

### Mac 验证 + 遗留项（SC3 / [P3→P5]）
- **D-35:** Mac 验证：本机交付「Mac 验证步骤」清单（拉取代码 → pytest 全量 → 网络封锁 fixture 证明），记录于 README/SUMMARY；Mac 实跑作为跨机 rollout 步骤由用户执行后回填（与 Phase 3 Mac 验证同模式）。
- **D-36:** 15:30 定时任务：确认现状（Get-ScheduledTask 全量列举）→ 若「主升浪每日选股流水线」仍在册，交付一条提权停用命令供用户执行（D-02 闭环）；不在册则记录确认结果。
- **D-37:** P2 会话清理现象（交互会话结束服务收 Ctrl+C，AtStartup 自启不受影响）：记录为已知部署生命周期特性，写入 README known-limits 部署注意段，不做代码改动。

### Claude's Discretion
- /health/details 路由模块位置（api/main.py 内联 vs 独立模块，参照 api/state.py 风格）；last_check 中 health_job 的查询实现。
- 轮转触发细节（5MB 阈值常量位置、console.log.1 命名、prune 排序依据——job 创建时间戳）。
- job 上限 20 的存储位置（常量 vs config）。
- Mac 验证清单的存放位置与格式。
</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `api/main.py:30` — uptime 锚点（模块导入时刻），/health/details 复用同一锚点。
- `api/auth.py` — require_api_key 依赖，/health/details 挂同一依赖（机密级）。
- `api/errors.py` — 冻结错误码表 + 信封；新端点错误体走既有 code 行（先查表）。
- `api/jobs.py` — job registry（logs/api/jobs/），last_check 与 prune 的读取源；write_job 原子写模式可参照。
- `api/boot.py` — 纯函数 boot 模式参照（log_housekeep 同风格）。
- `tests/conftest.py` — 零网络 autouse fixture（SC3 的网络封锁证明已在套件内）。
- `run_api.bat` — `>> logs\api\console.log 2>&1` 追加（轮转对象的写入端）。

### Established Patterns
- boot 顺序纪律：SEC-03 检查 → token 生成 → uvicorn.run；新增轮转调用放中间，diff 可审计。
- 分级表（PROJECT.md 定稿）：新端点先查表——/health/details 为机密级。
- 错误信封：404/422/503 走冻结码表，raise site 零改动。
- 最小 diff：api/main.py 仅加 import + include_router（若新路由模块化）。

### Integration Points
- `logs/api/` 当前结构：console.log（1.8KB）+ e2e 残留 + jobs/（10 文件 = 5 job 对）。
- 15:30 定时任务：Phase 3 D-02 已决定停用，verify-only 复确认（201 任务仅 gogo-api 匹配）；本阶段最终确认。
- README known-limits（Phase 4 04-06）：本阶段追加部署注意段（Ctrl+C 现象 + Mac 验证步骤）。
</code_context>

<specifics>
## Specific Ideas

- SC3 的 Mac 侧验证清单应包含：`pytest -q` 全量 + 确认 conftest 网络封锁生效（任何触碰网络的测试都会失败）+ 预期结果（157+ passed, 1 env-conditional skip）。
- console.log 轮转的 5MB 阈值与 job 上限 20 是工程常量，写进计划任务即可（不需要配置化，单用户工具）。
</specifics>

<deferred>
## Deferred Ideas

- ETag/304、按客户端限流、管线 digest 聚合接口 — v2（OPS-04/05/06）。
- job 取消（taskkill 树杀）+ 孤儿任务收养 — v2（ACT-04/ACT-05）。
- 进程守护/崩溃自动重启 — 超出本里程碑范围。
- Mac 端实跑验证结果回填 — 跨机 rollout 步骤，用户执行。
</deferred>
