# 会话上下文 — 2026-08-06 周三 → 08-07

## 当前状态

### 你的持仓
- 云南锗业(002428): 900股 @90.096, 现金11,895
- 4笔, 胜率75%, 累计+24,850

### 交易员A
- 兴民智通(002355)

## V3.1 (2026-08-06)
- **连板6档**: 首板-2/2板+6/3板+14/4板+22/5板+26/6板++30
- **选股**: 直接最高分(回测+11.2pp vs Top3最小量比)
- **过滤**: 近1年<2次涨停排除
- **半仓**, -10%止损
- **三年回测**: >=10 = +2,781% (搜狐不复权3044只)

## 选股流水线 (7步)
涨停池→K线更新→历史池→V3.1评分→龙虎榜→报告→T字板
`python scripts/daily/run_pipeline.py` (盘后)
`python scripts/daily/morning_check.py` (9:25竞价)

## 数据
- `data/kline_data/` — 3045只搜狐财经10年不复权K线
- `data/scoring_config.json` — V3.1配置
- `data/zt_pool_state.json` — 涨停池状态
- `data/auction/` — 竞价快照

## 编码修复
`screen_candidates.py` stdout强制utf-8, 解决Windows gbk崩溃

## 跨端同步
- GitHub: https://github.com/valdislaul-dot/main-wave.git
- Mac端需统一数据源后对比回测
- 回测条件: C:\Users\Davis\Desktop\gogo\回测对比条件.txt
