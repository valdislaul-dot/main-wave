# Phase 3: Trigger Runner, Job Registry & Locks + Auth Enforcement - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-09-03
**Phase:** 3-Trigger Runner, Job Registry & Locks + Auth Enforcement
**Areas discussed:** 单飞锁边界与并发者, 写侧原子化, 触发形态与参数, 鉴权契约与加固范围

---

## 单飞锁边界与并发者

| Option | Description | Selected |
|--------|-------------|----------|
| GUI 加同锁文件 (推荐) | 刷新按钮启动前先取同一把锁文件:锁被占时禁用刷新并提示运行中,不抢跑。改动最小,达成 SC2 意图 | ✓ |
| GUI 改走 API 触发 | GUI 刷新改调 POST /v1/actions/pipeline,面板展示 job 状态。改动大且引入 GUI↔API 耦合 | |
| GUI 不动只记文档 | GUI 保持直接 subprocess 不加锁,仅在文档说明并发风险。SC2 "any other entry point" 字面不达 | |

**User's choice:** GUI 加同锁文件(推荐项)——锁被占禁用刷新+提示运行中,保持直接 subprocess 形态只加锁检查。

**Notes:** 现状依据 gui_dashboard.py:88 `subprocess.run([sys.executable, 'scripts/daily/run_pipeline.py', '--fast'])` 无锁。

| Option | Description | Selected |
|--------|-------------|----------|
| 停用任务 (推荐) | 本阶段停用「主升浪每日选股流水线」任务(需一条提权命令),盘后靠手动跑面板/管线 + API 触发 | ✓ |
| 修路径保留任务 | 修 auto_start.bat 与 install_scheduled_task.ps1 硬编码旧路径,保留 15:30 自动盘后 + 开机自启,并让它先取锁 | |
| 留到 Phase 5 | 本阶段只记入 Phase 5 ops polish 处置 | |

**User's choice:** 停用任务(推荐项)。

**Notes:** 核实依据:auto_start.bat `set BASE=C:\Users\Davis\Desktop\主升浪`(仓库已迁 gogo)、install_scheduled_task.ps1:8 ScriptPath 同旧路径、双触发(开机+15:30)。任务自仓库更名后每天 15:30 静默失败无人发现。

| Option | Description | Selected |
|--------|-------------|----------|
| 本机锁 (推荐) | 锁文件在 Win 本机 data/ 下(gitignore),防本机 API/GUI/计划任务并发。Mac 端 crontab 不加锁、保持两机串行约定 | ✓ |
| 跨机锁经 git | 锁文件进 sync_cloud 白名单经 git 同步,Mac 端 crontab 跑前检查。竞态窗口大不可靠 | |

**User's choice:** 本机锁(推荐项)。

**Notes:** 跨机锁被否:两机各自 git pull 存在天然竞态(可同时 pull 到无锁状态再抢锁)。

---

## 写侧原子化

| Option | Description | Selected |
|--------|-------------|----------|
| 推迟到 Phase 4 (推荐) | Phase 3 API 不读 portfolio(持仓读是 Phase 4 STA-02),单飞锁已排除写写并发;Phase 4 交付 STA-02 前同批改交易账本模块 | ✓ |
| 本阶段改 | 本阶段改 save_portfolio/save_journal 为 tmp+os.replace(照 zt_pool.py:75 模式) | |

**User's choice:** 推迟到 Phase 4(推荐项)。

**Notes:** 事实依据:trading_journal.py:46/58 直接 `open('w')` 截断写非原子;zt_pool.py:75 有 tmp+os.replace 参照;Phase 2 读侧防御已保 0×5xx。

| Option | Description | Selected |
|--------|-------------|----------|
| 仅两函数 (推荐) | 只改 save_portfolio + save_journal(Phase 4 将读的两个文件) | ✓ |
| 全 logs/ 扫描 | 扫 logs/ 下全部写路径统一原子化,面大需逐处验证 | |

**User's choice:** 仅两函数(推荐项)。

| Option | Description | Selected |
|--------|-------------|----------|
| 绑入门槛 (推荐) | 写侧改造作为 STA-02 持仓读上线的前置任务写入 Phase 4 计划 | ✓ |
| 不绑定 | 两件独立推进,读侧防御已能兜 0×5xx | |

