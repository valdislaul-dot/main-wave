# Codebase Structure

**Analysis Date:** 2026-09-02

## Directory Layout

```
gogo/                          # 项目根 = BASE (各脚本三级上溯自检)
├── CLAUDE.md                  # 项目规则/定稿机制/持仓基线 (本地保留, 不上传)
├── CONTEXT.md                 # 项目上下文 (本地保留)
├── README.md / SETUP.md / 多端部署.md / 回测对比条件.txt / 策略分析完整报告.md
├── requirements.txt           # 依赖清单 (streamlit/tushare/pandas/requests + fastapi/uvicorn/pytest/httpx)
├── run_api.bat                # gogo 常驻服务启动器 (%~dp0 定位仓库, python -m api.main >> logs/api/console.log)
├── merge_kline.sh / setup_mac.sh        # 平台辅助脚本
├── .gitignore / .streamlit/            # git 与 Streamlit 配置
├── .planning/codebase/        # GSD 代码库地图文档 (本文件所在)
│
├── scripts/                   # 全部 Python 代码
│   ├── daily/                 # ★ 生产运维层: 7步流水线+竞价+评分+卖点 (42+ 模块)
│   │   ├── run_pipeline.py    #   盘后流水线主入口 (编排 Step1-9)
│   │   ├── morning_check.py   #   竞价面板主入口 (9:15-9:35)
│   │   ├── gui_dashboard.py   #   Streamlit GUI
│   │   ├── scoring.py         #   统一评分 (score_v4, 配置驱动)
│   │   ├── sell_engine.py     #   V4 卖点引擎 (决策树+执行价)
│   │   ├── zt_pool.py         #   涨停池管理器 (状态机+抓取+昨日池文件)
│   │   ├── update_data.py     #   K线增量更新+收盘快照
│   │   ├── kline_source.py    #   Tushare 数据源封装
│   │   ├── config.py          #   路径/平台配置 (PROJECT_ROOT/DATA_DIR/LOG_DIR)
│   │   ├── install_api_task.ps1 #   gogo-api 开机自启任务安装 (Task Scheduler, $PSScriptRoot 派生路径, 需管理员)
│   │   ├── ...                #   (其余 30+ 模块见下)
│   │   └── __pycache__/
│   └── *.py                   # 研究/回测/校准一次性脚本 (~70 只, 非每日链路)
│
├── data/                      # 行情数据与运行时状态 (快照文件, 部分是数据非代码)
│   ├── scoring_config.json    # ★ 中央配置: active/v4(weights,normalize)/buy_window/sell 段
│   ├── zt_pool_state.json     # 活跃涨停池状态 (stocks[].history)
│   ├── zt_pool_exit_log.json  # 离池记录
│   ├── zt_pool/               # 每日池快照 YYYYMMDD.json (纳入版本管理, 校准用)
│   ├── zt_pool_history/       # 东财历史池 2026-03~08 (gitignored)
│   ├── zt_pool_history_ths/   # 同花顺历史池 2025-07+ (已跟踪 271 文件)
│   ├── kline_data/            # 主K线库 3,046 文件 {code}.json/{name}_{code}.json (gitignored)
│   ├── backtest_kline/        # 回测K线 70 文件 (已跟踪)
│   ├── minute_kline/          # 分钟K线 {code}_{date}.json (890 文件, 已跟踪83)
│   ├── auction/               # 竞价快照 YYYY-MM-DD.json (纳入版本管理)
│   ├── auction_state.json     # 竞价状态汇总
│   ├── market_state.json      # 赚钱效应/温度历史 (30天)
│   ├── historical_zt_pool.json# 历史涨停股索引 (active_pool 产物)
│   ├── daily_close/           # 每日收盘快照 YYYY-MM-DD/daily_data.json + stock_index.json (gitignored)
│   ├── official_check.json    # 官方API双源校验结果
│   ├── weight_history.json    # 权重重搜历史 (2026-09-01 起)
│   ├── trading_calendar.json  # 交易日历 (gitignored)
│   ├── tushare_token.txt / hithink_token.txt  # token (gitignored, 勿读内容)
│   ├── raw/                   # 原始报文存档 raw/YYYY-MM-DD/ (gitignored, 审计用)
│   ├── full_market_meta.json / alive_codes.json / stock_data.json / active_pool.json / delisted_check.json / backtest_codes.json
│   ├── tools_backup/ / 副本主升浪.xlsx / README.md
│
├── logs/                      # 账本/候选/报告 (整体 gitignored, 本地保留)
│   ├── portfolio.json         # 持仓+现金+已平仓记录
│   ├── trading_journal.json   # 交易日志
│   ├── candidates_YYYY-MM-DD.json  # 每日候选存档 (流水线 Step4 产物)
│   ├── daily_report.md        # 每日报告 (Step5 产物)
│   ├── daily_reports/YYYY-MM-DD.md  # 盘后三块结构汇报 (2026-08-31 起)
│   ├── recommendation_review.json   # 推荐回看累计统计
│   ├── trader_a.json / backtest_*.txt / backtest_*.json / candidates_*.json
│
├── backup/                    # 归档 (v3 脚本/config 备份)
│   ├── legacy_scripts/        # v3 历史回测脚本归档 (运行报错提示 v3 已移除)
│   ├── CLAUDE_v3机制全量_20260826.md / scoring_config_v3全段_20260826.json
│   └── auction_backup_20260827.zip
│
├── results/                   # 研究输出 (gitignored)
├── setup/                     # 平台安装说明 (MAC_SETUP/WIN_SETUP/SKILLS)
├── memory/                    # 用户记忆/数据源优先级 (本地)
├── 资料/                      # 策略知识库: 连板模式_选股与卖点逻辑_Claude_Code知识库.md 等 (本地)
```

