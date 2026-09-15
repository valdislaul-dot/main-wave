# Technology Stack

**Analysis Date:** 2026-09-02

## Languages

**Primary:**
- Python 3.10+（SETUP.md 要求；当前开发机实际 Python 3.13.1）— 全部业务逻辑。核心目录 `scripts/daily/`，约 45 个模块；`scripts/` 根目录还有约 60 个历史研究/回测脚本
- 代码风格高度依赖标准库（`urllib.request` 而非 requests 完成大部分 HTTP 抓取），仅 4 个模块用 `requests`

**Secondary:**
- Bash — `scripts/daily/morning_run.sh`（Mac 竞价定时）、根目录 `setup_mac.sh`、`merge_kline.sh`
- Batch — `scripts/daily/auto_start.bat`（Windows 定时流水线入口，注意：其中 BASE 路径硬编码为旧路径 `C:\Users\Davis\Desktop\项目\gogo`）
- PowerShell — `scripts/daily/install_scheduled_task.ps1`（注册 Windows 计划任务）

## Runtime

**Environment:**
- CPython 3.10+，无虚拟环境规范（直接 `pip install -r requirements.txt`）
- 无 `.python-version` / `pyproject.toml` / poetry / uv；依赖只声明在根目录 `requirements.txt`
- 平台双端：Windows（本仓库 Win 端）+ macOS（Mac 端路径 `/Users/semple/Desktop/主升浪`），由 `scripts/daily/config.py` 运行时自动探测 `PROJECT_ROOT`，代码内不硬编码绝对路径

**Package Manager:**
- pip
- Lockfile: 缺失（`requirements.txt` 全部为 `>=` 无上限无锁定，见下方实际安装版本）

**依赖清单 `requirements.txt`（均为 `>=` 未锁定）：**
| 包 | 最低版本 | 实际安装(2026-09 本机) | 用途 |
|---|---|---|---|
| akshare | 1.10.0 | 1.18.70 | 交易日历 `ak.tool_trade_date_hist_sina()`（`scripts/daily/trading_calendar.py`）；研究脚本用东财行情（历史全量，已注明 2025 起失效弃用）|
| requests | 2.28.0 | 2.34.2 | 同花顺涨停池抓取（`scripts/daily/zt_pool.py`）、东财历史池（`scripts/daily/fetch_historical_zt_pools.py`）|
| streamlit | 1.28.0 | 1.60.0 | 本地 GUI `scripts/daily/gui_dashboard.py` + 云端只读面板 `scripts/daily/gui_cloud.py` |
| tushare | 1.2.0 | 1.4.29 | Tushare Pro daily 备源+校准（`scripts/daily/kline_source.py`）|

**间接依赖（实际被 import，未在 requirements.txt 声明）：**
- pandas 2.2.3 / numpy 2.2.0 — akshare 返回 DataFrame 的隐式依赖（`trading_calendar.py` 直接取 `df['trade_date']`，但代码未显式 import pandas）
- scipy 1.14.1 — 仅研究脚本 `scripts/analysis_emotion_metrics.py`、`scripts/analysis_emotion_metrics_3y.py`（斯皮尔曼/皮尔逊相关系数，用于验证赚钱效应指标）
- openpyxl 3.1.5 — 约 15 个根目录研究脚本读取 `资料/` 知识库 xlsx 源文档

## Frameworks

**Core:**
- 无 Web 框架、无 ORM、无应用框架。项目是纯脚本式流水线（CLI 编排 `scripts/daily/run_pipeline.py` + Streamlit 展示层）

**GUI/展示:**
- Streamlit 1.60.0 — 两个面板：本地全功能 `scripts/daily/gui_dashboard.py`（8501 端口）；云端只读 `scripts/daily/gui_cloud.py`（读 GitHub 同步的快照 JSON）
- `.streamlit/config.toml` — headless=true、深色主题、禁用统计收集

**Testing:**
- 无测试框架、无 pytest/unitest 测试文件（质量侧见 TESTING.md）；验证方式是数据体检模块 `scripts/daily/data_health_check.py`（八项交叉校验）+ 研究脚本自测入口（`if __name__ == '__main__'`）

## Key Dependencies

