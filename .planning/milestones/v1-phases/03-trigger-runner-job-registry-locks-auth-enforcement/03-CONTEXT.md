# Phase 3: Trigger Runner, Job Registry & Locks + Auth Enforcement - Context

**Gathered:** 2026-09-03
**Status:** Ready for planning

## Phase Boundary

消费方经 HTTP 触发 gogo 现有四个脚本(pipeline/morning-check/backtest-weights/health-check)——POST 立即返回 202+job_id,未改动的脚本在后台运行,同 kind 永不重跑,事件循环永不冻结,无有效 API key 什么都起不了。

**In scope:** ACT-01 (POST /v1/actions/{kind} 四种触发,arg-list spawn 无 shell,只启动现有脚本不改其逻辑), ACT-02 (202+job_id 异步契约 + 持久化 job registry `logs/api/jobs/`,重启可恢复,GET /v1/jobs/{job_id} 轮询 pending→running→succeeded/failed 并暴露日志路径), ACT-03 (单飞锁:同 kind 重叠返回 409 带 running job_id,两个同 kind 运行永不并发写 data/), SEC-01 (X-API-Key 鉴权:constant-time 比较、header 传递、密钥永不上日志)。

**Not this phase:** 持仓/账本/候选读取 (STA-02, Phase 4), 数据分级政策 (SEC-02, Phase 4), 写侧原子化改造 (推迟 Phase 4 并绑入门槛, 见 D-07), 启动级鉴权加固 WR-01 (推迟 Phase 4, 见 D-12), job 取消 taskkill 树杀 (ACT-04 v2), 孤儿任务收养 (ACT-05 v2), 日志轮转/health/details (OPS-03, Phase 5), ETag/限流/CORS (v2/OOS)。

**Success criteria** (from ROADMAP.md, must all be TRUE):
1. Consumer POSTs /v1/actions/{kind} (pipeline / morning-check / backtest-weights / health-check) with a valid X-API-Key and receives 202 with a job_id immediately; GET /v1/jobs/{job_id} polls pending → running → succeeded/failed and exposes the run's log path. The run is the existing script launched unmodified (arg-list spawn, no shell).
2. Triggering a kind that is already running — from the API or any other entry point — returns 409 with the running job_id, and two runs of the same kind never write data/ concurrently.
3. During a full pipeline run, GET /health keeps answering with P95 < 50 ms — background execution never blocks the event loop.
4. Requests with a missing or wrong X-API-Key receive 401/403 (constant-time comparison) and never spawn a process; keys never appear in any log.
5. After the API process is killed mid-run and restarted, the durable job registry (logs/api/jobs/) reloads and the interrupted job is queryable in a terminal state — no job is silently lost.

## Implementation Decisions

### 单飞锁边界与并发者 (ACT-03)
- **D-01:** GUI 一键刷新加入同一把锁文件。刷新按钮启动前先取锁,锁被占(API job 运行中)时禁用刷新并提示运行中,不抢跑。改 `scripts/daily/gui_dashboard.py:88` 的 subprocess 前置逻辑,保持"直接 subprocess 跑 run_pipeline --fast"的既有形态,只加锁检查。—— 最小改动达成 SC2 "any other entry point" 意图。
- **D-02:** 停用「主升浪每日选股流水线」计划任务。`scripts/daily/auto_start.bat` 硬编码 `BASE=C:\Users\Davis\Desktop\主升浪`(仓库已迁 `gogo`),任务每天 15:30 cd 失败静默退出;仓库更名以来无人发现,证明用户不依赖它。停用需一条提权命令(Phase 1 已验证 Unregister-ScheduledTask 需提权),盘后靠手动面板/管线 + API 触发。—— **Reversibility:** reversible — 重新注册即可恢复,但按 Phase 1 D-07 惯例重装时勿复制 stale 路径。
- **D-03:** 锁作用域 = Win 本机锁。锁文件放 Win 本机 data/ 下(gitignore),防本机 API/GUI/计划任务并发。Mac 端 crontab(15:00 盘后 / 9:26 竞价)不加锁,保持两机串行约定——跨机锁经 git 同步存在天然竞态(两机可同时 pull 到无锁状态再抢锁),不可靠。锁实现细节(portalocker/msvcrt/lockfile 选型、stale 锁处理)留给 research 在真机验证。

