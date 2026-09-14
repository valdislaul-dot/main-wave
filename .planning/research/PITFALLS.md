# Pitfalls Research

**Domain:** 给既有脚本式 A股打板交易系统(gogo, Python/全JSON文件/双机同步)新增常驻 FastAPI HTTP API 服务层（健康检查 + 只读状态接口 + 操作触发接口）
**Researched:** 2026-09-02
**Confidence:** MEDIUM（文件级）；代码实证类坑 HIGH，外部语义类坑 MEDIUM（多源交叉，见 Sources）

**阶段命名约定**（roadmap 尚未编号，以下阶段名与 PROJECT.md Active 需求对应）:
- **P1 服务骨架与健康检查**（FastAPI/uvicorn 服务、/health、日志、启动方式）
- **P2 只读状态接口**（读 data/ logs/ JSON 的 GET 端点、缓存、新鲜度）
- **P3 操作触发接口**（subprocess 任务运行器、锁、作业注册表）
- **P4 鉴权与暴露加固**（token、CORS、绑定边界、数据分级）

---

## Critical Pitfalls

### Pitfall 1: API 读到"写了一半"的 JSON —— 绝大多数状态文件写入非原子

**What goes wrong:**
API 的 GET 端点读取 JSON 时恰逢写入进程（管线/记账/竞价采集）正在写同一文件 → 读到 0 字节、截断或半旧半新内容 → JSONDecodeError / 空数据 / 面板展示不完整状态。本项目只读接口的需求正是"复用现有 JSON"，而现有写入几乎全部非原子。

**Why it happens:**
代码实证（HIGH 置信）: 全仓库仅 `data/zt_pool_state.json`（zt_pool.py:77-78）与 `data/auction/YYYY-MM-DD.json`（auction_pool.py:341-342）走 tmp+`os.replace` 原子写；**其余全是 `open(f,'w')` 直写**：`logs/portfolio.json`、`logs/trading_journal.json`（trading_journal.py:47,59）、`data/market_state.json`（capture_market_state.py:115）、`data/auction_state.json`（auction_pool.py:404）、`logs/candidates_YYYY-MM-DD.json`（screen_candidates.py:234，全池明细 indent=2 数 MB，写入窗口最大）、`data/zt_pool_exit_log.json`（zt_pool.py:146）。历史批处理是"单进程串行、写完才被读"约定，直写无感；常驻 API 进程打破了该隐含前提——每次轮询都可能撞上写入窗口。

**How to avoid:**
1. **读端防御（P2 必做，零侵入）**：唯一 `read_json(path)` helper —— 一次性读完立即 close（禁止流式/分块读这些状态 JSON）、捕获 JSONDecodeError 短重试 1-2 次（20-100ms）、仍失败则回退进程内 TTL 缓存的上一成功版本并附 `stale: true` 标记；绝对不要把解码失败变成裸 500。
2. **写端原子化（P2/P3 决策项）**：把上述 6 处写路径收敛到一个 `atomic_write_json` helper（tmp + os.replace + 错误重试）。注意：这会触碰现有管线模块 → **违反 PROJECT.md "不修改现有管线模块逻辑"约束**，需在 P2 规划时提请用户确认并修订约束条款，且按定稿机制不得顺手改逻辑。
3. 复用 gui_cloud.py 的既有先例：`_load_json` 捕获异常返回 None + `@st.cache_data(ttl=120)` —— API 应做同型但更严谨的版本（带 retry 与 stale 标记）。

**Warning signs:**
- API 日志偶发 `JSONDecodeError: Expecting value` / `Unterminated string starting at`
- 同一 GET 请求有时 200 有时 500、内容时全时空
- 管线运行中（15:30-16:00 附近）错误频率明显高于其他时段

**Phase to address:**
P2 只读状态接口（读端 helper 是 P2 验收门）；写端原子化作为 P3 前用户确认项。

---

### Pitfall 2: Windows 文件共享语义 —— 读进程打开目标文件时，写端 `os.replace` 抛 PermissionError（且被现有 except:pass 文化吞掉）

**What goes wrong:**
即使 Pitfall 1 的原子化完成，Windows 上 `os.replace`（MoveFileExW + MOVEFILE_REPLACE_EXISTING）在目标文件被**任何**进程持有打开句柄时直接失败 —— 出错的是**写端**不是读端，报 WinError 5/32（均映射 errno 13，无法区分）。CPython 默认打开文件不带 FILE_SHARE_DELETE（bpo-46003），所以"读进程只是 json.load 一下"也能挡掉写端的替换。反直觉点：读端瞬间关闭时窗口很小，但杀软扫描、同步盘（若 Desktop 挂 OneDrive/iCloud）、API 流式响应都会拉宽窗口；本项目"单步 try/except + 打印 [Warning] 继续"（119 处宽 except，run_pipeline.py:155,170 甚至 `except: pass`）文化下，**写失败会静默消失** —— 正是 2026-09-01 赚钱效应恒 0 连挂 7 天无人发现的那类事故形态。

