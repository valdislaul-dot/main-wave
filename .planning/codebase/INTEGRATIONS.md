# External Integrations

**Analysis Date:** 2026-09-02

## APIs & External Services

### 涨停池/特殊数据（选股核心数据链）

- **同花顺涨停揭秘** — 涨停池主源（2026-08-20 起，弃用东财 push2ex：lbc 连板数恒 1、zbc 炸板失真、收盘后修正）
  - 端点: `https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool`（GET，参数 page/limit/field/filter=HS,GEM2STAR/order_field/order_type/date）
  - 字段 `high_days`（"N天M板"→板数）、`first_limit_up_time`/`last_limit_up_time`（Unix 秒）、`open_num`（炸板次）、`reason_type`（涨停原因题材→industry）、`currency_value`（流通市值）、`limit_up_type`（板型）
  - 客户端: `scripts/daily/zt_pool.py` `fetch_zt_pool_raw()`（requests，分页 200/页）
  - 鉴权: 无；需 UA 伪装（`Mozilla/5.0 ... Safari/537.36`）；限速 1 请求/秒 + 随机抖动（`_zt_get`）
- **HiThink 同花顺官方金融 API** — 涨停池兜底源 + 双源校验 + 备用竞价快照/连板天梯（2026-08-31 接入，官方免费）
  - Base: `https://fuyao.aicubes.cn`（文档 fuyao.aicubes.cn/docs，仓库 HiThink-Tech/Financial-API）
  - 端点（`scripts/daily/hithink_api.py`，urllib）:
    - `/api/a-share/special-data/limit-up-pool`（支持近 2 年历史，date_ms 毫秒参数，分页 size=200）
    - `/api/a-share/special-data/limit-break-pool`（炸板池）
    - `/api/a-share/special-data/limit-up-ladder`（连板天梯）
    - `/api/a-share/auction/snapshot`（竞价快照，thscodes≤100 只，stage=final）
  - 鉴权: HTTP Header `X-api-key`，token 存 `data/hithink_token.txt`（gitignored）
  - 用途: `zt_pool.py` 爬虫失败兜底（缺炸板次数/换手率）、`run_pipeline.py` Step 1.1 双源校验（结果落 `data/official_check.json`，供 GUI 展示）
- **东财 push2ex** — 历史涨停池批量拉取（仅此用途，每日源已弃用）
  - 端点: `https://push2ex.eastmoney.com/getTopicZTPool`（参数 ut=7eea3edcaed734bea9cbfc24409ed989, dpt=wz.ztzt, date=YYYYMMDD）
  - 客户端: `scripts/daily/fetch_historical_zt_pools.py`（2026-03-04~08-04 段，输出 `data/zt_pool_history/`）；`scripts/update_lianban_stats.py`、`scripts/screen_candidates_v3.py`（归档研究）亦引用
  - 鉴权: 无；UA + Referer `https://quote.eastmoney.com/`

### 实时行情（竞价/盘后实时价）

- **腾讯 qt.gtimg.cn** — 批量实时行情/竞价（主源），GBK 编码 `~` 分隔字段（v[2]=code, v[3]=现价, v[4]=昨收, v[5]=今开, v[47]=涨停价）
  - 端点: `https://qt.gtimg.cn/q=sh600000,sz000001,...`（每批 ≤50 只，sh/sz 前缀按代码首位 6/9→sh）
  - 客户端: `scripts/daily/auction_pool.py` `fetch_quotes()`（竞价采集，9:25~9:30 窗口守卫 + open=0 超半数拒绝写入）；`scripts/daily/zt_pool.py` `_fetch_tencent_batch()`（三方确认收盘涨停 + 除权检测）；`scripts/daily/capture_market_state.py`（赚钱效应缺 K 线时兜底）
  - 鉴权: 无；需 UA；批次间 sleep 0.1s 限速
- **新浪 hq.sinajs.cn** — 实时行情（竞价双源交叉验证源）
  - 端点: `https://hq.sinajs.cn/list=sh600000,sz000001`（每批 ≤60 只）
  - 客户端: `scripts/daily/auction_pool.py` `fetch_sina_quotes()` — 与腾讯做昨收/gap 双源交叉（偏差>0.3% 或昨收不一致告警除权）
  - 鉴权: 无；必须带 `Referer: https://finance.sina.com.cn/` 否则拒绝

### K线数据