### 写侧原子化 (ROADMAP 签字门)
- **D-04:** portfolio.json / trading_journal.json 的非原子写(`scripts/daily/trading_journal.py:46/58` 直接 `open('w')` 截断写)**推迟到 Phase 4**。依据:Phase 3 API 不读 portfolio(持仓读是 Phase 4 STA-02);Phase 2 读侧防御已保 3 个白名单文件 0×5xx;单飞锁已排除写写并发。本阶段不动实盘账本模块。
- **D-05:** 推迟执行的改造范围仅两个函数:save_portfolio + save_journal,照 `scripts/daily/zt_pool.py:75` 的 tmp+`os.replace` 原子写模式。不做 logs/ 全量扫描。
- **D-06:** 该写侧改造绑定为 Phase 4 STA-02 持仓读上线的前置任务——写入 Phase 4 计划,STA-02 上线前必须完成,避免遗漏。

### 触发形态与参数 (ACT-01)
- **D-07:** POST /v1/actions/pipeline 固定跑 `--fast`(仅涨停池+评分,跳过 Step5-9 含 Step9 sync_cloud 自动 push)。全量管线保持手动/GUI 入口。API 不改 git 历史、不触发 push。—— 与上传纪律(2026-08-31:仅代码+行情数据上传)解耦。
- **D-08:** POST /v1/actions/morning-check 固定跑 `--quick`(决策摘要+持仓处置+买入开关三块),job log 快速出结论,表1-4 细则仍用 GUI/手动全量看。竞价 60 秒 SLA 窗口下 API 触发输出快照型结论。
- **D-09:** Phase 3 触发接口零参数——四种 kind 固定命令:pipeline=`run_pipeline.py --fast`、morning-check=`morning_check.py --quick`、backtest-weights=`backtest_v4.py`(无参=权重重搜)、health-check=`data_health_check.py`(无参)。请求体不接受任何参数。Phase 4 SC4 引入 date 白名单参数(YYYY-MM-DD / YYYYMMDD)时再扩参数面。—— **Reversibility:** costly — 参数面从零到有是契约扩展,一旦有消费方按固定命令接入,新增可选参数需保持向后兼容。
- 注意:backtest-weights 触发的权重重搜会写 `data/scoring_config.json` v4 权重 + `data/weight_history.json`(定稿机制内已定稿的月度流程,API 只是换入口,流程本身不变)。