**User's choice:** 绑入门槛(推荐项)。

---

## 触发形态与参数

| Option | Description | Selected |
|--------|-------------|----------|
| 固定 --fast (推荐) | API 触发的 pipeline 固定跑 --fast(跳过 Step5-9 含 sync_cloud 自动 push)。全量手动/GUI 照旧。快、安全、不改 git 历史 | ✓ |
| 固定全量 | API 触发即完整 9 步(含 Step9 git push 上云) | |
| 参数可选 | 请求体可选 {fast: true/false} 白名单布尔,缺省 fast | |

**User's choice:** 固定 --fast(推荐项)。—— ROADMAP 签字门 "trigger default --fast (skips Step9 git push)" 落定。

| Option | Description | Selected |
|--------|-------------|----------|
| 固定 --quick (推荐) | morning-check 固定 --quick(三块结论),job log 快速出结论;表1-4 细则仍用 GUI/手动全量看 | ✓ |
| 固定全量 | 输出完整表1-4细则进 job log | |
| 参数可选 | 请求体可选 {quick: true/false},缺省 quick | |

**User's choice:** 固定 --quick(推荐项)。

| Option | Description | Selected |
|--------|-------------|----------|
| 零参数固定 (推荐) | 四种 kind 固定命令零参数,最安全最简单;Phase 4 SC4 加 date 白名单时再扩参数面 | ✓ |
| 白名单布尔参数 | Phase 3 就支持请求体白名单布尔(fast/quick),灵活但扩大验证面与注入面 | |

**User's choice:** 零参数固定(推荐项)。—— backtest-weights=backtest_v4.py 无参、health-check=data_health_check.py 无参,自然落定。

---

## 鉴权契约与加固范围

| Option | Description | Selected |
|--------|-------------|----------|
| 401/403 分工 (推荐) | 缺 X-API-Key 头 → 401 + WWW-Authenticate;带了但错误 → 403。均 constant-time、不泄露 token | ✓ |
| 统一 401 | 缺失与错误一律 401,消费方只处理一种未授权响应 | |

**User's choice:** 401/403 分工(推荐项)。

| Option | Description | Selected |
|--------|-------------|----------|
| Phase 4 同批 (推荐) | WR-01 属启动意图检查加固 + 暴露面硬化,与 Phase 4 数据分级/暴露面审计同批做;Phase 3 只交付请求级 SEC-01 | ✓ |
| 本阶段一并修 | 本阶段修复(env 强制 token + 控制台警告) | |

**User's choice:** Phase 4 同批(推荐项)。—— STATE.md 阻塞项 "属 Phase 3/4 范围" 落定为 Phase 4。

| Option | Description | Selected |
|--------|-------------|----------|
| 公开 (推荐) | 与 /health 同精神:探活/就绪类端点公开,无数据泄露(仅 200/503) | ✓ |
| 需 token | 只有 /health 豁免,/health/ready 也要 token | |

**User's choice:** 公开(推荐项)。—— 豁免清单落定:/health、/health/ready、GET /v1/state/{name};其余一律 token。

---

## Claude's Discretion

- 锁文件机制选型(portalocker/msvcrt)、stale 锁 PID 探活处理——research 真机验证。
- subprocess 治理(thread+Popen vs create_subprocess_exec、GBK 输出矩阵、CREATE_NO_WINDOW)——research,按 SC3 P95<50ms 字面。
- job registry 落地格式/字段集/完成判定(退出码)/log 路径约定/保留策略上限。
- 401/403 错误体文案、header 名沿用 REQUIREMENTS.md 字面 `X-API-Key`。

## Deferred Ideas

- 写侧原子化(save_portfolio/save_journal)——Phase 4 前置任务,绑 STA-02 门槛。
- P2 WR-01 启动级鉴权加固——Phase 4 同批。
- date 白名单参数——Phase 4 SC4。
- job 取消/孤儿收养——REQUIREMENTS.md v2(ACT-04/ACT-05)。
- 日志轮转/health/details——Phase 5(OPS-03)。
- Mac 端 crontab 入锁/跨机锁——已否 git 同步方案,未来独立决策。
