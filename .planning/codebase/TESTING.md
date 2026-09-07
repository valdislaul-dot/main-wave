# Testing Patterns

**Analysis Date:** 2026-09-02

## Test Framework

**Runner:**
- 无。全库 grep 未发现 pytest / unittest / doctest / 任何 `assert` 语句, 无 `tests/` 目录, 无 CI 配置(`.github/` 不存在), `requirements.txt` 只含运行时依赖(akshare/requests/streamlit/tushare)
- 项目不写单元测试, 采用 **"数据体检 + 守卫告警 + 回测统计验证"三层自校验** 代替(见下)

**Run Commands:**
```bash
python scripts/daily/run_pipeline.py              # 盘后流水线, Step 8 自动跑数据体检
python scripts/daily/data_health_check.py         # 独立跑八项数据体检 [--date YYYY-MM-DD]
python scripts/daily/backtest_v4.py               # V4权重搜索验证 [--best|--sweep|--seeds N]
python scripts/daily/review_recommendations.py    # 推荐滚动回看 [--date YYYY-MM-DD] [--history N]
python scripts/daily/backtest_sell_exit.py        # 卖点规则月度跟踪(含 watch_summary)
python scripts/daily/morning_check.py --quick     # 竞价面板(持仓行情双源校验告警)
```

## 验证策略一: 数据体检(data_health_check)

**文件:** `scripts/daily/data_health_check.py`(322 行, 2026-08-15 起每次流水线后自动执行)

**八项交叉校验**(每一项: 无相关文件 → 打印 `- 跳过`; 通过 → `✓`; 异常 → `⚠` 并计入 warnings):
1. 当日池文件 vs `zt_pool_state.json` 连板数一致性
2. 候选评分覆盖率(真失败>3只告警; 活跃度过滤为设计内不计失败)
3. vr20↔换手率交叉验证(隐含20日均换手 0.03~60 区间)
4. 腾讯批量收盘价 vs 池文件价格偏差>2% 全池校验
5. 池内每只股票 K线最新日期(复用 `find_kline_path`)
6. 竞价快照质量(open=0 占比>30% 疑似采集过早)
7. 炸板次数异常(区分分钟线重算值与东财原始值)
8. 赚钱效应合理性(恒0且样本≥10 → 告警, 2026-09-01 教训的守卫)

**结果处理:** 返回告警数, `main()` exit code = 有告警则 1; 结果落 `logs/data_quality_log.json`(追加保留90天); 告警回写当日候选文件 `data_quality` 字段, 次日竞价面板 `morning_check.py` 顶部展示(`data_health_check.py:297-311` + `morning_check.py:517-523`)

**体检新增校验项的模式**(写新验证的样板): 文件级 `if os.path.exists(...): 读取 → 逐项比对 → warnings.append(f'...') / print(f'  ✓ ...')`, 数据缺失路径必须打印 `跳过` 而非报错。

## 验证策略二: 内联守卫告警

历史事故(赚钱效应连续7天恒0无人发现)驱动的模式——**计算端输出合理性自检**:

```python
# scripts/daily/capture_market_state.py:87-93 — 结果合理性守卫
if len(rets) >= 10 and (money_effect is None or abs(money_effect) < 0.005):
    warning = (f'赚钱效应{money_effect}%但样本{len(rets)}只≥10, 疑似日期过滤bug'
               f'(同日bar相减恒0), 检查昨日池文件选取')
    print(f'[MarketState] ⚠⚠ {warning}')
```

其他守卫实例:
- 采集端守卫: 竞价快照采集时间过早(open=0 超半数)自动拒绝写入(`scripts/daily/auction_pool.py` capture_auction)
- 除权边界守卫 `_corporate_action_suspect()`: qfq 首行 open 与存量末行 close 偏离超限 → 弃用 qfq 增量, 换 Tushare/新浪(`scripts/daily/update_data.py:127-134`)
- 防回归的结构性约定: 昨日池选取收敛到共享函数 `zt_pool.get_prev_pool_file()` 单点实现, 新代码禁止复制手写日期过滤(`scripts/daily/zt_pool.py:56-69`)

