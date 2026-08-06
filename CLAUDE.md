# 主升浪项目 — V3.1 (2026-08-07 Win端)

## ⚠️ 时间判断规则
- **任何操作前必须先执行 `date +"%H:%M"` 获取当前时间**
- 禁止使用记忆/缓存中的时间

## 持仓
- 云南锗业(002428) 900股@90.096, 现金11,895
- 4笔, 胜率75%, 累计+24,850
- A: 兴民智通(002355)

## 数据源
- **baostock** — K线（backtest_kline/ 786只 + kline_data/ 3558只）
- **东财 push2ex** — 涨停池实时
- **腾讯 qt.gtimg.cn** — 竞价行情
- **mootdx 禁用**

## V3.0 评分系统

### 双轨并行
1. **daily/scoring.py** — v2陡峭(旧) + v3平滑(新)，配置驱动，screen_candidates/morning_check/backtest 统一引用
2. **screen_candidates_v3.py** — 六维动态权重 + Sigmoid概率映射，首板/连板分别加权

### 六维因子（V3 Sigmoid版）
| 维度 | 首板权重 | 连板权重 | 子因子 |
|------|---------|---------|--------|
| 题材驱动 | 30% | 5% | 板块共振 + 周几效应 |
| 市场人气 | 20% | 10% | 换手率 + 量比 |
| 资金结构 | 20% | 20% | 流通市值 + 量比 |
| 上涨动能 | 15% | 30% | gap + T-2涨停 |
| 封单强度 | 10% | 25% | 封板时间 + 炸板次数 + 一字板 |
| 形态溢价 | 5% | 10% | 一字板 + 连板数 |

### V3平滑版（daily/scoring.py，配置驱动）
配置：`data/scoring_config.json`，active="v3"

| 因子 | v2（陡峭6档） | v3（平滑11档） |
|------|-------------|---------------|
| 量比 | <0.3(+37) … ≥3.0(0) | <0.2(+40) → <0.3(+34) → … → ≥5.0(-1) |
| gap | ≥9(+20) … <-3(+2) | ≥10(+22) → ≥8(+16) → … → <-3(+2) |
| 封板时间 | 无 | 0-5min(+14) → … → 60min+(-9) 共11档 |
| 炸板 | 无 | 早盘回封(-2/次) / 午盘回封(-6/次) / 尾盘(量能分级) |
| 板块共振 | 无 | ≥5只(+12) / ≥3只(+6) / ≥2只(+2) |
| 一字板 | 真一字+20 / T字+10 | 同 |
| 连板 | 首板-4 / 2-3板+10 / 4板++15 | 同 |
| 周几 | 周一+2 / 周五-1 | 同 |

### 过滤规则
- 真一字板 → 跳过（买不到）
- 4板+一字/T字板 → 过滤（高危回撤）
- 买入日一字板 → 跳过
- 300/301/688 → 剔除

### 买入
- T日开盘价，竞价区间 **4%-8%**
- 全仓（仓位分档不如全仓）
- 评分 ≥ 10

### 卖出判断（T+1竞价）
```
T日涨停 + T+1不低开 → 持有
T日涨停 + T+1低开   → 卖出
T日断板 + T+1 gap≥4% → 持有
T日断板 + T+1 gap<4% → 卖出
```

### 卖出执行
- 涨停日 → HIGH（挂涨停价限价单）
- 不涨停日 → 70%(H+O)/2 + 30%收盘价
- 14:45 未成交 → 市价兜底
- **硬止损 -10%**（已内置）

### 仓位映射
- 评分 ≥ 40 → 全仓(100%)
- 评分 ≥ 20 → 半仓(50%)
- 评分 < 20 → 1/3仓(33%)

## 回测参考（v2.2，200k初始，全仓）
| 区间 | 最终 | 收益 | 笔数 | 胜率 |
|------|------|------|------|------|
| 5个月(03-03~07-24) | 2,542k | +1,171% | 52 | 60% |

## 实盘操作
```
盘后: streamlit run scripts/daily/gui_dashboard.py  （GUI面板，一键刷新）
  或: python scripts/daily/run_pipeline.py            （命令行6步流水线）
9:25: python scripts/daily/morning_check.py           （竞价观察+卖出判断+竞价池采集）
9:30: 执行买卖
14:45: 限价单未成交→市价兜底
```

### 竞价池
- **data/auction/YYYY-MM-DD.json** — 每日全量竞价快照（涨停池+候选标的）
- **data/auction_state.json** — 竞价状态汇总（当前+历史gap分布）
- `scripts/daily/auction_pool.py` — 竞价池管理器
  - `capture_auction()` — 9:25采集全市场竞价（腾讯API批量）
  - `--summary` — 查看最新竞价摘要
  - `--history` — 查看历史竞价统计

## 6步流水线（run_pipeline.py）
1. 更新K线数据（baostock增量）
2. 更新涨停池（东财push2ex）
3. 筛选候选（V3平滑评分）
4. 龙虎榜+大宗因子（实验阶段）
5. 生成每日报告
6. 捕获T字板分钟K线

## Streamlit GUI 面板
```bash
streamlit run scripts/daily/gui_dashboard.py
```
- 标题栏：日期+星期+评分版本
- 🔄 一键刷新：拉涨停池 + 增量更新K线
- 持仓卡片：总资产/持仓/现金/胜率
- 涨停池：可买/全部两个标签，风控标记（一字/4板+/炸板）
- 交易记录：历史盈亏汇总

## 关键文件
```
data/scoring_config.json    ← 评分配置（v2+v3双表）
data/kline_data/            ← 3,558只K线（baostock，gitignored）
data/backtest_kline/        ← 回测K线
data/zt_pool/               ← 涨停池快照（每日保存）
data/zt_pool_state.json     ← 活跃涨停池状态
data/auction/               ← 竞价快照
logs/portfolio.json         ← 持仓+已平仓记录
logs/trading_journal.json   ← 交易日志
scripts/daily/scoring.py    ← 统一评分模块（配置驱动）
scripts/daily/zt_pool.py    ← 涨停池管理器
scripts/daily/gui_dashboard.py ← Streamlit GUI
scripts/screen_candidates_v3.py ← V3六维Sigmoid版（独立脚本）
```

## 跨端同步
- GitHub: https://github.com/valdislaul-dot/main-wave.git (私有)
- Win/Mac 脚本自动检测 BASE 路径
- Mac改完 → git push，Win开始前 → git pull