- **腾讯 fqkline（web.ifzq.gtimg.cn）** — 日 K 增量主源（前复权 qfq，当日实时）
  - 端点: `http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={mkt}{code},day,,,100,qfq`（count-only 形态拉最近 100 根后按日期过滤）
  - 注意: 无除权史的股票腾讯不返回 `qfqday` 键，需回退 `day` 键（`update_data.py` `_tencent_latest`，2026-09-02 修复）；行格式 [date, open, close, high, low, volume(手)]，volume ×100→股；pct_change 在 qfq 序列内计算
  - 客户端: `scripts/daily/update_data.py` `append_latest()`（除权边界守卫 `_corporate_action_suspect`：首行 open 偏离存量末行 close 超涨跌幅上限+1% → 弃用 qfq 行）；`scripts/daily/fetch_backtest_klines.py`（回测 K 线批量，900 根缓冲 → `data/backtest_kline/`）
  - 鉴权: 无；需 UA
- **腾讯 mkline（ifzq.gtimg.cn）** — 分钟 K 线（1/5 分钟）
  - 端点: `https://ifzq.gtimg.cn/appstock/app/kline/mkline?param={code},m1,,{count}&_var=result`（需 Referer gu.qq.com，GBK，JSONP `_var=result` 包壳）
  - 客户端: `scripts/daily/recalc_seal.py`（封板质量重算：首次封板/最后封板/炸板次数，替代东财失真派生字段）；`scripts/daily/capture_tboard_minute.py`（T 字板分钟存档 → `data/minute_kline/`）；根目录 `scripts/download_tboard_minute.py`（旧版归档）
- **Tushare Pro daily** — 增量备源 + 权威校准（不复权，与主库搜狐口径一致，120 积分）
  - SDK: `tushare`（`pro.daily(ts_code, start_date, end_date)`），ts_code 映射见 `scripts/daily/kline_source.py` `to_ts_code()`（6/9→SH, 0/3→SZ, 8/4→BJ）
  - volume 手→股 ×100；amount 千元→万元口径换算
  - 鉴权: token 读取顺序 环境变量 `TUSHARE_TOKEN` → `data/tushare_token.txt`（gitignored）
  - 客户端: `scripts/daily/kline_source.py` `fetch_tushare_daily()`；`update_data.py` 二源三源失败链 + 盘后 Tushare 校准抽查
- **新浪 CN_MarketData（money.finance.sina.com.cn）** — 全量日 K 兜底（新标的下载）
  - 端点: `https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sz000001&scale=240&ma=no&datalen=5000`（GBK）
  - 客户端: `scripts/daily/update_data.py` `download_full()`（新入池标的近 5000 根全量）
  - 鉴权: 无；需 UA + Referer finance.sina.com.cn
- **搜狐 hisHq** — 历史主库来源（`data/kline_data/` 原始全量下载源，2026-08-17 前的历史实现）；现役代码中已无搜狐 URL 抓取，仅在 `update_data.py` 元数据与 `kline_source.py` 注释中作为「与主库同口径」基准提及。注释还记录: 东财 `akshare stock_zh_a_hist` 2025 起反爬失效已弃用；baostock 2026-08-17 移除；mootdx 禁用

### 资金流（观察数据，不进评分）

- **新浪 MoneyFlow（vip.stock.finance.sina.com.cn）** — 日频主力/超大单净流入
  - 端点: `.../quotes_service/api/json_v2.php/MoneyFlow.ssl_qsfx_zjlrqs?page=1&num={days}&sort=opendate&asc=0&daima={sh|sz}{code}`（GBK）
  - 客户端: `scripts/daily/capture_money_flow.py` `fetch_money_flow()` → 写 `zt_pool_state.json` 每只的 `money_flow` 字段（netamount/ratioamount/r0_net/r0_ratio/r0x_ratio）
  - 设计约束: 观察数据，待推荐回看 N≥50 检验独立预测力后才走解冻流程进评分

### 交易日历

- **akshare `tool_trade_date_hist_sina`**（底层新浪）— 交易日历（`scripts/daily/trading_calendar.py`）
  - 缓存 `data/trading_calendar.json`（fetched_at 7 天内有效）；拉取失败降级「周一~周五」；再失败用过期缓存
  - 服务方: 竞价采集守卫（9:25~9:30、交易日）、prev/next 交易日查询

## Data Storage

**Databases:**
- 无数据库。全部本地 JSON 文件系统（见 STACK.md「数据存储约定」），关键快照原子写（tmp + os.replace）