## 验证策略三: 双源/三方交叉验证(数据正确性)

所有关键实时/收盘数据必须与独立第二源比对, 偏差超阈值当场告警:

- **持仓行情双源**: 腾讯 vs 新浪, open/prev_close 偏差>0.5% 逐字段列入 `issues` 列表; 新浪不可用返回 None(标记单源不告警)——`cross_check_quote()` (`scripts/daily/morning_check.py:75-90`)
- **涨停池三方确认**: 东财收盘 vs 腾讯收盘 >2% 疑似尾盘炸板; 腾讯昨收 vs K线昨收 >1% 疑似除权(`scripts/daily/zt_pool.py:498-510`)
- **权威校准**: 盘后 Tushare 抽查涨停池前3只收盘价 vs 本地 K线, 偏差>2% 标 ⚠(`scripts/daily/update_data.py:352-381`); 连板数官方 API 与本地池比对(仅警告不改数据, `scripts/daily/run_pipeline.py:64-93`)
- **测试代码示例** — 断言式告警逻辑的样板:

```python
# scripts/daily/morning_check.py:82-90 (双源比对核心)
diff = abs(tv - sv) / tv * 100
if diff > 0.5:
    issues.append((field, tv, sv, round(diff, 2)))
```

## 验证策略四: 回测统计验证(策略层)

无单测, 策略正确性靠**历史回测 + 滚动实盘回看**统计验证:

- **`scripts/daily/backtest_v4.py`** — V4 权重搜索: 预计算1年因子分 → 权重随机搜索(500组, 收益60%+胜率40%目标, 强弱两窗交叉); `--sweep` 单因子敏感性扫描(9/10 因子在峰为通过标准), `--seeds N` 多种子收敛检验(5种子 obj 收敛 ±2.8% 为通过标准); 每月1日重搜并追加 `data/weight_history.json`(`--show-history` 查看)
- **`scripts/daily/review_recommendations.py`** — 推荐滚动回看: 每次盘后结算前一日竞价可买前三的 T+1 收益, 有实盘按交易日志, 无实盘按开盘价买入+V4规则卖出模拟; 结果落 `logs/recommendation_review.json`, 累计胜率>50% = 推荐体系健康信号
- **`scripts/daily/backtest_sell_exit.py`** — 卖点规则月度跟踪(2026-09-02 加入流水线 Step 8.6, 断板低开持有vs卖口径)
- **`scripts/daily/backtest_v4_long.py`** — 3年长期检验, 已知局限: 仅K线可算的5因子子集, 结论只作参考(回测口径说明见 `CLAUDE.md`)
- 历史模式回测: `scripts/daily/backtest_divergence.py`(分歧弱转强)、`scripts/daily/research_streaks.py`(妖股指纹, 255个7板+事件 vs 67018短命板对照)
- 回测口径纪律(用户定稿, 新回测脚本必须沿用): 开盘价进出含成本(佣金万2.5+滑点0.1%)、Top1买不进依次向下、弱市半仓强市全仓、区间短期5个月/长期1年×强弱市四象限

## Mocking

**Framework:** 无 mock。代码直接打真实 HTTP 接口(腾讯 qt.gtimg.cn / 新浪 hq.sinajs.cn / 同花顺 data.10jqka.com.cn / Tushare), 统一带 `User-Agent: Mozilla/5.0`, 批量按50只分片, 请求间隔节流≥1s(`_zt_get`/`em_get` 模式)。

**What to Mock:** 不适用——但注意运行时序约束: 多数脚本是**时点敏感**的(9:25 竞价、15:00 盘后、T日涨停池), 手工验证时须先确认当前时间与数据新鲜度(`morning_check --quick` 快照<3分钟才可复用)。

**What NOT to Mock:** 行情/池数据一律走真实源并交叉比对——这正是本项目的校验哲学。

## Fixtures and Factories