## Directory Purposes

**`scripts/daily/` — 生产运维层（本次探索重点）**
- Purpose: 每日实际运行的 42+ 模块，扁平无包结构
- Contains: 入口编排（run_pipeline/morning_check/gui_dashboard）、领域逻辑（scoring/sell_engine/zt_pool/trading_journal/screen_candidates/auction_pool/active_pool/capture_market_state/yao_watch）、采集（update_data/kline_source/hithink_api/recalc_seal/capture_money_flow/capture_tboard_minute/trading_calendar/fetch_historical_zt_pools/backfill_kline_fields/migrate_kline_format）、质检与回看（data_health_check/generate_report/review_recommendations/backtest_sell_exit）、权重研究（backtest_v4/backtest_v4_long/factor_shape/fetch_backtest_klines）
- Key files: `run_pipeline.py`（编排总纲，新步骤注册点）、`scoring.py`（共享评分与K线预处理）、`zt_pool.py`（池状态机+共享日期函数）、`update_data.py`（K线主更新+find_kline_path 共享路径函数）

**`scripts/` 根目录 — 研究/回测层**
- Purpose: 早期选股模型（v2/v3 时代）与一次性分析/校准脚本；现行活跃引用少（`screen_candidates_v3.py` 为独立 V3 脚本，属存档）
- Contains: backtest_*/calibrate_*/final_*/analysis_*/weak_market_* 等约 70 只
- Key files: 无需维护；新研究脚本可放此层，生产逻辑严禁依赖

**`data/` — 数据层**
- Purpose: 行情快照 + 运行时状态 + 中央配置；`data/README.md` 有数据目录说明
- Contains: 见上 Layout 树
- Key files: `scoring_config.json`（唯一"参数定稿"入口）、`zt_pool_state.json`、`market_state.json`

**`logs/` — 账本/汇报层（全部 gitignored，2026-08-31 起不上传）**
- Purpose: 持仓账目、每日候选、报告
- Contains: portfolio/trading_journal/candidates_*/daily_report*

**`backup/` — 归档** | **`results/` — 研究输出 (gitignored)** | **`setup/` `memory/` `资料/` — 文档/知识库（本地保留不上传）**

## Key File Locations

**Entry Points:**
- `run_api.bat`: gogo 常驻 API 服务启动器（根目录, `%~dp0` 定位, 任意目录可跑; 开机自启由 gogo-api 任务调用）
- `scripts/daily/install_api_task.ps1`: gogo-api 开机自启任务安装/更新（幂等, 需管理员 PowerShell）
- `scripts/daily/run_pipeline.py`: 盘后流水线 CLI（`--fast/--status/--buy/--sell/--value`）
- `scripts/daily/morning_check.py`: 竞价面板 CLI（`--quick`）
- `scripts/daily/gui_dashboard.py`: Streamlit GUI
- `scripts/daily/run_pipeline_for_date.py`: 指定日期补跑（monkey-patch 时间）
- `scripts/daily/backtest_v4.py`: 每月1日权重重搜 + `--show-history`

