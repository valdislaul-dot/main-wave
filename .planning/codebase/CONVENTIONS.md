# Coding Conventions

**Analysis Date:** 2026-09-02

## 总览

本仓库是 Python 量化交易流水线(主升浪 V4)。全部代码注释/文档字符串/控制台输出使用简体中文; 代码标识符、文件路径、技术名词(JSON 字段名、API 名称、因子名)保持英文。生产代码集中在 `scripts/daily/`, `scripts/` 根目录是历史研究/回测脚本, `backup/legacy_scripts/` 是已归档的 v3 时代脚本(运行报错提示 v3 已移除)。没有任何格式化/静态检查工具配置(无 pyproject.toml/.ruff.toml/.flake8/pre-commit), 风格靠手写约定维持一致。

## Naming Patterns

**Files:**
- snake_case, 动词或领域词驱动: `zt_pool.py` / `sell_engine.py` / `morning_check.py` / `capture_market_state.py` / `data_health_check.py` / `review_recommendations.py` / `backtest_v4.py` / `update_data.py`
- 目录: `scripts/daily/` = 生产模块; `scripts/` 根 = 一次性研究/回测; `backup/legacy_scripts/` = 归档

**Functions:**
- 动词开头 snake_case: `update_zt_pool()` / `fetch_zt_pool_raw()` / `load_state()` / `save_state()` / `compute_score()` / `classify_volume()` / `score_v4()` / `snapshot_daily_close()` (`scripts/daily/zt_pool.py`, `scripts/daily/scoring.py`, `scripts/daily/update_data.py`)
- 私有辅助函数用单下划线前缀: `_save_raw()` / `_load_klines()` / `_fmt_ts()` / `_parse_high_days()` / `_empty_state()` / `_corporate_action_suspect()` (`scripts/daily/zt_pool.py:25`, `scripts/daily/update_data.py:127`)
- 返回 "没有数据" 的约定: 失败返回 `None` / `[]` / `(None, None)`, 不抛异常(见 Error Handling)

**Variables:**
- 局部变量 snake_case, 短循环内允许单字母(`i`, `k`, `s`, `v`), 紧凑作用域内允许嵌套三元链和一行表达式(如 `scripts/daily/scoring.py:519-520` 的 seal_b 分段)
- 日期变量命名有口径区分: `date_str`='YYYY-MM-DD' 字符串, `today`, `date_yyyymmdd`/`ymd`='YYYYMMDD', `date_fmt` 由 ymd 格式化而来(`scripts/daily/capture_market_state.py:31-32`)。两种格式混用时必须在转换处立刻落成新变量, 禁止用同名变量覆盖——2026-09-01 赚钱效应恒 0 事故即日期过滤写错格式所致

**Types:**
- JSON 持久化字段: snake_case(`limit_days`/`break_times`/`first_seal`/`last_lu_date`/`days_in_pool`), 与数据源字段一致用 `limit_up_suc_rate`→本地 `seal_rate` 这类映射在采集处完成(`scripts/daily/zt_pool.py:310-329`)
- 语义上的 "类型" 用返回结构注释描述而非 class/dataclass: 模块头 docstring 写明返回 dict 结构(见 `scripts/daily/auction_pool.py:57-62` 的 fetch_quotes 返回注释)

## Code Style

**Formatting:**
- 无格式化工具。实际风格: 4 空格缩进; 单引号为主(偶见双引号, 如 `scripts/screen_candidates_v3.py` 系东财时代旧代码); 行长不设限, 长 f-string 与多行嵌套常用
- **一行多 import**: `import json, os, sys` 是多数字模块的固定开头(非 PEP8 但全库一致): `scripts/daily/zt_pool.py:10`, `scripts/daily/run_pipeline.py:10`, `scripts/daily/scoring.py:5`
- 模块级常量紧跟 import, 由 `__file__` 推导路径: `BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))` 然后 `STATE_PATH = os.path.join(BASE, 'data', 'zt_pool_state.json')`(`scripts/daily/zt_pool.py:17-22`)。`scripts/daily/config.py` 提供了集中路径常量但多数模块自行推导(自包含优先)
- 中英文之间无空格, 中文注释后不加句号(紧凑风格), 数字阈值注释标注来源与日期