**Why it happens:**
Windows 与 POSIX 的 rename 语义差异：POSIX 上打开旧 inode 的读进程不受影响；Windows 不允许替换被打开的现存文件。开发者按 Linux 经验写 os.replace 后只在 Mac 上测试（本项目 Win/Mac 双端），Win 端上线才炸。

**How to avoid:**
- 原子写 helper 必须捕获 PermissionError 做有界重试（4 次、20-100ms 抖动），仍失败则**带上下文打日志并标记失败**（不许吞）；写入结果进状态字段，供 /health 或 status 展示。
- API 读端纪律：小 JSON 一次性 read+close；不用 FileResponse/分块流式服务这些文件。
- Windows 与 Mac 双端都必须冒烟覆盖"写文件时另一端在读"的并发场景（P3 并发测试项）。
- 不依赖 `os.rename` 绕过——同样的底层限制（社区实证）。

**Warning signs:**
- 管线输出/日志出现 `PermissionError: [WinError 5/32]` 但整体 rc==0
- 文件 mtime 未更新、无任何报错 → 怀疑被吞
- 加了 API 后首次出现（此前单进程无并发）

**Phase to address:**
P3（写端 helper 落地时的硬性要求）；P2 读端纪律同步生效。

---

### Pitfall 3: 并发管线调用无锁 —— 定时任务 + GUI 刷新 + API 触发三方抢跑

**What goes wrong:**
ARCHITECTURE.md 明确："无跨进程锁，并发运行两个流水线会竞争读写同一 state JSON，日常约定串行执行"。API 触发接口上线即打破此约定：
1. 本机已有 Windows 计划任务基建（install_scheduled_task.ps1：每日 15:30 + 开机自动跑 auto_start.bat 执行 run_pipeline）——15:30 定时全量 + 用户此时点 API 触发 = 双管线并发写同一批非原子 JSON（交错写坏文件、last-write-wins 状态漂移）；
2. 双倍命中外部限速数据源（同花顺/腾讯均有 ≥1s 间隔限速与封禁史）→ 可能触发 IP 风控，拖慢/弄脏当天数据（竞价 9:15-9:35 窗口 60s SLA 最脆弱）；
3. Step9 两个 `sync_cloud.sync()` 同时 git commit → `.git/index.lock` 冲突，自动推送失败（仓库已 603MB pack，双机共用 origin，冲突代价高）；
4. 竞价双采：两个触发同时判"快照 <3 分钟"过期 → 各自 capture_auction 双写 auction_state（非原子）→ 快照与 state 不一致，次日面板数据打架。

**Why it happens:**
"触发 = 起一个 python 进程"看起来天然串行；单用户系统没有多实例心智，直到 API 让触发变成"一键可重复、可被探活/脚本误触发"。

**How to avoid:**
- **跨进程运行锁是 P3 验收门**：锁文件含 PID + 启动时间；acquire 失败 → 409 + 返回当前运行者（pid/started/args）。
- 锁的 stale 处理（Windows）：PID 存活探测用 `tasklist /FI "PID eq n"`（os.kill(pid,0) 在 Windows 语义不可靠），再叠加锁 mtime 超时兜底（全量 >90min、--fast >20min 视为死锁可抢占）。
- **所有触发路径共用同一把锁**：API 触发、GUI 一键刷新（gui_dashboard.py:88 现在无锁）、定时任务入口都要先 acquire —— 定时任务脚本改动属于现有管线模块，需用户确认。
- 触发默认参数化：全量 vs `--fast`（跳过 Step5-9，含 sync_cloud git 推送）——API 触发建议默认 --fast 或允许禁 Step9，消除 git 并发面。
- 时间窗护栏：利用现有 `scripts/daily/trading_calendar.py`，非交易时段、竞价窗口外（9:15-9:35 外）拒绝竞价类触发，直接 409 而非静默空采（auction_pool 已有 9:25 前 open=0 拒写守卫，但 API 层应前置拒绝并给出解释）。

**Warning signs:**
- pipeline.log 同一秒两份启动记录；`.git/index.lock` 出现
- auction_state 的 captured 时间戳在同一天出现两次交错
- 外部数据源开始返回风控/空数据，采集耗时翻倍

**Phase to address:**
P3 操作触发接口。

---

### Pitfall 4: 同步 subprocess 阻塞 asyncio 事件循环（含 BackgroundTasks 误用）

**What goes wrong:**
在 `async def` 端点里直接 `subprocess.run(...)`（或任何同步阻塞调用）→ **整个事件循环冻结**：/health、所有 GET 全部 pending，负载均衡把服务摘除；把阻塞代码包进 `BackgroundTasks` 或 `asyncio.create_task` **并不解决**——只要任务函数是 async def 且内部是同步阻塞调用，loop 照堵。本项目要触发的全是长任务：run_pipeline 全量是数百个限速 HTTP 的 10-30 分钟级作业（gui_dashboard 对 --fast 都给了 180s timeout），回测类更久——"请求内等待完成"是必然踩坑模式。