**Configuration:**
- `data/scoring_config.json`: 评分 v4 权重/归一化 + buy_window/score_min/filters + sell 段（代码 default 仅兜底）
- `scripts/daily/config.py`: 路径常量 PROJECT_ROOT/DATA_DIR/DAILY_DIR/LOG_DIR/KLINE_DIR + 平台检测
- `.streamlit/config.toml`、`requirements.txt`、各平台 setup 文档
- 各模块顶部自带 BASE 路径自检（见 ARCHITECTURE Anti-Patterns）

**Core Logic:**
- 评分 `scripts/daily/scoring.py`（precompute_klines pdb → score_v4）
- 卖点 `scripts/daily/sell_engine.py`（sell_signal → sell_execution_price）
- 池状态机 `scripts/daily/zt_pool.py`
- K线更新 `scripts/daily/update_data.py` / `scripts/daily/kline_source.py`
- 候选筛选 `scripts/daily/screen_candidates.py`
- 账本 `scripts/daily/trading_journal.py`
- 竞价 `scripts/daily/auction_pool.py` + `scripts/daily/morning_check.py`

**Testing:**
- 无 pytest/单元测试目录；验证手段 = 回测脚本（`backtest_v4.py`/`backtest_sell_exit.py`/`backtest_divergence.py`）+ `data_health_check.py` 八项体检 + 各模块 `if __name__ == '__main__'` 自测段（如 `kline_source.py:104`）
- 每模块 docstring 头部即"契约说明"（数据流/用法/口径），改动先读 docstring

## Naming Conventions

**Files:**
- Python: snake_case，域名直呼（`zt_pool.py`/`sell_engine.py`/`auction_pool.py`），不按类型分目录
- 状态/快照 JSON：语义化（`zt_pool_state.json`/`auction_state.json`/`market_state.json`/`official_check.json`）
- 每日候选：`candidates_YYYY-MM-DD.json`（logs/，按文件名日期排序取最新）

**Directories:**
- data 下按数据形态分子目录（zt_pool/auction/kline_data/minute_kline/daily_close/raw）；历史数据目录带 _history 后缀，东财/同花顺两源用 `zt_pool_history` vs `zt_pool_history_ths` 区分

**每日期文件命名（两套日期格式并存，见 ARCHITECTURE Constraints）:**
- YYYYMMDD.json: `data/zt_pool/`、`data/zt_pool_history*/` 池快照
- YYYY-MM-DD.json: `data/auction/`、`data/daily_close/YYYY-MM-DD/`、`data/raw/YYYY-MM-DD/`、`logs/candidates_YYYY-MM-DD.json`

**K线文件命名（新旧格式并存，读取端均兼容）:**
- 新格式: `data/kline_data/{code}.json`（dict{metadata,data}，搜狐主库迁移后）
- 旧格式: `data/kline_data/{name}_{code}.json`（纯 list）
- 回测库: `data/backtest_kline/{code}.json`；分钟线: `data/minute_kline/{code}_{YYYY-MM-DD}.json`

**函数/变量:**
- 函数 snake_case 动词短语（`update_zt_pool`/`sell_execution_price`/`snapshot_daily_close`）；内部实现 `_` 前缀（`_load_klines`/`_zt_get`/`_fmt_date`）；模块级常量 UPPER（BASE/STATE_PATH/KLINE_DIR）；评分因子分统一进 `factor_scores` dict

## Where to Add New Code

**新盘后流水线步骤（最常见扩展点）:**
- 实现: 新建 `scripts/daily/<name>.py`，提供 `def main()`；docstring 头部写清 数据流/用法/日期改动 注释
- 注册: 在 `scripts/daily/run_pipeline.py` main() 中仿照现有 Step（如 Step4.5 妖股, `run_pipeline.py:141`）以 lazy import + try/except 打印 [Warning] 的方式挂入，放在 `print_status()` 之前；`--fast` 外的步骤放入非 fast 分支
- 产出: 落盘 `data/<name>.json`（或当日快照目录）；若需次日竞价消费，在 `morning_check.py` 对应块读取
- 检验: 在 `data_health_check.py` 八项体检中增加对应校验项（若数据可能异常）