**Linting:**
- 未使用任何 lint 工具。既有代码含大量 PEP8 违反(bare except、一行多 import、超长行), 新增代码应跟随文件既有风格而不是引入黑/ruff 规范化

**Console output:**
- 控制台输出必须防 Windows GBK 崩溃: `main()` 首行 `sys.stdout.reconfigure(encoding='utf-8')`(`scripts/daily/data_health_check.py:103`, `scripts/daily/morning_check.py:444`, `scripts/daily/capture_market_state.py:23`); 旧文件用 `io.TextIOWrapper(... encoding='utf-8', errors='replace')` 变体(`scripts/daily/screen_candidates.py:6-8`)。纯逻辑模块(如 `scoring.py` 的计算函数)不 print

## Import Organization

**Order:**
1. 标准库 `import json, os, sys` / `from datetime import datetime, timedelta`
2. 路径引导 + 项目内模块: `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` 之后 `from scoring import ...`(`scripts/daily/zt_pool.py:14-15`, `scripts/daily/morning_check.py:119`)
3. **循环依赖回避**: 相互引用的模块在函数内部延迟 import, 而非模块顶部。例: `update_data.py` 顶部 import `zt_pool`, 而 `zt_pool` 只在模块内 import `scoring`; `run_pipeline.py` 全部步骤模块都在 main() 内 `from X import main`(`scripts/daily/run_pipeline.py:58-61`)

**Path Aliases:**
- 无别名机制。脚本间通过相对 `__file__` 的 `sys.path.insert` 互相 import, 因为脚本可能从任意 cwd 被调用(streamlit / 计划任务 / 手动)
- `BASE`(项目根) 是唯一共享锚点, 每个文件各自计算, 不依赖 `scripts/daily/config.py`(仅有少数文件用它, 如 `scripts/daily/backup_for_mac.py`)

## Error Handling

**Patterns:**
- **网络层返回空值 + 调用方级联兜底(主源/备源/兜底)**: 每个 fetch 函数 try/except 返回 `None`/`[]` 并 print 失败; 调用方依次尝试下一数据源。K线三级源: 腾讯 fqkline → Tushare → 新浪(`scripts/daily/update_data.py:153-172`); 涨停池: 同花顺 → 官方 API(`scripts/daily/zt_pool.py:353-375`); 行情: 腾讯 + 新浪双源
- **流水线 fail-open**: 每个 Step 包 `try/except Exception` 打印 `[Warning] ...` 后继续, 单步失败不中断整体(`scripts/daily/run_pipeline.py:57-200`)
- **bare except 用于兜底路径**: `except: pass` 出现在可选增强、编码回退、日志写入等非关键路径(全库 15+ 处, 如 `scripts/daily/zt_pool.py:188,198`, `scripts/daily/run_pipeline.py:155`)。约定: 仅在次要/兜底代码使用, 主逻辑必须捕获具体异常; `scoring.py` 的评分计算内 `except:` 后走 fallback 分值是设计内行为(`scripts/daily/scoring.py:391-392, 413-414`)
- **文件读取编码回退**: 历史文件 utf-8/gbk 两态, 用 `for enc in ('utf-8', 'gbk')` try 循环或共用 helper `load_json(p, encodings=...)`(`scripts/daily/data_health_check.py:26-33`); 写入一律 `encoding='utf-8', ensure_ascii=False`
- **JSON 原子写**: 先写 `.tmp` 再 `os.replace()`(`scripts/daily/zt_pool.py:75-78`), 防写一半崩溃损坏 state 文件
- **防御性解析**: `float(p.get('x', 0) or 0)`、`int(x or 0)`、时间串统一 `str(t).replace(':', '')` 后取位——全库一致(`scripts/daily/zt_pool.py:311-328`, `scripts/daily/scoring.py:386-389`)
- **日志/告警函数返回计数**: `data_health_check.main()` 返回警告数, `__main__` 里 `sys.exit(1 if main() else 0)` 使计划任务可感知失败(`scripts/daily/data_health_check.py:321-322`)