### 鉴权契约与加固范围 (SEC-01)
- **D-10:** 鉴权失败分工:缺失 X-API-Key 头 → 401 + `WWW-Authenticate` 头;带了但错误 → 403。两者均 constant-time 比较,响应体不泄露 token 值(沿 Phase 2 D-04 最小 JSON `{"detail": ...}` 风格,detail 不含 token/路径)。单 token 无用户枚举风险,403 精确表达"key 无效"。
- **D-11:** GET /health/ready 豁免鉴权,与 /health 同精神(HLT-01 纯度:探活/就绪类端点公开,仅 200/503 无数据泄露)。SEC-02 分级只针对数据端点。豁免清单 Phase 3 起为:/health、/health/ready、GET /v1/state/{name}(Phase 2 已公开);其余(全部 POST /v1/actions/*、GET /v1/jobs/*)一律 token。
- **D-12:** P2 遗留 WR-01 修复(非回环绑定只查 token 存在、回环默认运行自动生成 token 的启动意图检查缺陷)推迟到 Phase 4 与数据分级/暴露面硬化同批做(env 强制 token + 控制台警告)。Phase 3 只交付请求级 SEC-01,不动 Phase 1 启动序列(SEC-03 检查先于 token 生成的顺序是 Phase 1 载荷,保持 diff 可审计)。

### Claude's Discretion
- 锁文件机制选型、stale 锁(PID 探活确认持有者已死)处理策略——ROADMAP Research 段已列,research 真机验证后定。
- subprocess 治理方式(thread+Popen vs create_subprocess_exec, bpo-37381)、GBK/UTF-8 输出重定向矩阵、CREATE_NO_WINDOW——research 主题,按 SC3(P95<50ms 事件循环不阻塞)字面执行。
- job registry 落地格式(每 job 一文件 vs 聚合)与字段集、完成判定(退出码)、job log 路径约定(`logs/api/jobs/{job_id}/` 或同级)——ACT-02/SC1/SC5 字面内自定;退出码 0→succeeded 非 0→failed 是合理默认。
- job registry 文件保留策略(增长有界)——OPS-03 日志轮转属 Phase 5,但 registry 目录从 Phase 3 起就要有上限设计,至少按数量封顶。
- 401/403 错误体具体文案、X-API-Key 头名(与 hithink 的 `X-api-key` 区分,建议沿用 REQUIREMENTS.md 字面 `X-API-Key`)。

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Planning docs
- `.planning/ROADMAP.md` — Phase 3 goal、5 条成功标准(202+job_id/409 single-flight/P95<50ms/401-403/registry 重启恢复)、Research 段(research-phase 主题与签字门清单)、Phase 4 SC4(date 白名单参数,Phase 3 参数面据此留零)
- `.planning/REQUIREMENTS.md` — ACT-01/ACT-02/ACT-03/SEC-01 逐字契约;v2 排除(ACT-04 job 取消/ACT-05 孤儿收养);Out of Scope 表(Celery/Redis、PUT/PATCH、JWT/OAuth、CORS、GET 实时抓取)
- `.planning/PROJECT.md` — Key Decisions(数据分级鉴权 2026-09-02 确认、触发接口一律 token);Constraints(reuse 只读、不改管线模块逻辑)
- `.planning/phases/01-service-skeleton-health-liveness/01-CONTEXT.md` — Phase 1 锁定决策 D-01..D-10(api/ 包、config.py 路径、token 文件 D-03..D-06、端口 8000、/health 纯度、SEC-03 启动检查顺序)
- `.planning/phases/02-read-only-state-endpoints-defensive-read-layer/02-CONTEXT.md` — Phase 2 锁定决策 D-01..D-05(raw 透传契约、白名单映射、404/503 分工、防御读层);写侧原子化推迟决定(D-04..D-06)与其读侧防御的配合关系
- `.planning/STATE.md` — P2 REVIEW WR-01 遗留(Phase 4 修复)、P3 签字门清单、15:30 任务活性阻塞项

### Codebase maps
- `.planning/codebase/ARCHITECTURE.md` — 线程模型(单线程批处理、无常驻)、入口表(run_pipeline/morning_check/backtest_v4/健康检查)、导入约定(api/ 从 config.py 导入路径)、原子写参照(zt_pool.py:75)、反模式(每文件路径样板、吞错)
- `.planning/codebase/INTEGRATIONS.md` — 计划任务现状(install_scheduled_task.ps1 双触发+旧路径)、鉴权现状(无用户体系)、环境配置(密钥文件惯例)
- `.planning/codebase/CONCERNS.md` — 仓库疑似公开风险(鉴权分级背景)、P2 WR-01 细节、trading_journal 写路径脆弱点

### Existing code
- `scripts/daily/run_pipeline.py` §20 — `fast_mode = '--fast' in sys.argv` 手写参数解析;Step5-9 范围(API 触发 --fast 时被跳过的部分)
- `scripts/daily/morning_check.py` §426 — `quick = '--quick' in sys.argv`;竞价 SLA 上下文
- `scripts/daily/backtest_v4.py` §29 — main() 无参=权重重搜(写 scoring_config + weight_history)
- `scripts/daily/data_health_check.py` §102 — 八项体检入口(health-check kind 目标脚本)
- `scripts/daily/gui_dashboard.py` §88 — 一键刷新 subprocess(D-01 加锁改造点)
- `scripts/daily/trading_journal.py` §45-59 — save_portfolio/save_journal 非原子写(D-04..D-06 推迟改造对象)
- `scripts/daily/zt_pool.py` §72-78 — tmp+os.replace 原子写参照模式
- `scripts/daily/auto_start.bat` + `scripts/daily/install_scheduled_task.ps1` §8 — 旧路径 stale 示例(D-02 停用对象)
- `api/main.py` — 路由挂载点,触发/job 路由在此注册;main() 启动顺序勿破坏 SEC-03 检查
- `api/state.py` — Phase 2 读层模块,触发模块的风格参照(纯函数、显式参数、零 print)
- `api/boot.py` — Phase 1 纯函数 boot 模式参照
- `tests/conftest.py` — 零网络 autouse fixture;Phase 3 测试同轨(TestClient + 假脚本/fake subprocess)
- `.gitignore` — 锁文件与 job registry 落位处(logs/ 已 gitignore)

## Existing Code Insights

### Reusable Assets
- `api/main.py` 的 FastAPI app:触发路由 `POST /v1/actions/{kind}` 与 `GET /v1/jobs/{job_id}` 在此注册,鉴权依赖挂 app 级(豁免 /health、/health/ready、/v1/state)。
- Phase 1 的 token 读取链路(D-04:env `GOGO_API_TOKEN` 优先,`data/api_token.txt` 兜底)——SEC-01 鉴权直接复用,勿重造 token 加载。
- `scripts/daily/zt_pool.py` tmp+os.replace 原子写模式——job registry 写入应沿用(registry 本身是可变单点状态,需原子写防撕裂)。
- `tests/` 套件基础设施(pytest.ini pythonpath=.,conftest 网络封锁)——Phase 3 测试同轨;subprocess 触发用假脚本(tmp_path 内自写脚本)而非真管线,验证 arg-list spawn、409、鉴权拦截。

### Established Patterns
- 单进程纪律:API 是一常驻 uvicorn 进程;被触发的管线是短命子进程——subprocess 治理是 Phase 3 核心风险(全部 Windows 子进程风险集中隔离于此,ROADMAP 定位)。
- 数据引用纪律:API 不改脚本逻辑、不解析脚本输出做决策(job 状态只看退出码+日志文件落盘),禁止推测覆盖。
- 定稿机制:backtest-weights 触发会改评分参数(scoring_config v4 权重)——流程本身已定稿,API 仅换入口,不改流程。
- 跨端纪律:本机锁(D-03)只防 Win 端;Mac 端串行约定不变——锁文件绝不进 sync_cloud 白名单。
- Phase 2 最小 diff 惯例:api/main.py 每次仅加 import + include_router 两行式变更,启动序列与 SEC-03 顺序保持 diff 可审计——Phase 3 继续遵守。

### Integration Points
- `run_api.bat` / Task Scheduler 自启任务(Phase 1)会拉起常驻服务;job registry 在服务重启后必须可重载(SC5)。
- GUI 一键刷新(gui_dashboard.py:88)与 API 触发共用锁文件——GUI 改动需 Win/Mac 双端一致(Mac 端 GUI 同源码)。
- 停用 15:30 计划任务(D-02)是提权操作,计划中作为一条用户手动执行命令交付(如 `Unregister-ScheduledTask -TaskName "主升浪每日选股流水线" -Confirm:$false` 于提权 PowerShell)。
- `logs/api/jobs/` 目录:gitignored(logs/ 已在 .gitignore),无需新 gitignore 条目;registry 文件不进入 sync_cloud 白名单。
- Phase 4 衔接:STA-02 持仓读上线门槛包含写侧原子化(D-06);WR-01 修复与暴露面硬化同批(D-12);date 白名单参数扩展参数面(D-09)。

## Specific Ideas

无额外特定引用——四个灰区(锁边界/写侧原子化/触发形态/鉴权契约)已逐一与用户确认,其余按 ROADMAP 成功标准与需求字面落入 research/Claude 裁量。

## Deferred Ideas

- 写侧原子化改造(save_portfolio/save_journal tmp+os.replace)——Phase 4 前置任务,绑 STA-02 上线门槛(D-04..D-06)。
- P2 REVIEW WR-01 启动级鉴权加固(env 强制 token + 控制台警告)——Phase 4 与数据分级同批(D-12)。
- date 白名单参数(YYYY-MM-DD/YYYYMMDD)——Phase 4 SC4(D-09 参数面届时扩展)。
- job 取消(taskkill /F /T 树杀)与孤儿任务收养打磨——REQUIREMENTS.md v2(ACT-04/ACT-05),仅当真实出现失控运行时。
- 日志轮转 + 鉴权版 /health/details——Phase 5(OPS-03)。
- Mac 端 crontab 入锁/跨机锁——D-03 已否掉 git 同步方案;若未来需要,属独立决策。
- None — discussion stayed within phase scope (todo match count: 0)。

---

*Phase: 3-Trigger Runner, Job Registry & Locks + Auth Enforcement*
*Context gathered: 2026-09-03*