**Why it happens:**
FastAPI 的 async 端点默认单线程事件循环；"把耗时活丢给后台就完事"是社区最高频误用（BackgroundTasks 文档外最常见的坑：async def 后台任务里的同步调用依然堵 loop）。另外 `await proc.wait()` 但不读 stdout/stderr → 子进程写满 64KB 管道缓冲后死锁挂起。

**How to avoid:**
- 触发接口模式定为：**202 Accepted + job_id + GET /jobs/{job_id} 轮询**；后台执行用 `asyncio.create_subprocess_exec(sys.executable, [...])` + `await proc.communicate()`（必须 consume 管道，或重定向 DEVNULL）；cwd=BASE（复用 gui_dashboard.py:88 的 `cwd=BASE` 正确姿势，杜绝相对路径依赖）。
- 同步后台函数写成**普通 `def`**（FastAPI/Starlette 会丢线程池跑）而不是 async def 里塞同步代码。
- 若个别端点坚持同步返回：`run_in_executor` + 明确超时，但必须处理"客户端超时重试 → 重复触发"的幂等问题（见 Pitfall 7），不推荐为主路径。
- 用 `sys.executable` 直启 python，不要 `cmd /c`/shell=True（既防注入也免进程树问题）。

**Warning signs:**
- 触发管线后 /health 也卡住不响应（全站冻结 10s+）
- uvicorn access log 显示单个请求耗时数百秒
- 子进程 stdout 大输出时任务永久挂起（管道死锁）

**Phase to address:**
P3 操作触发接口（runner 设计即验收项）。

---

### Pitfall 5: 鉴权边界错配 —— 无鉴权绑 0.0.0.0 / CORS 通配 + credentials / token 落日志落仓库

**What goes wrong:**
1. **隐私红线被绕过**：2026-08-31 起持仓/账目/日志刻意不上云（gitignore + sync_cloud 白名单），PROJECT.md 却写"只读接口可放开"——若按"读写分级"而非"数据敏感分级"，portfolio.json/trading_journal.json/candidates（本地机器独有、比 GitHub 上任何东西都敏感的交易与持仓数据）将无鉴权暴露到 LAN。且 CONCERNS.md 实测远程仓库疑似**公开**（匿名 200），git 历史仍含账目——机器上的 API 是攻击者进入这套系统的第二入口。
2. **绑定与启动语义**：`--host 0.0.0.0` 而无 token = 整个 LAN 可读持仓；绑定 0.0.0.0 还会让 CORS/Host 白名单被绕过（社区实证 janhq/jan #8453：0.0.0.0 绑定静默丢弃 Trusted Hosts/CORS 限制）。
3. **CORS 通配 + 凭证**：浏览器语义里 Authorization 头 = credentials；`allow_origins=["*"]` 只对无凭证请求安全，与 Bearer token 组合时浏览器拒绝/或需 allow_credentials=True 而 `*`+credentials=True 是 FastAPI 官方文档明令禁止的组合。若消费方只是负载均衡探活 + curl/脚本（无 Origin 头），**根本不需要 CORS**——顺手加通配 CORS 纯属引入漏洞面。
4. **token 卫生**：token 进 URL query（被 access log/代理日志记录）、打印 Authorization 头、把 token 文件加进 sync_cloud 白名单或 `git add .`（仓库疑似公开 + data/ 下已有 tushare_token.txt/hithink_token.txt 明文先例）——任一发生都是实害。

**Why it happens:**
"内网/本地服务不用太认真"心态 + Streamlit 面板无鉴权的既有先例（gui_dashboard 无鉴权但绑 localhost、gui_cloud 无鉴权但只读上云快照——两者都没有把"最敏感数据 + 可触发操作"组合暴露）→ 惯性照抄就出问题。

**How to avoid:**
- **数据分级鉴权（P4 核心决策）**：行情/温度/市场状态类（上云快照同款数据）→ 可放开；**持仓/账本/候选/触发类 → 一律 token**，不论读写。这与 PROJECT.md "写入鉴权、只读放开"需求冲突 → 规划时按"只放行情类只读"修订需求措辞。
- **默认绑 127.0.0.1**；确需 LAN（负载均衡远程探活）时 fail-closed：配置了非 loopback 绑定而无 token → 启动即拒绝（不是警告）。
- token 只走 `Authorization: Bearer` 头；校验用恒时比较；任何日志不打印请求头。
- token 存环境变量或 data/ 下 gitignored 文件，**双保险验证**：确认不在 git 历史、不在 sync_cloud.py 白名单。
- CORS：默认不加中间件；加了就显式 origin 列表（127.0.0.1:8501 Streamlit 等），永不 `["*"]`+credentials；无浏览器消费方时删掉。
- 触发端点参数（date/code）严格白名单校验（`^\d{4}-\d{2}-\d{2}$` / `^\d{6}$`）后以**参数列表**传 subprocess，永不 shell=True——run_pipeline_for_date 会 monkey-patch datetime 按传入日期重跑，任意日期串能触发历史重写。