**Data integrity discipline(数据校验, 本库最核心的工程约定):**
- **三方确认**: 采集入库时与第二个独立源交叉比对, 偏差超阈值当场告警。收盘价东财 vs 腾讯 >2% 疑似炸板/滞后; 昨收腾讯 vs K线 >1% 疑似除权(`scripts/daily/zt_pool.py:499-510`); 持仓行情腾讯 vs 新浪偏差 >0.5% 逐字段列告警(`scripts/daily/morning_check.py:75-90`)
- **除权边界守卫**: qfq 首条新行 open 与存量末行 close 偏离超涨跌幅上限 → 弃用该批 qfq 行(`scripts/daily/update_data.py:127-134`)
- **结果合理性守卫**: 计算完怀疑性检查——赚钱效应样本≥10 且均值恰 0 → ⚠⚠ 告警并写 `state.warning`(`scripts/daily/capture_market_state.py:87-93`); 竞价快照 open=0 占比>30% 拒绝/告警(`scripts/daily/data_health_check.py:240-245`, 采集侧 9:25 前拒绝写入见 `scripts/daily/auction_pool.py`)
- **共享函数防复制回归**: 昨日池文件选取必须用 `zt_pool.get_prev_pool_file(ref_date)` 单点实现, 新模块禁止手写日期过滤(2026-09-01 事故教训已写入 `CLAUDE.md` 与函数 docstring `scripts/daily/zt_pool.py:56-69`); K线文件查找统一 `update_data.find_kline_path()`(`scripts/daily/data_health_check.py:23`)

## Logging

**Framework:** 无 logging 模块, 全库 print。运行型脚本自解释式分节输出。

**Patterns:**
- 模块前缀 + 消息: `[ZT Pool]`, `[K线更新]`, `[MarketState]`, `[Auction]`, `[Screen]`, `[DailyClose]`(如 `scripts/daily/zt_pool.py:332,349`)
- 流水线分节标题: `print('\n[Step 2/7] 更新K线数据(涨停池标的)...')`(`scripts/daily/run_pipeline.py:112`)
- 严重度词: `[Warning]`/`[警告]`(可继续) vs `[Error]`(该步失败) vs `[ERROR]`(单只失败); 数据问题用 emoji 前缀 ⚠ / ⚠⚠ / ✅ / ❌(`scripts/daily/data_health_check.py:135-137`)
- 落库式结果日志(供追溯/面板读取): `logs/data_quality_log.json`(保留 90 天, `scripts/daily/data_health_check.py:78-99`)、体检警告回写候选文件 `data_quality` 字段供次日竞价面板显示(`scripts/daily/data_health_check.py:297-311`)

## Comments

**When to Comment:**
- 凡是带经验阈值/回测来源的数字旁必有中文注释说明出处与依据: 如炸板扣分 tiers 旁注明 "基于1,008样本实测"(`scripts/daily/scoring.py:108-110`)、卖点引擎 docstring 注明 "数据支撑: A的77笔..."(`scripts/daily/sell_engine.py:34-35`)
- **Bug 修复必须内联留档**: 修复处注释标注日期+根因+修复内容, 如 `2026-08-31修复A/B`(`scripts/daily/zt_pool.py:432-439`), 多份修复在同函数时用字母区分
- **弃用决策注释**: 数据源切换、因子移除处写明弃用原因与替代(`scripts/daily/zt_pool.py:256-264` 同花顺切换注释; `scripts/daily/scoring.py:296-307` v2/v3 移除说明)

**JSDoc/TSDoc:**
- 无。Python docstring 惯例: 每个文件模块头 docstring = 用途 + 数据流/时序 + 用法示例 + 涉及文件; 复杂函数 docstring = 输入输出结构 + 逻辑说明 + 兜底行为。多行 docstring 顶部和底部无引号缩进约定问题(全库一致、均顶格对齐)

