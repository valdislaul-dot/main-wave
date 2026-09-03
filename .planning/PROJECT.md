# gogo API 服务 (main-wave API)

## What This Is

gogo 主升浪交易系统的 HTTP API 服务层（FastAPI）。为负载均衡探活与外部消费方提供健康检查、状态数据与操作触发接口——是 gogo 现有 CLI 脚本之外的第二入口（GUI 面板已于 2026-09-04 弃用，CLI-only）。服务运行在 gogo 仓库内，直接复用 `data/` 与 `logs/` 的 JSON 状态数据。

## Core Value

外部系统通过一个稳定的 HTTP API 就能拿到 gogo 的实时状态（探活/持仓/温度/市场状态）并触发核心操作（管线/竞价/回测），且不干扰现有管线的运行。

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

- ✓ 评分 V4 体系（10因子百分制加权，权重月度滚动更新）— existing
- ✓ 温度三档开关（极弱/弱市/强市 → 空仓/半仓/全仓）— existing
- ✓ 卖出引擎 V4.1（竞价观察/弱转强/硬止损/执行价公式）— existing
- ✓ 每日管线 run_pipeline（涨停池→评分→候选）— existing
- ✓ 竞价面板 morning_check（9:15-9:35 决策）— existing
- ✓ 回测 V4（1年定形状+5个月定权重+3年检验）— existing
- ✓ 数据获取层（腾讯K线/同花顺涨停池/Tushare校准/竞价行情）— existing
- ✓ GET /health 探活（纯内存 always-200 + monotonic uptime）+ 常驻 FastAPI 服务（fail-closed 启动、Task Scheduler 开机自启、token at rest）— Phase 1
- ✓ 仓库首套自动化测试（pytest 18+1，零网络，TestClient 契约）— Phase 1
- ✓ 公开状态接口（market/auction/zt-pool raw 透传 + X-Data-Mtime/Age-S/Stale 新鲜度头）+ 防御式读取层（validate-then-serve + 短重试 + last-good stale 缓存，写入期间 0×5xx）+ /health/ready（stat-only，与数据年龄解耦）— Phase 2
- ✓ 操作触发接口（trigger/health-check/kill，subprocess，202+job_id，单飞锁：内存 claim 带 running_job_id + OS 文件锁双形态 409）— Phase 3

### Active

- [ ] 持仓/账本/候选 reads（token-gated，Phase 4 数据分级政策下交付，STA-02）
- [ ] 分级鉴权：行情/温度类只读放开；持仓/账本/候选与所有触发接口一律 token 保护（2026-09-02 用户确认）

### Out of Scope

- Node/Express 实现 — 已定 FastAPI，与 gogo 全 Python 栈一致
- 自动实盘下单 — 安全边界；API 不含任何交易下单能力，另行明确授权才考虑
- GUI（Streamlit gui_dashboard.py）— 2026-09-04 用户拍板弃用（CLI-only），锁接入代码保留供 API 共用同一锁文件仲裁；Mac 侧 GUI 对等验证取消

## Context

- gogo：Python 27.5k LOC / 116 个 .py 文件，live-traded A股打板决策系统，Win 端为主（Mac 端存在，双端同步）
- 数据形态：`data/` 下 kline_data、zt_pool、auction、market_state.json 等 JSON 状态文件；`logs/` 下 portfolio.json、trading_journal.json、candidates_*.json
- GUI：gui_dashboard.py（本地）、gui_cloud.py（云端）均 Streamlit — 2026-09-04 起弃用（CLI-only），代码保留未删
- 安全注意（.planning/codebase/CONCERNS.md）：远程仓库疑似公开（匿名访问 200）；交易记录存在于 git 历史；零自动化测试；仓库 JSON 数据膨胀（603MB pack）
- 跨端同步规则：Mac 端推送到 GitHub 的修复必须先审查再应用（git diff HEAD..origin/main）
- 定稿机制：V4 评分/温度/卖出引擎为定稿口径，改动需用户明确确认

## Constraints

- **Tech stack**: Python + FastAPI — gogo 全栈 Python，不引入 Node 运行时
- **复用**: 只读 data/、logs/ 现有 JSON，不修改现有管线模块逻辑
- **Compatibility**: Win 端为主，Mac 端需可用
- **Security**: 操作触发接口必须鉴权；不含实盘下单