**Warning signs:**
- 启动命令里 host=0.0.0.0 且未配 token
- 从另一台机器 curl 任意端点 200 无认证
- 日志/URL 中出现 token 明文；`git ls-files | grep token` 有结果
- 浏览器直接访问 API 返回了 CORS 通配头

**Phase to address:**
P1 起绑定即默认 loopback、token 机制 P1 就位（安全后置是最大返工源）；完整策略 P4 鉴权加固。

---

### Pitfall 6: 只读/探活接口顺手触发实时采集 —— 打爆外部数据源，竞价窗口 SLA 事故

**What goes wrong:**
"状态端点要有新鲜数据"的诱惑：GET 端点里复用 morning_check 现成的腾讯实时行情/竞价采集函数（代码就在同仓库，import 即可），负载均衡每 2-10s 轮询一次 → 一上午凭空多出几百次对外请求，撞上数据源限速（每模块 ≥1s 间隔 + 抖动是既有纪律）与封禁；9:15-9:35 是 60 秒 SLA 决胜窗口（快照 <3 分钟复用是硬规则），任何多余采集延迟都直接威胁当日买卖决策。数据源无 contract（腾讯/同花顺非官方端点），封了只能等——当日不可恢复。

**Why it happens:**
脚本系统的函数都是"即调即抓"；移植到 API 时开发者保留"读时抓"心智，没意识到调用方从"人每天几次"变成"机器每秒一次"。

**How to avoid:**
- **硬规则：所有 GET 端点只读文件系统数据（含进程内缓存），永不发起对外网络调用**。需要新数据 = 走显式触发接口（带 Pitfall 3 的锁 + 时间窗校验）。
- 新鲜度语义外置：响应带 `updated_at`（来源文件 mtime/快照 captured 时间戳，auction_state/快照里已有）；过期时返回 409/503 + stale 标记，**由消费方决定是否触发**，而不是 API 代抓——这是 morning_check "快照 <3 分钟复用否则重采"纪律的 API 版。
- 探活端点（LB 每 2-10s 打）只回内存态 status+uptime，不读盘不解析大 JSON（见 Performance Traps）。

**Warning signs:**
- 数据源开始返回风控/空数据/HTTP 403，时段恰与某 GET 端点被轮询重合
- uvicorn access log 显示外部抓取函数调用次数远高于管线自身频率
- auction 采集耗时从秒级恶化到分钟级

**Phase to address:**
P2 只读状态接口（验收项：GET 全链路零外呼）；P3 触发接口承接刷新诉求。

---

### Pitfall 7: spawn-and-forget + kill 语义混乱 —— 孤儿管线、僵尸子进程、重复触发

**What goes wrong:**
1. **断连/超时后任务仍在跑**：客户端 5s 超时断开，run_pipeline 继续跑 20 分钟——本身可接受，但无 job 记录时不可知、不可查、不可控。
2. **服务被杀 = 孤儿管线**：uvicorn 重启/被杀时 in-flight 子进程不被自动终止，孤儿管线继续写 JSON、继续 Step9 git push——用户以为"API 挂了任务就没了"，实际管线还在动数据。
3. **kill 只杀直接子进程**：Windows 上 `proc.kill()` = TerminateProcess，仅杀直接子进程；经 cmd/venv 启动器间接产生的孙进程全部存活（社区实证；需 taskkill /T /F 杀树）。
4. **重复触发无幂等**：LB/脚本对慢请求重试 → 同一管线触发两次（叠加 Pitfall 3 的并发问题）。

**Why it happens:**
"起个进程而已"的轻量心智；asyncio 子进程生命周期（shutdown 钩子、进程树、超时清理）与同步 subprocess 完全不同，但代码长得像，容易被当成一回事。

**How to avoid:**
- **作业注册表（P3 必做）**：每次触发写 jobs 记录（id/pid/args/started/finished/exit_code/输出摘要路径），GET /jobs 与 GET /jobs/{id} 可查；触发时同型任务运行中 → 409（幂等）。
- **shutdown 策略显式化**：FastAPI lifespan shutdown 钩子对 in-flight 子进程二选一（等完成 or taskkill /T /F），策略写进运行手册，默认建议"等完成 + 超时上限后强杀"。
- **超时上限**：全量 90min / --fast 20min / 竞价类 5min 超时 → taskkill /PID {pid} /T /F（taskkill 自身用 CREATE_NO_WINDOW + DEVNULL stdin 防闪窗防死锁）。
- gui_dashboard 现用的 `subprocess.run(timeout=180)` 是反面先例：3 分钟超时杀 --fast 管线 → 若正逢写 candidates 大文件 → 次日 morning_check 读半写文件（Pitfall 1 的真实触发链）；API runner 不得照抄该模式。

