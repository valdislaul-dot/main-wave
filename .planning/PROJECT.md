# gogo API 服务 (main-wave API)

## What This Is

gogo 主升浪交易系统的 HTTP API 服务层（FastAPI）。为负载均衡探活与外部消费方提供健康检查、状态数据与操作触发接口——是 gogo 现有 CLI 脚本和 Streamlit 面板之外的第三个入口。服务运行在 gogo 仓库内，直接复用 `data/` 与 `logs/` 的 JSON 状态数据。

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

### Active

- [ ] HTTP API 服务：FastAPI 服务提供 GET /health 探活（status + uptime 秒）
- [ ] 只读状态接口：持仓/温度/市场状态/候选等经 HTTP 暴露（读现有 JSON）
- [ ] 操作触发接口：触发管线/竞价/回测等现有脚本（subprocess）
- [ ] 写入接口鉴权：操作类接口受保护，只读接口可放开

### Out of Scope

- Node/Express 实现 — 已定 FastAPI，与 gogo 全 Python 栈一致
- 自动实盘下单 — 安全边界；API 不含任何交易下单能力，另行明确授权才考虑
- 替换现有 Streamlit GUI — 面板保留，API 是补充入口

## Context

- gogo：Python 27.5k LOC / 116 个 .py 文件，live-traded A股打板决策系统，Win 端为主（Mac 端存在，双端同步）
- 数据形态：`data/` 下 kline_data、zt_pool、auction、market_state.json 等 JSON 状态文件；`logs/` 下 portfolio.json、trading_journal.json、candidates_*.json
- GUI：gui_dashboard.py（本地）、gui_cloud.py（云端）均 Streamlit；sync_cloud.py 同步云端
- 安全注意（.planning/codebase/CONCERNS.md）：远程仓库疑似公开（匿名访问 200）；交易记录存在于 git 历史；零自动化测试；仓库 JSON 数据膨胀（603MB pack）
- 跨端同步规则：Mac 端推送到 GitHub 的修复必须先审查再应用（git diff HEAD..origin/main）
- 定稿机制：V4 评分/温度/卖出引擎为定稿口径，改动需用户明确确认

## Constraints

- **Tech stack**: Python + FastAPI — gogo 全栈 Python，不引入 Node 运行时
- **复用**: 只读 data/、logs/ 现有 JSON，不修改现有管线模块逻辑
- **Compatibility**: Win 端为主，Mac 端需可用
- **Security**: 操作触发接口必须鉴权；不含实盘下单

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| FastAPI 而非 Express | gogo 全栈 Python，单一运行时 | — Pending |
| .planning/ 移入 gogo 仓库 | 项目归属 gogo，随仓库提交 | ✓ Good |
| 移除主目录空 .git | 误初始化（无提交），恢复原状 | ✓ Good |
| API 复用现有 JSON 状态文件 | 不引入第二数据源，避免推测污染 | — Pending |

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
*Last updated: 2026-09-02 after initialization*
