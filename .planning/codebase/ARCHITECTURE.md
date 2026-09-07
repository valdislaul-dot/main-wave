<!-- refreshed: 2026-09-02 -->
# Architecture

**Analysis Date:** 2026-09-02

## System Overview

单用户本地运行的 A 股打板选股系统（主升浪 V4）：盘后流水线采集涨停池与 K 线 → 评分选候选 → 次日 9:25 竞价面板做卖出/买入决策。无数据库、无常驻后端服务；持久化全部为 `data/` 与 `logs/` 下的 JSON 文件；展示层为命令行打印 + 本地 Streamlit GUI；"上云" = `sync_cloud.py` 用 git 白名单提交快照。

```text
┌──────────────────────────────────────────────────────────────────┐
│                     外部数据源 (HTTP 抓取)                         │
│   同花顺涨停揭秘  腾讯qt.gtimg/ifzq  新浪  东财push2ex  官方API    │
│   Tushare Pro    同花顺官方API(hithink)   日历/资金流/分钟K线      │
└───────────┬──────────────────────────────────────────────────────┘
            │ urllib.request / requests (每模块限速会话)
            ▼
┌──────────────────────────────────────────────────────────────────┐
│                  采集层 scripts/daily/                             │
│  zt_pool.fetch_zt_pool_raw  update_data(.py)  kline_source(.py)   │
│  hithink_api(.py)  recalc_seal  auction_pool  capture_*          │
└───────────┬──────────────────────────────────────────────────────┘
            │ 直接读写 JSON
            ▼
┌──────────────────────────────────────────────────────────────────┐
│                 存储层 data/ + logs/ (纯JSON文件)                  │
│  zt_pool_state.json  zt_pool/YYYYMMDD.json  kline_data/  auction/ │
│  market_state.json  daily_close/  candidates_*.json  portfolio   │
└───────────┬──────────────────────────────────────────────────────┘
            │ 领域模块读写
            ▼
┌──────────────────────────────────────────────────────────────────┐
│      领域逻辑层 scripts/daily/ (无包平铺, sys.path互引)             │
│  scoring(.py)  sell_engine(.py)  zt_pool  screen_candidates       │
│  trading_journal  capture_market_state  active_pool  yao_watch    │
└───────────┬──────────────────────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────────────────────┐
│  入口/编排层 scripts/daily/run_pipeline.py  morning_check.py       │
│  gui_dashboard.py(Streamlit)  backtest_v4.py   review_*.py        │
│  scripts/ 根目录 ≈70只研究/回测一次性脚本 (非生产链路)               │
└──────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| 流水线编排 | 盘后 Step1–9 顺序执行各采集/筛选模块，单步 try/except 不中断 | `scripts/daily/run_pipeline.py` |
| 涨停池管理器 | 涨停池状态机：更新/加减仓进出池/离池记录/历史快照/昨日池文件选取 | `scripts/daily/zt_pool.py` |
| 涨停池抓取 | 同花顺涨停揭秘爬虫 fetch_zt_pool_raw + 东财 push2ex 历史 | `scripts/daily/zt_pool.py:256` |
| 官方 API | 同花顺官方涨停池/炸板池/连板梯队 (Step1.1 双源校验用) | `scripts/daily/hithink_api.py` |
| K 线增量更新 | 腾讯qfq主源 + Tushare备源 + 新浪兜底三级追加；新标的全量下载；收盘快照 | `scripts/daily/update_data.py` |
| Tushare 封装 | token 读取、ts_code 转换、daily 拉取与单位换算 | `scripts/daily/kline_source.py` |
| 封板质量重算 | 腾讯分钟 K 线重算首次封板/末封/炸板次数，覆盖东财失真派生字段 | `scripts/daily/recalc_seal.py` |
| 评分模块 | 统一评分：K线预处理 pdb → 因子分 → score_v4 加权；配置驱动 | `scripts/daily/scoring.py` |
| 候选筛选 | 全市场涨停股打分存档 → `logs/candidates_*.json`（次日竞价消费） | `scripts/daily/screen_candidates.py` |
| 卖点引擎 | 卖出决策树 sell_signal + 执行价 sell_execution_price | `scripts/daily/sell_engine.py` |
| 交易账本 | 持仓/买卖/盈亏记录 (portfolio/trading_journal) | `scripts/daily/trading_journal.py` |
| 竞价池 | 9:25 腾讯批量行情快照 + gap 分布汇总；9:25 前 open=0 拒写 | `scripts/daily/auction_pool.py` |
| 竞价面板 | 竞价观察输出（决策摘要/持仓处置/可买前三/温度开关），quick 模式提速 | `scripts/daily/morning_check.py` |
| 市场状态 | 盘后赚钱效应采集（次日温度降档校准），恒0守卫 | `scripts/daily/capture_market_state.py` |
| 历史池索引 | 汇总所有上过涨停榜的股票 (historical_zt_pool.json) | `scripts/daily/active_pool.py` |
| 妖股观察 | 2–4 板强连板指纹，只提示不自动交易 | `scripts/daily/yao_watch.py` |
| 推荐回看 | 结算前日可买前三：实际交易或模型模拟收益 | `scripts/daily/review_recommendations.py` |
| 数据体检 | 八项交叉校验 → warnings 写入 candidates 供竞价面板联动 | `scripts/daily/data_health_check.py` |
| 上云同步 | git add/commit/push 白名单快照（仅行情数据） | `scripts/daily/sync_cloud.py` |
| GUI 面板 | Streamlit 本地面板；复用 morning_check 与 scoring | `scripts/daily/gui_dashboard.py` |

## Pattern Overview

**Overall:** 扁平模块 + 配置驱动 + 直写 JSON 的"管道式"每日批处理。`scripts/daily/` 内 40+ 模块无包结构（无 `__init__.py`），靠每个文件顶部 `sys.path.insert(0, dirname)` + `BASE` 三级上溯自检实现同级互引；模块之间通过函数内 lazy import 解耦（`run_pipeline.py` 16 处、`morning_check.py` 12 处），因此静态 grep 看不到完整依赖图。

**Key Characteristics:**
- 每个文件独立计算 `BASE = os.path.dirname(...)` 三级上溯，不依赖包导入路径
- 关键参数集中在 `data/scoring_config.json`（active/v4 weights/normalize/buy_window/score_min/filters/sell 段），代码内 default 仅兜底
- 所有产出物是 JSON/文本/Markdown 文件，无 ORM、无 schema 校验层
- 日期敏感模块全部带注释 `YYYY-MM-DD 改动` 防回归；决策类改动需用户确认（CLAUDE.md 定稿机制）
- 状态分两类：**可变单点 state**（`zt_pool_state.json`/`portfolio.json`/`market_state.json`，tmp+`os.replace` 原子写）与**每日不可变快照**（`data/zt_pool/YYYYMMDD.json`、`data/auction/YYYY-MM-DD.json`、`logs/candidates_YYYY-MM-DD.json`）
- 数据引用纪律：汇报只引用抓取数据（腾讯实时/快照/池 state），禁止反推

## Layers

**入口/编排层:**
- Purpose: 按时间段触发各领域模块，先"结论"后"解释"
- Location: `scripts/daily/run_pipeline.py`, `scripts/daily/morning_check.py`, `scripts/daily/gui_dashboard.py`
- Contains: main() 编排 + CLI 参数解析 + 打印模板
- Depends on: 采集层 + 领域层全部模块（lazy import）
- Used by: 人工 cron 式日常调用（无系统 cron；用户在 9:25/盘后手动跑）

**领域逻辑层:**
- Purpose: 池管理/评分/卖出决策/账本等业务规则
- Location: `scripts/daily/scoring.py`、`sell_engine.py`、`zt_pool.py`、`trading_journal.py`、`screen_candidates.py`、`auction_pool.py`、`active_pool.py`、`capture_market_state.py`、`yao_watch.py`
- Contains: 决策树/因子函数/状态读写封装/过滤规则
- Depends on: 采集层输出（data/ 文件）与 `data/scoring_config.json`
- Used by: 编排层与互相引用（如 `morning_check` → `sell_engine.sell_signal`、`screen_candidates` → `scoring.score_v4`）

**采集层:**
- Purpose: 外部 HTTP 数据抓取与字段口径统一
- Location: `scripts/daily/update_data.py`、`kline_source.py`、`hithink_api.py`、`recalc_seal.py`、`capture_tboard_minute.py`、`capture_money_flow.py`、`trading_calendar.py`（+ `zt_pool.py`/`auction_pool.py`/`morning_check.py` 内的抓取函数）
- Contains: urllib/requests 调用、UA/限速/重试、单位换算（手→股 ×100、成交额→万元）、原始报文落盘 `data/raw/YYYY-MM-DD/`
- Depends on: 外部 HTTP API
- Used by: 编排层（Step1/1.5/1.6/2/7）与领域层

**存储层（非代码层）:**
- Purpose: 全部运行时状态
- Location: `data/`（行情快照与状态）、`logs/`（账本/候选/报告，gitignored）
- Contains: JSON 快照、K线库（3,046 文件，gitignored）、auction 快照（纳入版本管理）
- Depends on: 采集层写入，领域层读取

**研究/回测层:**
- Purpose: 权重搜索、历史验证、一次性分析；不参与每日生产链路
- Location: `scripts/` 根目录（约 70 只，多为 v2/v3 时代回测校准残留）+ `scripts/daily/backtest_v4.py`/`backtest_v4_long.py`/`backtest_sell_exit.py`/`research_streaks.py`/`backtest_divergence.py`
- Contains: 因子敏感性扫描、权重重搜、卖点规则回测、妖股研究
- Used by: 每月 1 日权重滚动更新（backtest_v4）、规则裁决（3年数据验证）
- 注意: v3 旧回测已归档 `backup/legacy_scripts/`，运行报错提示 v3 已移除

## Data Flow

### 盘后主链路（run_pipeline.py main, `scripts/daily/run_pipeline.py:19`）

1. Step1 更新涨停池 `update_zt_pool()` (`zt_pool.py:336`): 拉当日涨停 → 过滤 300/301/688 → 腾讯行情+K线验证收盘涨停 → 更新 `data/zt_pool_state.json` + 快照 `data/zt_pool/YYYYMMDD.json`（`run_pipeline.py:57`）
2. Step1.1 官方 API 双源校验，差异写 `data/official_check.json`，仅警告不改数据（`run_pipeline.py:64`）
3. Step1.5 封板质量分钟线重算 `recalc_seal()`（`run_pipeline.py:95`）
4. Step1.6 资金流采集 `capture_money_flow()`（观察数据不进评分）（`run_pipeline.py:103`）
5. Step2 更新 K 线 `update_data.main()`：池+持仓标的，腾讯qfq增量 → Tushare → 新浪兜底；除权边界守卫（`run_pipeline.py:111`）
6. Step2.5 每日收盘快照 `snapshot_daily_close()` → `data/daily_close/YYYY-MM-DD/daily_data.json`（滚动宇宙 = 昨日 ∪ 今日池）（`run_pipeline.py:118`）
7. Step3 历史涨停池索引 `active_pool.update()` → `data/historical_zt_pool.json`（`run_pipeline.py:126`）
8. Step4 筛选评分 `screen_candidates.main()` → `logs/candidates_YYYY-MM-DD.json`（含 top_pick/candidates/fail_reasons/data_quality）（`run_pipeline.py:134`）
9. Step4.5 妖股观察 `yao_watch.main()`（只提示）（`run_pipeline.py:141`）
10. Step5 每日报告 `generate_report.generate()`（`run_pipeline.py:149`）
11. Step6 昨日推荐回看 `review_recommendations.review_previous_day()`（`run_pipeline.py:157`）
12. Step7 T 字板分钟 K 线 `capture_tboard_minute.main()`（`run_pipeline.py:165`）
13. Step8 数据体检 `data_health_check.main()` 八项交叉校验（`run_pipeline.py:172`）
14. Step8.5 市场状态采集 `capture_market_state.main()` → `data/market_state.json` 赚钱效应（`run_pipeline.py:180`）
15. Step8.6 卖点规则月度跟踪 `backtest_sell_exit.watch_summary()`（`run_pipeline.py:187`）
16. Step9 数据上云 `sync_cloud.sync()` git 提交白名单快照（`run_pipeline.py:194`）
17. `print_status()` 输出持仓状态（`run_pipeline.py:204`）
    `--fast` 跳过 Step5–9；CLI 另支持 `--status/--buy/--sell/--value` 手动记账（`run_pipeline.py:20`）

### 次日竞价链路（9:15–9:35，morning_check.main, `scripts/daily/morning_check.py:443`）

1. 读最新候选 `load_latest_candidates()`（`logs/candidates_*.json` 按日期取最新，`morning_check.py:11`）与持仓 `load_portfolio()`（`morning_check.py:21`）
2. 竞价池采集：quick 模式快照 <3 分钟直接复用，否则 `auction_pool.capture_auction()` 写 `data/auction/YYYY-MM-DD.json`（`morning_check.py:456`）
3. 静默计算每只持仓决策 `compute_position_decision()`：腾讯实时行情 + 新浪双源校验 + K线新鲜度 → `sell_engine.sell_signal()` + `sell_execution_price()`（`morning_check.py:93`）
4. 静默计算环境评级 `compute_environment()`：昨日涨停数/最高板/池均 gap → 温度三档 + 二次确认降档 + 盘后赚钱效应 < -2% 降档（`morning_check.py:140`）
5. 输出硬模版：决策摘要 → 体检警告 → 持仓块 → 环境评级 → 表1/2 可买前三 → 一字板隔日关注 → 分歧弱转强 → 盘中买点参考（`morning_check.py:505` 起）
6. `--quick` 只出 决策摘要+持仓处置+买入开关（可买前三一行式，开关关闭标注「仅参考」）

### 评分链路（Step4 内，screen_candidates.main, `scripts/daily/screen_candidates.py:99`）

1. `fetch_zt_pool()` 取当日涨停池（复用 `zt_pool.fetch_zt_pool_raw`，`screen_candidates.py:53`）
2. `merge_recalced_seal()` 用 state 的 seal_recalced 覆盖封板字段、合并资金流（`screen_candidates.py:79`）
3. 逐股 `load_kline()` 读 `data/kline_data/{name}_{code}.json` 或 `{code}.json`（兼容新旧格式，`screen_candidates.py:64`）
4. `scoring.score_v4(code, klines, details_raw)`：`precompute_klines()` 先建 pdb（每日期中间量: is_limit_up/gap_open_pct/vol_ratio20/is_one_line/cons_lu_before/vol_class，`scoring.py:211`）→ 近1年涨停<2 活跃度过滤 → 因子分 → Σ(权重×归一化分)（`scoring.py:475`）
5. 过滤（一字跳过/4板+一字过滤）→ 排序 → 首选+Top3 → 写 `logs/candidates_YYYY-MM-DD.json`（`screen_candidates.py:221`）

### 温度校准闭环（跨日）

- T 盘后 `capture_market_state.main()` 用 `zt_pool.get_prev_pool_file()` 取昨日池 → K线算昨日涨停股今日收益 → 赚钱效应 → `data/market_state.json`（样本≥10 且均值恰 0 → ⚠ 告警+state.warning，`capture_market_state.py:22`）
- T+1 竞价 `compute_environment()` 读取：昨日赚钱效应 < -2% → 降一档；池均 gap ≤ -0.5% → 再降一档（`morning_check.py:140`）

### 回看结算链路（review_recommendations, `scripts/daily/review_recommendations.py:164`）

T 日盘后读 T-1 `data/auction/T-1.json` 前三 → 有真实交易按交易日志，无交易按 V4 卖点规则模拟（T 开盘买 → T+1 卖）→ 累计统计 `logs/recommendation_review.json`

### 权重重搜链路（每月1日，`scripts/daily/backtest_v4.py:29`）

近1年回测网格搜索因子权重 → 写 `data/scoring_config.json` v4.weights → 历史追加 `data/weight_history.json`（`backtest_v4.py:410` show_history 可查）

**State Management:**
- 单文件可变状态: `data/zt_pool_state.json`（`save_state` tmp+`os.replace` 原子写，`zt_pool.py:72`）、`data/market_state.json`、`data/auction_state.json`、`logs/portfolio.json`、`logs/trading_journal.json`
- 每日不可变快照: `data/zt_pool/`、`data/auction/`、`data/daily_close/`、`data/raw/`（原始报文审计用）
- 契约文件: `logs/candidates_*.json`（字段: date/version/top_pick/candidates/one_line_watch/score_fail/fail_reasons/data_quality）——候选为"存档+回看"用，不展示（盘后规则 2026-08-30）

## Key Abstractions

**涨停池状态机（zt_pool）:**
- Purpose: 池子跨日演进的核心数据模型：T 收盘涨停 → 留池；不涨停 → 移出并记离池原因
- Examples: `data/zt_pool_state.json`（stocks[].history 记录）`data/zt_pool_exit_log.json`、每日快照 `data/zt_pool/`
- Pattern: 状态机 + 事件日志（离池记录）+ 快照归档；`get_prev_pool_file()`（`zt_pool.py:56`）是唯一"昨日池文件选取"实现（2026-09-01 收敛纪律，防止 `< =` 边界错误复制）

**pdb 预处理日线（scoring.precompute_klines）:**
- Purpose: K线 → 逐日因子中间量字典 {date: {is_limit_up, gap_open_pct, vol_ratio20, is_one_line, cons_lu_before, vol_class, ...}}，所有评分因子与连板回算基于它
- Examples: `scoring.py:211`；消费方 `compute_score`/`score_v4`/`classify_volume`
- Pattern: 计算缓存中间层，隔离「K线格式差异」（dict{data}/list、前复权/不复权、volume/volume_lots 混排）

**score_v4 配置驱动加权:**
- Purpose: 10 因子百分制加权（vr/gap/board_type/cons/seal/zhaban/sector/divergence/dt_risk/turnover）
- Examples: `scoring.py:475`；权重与归一化分段在 `data/scoring_config.json` v4 段（sector 32.7/dt_risk 17.0/gap 12.0/vr 9.5/…），`active: v4`
- Pattern: 参数外置 JSON + 每月重搜（backtest_v4），因子分全部进 details.factor_scores 供展示/回看

**sell_signal 卖出决策树:**
- Purpose: (持仓 + 当日竞价 {gap_pct, open, prev_close}) → {action: hold/watch/sell_half/sell, urgency, reason, reference_price}；执行价由 sell_execution_price 按涨停日/非涨停日公式给
- Examples: `sell_engine.py:245`、`sell_engine.py:503`
- Pattern: 决策树（硬止损-10% 例外 → 昨涨停分支 → 昨断板分支 → 执行价），阈值来自 `data/scoring_config.json` sell 段

**温度开关（capture_market_state + morning_check.compute_environment）:**
- Purpose: 用昨日涨停数/最高板/赚钱效应定 空仓/半仓/全仓 三档，竞价二次确认降档
- Examples: `morning_check.py:140`、`capture_market_state.py:22`、`data/market_state.json`
- Pattern: 盘后写分、竞价读分校准的跨日状态循环

**每日收盘快照宇宙（snapshot_daily_close）:**
- Purpose: 滚动累计宇宙（昨日快照 ∪ 今日涨停池）OHLCV 落盘，供持仓估值与回测快照补充，避免依赖全量 K 线库
- Examples: `update_data.py:204` → `data/daily_close/YYYY-MM-DD/daily_data.json` + `stock_index.json`（name→code）
- Pattern: 追加式宇宙（universe.setdefault），昨覆盖今

**双源校验模式:**
- Purpose: 行情/池数据互相印证，偏差告警不改数据
- Examples: 持仓行情腾讯 vs 新浪（`morning_check.py:75`）；本地池 vs 官方 API 连板数（`run_pipeline.py:64` → `data/official_check.json`）
- Pattern: 采集→比对→仅警告/落盘，由数据体检兜底

## Entry Points

| Entry Point | Location | Triggers | Responsibilities |
|---|---|---|---|
| 盘后流水线 | `scripts/daily/run_pipeline.py:19` | 交易日 15:00+ 手动 | Step1–9 全链路；`--fast` 轻量；`--status/--buy/--sell/--value` 记账 |
| 竞价面板 | `scripts/daily/morning_check.py:443` | 交易日 9:15–9:35 | 竞价采集+卖点决策+温度开关+可买前三；`--quick` 只出三块结论 |
| GUI 面板 | `scripts/daily/gui_dashboard.py` | `streamlit run scripts/daily/gui_dashboard.py` | 一键刷新（subprocess 跑 run_pipeline --fast）、持仓卡片、涨停池两标签、交易记录 |
| 权重重搜 | `scripts/daily/backtest_v4.py:29` | 每月 1 日 | 近1年重搜权重 → scoring_config v4 + weight_history；`--show-history` 对比 |
| 补跑历史盘后 | `scripts/daily/run_pipeline_for_date.py` | 补跑指定日期 | monkey-patch datetime 锚定日期后调 run_pipeline.main() |
| 推荐回看 | `scripts/daily/review_recommendations.py:306` | 盘后 Step6 + 手动 `[--date] [--history N]` | 结算前三推荐收益 |
| 妖股验证 | `scripts/daily/yao_watch.py:96` | 次日 9:25 `--next` | 竞价 gap 4-8% 验证指纹命中 |
| 竞价池工具 | `scripts/daily/auction_pool.py` | `--summary/--history` | 查看最新竞价摘要/历史 gap 统计 |
| 数据体检 | `scripts/daily/data_health_check.py:102` | 流水线 Step8 + 手动 | 八项交叉校验写警告 |
| 历史回填 | `scripts/daily/fetch_historical_zt_pools.py` | 一次性补历史 | 东财历史池 → `data/zt_pool_history/`（2026-03~08，gitignored） |
| 卖点规则跟踪 | `scripts/daily/backtest_sell_exit.py` | 盘后 Step8.6 + 独立回测 | 断板低开持有 vs 卖跟踪统计 |

## Architectural Constraints

- **线程模型:** 全部单线程批处理脚本，进程式运行无常驻（唯一例外：Streamlit `gui_dashboard.py`，读文件渲染，一键刷新另起子进程）。无跨进程锁 —— 并发运行两个流水线会竞争读写同一 state JSON，日常约定串行执行
- **全局状态:** 每模块模块级常量路径（BASE/LOG_DIR/…各文件自算一份）；采集会话单例与限速器（`screen_candidates.py` 的 EM_SESSION/_em_last_call、`zt_pool.py` 的 ZT_SESSION、`auction_pool.py` 内同型）——均为进程内只读单例
- **导入方式:** 扁平目录 + 函数内 lazy import 是**强制约定**（顶层互引只有 zt_pool→scoring、update_data→zt_pool 等少数），新增模块不得建立包结构依赖；跨模块签名改动需 grep 全部调用点
- **编码:** Windows GBK 控制台 → 每个 CLI 入口自行 `sys.stdout.reconfigure(encoding='utf-8')`（`morning_check.py`/`screen_candidates.py`/`capture_market_state.py` 等），无共享封装
- **时间纪律:** 运行前先 `date` 取时；`get_today()` 约定 <15:00 回退上一交易日（`update_data.py:23`、`screen_candidates.py:58`）；日期过滤统一走 `zt_pool.get_prev_pool_file`（2026-09-01 事故收敛）
- **日期格式:** 文件内 YYYY-MM-DD；`data/zt_pool/`、`data/zt_pool_history*/` 文件名 YYYYMMDD；`data/auction/`、`logs/candidates_*`、`data/daily_close/` 文件名 YYYY-MM-DD —— 两套并存，比较时注意
- **单位口径:** volume 统一"股"（手 ×100 仅 Tushare 返回处），成交额统一 `amount_10k_cny` 万元；追加行缺字段从涨停池映射补（`update_data.py:175`）
- **数据边界:** 涨停判定走 K 线收盘价 + 腾讯行情双确认；除权边界守卫弃用 qfq 行（`update_data.py:127`）；资金流/买点/妖股均为观察数据，不进评分、不自动交易

## Anti-Patterns

### 每文件重复路径自检样板

**What happens:** 40+ 模块各自重复 `BASE = os.path.dirname(dirname(dirname(abspath(__file__))))` + `sys.path.insert(0, …)` + 目录 os.makedirs 样板（`config.py` 已集中 PROJECT_ROOT/DATA_DIR 但多数模块不用它）
**Why it's wrong:** 路径常量散落，改目录结构需全量替换；`__file__` 缺失环境（交互式/云 GUI）会炸，部分文件加 `if '__file__' in dir()` 兜底（`scoring.py:8`）
**Do this instead:** 新模块从 `config.py` 导入 `PROJECT_ROOT/DATA_DIR/LOG_DIR`；短脚本沿用现样板时保持与 `config.py` 常量一致

### try/except 吞错 + print 警告即"监控"

**What happens:** 流水线每步包 try/except 打印 [Warning] 继续（`run_pipeline.py` Step5/7 甚至 `except: pass`）；失败仅存在于 stdout，不落盘
**Why it's wrong:** 静默失败难追溯；已发生事故：赚钱效应恒 0 连续 7 天无人发现（2026-09-01 教训，靠守卫补救）
**Do this instead:** 保持单步不中断（流水线设计意图），但关键结果必须过守卫（capture_market_state 恒0告警模式）或进 `data_health_check` 体检项；Step5/7 的裸 `except: pass` 至少补打印

### 同域逻辑多处重复实现

**What happens:** 涨停池抓取存在多份实现痕迹：`screen_candidates.py` 内 `fetch_zt_pool`/`_em_zt_api`（东财）已弃用但代码仍在（`screen_candidates.py:41-56`），现行实现在 `zt_pool.fetch_zt_pool_raw`；K线路径查找同样散落 `find_kline_path`（`update_data.py:32`）、`zt_pool._load_klines`、`morning_check` 内联 glob
**Why it's wrong:** 同接口语义分歧（如 2026-09-01 四份手写"昨日池文件过滤"出 `< = today` 边界错），修复要处处同步
**Do this instead:** 新代码收敛到单一实现：昨日池文件 → `zt_pool.get_prev_pool_file`；K线路径 → `update_data.find_kline_path`（体检已复用）；原始池抓取 → `zt_pool.fetch_zt_pool_raw`

### scoring_config 内死配置与代码双轨

**What happens:** `scoring.py:81 default_scoring_config()` 仍含 v2/v3 tables 全套（已删版本仅剩 raise 提示，`scoring.py:304`）；实际配置 v4 全在 `data/scoring_config.json`，default 与磁盘配置可能漂移
**Why it's wrong:** 读代码者分不清生效配置；compute_score 兼容壳（v2/v3 参数）误导新调用方
**Do this instead:** 调用一律 `score_v4`；default 函数只留 v4 兜底结构；v2/v3 残留块在下次评分改动时清理

## Error Handling

**Strategy:** 流水线级"单步容错"（每步 try/except 打印 [Warning] 继续），业务级守卫 + 盘后体检兜底

**Patterns:**
- 评分失败分类落库：`fail_reasons` 区分「设计内过滤」（K线<25根/末日非涨停/活跃度过滤）与「真失败」（无K线文件）（`screen_candidates.py:153-184`），体检据此判断
- 结果守卫：样本≥10 且均值恰 0 → ⚠⚠ 告警 + `state.warning` 字段（`capture_market_state.py` 尾部）
- 八项数据体检（`data_health_check.py:102`）：池/state 连板一致、评分覆盖率>3 报警、vr20↔换手矛盾、收盘价抽样 vs 腾讯、K线新鲜度、竞价快照质量、炸板异常、赚钱效应恒0 —— warnings 写入 candidates.data_quality，竞价面板顶部显示
- 除权边界守卫：qfq 首行与存量末行偏离超涨跌幅上限 → 弃用腾讯行转备源（`update_data.py:127`）
- 双源交叉校验（官方 API/新浪）只警告不改数据
- 原子写：state 先写 .tmp 再 `os.replace`（`zt_pool.py:75`）
- 抓取失败降级链：同花顺失败 → 官方 API 兜底（字段缺失置 0，`zt_pool.py:347`）；K线 腾讯 → Tushare → 新浪
- 原始报文存档 `data/raw/YYYY-MM-DD/`，失真时回溯"源错还是解析错"

## Cross-Cutting Concerns

**Logging:** 无 logging 库，全 stdout print + 状态/账本/回看落 JSON；报告为 `logs/daily_report.md` 与 `logs/daily_reports/YYYY-MM-DD.md`（三块结构）
**Validation:** 规则阈值全在 `data/scoring_config.json`（v4 权重/归一化/买卖窗口/sell 段），代码改动需回测验证（3年数据裁决传统）+ 用户确认（定稿机制）
**Authentication:** 外部服务无鉴权；Tushare token 环境变量或 `data/tushare_token.txt`（gitignored，`kline_source.py:26`）；hithink token `data/hithink_token.txt`
**Rate limiting:** 每采集模块独立限速（≥1s 间隔 + 随机抖动 + 复用 Session）
**提示 vs 自动:** 妖股/分歧弱转强/买点参考/资金流 = 只提示不自动交易；自动域仅限 池更新/评分/卖点引擎/账本 —— 模块边界清晰

---

*Architecture analysis: 2026-09-02*