**Warning signs:**
- 任务管理器出现多个 python.exe 同型进程
- 服务重启后 data/ 文件仍在变化（孤儿管线）
- 同一 job 在日志中重复出现两次 start

**Phase to address:**
P3 操作触发接口。

---

## Other Moderate Pitfalls

| Pitfall | What goes wrong | Prevention | Phase |
|---------|-----------------|------------|-------|
| **子进程输出编码 GBK/UTF-8 混战** | Win 中文系统默认 cp936；子进程 stdout 是管道时按 locale 编码，未 reconfigure 的脚本/裸 stderr 输出 GBK → API 侧 `text=True` UTF-8 解码崩。现有脚本各自 `sys.stdout.reconfigure(encoding='utf-8')`，但 API 不能赌每个子进程都做了 | spawn 时注入 env `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1`；API 侧 decode 带 `errors="replace"`；日志落盘前统一转义 | P3 |
| **rc==0 不等于成功** | 管线单步容错文化：Step 失败只打 [Warning] 继续，整体 rc==0（gui_dashboard 已按 rc 显示"完成!"，属误报先例）→ job 状态与真实数据质量脱节 | job 记录 exit_code 之外，抓 stdout 摘要/步进标记或数据体检 warnings 进 status；/jobs/{id} 暴露"degraded"而非仅 0/非0 | P3 |
| **/health 与数据新鲜度耦合** | /health 去读 market_state.json 判"系统健康" → 盘后管线未跑时（如非交易日/早上）LB 误判服务挂；或解析 MB 级 JSON 拖慢探活 | /health 只报进程存活 + uptime（纯内存）；数据新鲜度另设 /status 端点带 updated_at | P1 |
| **时间/日期口径漂移** | 项目纪律：<15:00 取上一交易日（get_today 约定）、竞价窗口 9:15-9:35、日期格式两套（YYYY-MM-DD vs YYYYMMDD）。API 若用 naive 本地时间/UTC 混用或自写日期过滤 → 状态端点与面板口径不一致 | 日期语义复用管线模块约定（get_today 类函数/trading_calendar），响应统一带 date + captured；新增"取昨日池"类逻辑必须走 `zt_pool.get_prev_pool_file`（2026-09-01 四份手写过滤事故的收敛纪律） | P2 |
| **每请求重解析 MB 级 JSON** | candidates/auction 快照为全池明细（indent 输出，数 MB）；无缓存时每次 GET 全量 parse → CPU/IO 浪费，多消费方轮询时明显 | TTL 缓存（gui_cloud 的 `st.cache_data(ttl=120)` + mtime 校验是项目先例）；只返回请求子集（top_pick 不带全 candidates） | P2 |
| **uvicorn --reload 在 Windows 的 SelectorEventLoop 陷阱** | 开发常用 `--reload`；Windows 上 uvicorn reload/多 worker 可能强制 SelectorEventLoop，而 Selector 不支持 asyncio 子进程（create_subprocess_exec 抛 NotImplementedError）→ 开发环境"能跑 GET 不能跑触发"，且只在 Win 复现 | 生产与开发都单进程跑、不用 --reload（Python 3.13 默认 Proactor 无此问题）；若必须 reload，子进程走线程池同步 subprocess | P3 |
| **console 窗口闪烁/会话依赖** | uvicorn 若由 auto_start.bat（开机启动计划任务语境）或服务方式拉起，spawn 控制台子进程会闪窗；DETACHED_PROCESS 又切断 stdio 破坏输出采集 | spawn 一律 `creationflags=CREATE_NO_WINDOW`（POSIX 无此常量 → `getattr(subprocess,'CREATE_NO_WINDOW',0)` 门控，Mac/Win 双端必需）；不要 DETACHED_PROCESS（stdio 断裂） | P3 |
| **start_new_session 在 Windows 是 no-op** | POSIX 习惯用 start_new_session 隔离会话；Windows 上接受但无效 → 子进程随父控制台同生共死 | 平台分支：POSIX start_new_session=True / Win creationflags | P3 |

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| GET 端点里内联 import morning_check 抓取函数"顺手刷新" | 少写一个触发接口 | 数据源被探活打爆、Pitfall 6 全貌 | **never**（文件只读是硬边界） |
| 服务内嵌一套自写的 JSON 读写 | 不碰现有模块 | 第 N 份手写实现——2026-09-01"四份手写昨日池过滤"事故的复刻；路径/日期口径漂移 | never；收敛到共享 helper |
| 触发 = 裸 subprocess.Popen 不记 job | 3 行代码上线 | 不可观测、不可清理、重复触发无解（Pitfall 7） | never |
| API 模块复制每文件路径样板（BASE 三级上溯） | 与其他文件一致 | 路径常量继续散落；config.py 已有 PROJECT_ROOT/DATA_DIR 却没人用 | 新模块从 config.py 导入（ARCHITECTURE.md 反模式清单明确要求） |
| 把 run_pipeline 触发与 sync_cloud Step9 捆绑 | 全量一步到位 | 并发 git 推送冲突 + 每次触发都动仓库历史 | 触发默认 --fast 或参数化跳 Step9；全量保留给定时任务 |
| 只读接口不设缓存"反正单用户" | 实现最简单 | 消费方轮询放大 IO；大 JSON 每请求重 parse | 数据 >1MB 或轮询 >1/min 时必须 TTL 缓存（ttl=120+mtime 先例） |
| 不加锁"用户不会同时点" | 免锁复杂度 | 15:30 定时任务自动跑 + 用户随手点 = 数据写坏，且难排查（写坏的是不可再生的当日数据） | never |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| 外部数据源（腾讯 qt.gtimg/ifzq、同花顺涨停揭秘） | API 内新增直连抓取点（复制 morning_check 的解析，schema bug 修一处漏五处的历史重演——同端点 5+ 文件独立解析，commit a8514d5 只修了 2 处） | API 零外呼；一律复用 scripts/daily 既有模块函数，禁止复制；明文 http 端点不新增 |
| Windows 文件系统 | 以为 os.replace 与 POSIX 同语义；或读写都用默认 open | 写端 tmp+replace+PermissionError 重试；读端一次性读完即 close |
| Windows 子进程 | 忘 CREATE_NO_WINDOW（闪窗）；DETACHED_PROCESS 后 capture_output 拿不到输出；kill 只杀直接子进程 | spawn 用 getattr 门控的 creationflags；杀树 taskkill /T /F（自带 CREATE_NO_WINDOW + DEVNULL）；POSIX 侧 start_new_session |
| Windows asyncio | 生产没事、`--reload`/多 worker 下 create_subprocess_exec NotImplementedError（SelectorEventLoop） | 单进程 uvicorn（Python ≥3.8 默认 Proactor）；子进程统一走一个 runner 便于换实现 |
| git/同步（sync_cloud、双机 origin） | 触发全量管线 = 隐式触发 git commit+push（Step9） | 触发默认 --fast；锁覆盖 git 操作；token/密钥永不进白名单 |
| Streamlit 面板并存（gui_dashboard/gui_cloud） | API 与 GUI 各自实现同一份"读状态"逻辑，口径漂移 | 读端 helper 从 P2 起作为共享层；GUI 改造与否单独决策（不扩大本里程碑范围） |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| 每请求全量 parse candidates/auction 大 JSON | CPU 升高、请求延迟数百 ms | TTL 缓存 + mtime 校验；端点只返回请求子集 | 消费方轮询 >1/min 或文件 >1MB |
| GET 内联实时抓取 | 外部 API 被限速/封禁，采集耗时从秒到分钟 | GET 零外呼硬规则；刷新走触发接口 | 探活轮询一上午即触发 |
| 事件循环内同步 subprocess | 全站冻结，LB 摘除 | create_subprocess_exec + communicate / def 后台函数线程池 | 任何一次触发 |
| 每请求 stat/打开整个目录 glob 找最新快照 | 文件数增长后 ls 变慢（data/zt_pool 每日 +1 文件） | 文件名索引/状态文件指针；morning_check load_latest_candidates 的排序逻辑集中复用 | 目录文件数百级别（本项目数年可达） |
| 日志无轮转：API 日志 + 子进程输出全量入库 | 磁盘膨胀（仓库已 2GB；logs gitignored 但本机磁盘有限） | uvicorn 日志轮转 + job 输出只留尾部摘要 | 常驻服务数月 |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| 无鉴权绑定 0.0.0.0 | LAN 任意设备读持仓/账本/候选（本地独有敏感数据）+ 触发操作 | 默认 127.0.0.1；非 loopback 绑定无 token 拒绝启动（fail-closed） |
| 只读"放开"不按数据分级 | 2026-08-31 隐私红线（持仓/账目不上云）被 API 侧绕过 | 持仓/账本/候选 = 敏感数据一律 token；行情/温度类可放开；修订 PROJECT.md 需求措辞 |
| token 放 URL query / 打印日志 | access log、代理、历史记录泄漏 token | 只走 Authorization 头；日志清洗；恒时比较 |
| token 文件进 git / sync_cloud 白名单 | 仓库疑似公开（CONCERNS.md 匿名 200）+ git 历史已含账目 → token 直接暴露 | 双保险验证：git ls-files 与 sync_cloud 白名单均不含；.gitignore 已有条目保持 |
| CORS `["*"]` + allow_credentials / Bearer | 浏览器场景凭证失效或跨域读取 | 无浏览器消费方则不加 CORS；加了用显式 origin 列表 |
| 触发参数不校验（date/code） | run_pipeline_for_date monkey-patch datetime 按入参重跑 → 历史状态被覆盖 | `^\d{4}-\d{2}-\d{2}$` / `^\d{6}$` 白名单 + 交易日历校验 + 参数列表传参（禁 shell） |
| /health 与错误详情泄露内部结构 | 500 响应带文件路径/堆栈，辅助内网横向 | 对外错误信息脱敏；堆栈只进日志 |
| 明文 HTTP（LAN 嗅探 token） | 同网段被动窃听 | LAN 信任边界内可接受但需明示；token 非网络隔离替代品——防火墙规则限制可达主机 |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| 触发后请求挂起数分钟无反馈 | 用户以为卡死 → 重复点击 → 双跑 | 202 + job_id 秒回；GET /jobs/{id} 查进度；语义化 409（"管线运行中 pid=…"） |
| 接口成功/失败无区分（200 + 半份数据） | 消费方把 stale/空数据当新鲜（数据引用纪律的 API 版事故） | 响应带 updated_at/captured/date + stale 标记；过期返回 409/503 而非 200 半数据 |
| 竞价窗口外调用竞价端点"静默空采" | 面板显示空竞价，用户误判为无数据 | 时间窗护栏前置拒绝并解释（9:15-9:35、<15:00 取上一交易日口径一致） |
| 错误信息全英文堆栈 | 用户看不懂、无法自助 | 中文一句话错误 + code + 排查指引（项目文档惯例是中文） |
| 中文 JSON 字段无 schema 版本 | 外部消费方随 v2/v3/v4 演进断裂 | 响应包 version（candidates 文件已有 version 字段先例）+ 日期字段固定格式 |

