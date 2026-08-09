# 会话上下文 — 2026-08-09 周六

## 当前状态

### 你的持仓
- 云南锗业(002428): 900股 @90.096, 现金0（盈利已转出）
- 8笔, 胜率88%, 累计+60,675
- 模型7笔全胜 +63,094 | 主观（盈峰环境）1笔 -2,419

### 交易员A
- 百花药业(600721) @10.20, 55800股 (08/07买入)

## V3.2 (2026-08-07)
- 三年回测: >=10 = +2,953% (全市场3035只, 全仓)
- 回测验证: DT因子（龙虎榜+大宗）多轮测试均无提升，已移除

## 选股流水线 (5步)
涨停池→K线更新→历史池→V3.2评分→报告→T字板
`python scripts/daily/run_pipeline.py` (盘后)
`python scripts/daily/morning_check.py` (9:25竞价)

## 数据
- `data/kline_data/` — 3045只搜狐财经10年不复权K线
- `data/scoring_config.json` — V3.2配置
- `data/zt_pool_state.json` — 涨停池状态
- `data/auction/` — 竞价快照

## 编码修复
`screen_candidates.py` stdout强制utf-8, 解决Windows gbk崩溃

## 跨端同步
- GitHub: https://github.com/valdislaul-dot/main-wave.git
- Mac端需统一数据源后对比回测
- 回测条件: C:\Users\Davis\Desktop\gogo\回测对比条件.txt