**File Storage:**
- 本地文件系统为主；外部原始报文归档 `data/raw/YYYY-MM-DD/`（zt_pool_10jqka.json、auction_tencent.txt、auction_sina.txt 等，失真时回溯「源错了」还是「解析错了」）
- 私有 GitHub 仓库（github.com/valdislaul-dot/main-wave.git）作为跨端同步 + 数据上云的「云存储」：`scripts/daily/sync_cloud.py` 流水线 Step 9 自动 `git add/commit/push` 关键快照（zt_pool_state.json/zt_pool_exit_log.json/auction_state.json/market_state.json/active_pool.json/data/auction/*.json），2026-08-31 起持仓/账目/日志不上传

**Caching:**
- `data/trading_calendar.json`（交易日历 7 天缓存）
- `data/kline_data/` 本地 K 线库即长效缓存（增量追加，避免重复拉取）

## Authentication & Identity

**Auth Provider:**
- 无用户/身份体系，无 OAuth。两类密钥鉴权:
  - Tushare Pro: token（env `TUSHARE_TOKEN` 或 `data/tushare_token.txt`）
  - HiThink 官方 API: `X-api-key` header（`data/hithink_token.txt`）
  - 两者 token 文件均已 gitignore，不入库
- 其余源（同花顺/腾讯/新浪/东财）均匿名公开接口，靠 UA/Referer 伪装 + 限速（sleep 0.03~0.5s 随机抖动）反反爬

## Monitoring & Observability

**Error Tracking:**
- 无 Sentry/云监控。可靠性靠:
  - 双源/三源交叉验证（竞价 gap、昨收除权、收盘涨停三方确认、官方 API 家数/连板数校验）
  - 每步 try/except 包裹并打印 `[Warning]` 后继续（流水线 `run_pipeline.py` 各 Step 互不阻断）
  - 数据体检 `scripts/daily/data_health_check.py`（八项：池文件 vs state 连板一致/评分覆盖率/vr-换手矛盾/收盘抽样 vs 腾讯/K 线新鲜度/竞价快照质量/炸板异常/赚钱效应恒 0 守卫）
  - `data/raw/` 原始报文留档供复盘

**Logs:**
- 纯 stdout 打印 + Windows 计划任务重定向 `logs/pipeline.log`；无 logging 框架。`logs/` 已 gitignore
- 运行痕迹另存 `data/market_state.json`（含 warning 字段，2026-09-01 赚钱效应恒 0 事故后加的守卫）

## CI/CD & Deployment

**Hosting:**
- Streamlit Cloud（部署说明在 SETUP.md）：云端只读面板 `gui_cloud.py`（market_state/auction_state/zt_pool_state 快照），因海外 IP 限制不依赖实时行情
- 本地运行: `streamlit run scripts/daily/gui_dashboard.py`（localhost:8501，headless=true 配 `.streamlit/config.toml`）

**CI Pipeline:**
- 无 CI。自动化仅为定时任务:
  - Windows: `scripts/daily/install_scheduled_task.ps1` 注册计划任务「主升浪每日选股流水线」→ 开机 5 分钟后 + 每日 15:30 跑 `auto_start.bat`（注意 bat 内 BASE 硬编码为旧路径 `C:\Users\Davis\Desktop\项目\gogo`，本机仓库实际在 `C:\Users\Davis\Desktop\项目\gogo`）
  - Mac: crontab `0 15 * * 1-5`（SETUP.md 示例）+ `scripts/daily/morning_run.sh` 9:26 竞价
- 代码同步: Win/Mac 双端共享同一 GitHub 私有仓库，手动 git pull/push（无自动 CI）

## Environment Configuration

**Required env vars / 密钥文件:**
- `data/tushare_token.txt` 或环境变量 `TUSHARE_TOKEN`（Tushare，缺失时自动跳过备源与校准，不崩溃）
- `data/hithink_token.txt`（HiThink API，缺失时兜底失效但不崩溃）
- 无其他密钥；无 `.env` 文件

**Secrets location:**
- 仓库内 gitignored 文件: `data/tushare_token.txt`、`data/hithink_token.txt`

## Webhooks & Callbacks

**Incoming:**
- 无

**Outgoing:**
- 无（对 GitHub 的 push 是 sync_cloud.py 主动 git 操作，非 webhook）

---

*Integration audit: 2026-09-02*