---

## "Looks Done But Isn't" Checklist

- [ ] **/health**：只测了进程存活没测依赖——确认 /health 纯内存、不碰磁盘/大 JSON；数据新鲜度独立成 /status
- [ ] **触发接口**：返回了 200 但没记录 job——确认每次触发都有 job 记录（pid/started/exit_code），rc==0 之外还有 degraded 语义
- [ ] **并发防护**：只测了单发——确认"两个触发同发"、"触发撞 15:30 定时任务"、"GUI 刷新 + API 触发"三场景都返回 409 且数据无损坏
- [ ] **安全**：token 只在文档里没在启动路径——确认无 token + 非 loopback 绑定 = 拒启（fail-closed 实测，而非警告）
- [ ] **CORS**：确认无浏览器消费方时中间件根本不存在；有消费方时 origin 是显式列表
- [ ] **双端兼容**：只在 Windows 测过——确认 Mac 端 smoke（getattr 门控的 creationflags、无 GBK 编码假设、路径用 config.py）
- [ ] **子进程编码**：中文 Windows 下子进程中文输出——确认 PYTHONIOENCODING=utf-8 注入 + errors=replace
- [ ] **杀进程语义**：确认服务重启后无孤儿管线继续写 data/（shutdown 钩子实测）
- [ ] **只读零外呼**：grep 确认 GET 处理器无 requests/urllib/腾讯/同花顺调用路径
- [ ] **隐私边界**：从第二台机器无 token 访问 portfolio/candidates 端点——确认非 200
- [ ] **日期口径**：竞价/盘后端点与 get_today 约定一致（<15:00 回退上一交易日），非交易日不空转

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| API 读到半写 JSON（偶发 5xx） | LOW | 读端 retry + 缓存回退自动吸收；写端原子化后根除；偶发坏文件可从 git 快照/原始报文 data/raw 恢复 |
| 写端 PermissionError 被吞导致状态陈旧 | MEDIUM | 体检链（data_health_check 八项）已能暴露多数陈旧；补：写端失败日志 + 状态字段标记；重跑失败步骤 |
| 双管线并发写坏 state | HIGH（当日数据部分不可再生） | 锁仲裁后重跑被抢占方；从 data/raw 与 git 快照比对恢复；auction 当日快照丢失只能次日重采 |
| 孤儿管线继续跑（服务被杀） | MEDIUM | taskkill /T /F {pid}；jobs 注册表定位；检查 git 是否被 Step9 多推一次 |
| 事件循环被阻塞全站冻结 | LOW | 重启服务即恢复（一次性伤害）；根修：async spawn |
| 数据源被 API 误抓打到封禁 | HIGH（当日竞价决策窗口内不可恢复） | 等待解封窗口（无捷径）；临时切备源（同花顺→hithink 官方 API、腾讯→Tushare→新浪 已有降级链）；根修：GET 零外呼 |
| token 泄漏进日志/git | HIGH | 轮换 token；清 git 历史（仓库疑似公开时的全量治理已在 CONCERNS.md 挂账）；日志轮转删除 |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 读半写 JSON（非原子写） | P2 读端 helper（retry+stale 回退）；写端原子化 P2/P3 决策项 | 管线运行中并发压 GET 100 次：0 次 5xx、无半数据 |
| Windows os.replace 共享冲突 | P3 写端 helper（PermissionError 重试+失败落标） | Win 端并发读写冒烟通过；Mac 端回归不回归 |
| 并发管线无锁 | P3（锁 + 409 + stale 策略） | 双触发/触发撞定时任务 → 409 + 数据完整 |
| 同步 subprocess 阻塞 loop | P3（202+job_id、create_subprocess_exec+communicate） | 触发全量管线时 /health P95 <50ms |
| 鉴权边界错配 | P1 默认 loopback + token 机制就位；P4 完整数据分级/CORS/绑定策略 | 无 token 从第二台机访问敏感端点全 403/拒启 |
| 只读接口触发实时采集 | P2（GET 零外呼验收项） | grep GET 处理器无网络调用；轮询 1 小时数据源零新增请求 |
| spawn-and-forget/kill 混乱 | P3（作业注册表 + shutdown 钩子 + 超时 taskkill） | 杀服务进程后无孤儿 python；/jobs 可查全生命周期 |
| 编码/日期/大 JSON/健康检查等 moderate | P1（health/日志）P2（缓存/日期）P3（编码/rc 语义） | 各表 Warning signs 在双端回归中置 0 |