**Critical（运行时数据链）:**
- 腾讯行情/K线接口（无 SDK，urllib 直连）— 日 K 增量主源、实时报价、分钟 K 线，见 INTEGRATIONS.md
- tushare（`scripts/daily/kline_source.py`）— K 线增量备源 + 权威校准；token 在环境变量 `TUSHARE_TOKEN` 或 `data/tushare_token.txt`
- 同花顺涨停揭秘接口（无 SDK，requests 直连）— 涨停池主源
- HiThink 官方金融 API（`scripts/daily/hithink_api.py`，官方免费）— 涨停池兜底 + 双源校验；token 在 `data/hithink_token.txt`

**Infrastructure:**
- akshare — 交易日历缓存源
- openpyxl / scipy — 仅研究脚本

## Configuration

**评分配置（业务核心，版本化入库）:**
- `data/scoring_config.json` — V4 评分权重（10 因子：sector/dt_risk/gap/cons/seal/zhaban/vr/turnover/board_type/divergence）、买入窗口、风控过滤、卖点引擎全部阈值参数，配置驱动设计
- `data/weight_history.json` — 每月 1 日权重重搜历史记录

**环境/运行时配置:**
- `scripts/daily/config.py` — 唯一路径基座：`PROJECT_ROOT`/`DATA_DIR`/`KLINE_DIR`/`LOG_DIR` 自动探测（Win/Mac 双端）
- `.streamlit/config.toml` — Streamlit 服务配置
- 无 `.env` 体系；密钥走 gitignored 文件：`data/tushare_token.txt`、`data/hithink_token.txt`
- `.gitignore` — `data/kline_data/`（3 千余只 JSON 行情大文件）等数据目录排除入库；持仓/账目/logs/文档类按 2026-08-31 隐私约定全部 gitignore

**时间/时区约定:**
- 全部按北京时间（Asia/Shanghai）交易日历运行；`scripts/daily/trading_calendar.py` 用 akshare 新浪交易日历缓存（7 天有效，失败降级周一~周五）
- 盘后窗口判定（<15:00 取 T-1）在 `scripts/daily/update_data.py` `get_today()`

## 数据存储约定（无数据库）

- 纯本地 JSON 文件系统存储，无数据库/无对象存储：
  - `data/kline_data/` — 个股日 K 线（3000+ 只，两种格式：dict 带 metadata 或纯 list，utf-8/gbk 兼容读取）
  - `data/backtest_kline/` — 回测 K 线
  - `data/zt_pool/`、`data/zt_pool_state.json`、`data/zt_pool_exit_log.json` — 涨停池快照/状态/离池记录
  - `data/auction/YYYY-MM-DD.json`、`data/auction_state.json` — 竞价快照
  - `data/daily_close/YYYY-MM-DD/daily_data.json` — 每日收盘快照（滚动宇宙）
  - `data/raw/YYYY-MM-DD/` — 外部 API 原始报文存档（失真回溯用）
  - `data/trading_calendar.json`、`data/market_state.json`、`data/money_effect_series.json`、`data/industry_map.json` 等
- 写文件规范：临时文件 + `os.replace` 原子替换（`zt_pool.py` save_state / `auction_pool.py`）
- 单位口径：volume 统一「股」（腾讯/新浪返回手 ×100 换算，见 `kline_source.py` 头注释）、成交额 `amount_10k_cny`（万元）、搜狐不复权历史库口径（`data/kline_data/` 元数据 `source: Sohu+EM/Tencent/Sina`）

## Platform Requirements

**Development:**
- Windows（本机 Win 11）或 macOS；Python 3.10+；`pip install -r requirements.txt`
- 数据初始化：`python scripts/daily/fetch_backtest_klines.py`（一次性全量 K 线，~15 分钟）
- 每日流程：盘后 `python scripts/daily/run_pipeline.py`；竞价 9:25 `python scripts/daily/morning_check.py --quick`

**Production/部署:**
- 无服务器部署；两种运行形态：
  1. 本地：`streamlit run scripts/daily/gui_dashboard.py`（localhost:8501）
  2. 云端只读：Streamlit Cloud（`gui_cloud.py`，数据靠 GitHub 仓库快照，不依赖本地行情文件）
- 自动化：Windows 计划任务（`install_scheduled_task.ps1` 注册开机启动 + 每日 15:30 跑 `auto_start.bat`）；Mac crontab 9:26 跑 `morning_run.sh`
- 跨端同步：私有 GitHub 仓库 `github.com/valdislaul-dot/main-wave.git`（代码 + 行情数据双向同步载体，见 INTEGRATIONS.md）

---

*Stack analysis: 2026-09-02*