**Security / 数据分级分类表（定稿）**：新增或审计任何 API 端点前先查本表（SEC-02 常驻参考，勿凭记忆）——端点字符串与 api/main.py + 路由文件的装饰器逐字节核对过，路由来源列可直接 grep 表 → 码。定稿机制：数据分级政策 2026-09-02 用户确认 + Phase 4 定稿 2026-09-04，改动需用户明确确认。隐私红线（2026-08-31）：持仓/账目/日志与项目说明一律不上传 GitHub（仅本地）。已知限制（single-flight 范围/残余并发入口/boot 姿态）见 README「API 已知限制」。

| 数据类别 | 端点 | 保护级别 | 路由来源（grep 起点） |
|----------|------|----------|------------------------|
| 公开级 | `/health`、`/health/ready`、`/v1/state/*`、`/openapi.json` | 无需 key（无持仓/无策略暴露面） | api/main.py、api/state.py |
| 机密级 | `/v1/private/*`（portfolio/journal/candidates）、`POST /v1/actions/*`、`GET /v1/jobs/*` | X-API-Key 必填（持仓/操作/任务状态） | api/private.py、api/actions.py |

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| FastAPI 而非 Express | gogo 全栈 Python，单一运行时 | — Pending |
| .planning/ 移入 gogo 仓库 | 项目归属 gogo，随仓库提交 | ✓ Good |
| 移除主目录空 .git | 误初始化（无提交），恢复原状 | ✓ Good |
| API 复用现有 JSON 状态文件 | 不引入第二数据源，避免推测污染 | — Pending |
| 数据分级鉴权：行情/温度放开，持仓/账本/候选/触发一律 token | 隐私红线（2026-08-31），仓库疑似公开 | ✓ Good |
| 状态接口 raw 透传 + 新鲜度头（不用 data/meta 信封） | 与既有 JSON schema 零适配兼容 | ✓ Good (Phase 2) |
| 防御式读取层：validate-then-serve + 2×20ms 短重试 + last-good 缓存 | 半写 JSON 永不作为新鲜数据服务；冷缓存 503，绝无裸 500（STA-03） | ✓ Good (Phase 2) |
| D-03 白名单：3 名固定映射，路径组合前检查 | 遍历结构性不可能；404 detail 钉死无路径（D-04） | ✓ Good (Phase 2) |
| /health/ready 只用 stat/os.access，与数据年龄解耦 | 陈旧数据（夜间/周末）永不 503；WinError-5 证据使 handle-不跨重试成为硬约束 | ✓ Good (Phase 2) |
| Phase 2 零新依赖 | 已装栈机器验证（fastapi 0.115.14/uvicorn 0.51.0）；包合法性门不触发 | ✓ Good (Phase 2) |
| SEC-03 检查先于 token 生成（Pitfall-2 顺序） | 非回环无 token 时拒绝启动且不生成 token 文件；生成只在回环/默认分支 | ✓ Good (Phase 1) |
| Token at rest：data/api_token.txt，secrets.token_urlsafe(32)，env 优先文件兜底 | 与 tushare token 惯例一致；同 commit gitignore（D-06） | ✓ Good (Phase 1) |
| 计划任务延迟用固定 Delay=PT5M 而非 RandomDelay | PS 5.1 BootTrigger 不支持 RandomDelay（CIM/XML 双验证）；惯例任务也从未真正携带随机延迟 | ✓ Good (Phase 1) |
| 计划任务注册需提权（RESEARCH 假设 A1 被证伪） | 非提权 Register-ScheduledTask 返回 0x80070005 | ✓ Good (Phase 1) |
| -ExecutionTimeLimit 无限（PT0S） | 默认 3 天上限会静默杀死常驻服务 | ✓ Good (Phase 1) |
| 单飞锁双形态：内存 claim（409 带 running_job_id）+ OS 文件锁（job_lock） | 同一锁文件仲裁 API/GUI/CLI 三入口；双形态区分「同入口运行中」与「他入口独占」 | ✓ Good (Phase 3) |
| write_job 迁移 4×10ms os.replace 重试 | Windows WinError-5 读碰撞实测；轮询读者绝不把迁移打成失败 | ✓ Good (Phase 3) |
| start_job 202 响应体 = 接受时刻 dict 快照 | worker 线程启动后即迁移状态，活引用会让 202 竞态出现 running/succeeded | ✓ Good (Phase 3) |
| GUI 弃用（CLI-only） | 2026-09-04 用户拍板：日常盘后/竞价全走 CLI；API 侧锁接入保留 | ✓ Good (Phase 3) |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-09-04 after Phase 3*