---

## Sources

- 官方/文档（MEDIUM）：[Python asyncio Platform Support (Windows subprocess → Proactor)](https://docs.python.org/3/library/asyncio-platforms.html) 、[FastAPI CORS 官方文档（`*` 与 credentials 互斥、默认方法仅 GET）](https://fastapi.tiangolo.com/tutorial/cors/)
- os.replace/Windows 共享语义（MEDIUM，多源交叉）：[bpo-46003 os.replace 跨平台文档讨论](https://bugs.python.org/issue46003)、[StackOverflow: os.replace Windows known issue #75140357](https://stackoverflow.com/questions/75140357)、[StackOverflow: Permission errors with os.replace #76142678](https://stackoverflow.com/questions/76142678)、[simonw til: os.remove on Windows fails if file open](https://github.com/simonw/til/blob/main/python/os-remove-windows.md)、[hermes-agent: Windows sharing-violation retry 实装](https://github.com/NousResearch/hermes-agent/pull/57777)
- asyncio/Windows 事件循环（MEDIUM）：[browser-use PR #1875（Selector 不支持子进程 → NotImplementedError）](https://github.com/browser-use/browser-use/pull/1875)、[uvicorn --reload Windows 触发 SelectorEventLoop 的修复实录](https://github.com/debpalash/VoiceStudio/commit/e69dcbb6b18f3b66c2ea816e974885b8c7d5228f)
- FastAPI 阻塞与后台任务（MEDIUM）：[FastAPI 并发下的 5 个生产问题（loop 阻塞案例）](https://dev.to/zestminds_technologies_c1/fastapi-under-load-5-production-issues-most-teams-discover-too-late-4m39)、[FastAPI 后台任务实战模式（async def 内同步调用仍阻塞）](https://dev.to/ayush_kumar_085a0f2c54e3f/mastering-fastapi-background-tasks-real-world-patterns-testing-and-when-to-reach-for-celery-22o8)、[事件循环阻塞事故记录](https://sovgrid.org/blog/fixes-dashboard-api-performance-fix/)
- Windows 进程旗标与杀树（MEDIUM）：[hermes-agent Windows subprocess 兼容层（CREATE_NO_WINDOW/taskkill/start_new_session no-op）](https://github.com/NousResearch/hermes-agent/blob/524b0622/hermes_cli/_subprocess_compat.py)、[Eryk Sun: GUI 上下文 spawn 控制台闪窗与 CREATE_NO_WINDOW](https://stackoverflow.com/posts/56436214/timeline)
- LAN/内网 API 安全（MEDIUM，多源 + FastAPI 文档交叉）：[janhq/jan #8453: 0.0.0.0 绑定静默丢弃 Trusted Hosts/CORS 限制](https://github.com/janhq/jan/issues/8453)、[qwen daemon 认证模型（非 loopback 绑必须 token、恒时比较）](https://qwenlm.github.io/qwen-code-docs/zh/developers/daemon/12-auth-security/)、[opencode-llm-proxy security（token 不替代网络隔离、日志卫生）](https://github.com/KochC/opencode-llm-proxy/blob/HEAD/docs/security.md)
- 本地代码实证（HIGH）：`scripts/daily/trading_journal.py:47,59`、`capture_market_state.py:115`、`auction_pool.py:341-342,404`、`zt_pool.py:77-78,146`、`screen_candidates.py:234`（写路径非原子性）、`gui_dashboard.py:88`（subprocess.run timeout=180 先例）、`scripts/daily/install_scheduled_task.ps1`/`auto_start.bat`（15:30+开机定时跑管线，锁冲突现实场景）、`gui_cloud.py`（纯文件只读 + ttl=120 缓存先例）、`.planning/codebase/ARCHITECTURE.md`（"无跨进程锁，约定串行"）、`.planning/codebase/CONCERNS.md`（119 宽 except、仓库疑似公开、token 明文、git 历史含账目）、`.planning/PROJECT.md`（约束与需求，含"不改现有管线模块逻辑"与鉴权措辞冲突点）

---
*Pitfalls research for: gogo FastAPI 服务层（脚本式交易系统加 HTTP API 的领域坑）*
*Researched: 2026-09-02*