## Function Design

**Size:** 函数体长(50-200 行常见), 流水线式长 main() 普遍(如 `scripts/daily/update_data.py` 的 `main()`, `scripts/daily/data_health_check.py` 的 `main()` 内含 8 个校验块)。通过分节注释 `# ── N. 校验项名 ──` 组织, 不用抽小函数。**新增代码建议**: 跟随文件现有风格即可, 若写新模块可适度拆分, 但必须保留分节注释标记

**Parameters:** 全部位置参数 + 默认值; 可选配置参数末位 `config=None` 并在函数内 `if config is None: config = load_config()`(配置驱动惯例, `scripts/daily/scoring.py:301-307`, `scripts/daily/sell_engine.py:37-38`)

**Return Values:**
- 成功 `(score, details)`, 失败 `(None, None)` 成对返回(`scripts/daily/scoring.py:296-301` 的 `compute_score`/`score_v4` 约定)
- 状态类函数返回 None 表示跳过(快照不存在等), 或 bool
- 自检函数返回告警计数/布尔, 由 `__main__` 转 exit code

## Module Design

**Exports:** 无 `__init__.py`, 目录即命名空间。模块既是库(被 morning_check/gui 跨模块 import)又是 CLI(`if __name__ == '__main__'` 手动 `sys.argv` 分发, 无 argparse, 见 `scripts/daily/zt_pool.py:666-679` 的 `--update/--summary/--activity`, `scripts/daily/data_health_check.py:104-108` 的 `--date`)

**Barrel Files:** 无。

**Config-driven thresholds(配置驱动):**
- 业务阈值集中在 `data/scoring_config.json`(评分配置 v4 段 + sell 段), 代码内嵌 `_default_sell_config()`/`default_scoring_config()` 作为文件缺失兜底(`scripts/daily/sell_engine.py:83-105`, `scripts/daily/scoring.py:81-137`)
- 回测验证过的参数必须可配置, 禁止硬编码(来源未明确的参数保持可配置——`CLAUDE.md` 参数溯源纪律)
- 上传口径: 代码+行情数据提交, `logs/` 与密钥(`data/*token*.txt`)gitignore 不上传

**Top-level 副作用:** 允许模块顶部执行 `os.makedirs(..., exist_ok=True)` 和 `sys.path.insert`; 不做运行时导入检查之外的初始化

**请求限速:** 外呼 API 用模块级 Session + 最小间隔节流 + 随机抖动: `ZT_SESSION`/`_zt_get()` 保证两次请求 ≥1s(`scripts/daily/zt_pool.py:237-253`); `EM_SESSION`/`em_get()` 同模式(`scripts/daily/screen_candidates.py:22-33`)。腾讯批量行情按 50 只一批(`scripts/daily/auction_pool.py:66`, `scripts/daily/data_health_check.py:55`), 全程 UA header `'Mozilla/5.0'` 或 Mac 系 UA

**GUI(streamlit) 模块:** 脚本式布局(模块级顺序执行): `st.set_page_config` → 顶部 CSS → `@st.cache_data(ttl=300)` 包数据读取 → `st.columns` 布局; 一键刷新用 `subprocess.run([sys.executable, 'scripts/daily/run_pipeline.py', '--fast'])`(`scripts/daily/gui_dashboard.py:10-90`)

## 历史/研究脚本注意

- `scripts/` 根目录大量 `*_v2.py`/`*_v3.py`/`final_*.py`/`worst_trades*.py` 等一次性研究脚本: 命名带版本后缀递增、硬编码日期窗口与数据路径(如 `scripts/verify_review.py` 引用 `C:\Users\Davis\Desktop\主升浪\...` 旧路径), 不属生产代码, 勿以其风格为准
- 生产风格判断依据: 位于 `scripts/daily/` 且被 `run_pipeline.py`/`morning_check.py`/`gui_dashboard.py` 引用, 或与它们共享 `BASE` 推导模式与 `[模块名]` 前缀 print

---

*Convention analysis: 2026-09-02*