**新评分因子或规则改动:**
- 因子中间量进 `scoring.py` 的 `precompute_klines` pdb；因子分与归一化在 `scoring.py` score_v4 + `data/scoring_config.json` v4 段 weights/normalize（权重总和100，sector 等池因子从 details_raw 取）
- 验证: `backtest_v4.py` 单因子敏感性扫描 + 5种子收敛检查（±2.8% 定稿线），历史记入 `data/weight_history.json`
- 纪律: 定稿机制 —— 评分/卖出/筛选规则改动需用户明确确认

**新卖点/风控规则:**
- 决策树改 `scripts/daily/sell_engine.py` 的 `sell_signal`（`sell_engine.py:245`）；阈值放 `data/scoring_config.json` sell 段（volume/heavy_shrink 等）；回测验证走 `backtest_sell_exit.py`/3年数据裁决传统

**新数据源接入:**
- 仿 `kline_source.py`（Tushare）写封装：token 读取（环境变量 > data/*_token.txt gitignored）、字段口径统一（volume 股、amount_10k_cny 万元、序列内 pct_change）
- K线增量链挂 `update_data.py` `append_latest` 的候选→备源→兜底三级 if 链（`update_data.py:154-172`）

**共享工具（禁止复制实现）:**
- 昨日池文件选取 → 只用 `zt_pool.get_prev_pool_file()`（`zt_pool.py:56`，2026-09-01 统一纪律）
- K线文件路径查找 → `update_data.find_kline_path()`（`update_data.py:32`；体检已复用）
- 项目路径/平台 → 优先 `scripts/daily/config.py` 常量
- 涨停判定/涨跌幅上限 → `scoring.py` 的 `is_limit_up`/`get_lp`

**研究/一次性验证:**
- 放 `scripts/` 根目录（与生产隔离），产出去 `results/` 或 `logs/`；不再使用的旧脚本归档到 `backup/legacy_scripts/`

**Tests:**
- 新模块不强制写单测；交付自检 = 运行入口脚本看打印 + 跑 `data_health_check.py` + 与既有 JSON 产物 diff（如 zt_pool 快照）

## Special Directories

| Directory | Purpose | Generated | Committed |
|---|---|---|---|
| `data/kline_data/` | 主K线库 3,046 文件 | Yes（每日增量） | No（gitignored，过大） |
| `data/zt_pool/` | 每日池快照 | Yes（每交易日） | Yes（校准用，2026-08 起纪律） |
| `data/zt_pool_history/` | 东财历史池补拉 | Yes（一次性） | No（gitignored） |
| `data/zt_pool_history_ths/` | 同花顺历史池 271 文件 | Yes（2025-09 疯牛段缺失） | Yes |
| `data/auction/` | 竞价快照 27 文件 | Yes（每交易日 9:25） | Yes |
| `data/minute_kline/` | 分钟K线 890 文件（T字板） | Yes（Step7） | 部分（83 历史已跟踪，gitignore 声明忽略） |
| `data/daily_close/` | 每日收盘快照 | Yes（Step2.5） | No（gitignored） |
| `data/raw/` | 原始 HTTP 报文存档 | Yes | No（gitignored） |
| `data/tushare_token.txt` `data/hithink_token.txt` | API token | No | No（gitignored，勿读内容） |
| `logs/` | 账本/候选/报告 | Yes | No（gitignored 全量；2026-08-31 定: 持仓账目不上传） |
| `scripts/__pycache__/` `scripts/daily/__pycache__/` | Python 字节码 | Yes | No |
| `backup/` | v3 时代归档 | No | Yes（文档类除外） |
| `results/` | 研究输出 | Yes | No |
| `setup/` `memory/` `资料/` `CLAUDE.md` `CONTEXT.md` | 文档/知识库 | No | No（本地保留，2026-08-31 定） |
| `.planning/` | GSD 规划/代码库地图 | Yes | Yes |

---

*Structure analysis: 2026-09-02*