**Test Data:** 无 fixture 工厂。验证用真实存量数据文件:
- `data/kline_data/*.json` — 日K线(3048只; dict 新格式 `{'data': [...]}` 或 list 旧格式, 读取时 `raw.get('data', raw) if isinstance(raw, dict) else raw` 双格式兼容)
- `data/zt_pool/YYYYMMDD.json` — 每日涨停池快照(可能含 sh/sz 前缀 code, 读取时 `.replace('sh','').replace('sz','')` 归一, `scripts/daily/data_health_check.py:124-128`)
- `data/auction/YYYY-MM-DD.json`、`logs/candidates_YYYY-MM-DD.json`

**Location:** 验证逻辑直接在 `scripts/daily/` 各模块内或 `data_health_check.py` 内联; 候选/池文件名跨模块查找需排除 `candidates_v*` 旧格式(`scripts/daily/auction_pool.py:47-54`, `scripts/daily/morning_check.py:11-18`)

**Encoding:** 读取必须兼容 utf-8/gbk 两态(历史文件), 推荐共用 `load_json(p, encodings=('utf-8','gbk'))` helper(`scripts/daily/data_health_check.py:26-33`)

## Coverage

**Requirements:** 无代码覆盖率工具与目标。

**替代的质量度量**(运行 `run_pipeline.py` Step 8 后看):
- 评分覆盖率: 当日池评分成功比例, 真失败>3只告警
- K线新鲜度: 全池 K线最新日期 == 当日
- 双源/三方偏差率: 收盘价/昨收比对一致
- 体检历史: `logs/data_quality_log.json` 90天记录, 连续告警趋势 = 回归信号

## Test Types

**Unit Tests:** 不存在。纯逻辑函数(`scoring.py` 的 `is_limit_up`/`piecewise_linear`/`step_score_*`, `zt_pool.py` 的日期选取)无任何测试——改动需人工跑一次 `python scripts/daily/run_pipeline.py` + `morning_check.py` 验证链路。`scoring.py` 的 `__main__` 块是唯一的自检近似(打印配置 + 插值采样点对比, `scoring.py:739-756`)

**Integration Tests:** 无测试框架集成。流水线即集成测试: `run_pipeline.py` 顺序执行 9 步、每步 fail-open、Step 8 体检收尾; 次日 `morning_check.py --quick` 消费前日产物并做双源校验, 形成"生产即测试"的日循环

**E2E Tests:** 无。回测(backtest_v4 等)是离线的策略端到端验证; 实盘推荐正确性由 `review_recommendations.py` 滚动回看持续度量

## Common Patterns

**Async Testing:** 不适用——全同步阻塞 IO + 显式 `time.sleep` 限速。

**Error Testing:** 网络层错误处理本身就是可测试路径, 约定: 任一源失败必须可降级(返回 None/[]), 调用方走备源/兜底且打印 `[模块] 失败原因`。人工验证方法: 断网/改错 token 后运行 `python scripts/daily/run_pipeline.py`, 观察各 Step 是否打印 `[Warning]` 并继续、数据是否仍产出(腾讯→Tushare→新浪级联)。

## Test Coverage Gaps

- **评分/卖点纯逻辑零单测**: `scoring.py` 的 `precompute_klines`、`sell_engine.py` 的决策树分支(gap 分级/弱转强/深水分支)是高频改动区, 任何改动只靠当日实盘回看发现——若未来引入 pytest, 这两个模块的纯函数(输入 K线行 + details_raw → 输出 signal/score)最适合先补
- **日期过滤类回归无保护**: 历史上同类 bug 出过两次(池文件选取 `<=today`; 日期格式混用), 现靠共享函数 + 守卫告警兜底, 但守卫只在"样本≥10 且均值恰0"触发, 边界外仍可能漏
- **K线双格式兼容**: dict `{'data':...}` vs list 格式全库散落 10+ 处手写兼容(格式演进中), 新格式字段(volume_lots→volume 手→股换算)不一致风险高, 改动后应全链跑一次数据体检项 4/5 确认
- **`scripts/` 根目录研究脚本**大量硬编码路径/日期窗口、无注释约定, 属一次性产物, 不可作为回归基线

---

*Testing analysis: 2026-09-02*
