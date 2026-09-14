# Architecture Research

**Domain:** FastAPI HTTP 服务层包裹既有 Python CLI/脚本系统（gogo 主升浪交易系统）
**Researched:** 2026-09-02
**Confidence:** MEDIUM（服务端行为结论来自 web 多源交叉验证 MEDIUM；仓库现状结论来自 codebase 文档 HIGH）

## Executive Architecture

gogo 需要一个第三入口（HTTP API），它**不改动**现有 116 个 .py 文件、42+ 生产模块的任何逻辑，通过两条稳定边界与既有系统交互：**文件边界（读）** —— 直接读 `data/`、`logs/` 下现有 JSON 状态文件；**进程边界（写/触发）** —— 以 subprocess 启动现有 CLI（`run_pipeline.py`/`morning_check.py`/`backtest_v4.py` 等），靠退出码 + 落盘产物感知结果。服务层自身的写法参考了仓库内已有先例 `gui_dashboard.py:88`（`subprocess.run([sys.executable, 'scripts/daily/run_pipeline.py', '--fast'], cwd=BASE, capture_output=True, text=True, timeout=180)`）。

核心架构结论（每条都有依据，详见后文）：

1. **绝不 import `scripts/daily` 领域模块**。现有模块是"无包平铺 + 每文件 sys.path 样板 + 函数内 lazy import + 顶层副作用"形态，import 即耦合 27.5k LOC 零测试代码，且违反"不修改现有管线模块逻辑"约束。API 与系统的契约只有两个：JSON 文件形态 + CLI argv/退出码。这是本架构最重要的一条边界。
2. **触发用线程 runner，不用 asyncio subprocess、不用 async 端点里跑 subprocess.run**。Windows 下 uvicorn 单进程用 ProactorEventLoop（默认，支持子进程），但 `--reload`/`--workers>1` 会强制 SelectorEventLoop（子进程直接 NotImplementedError）；且 Proactor 下 asyncio terminate 有挂死历史问题（bpo-37381）。用专用后台线程跑 `subprocess.Popen` + `wait()` 完全绕开事件循环陷阱，双端（Win/Mac）行为一致。
3. **写路径只落在 `logs/api/`**（logs/ 全量 gitignored）。API 不新增任何被 sync_cloud 白名单/仓库跟踪的写入，不给 603MB 膨胀仓库再加 churn。
4. **每类脚本单飞（single-flight）锁**：API 内进程级锁 + portalocker 文件锁（进程死自动释放，无陈旧锁），避免"API 触发 + 15:30 计划任务"并发双跑同一管线竞争写 state JSON（仓库今天无任何跨进程锁，这是既有风险，API 至少要管住自己这一侧）。
5. **读路径零缓存起步、mtime 旁路**：写方已是 tmp+`os.replace` 原子写（zt_pool.py:75 模式），读者永远看不到半截文件，单用户 localhost QPS 下逐请求 `json.load` 即可；响应头带数据 mtime/age 让消费方自己判断新鲜度。
6. **默认绑 127.0.0.1**；操作类端点默认拒绝（X-API-Key header + `hmac.compare_digest`）；只有存在真实外部消费方才考虑 0.0.0.0 + TLS，绝不让"以后要接 LB"变成裸奔理由。

## Standard Architecture

### System Overview

```
┌────────────────────────────────────────────────────────────────────────┐
│                        HTTP 消费方 (LB探活/外部系统)                     │
└───────────────┬──────────────────────────────────────┬─────────────────┘
                │ GET /health                          │ GET /v1/state/*  POST /v1/actions/*  GET /v1/jobs/*
                ▼                                      ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     HTTP 服务层 scripts/api/ (FastAPI+uvicorn)          │
│  ┌────────────┐  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │main.py     │→ │routers/     │→ │services/     │  │security.py    │  │
│  │app工厂/起   │  │health       │  │state_reader  │  │X-API-Key守卫   │  │
│  │停/reload   │  │state_routes │  │runner        │  │(仅actions路由) │  │
│  │            │  │action_routes│  │jobs          │  │               │  │
│  └────────────┘  └─────────────┘  └──────────────┘  └───────────────┘  │
│   config.py: BASE/DATA_DIR/LOG_DIR/port/bind/key (env优先)              │
└──────┬────────────────────────────┬────────────────────────────────────┘
       │ 读: 只读现有JSON           │ 写: 仅 logs/api/ (job记录+stdout日志)
       ▼                            ▼
┌─────────────────────────────┐  ┌──────────────────────────────────────────┐
│ 存储层 data/ + logs/ (现有)  │  │ 进程边界: subprocess.Popen (专用线程)      │
│ portfolio/market_state/     │  │ [sys.executable, scripts/daily/xxx.py, …] │
│ candidates_*/auction_*/     │←─│ cwd=BASE · CREATE_NO_WINDOW · utf-8捕获   │
│ zt_pool_state/scoring_config│  │ 单飞锁 · taskkill /F /T 取消               │
└─────────────────────────────┘  └──────────────┬───────────────────────────┘
                                               ▼
                              ┌──────────────────────────────────────┐
                              │ 既有 CLI 入口 (逻辑零改动)             │
                              │ run_pipeline.py  morning_check.py     │
                              │ backtest_v4.py   data_health_check.py │
                              │ … → 写回 data/,logs/ → 读路径可见变化   │
                              └──────────────────────────────────────┘
```

**边界规则（硬约束）:**
- `services/` 与 `scripts/daily/` 之间**零 import**。唯一通信：文件读 + subprocess。
- HTTP 层不直接碰文件系统，统一走 `state_reader`（读）与 `runner`（进程）。
- API 的写范围**只限 `logs/api/`**（job 记录、stdout 日志）；`data/`、`logs/` 其余内容一律只读。
- 触发类端点必须挂在 security 依赖之下（默认拒绝）；读类与 /health 默认放开。

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| `config.py` | BASE/DATA_DIR/LOG_DIR 自定位（沿 scripts/daily 的 `__file__` 上溯惯例但独立计算）；端口/bind/API key 从 env 读 | 模块级常量 + `os.environ.get`，无 .env 依赖 |
| `main.py` | FastAPI app 工厂 + lifespan（启动时 reload job 记录、标记孤儿 job）+ 挂路由；uvicorn 目标 | `app = FastAPI()`；`uvicorn.run` 在 `__main__` |
| `routers/health.py` | GET /health：进程存活 + uptime_seconds + 版本 + 关键数据文件 age（只当字段，不当失败） | 进程启动时间戳减法 |
| `routers/state_routes.py` | GET /v1/state/*：把现有 JSON 原样吐给外部（response body = 文件原始内容），新鲜度放响应头 `X-Data-Mtime`/`X-Data-Age-S` | state_reader 逐请求读 |
| `routers/action_routes.py` | POST /v1/actions/{kind}：登记 job → 202；GET/DELETE /v1/jobs/{job_id}：查状态/取消 | jobs + runner |
| `security.py` | X-API-Key header 校验（`hmac.compare_digest`），router 级依赖默认拒绝 | FastAPI `Security(APIKeyHeader)` |
| `services/state_reader.py` | 读 JSON 文件 + `os.stat` mtime；不做缓存（或 mtime 键控缓存）；关闭句柄要快 | 每次请求独立 `open→json.load→close` |
| `services/runner.py` | 脚本注册表 kind→argv；专用线程 `Popen`+`wait`；每 kind 单飞锁；taskkill 取消；stdout 落 `logs/api/` | `threading.Thread(daemon=True)` + `subprocess.Popen` |
| `services/jobs.py` | job 记录（uuid/kind/状态/退出码/起止时间/log 路径）：进程内 dict + JSON 持久化 `logs/api/jobs/`；启动恢复（running→interrupted，taskkill 残留 PID） | dataclass + 每次状态变更原子写 |

## Recommended Project Structure

```
gogo/
├── scripts/api/                    # ★ 新服务层（与 daily 平级的独立包）
│   ├── main.py                     # app 工厂 + lifespan + 路由挂载 (uvicorn 目标)
│   ├── config.py                   # BASE/DATA_DIR/LOG_DIR 自定位 + port/bind/key
│   ├── security.py                 # X-API-Key 依赖（compare_digest, 默认拒绝）
│   ├── state.py                    # JSON 状态读取 + mtime/freshness
│   ├── runner.py                   # 脚本注册表 + 线程 spawn/wait + 单飞锁 + taskkill
│   ├── jobs.py                     # job 记录 + logs/api/jobs/*.json 持久化 + 启动恢复
│   └── routers/
│       ├── __init__.py
│       ├── health.py               # GET /health
│       ├── state_routes.py         # GET /v1/state/*
│       └── action_routes.py        # POST /v1/actions/* · GET/DELETE /v1/jobs/*
├── run_api.bat                     # Win 启动: python -m uvicorn main:app (cwd=scripts/api)
├── run_api.sh                      # Mac 启动: 同义
└── (logs/api/ 运行时生成, logs/ 全量 gitignored 无需处理)
```

### Structure Rationale

- **`scripts/api/` 而非仓库根 `api/` 或 `scripts/daily/` 内**：仓库分层惯例是"生产代码在 scripts/ 下分目录"（daily=日频批处理）。API 是新的"常驻服务"层，与 daily 平级放 `scripts/` 下最贴惯例；放 daily 内会污染 42 模块的扁平目录并误诱导他人对它 lazy import。
- **允许包结构（routers/services 子目录），这是对"无包平铺"惯例的显式例外**：该惯例服务于 CLI 模块间 sys.path 互引；API 是长驻服务且**刻意不 import daily 任何模块**，包结构不产生耦合成本，反而让 uvicorn 导入与路由组织干净。
- **`logs/api/` 自解释放 logs/**：logs/ 已整体 gitignored（2026-08-31 纪律），job 记录/日志天然不上传、不进 sync_cloud 白名单、不进 git 膨胀；与"API 写路径最小化"结论一致。
- **运行方式 `cwd=scripts/api` + `python -m uvicorn main:app`**：config.py 从 `__file__` 上溯定位 BASE，不依赖启动目录；子进程仍以 BASE 为 cwd（对齐 gui_dashboard 先例，argv 用相对路径 `scripts/daily/run_pipeline.py`）。
- **读/写两类端点拆两个 router**：读路由可匿名、写路由挂鉴权依赖，路由级依赖保证"写端点不可能忘记鉴权"（default-deny）。

## Architectural Patterns

### Pattern 1: Shell-Boundary Wrapper（壳边界封装）★本架构主线

**What:** 服务与既有系统之间只存在两条契约——文件形态（读 JSON）与进程 argv/退出码/落盘产物（触发）。API 代码对领域逻辑零 import、零复用、零假设。
**When to use:** 包裹存量脚本系统、且明确"不修改被包系统逻辑"时。gogo 现有模块 import 成本极高（sys.path 样板、顶层副作用、零测试），import 复用是陷阱不是捷径。
**Trade-offs:** 失去进程内复用（每触发一次都是冷启动，多 1-2s Python 启动开销——对分钟级任务可忽略）；获得解耦（daily 内部改动不会炸 API、API 崩溃不影响管线、无共享内存竞态）。
**Example:**
```python
# runner.py 内部（示意）
result = subprocess.run(
    [sys.executable, "scripts/daily/run_pipeline.py", "--fast"],
    cwd=BASE, capture_output=True, text=True,
    encoding="utf-8", errors="replace",
    creationflags=subprocess.CREATE_NO_WINDOW,  # Windows-only, os.name 判断
    timeout=...)
```

### Pattern 2: 202 + job_id + 轮询（异步触发）★触发接口主线

**What:** POST 触发 → 校验单飞 → 登记 job（初始状态 pending）→ 后台线程执行 → 立即返 202 `{job_id}`；客户端轮询 GET /v1/jobs/{id}（状态/退出码/时长/log 路径）；DELETE = 取消。
**When to use:** 被触发任务耗时分钟级（run_pipeline 全量含数百次限速 HTTP 抓取，远超 HTTP 超时容忍），同步等待不可行。
**Trade-offs:** FastAPI BackgroundTasks 可用但语义弱（进程内 fire-and-forget、崩了任务与状态一起没）；Celery/RabbitMQ 对单人 localhost 是杀鸡用牛刀（官方文档也仅在"需多进程/多机"时推荐）。中间解：**job 记录落盘 logs/api/jobs/*.json** —— API 重启后状态仍在、running 记录可标记 interrupted；子进程是独立进程，API 崩了它可能还在跑，启动恢复时用记录的 PID taskkill 兜底（杀不掉也无妨，脚本幂等性由管线自身 try/except 文化兜着）。
**Example:**
```
POST /v1/actions/pipeline {"fast": true}
  → 409 {detail:"pipeline already running (job 3f2a…)"}  # 单飞冲突
  → 202 {"job_id":"3f2a…","status":"running"}
GET  /v1/jobs/3f2a… → {"job_id":…,"status":"done","exit_code":0,"started_at":…,"finished_at":…,"log":"logs/api/run/pipeline_2026-09-02_3f2a.log"}
```

### Pattern 3: 单飞锁 + 每 kind 隔离（Single-Flight per Script Kind）

**What:** 同一种脚本同时只允许一个实例：进程内 `threading.Lock`/dict 登记 + 跨进程 advisory 文件锁（portalocker `PidFileLock`/msvcrt 语义，进程死 OS 自动释放 → 无陈旧锁困扰；portalocker 4.2.0+ 修过 LK_LOCK fallback 旧 bug，用新版）。不同 kind（pipeline vs morning-check vs backtest）互不阻塞。
**When to use:** 仓库今天"无跨进程锁、并发双跑会竞争写同一 state JSON"（codebase ARCHITECTURE 明示）。API 至少要保证自己这侧不双跑；15:30 Windows 计划任务（注意：auto_start.bat 的 BASE 还硬编码旧路径 `C:\Users\Davis\Desktop\主升浪`，该任务大概率已失效）这类外部触发无法强制，作为已知限制写进 README。
**Trade-offs:** advisory 锁只在所有参与者都遵守时才完备——只能约束 API 自身触发的请求；换来的是零侵入（不改 daily 代码）。

### Pattern 4: Freshness-Proxying Read（新鲜度透传只读）

**What:** 读端点 response body = 状态文件原始 JSON（与本地文件格式完全一致，消费方零适配），新鲜度经响应头旁路：`X-Data-Mtime`（文件修改时间）、`X-Data-Age-S`（距今秒数）；/health 汇总关键文件（market_state/auction_state/candidates 最新）的 age 字段。
**When to use:** 数据源是被外部进程周期性重写的文件，"数据是否新鲜"与"服务是否存活"是两个问题，必须分开表达。
**Trade-offs:** 拒绝"包一层 envelope 带 meta"的方案 —— 破坏与文件格式的 drop-in 一致性，消费方要么解包要么拿到双份结构。头部旁路两全。逐请求直读 vs 缓存：单用户 QPS 直读足够（文件小）；要缓存就按 mtime 失效，**禁止纯 TTL 缓存**（会掩盖外部写入失败）。

### Pattern 5: Windows 子进程治理（CREATE_NO_WINDOW + taskkill 树杀）

**What:** 服务 spawn CLI 用 `creationflags=CREATE_NO_WINDOW`（无控制台闪现）；取消/超时杀进程**必须树杀**：`taskkill /F /T /PID <pid>`（`TerminateProcess`/`proc.kill()` 只杀目标，子子孙孙存活）；asyncio subprocess 在 Windows Proactor 有 terminate 挂死历史（bpo-37381）→ 一律线程 runner 回避。
**When to use:** 凡 Windows 上由长驻进程拉起的 CLI。
**Trade-offs:** 比 POSIX `killpg` 丑，但这是 Windows 的事实标准；对"拉起的 CLI 会再拉子进程"（run_pipeline 内部不拉子进程，风险低）仍需兜底。

## Data Flow

### Request Flow 1: 探活（LB/外部）

```
GET /health ──→ main ──→ routers/health ──→ config(start time)
     响应 {status:"ok", uptime_seconds:N, version, data_age:{market_state:…}}
     (进程活着就 200；数据陈旧只作字段——LB 不该因 A 股隔夜数据"旧"而摘流)
```

### Request Flow 2: 只读状态（外部消费 gogo 当前状态）

```
GET /v1/state/portfolio ──→ state_routes ──→ state_reader
      │                                          │ open→json.load→close (快开快关)
      │                                          ▼
      │                              logs/portfolio.json (抓取数据唯一来源, 不做推断)
      ▼
 200 body=文件原始JSON + X-Data-Mtime/Age 头
```

### Request Flow 3: 触发管线/竞价/回测（闭环）

```
POST /v1/actions/pipeline ──→ security(X-API-Key) ──→ action_routes
      │  登记 job {id,pending} 落盘 logs/api/jobs/
      │  runner 单飞检查 (已有 running → 409)
      ▼
 runner 线程: Popen([python, scripts/daily/run_pipeline.py, …], cwd=BASE)
      │  stdout/stderr → logs/api/run/pipeline_*.log (utf-8)
      │  脚本自行写回 data/zt_pool_state.json, logs/candidates_*.json …
      ▼
 脚本结束 → 更新 job {done/failed, exit_code} ──→ GET /v1/jobs/{id} 轮询可见
      │
      ▼ (副作用回环: 管线写的新文件被 state_reader 读到)
 GET /v1/state/candidates → 新数据 + 新 mtime → 消费方看到"刷新完成"
```

### Key Data Flows

1. **数据流向永远是单向闭环**：现有脚本写 `data/`+`logs/`（它们原有的原子写 tmp+`os.replace` 不变）→ API 只读并透传新鲜度 → 外部消费方。API 不产生、不修改、不迁移任何业务数据。
2. **job 元数据流**：action_routes → jobs.py（内存 + logs/api/jobs/ 落盘）↔ runner 线程更新 → state_routes 之外的 jobs 查询出口。API 重启 → 启动时 reload，running→interrupted。
3. **触发时间敏感链路**（竞价 9:15-9:35）：morning-check 的时间窗/快照新鲜度守卫（<3 分钟复用、9:25 前拒写）全部在脚本内部，API 不做第二套时间判断、不设窗口，只透传 —— 避免双份规则漂移。

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 现状（单用户 localhost，1-10 req/min 的探活+查询+偶尔触发） | 上述结构即可。单 worker uvicorn、零缓存、直读文件、每 kind 单飞 |
| 数十外部消费方/持续轮询（如云端面板按秒轮询 + 多脚本并发触发） | 读路径加 mtime 键控内存缓存（TTL 只作上限不作失效依据）；写路径仍被"每 kind 单飞"钉死，无需改；uvicorn 仍 1 worker（job 状态在进程内，多 worker 反而分裂） |
| 100+ 并发或需跨机触发 | 才考虑进程外队列（Celery/arq + broker）；在此之前任何队列都是过度设计 |

### Scaling Priorities

1. **第一瓶颈不是吞吐，是事件循环被阻塞与管线双跑**：前者被线程 runner 结构性消除；后者被单飞锁结构性消除。这两个是"架构上防住"的，不是"性能上优化"的。
2. **第二瓶颈是 Windows 进程模型**（uvicorn `--reload`/`--workers` → SelectorEventLoop → 子进程炸）：用 1 worker + 线程 runner 后不再出现；若未来换 Mac 主跑，同样代码直接工作（POSIX 无 CREATE_NO_WINDOW 问题，按 `os.name` 分支）。

## Anti-Patterns

### Anti-Pattern 1: import 领域模块"复用逻辑"

**What people do:** API 里 `from scripts.daily.scoring import score_v4` 之类，图省事直接算。
**Why it's wrong:** daily 模块是 sys.path 样板 + 顶层副作用 + lazy import 网形态，import 会连带执行路径自检/建目录/可能联网初始化；27.5k LOC 零测试，任何改动都变成 API 的隐性依赖；与"不修改管线逻辑"约束直接冲突。
**Do this instead:** 壳边界（Pattern 1）。需要脚本能力就触发脚本，需要数据就读它落盘的 JSON。多 1-2s 冷启动换十年解耦。

### Anti-Pattern 2: async 端点里 subprocess.run / async BackgroundTasks 里跑阻塞

**What people do:** `@app.post` async 函数里 `subprocess.run(...)` 等 180s，或 async background 里同步等待。
**Why it's wrong:** 整个事件循环被占死，期间所有请求（含 /health）卡住；Windows 下 uvicorn reload/多 worker 变 SelectorEventLoop 直接 NotImplementedError。
**Do this instead:** 同步 `def` 端点（FastAPI 自动进线程池）或专用 runner 线程 + Popen；**彻底不用 asyncio.create_subprocess**。

### Anti-Pattern 3: job 状态只放内存 dict

**What people do:** `JOBS: dict[str, dict]` 模块级存状态。
**Why it's wrong:** API 一重启（手动/崩溃/NSSM 重启）所有 job 状态蒸发，轮询方拿到 404 或永远 pending；无法区分"没跑"与"跑挂了"。
**Do this instead:** 每状态变更原子写 `logs/api/jobs/{id}.json`（沿用仓库 tmp+os.replace 原子写文化），启动 lifespan reload + 孤儿标记。

### Anti-Pattern 4: 触发接口不设单飞就上

**What people do:** 每个 POST 都直接 spawn。
**Why it's wrong:** 仓库无跨进程锁的既有事实意味着两个管线并发会竞争写 zt_pool_state.json/market_state.json —— 这是 codebase 明示的已知风险；API 让双跑更易发生（可脚本化、可误双击）。
**Do this instead:** 每 kind 单飞（进程内 + portalocker advisory 文件锁），冲突返 409 + 现有 job_id；README 写明"API 只管得住自己这侧"。

### Anti-Pattern 5: 为"以后接 LB"直接绑 0.0.0.0 且无鉴权裸 HTTP

**What people do:** `--host 0.0.0.0` 方便"外部负载均衡探活"，操作接口 token 都还没有。
**Why it's wrong:** 绑 0.0.0.0 是安全决策不是连通性参数；仓库疑似公开 + 历史含交易记录（CONCERNS.md），这台机器上的 API 若可被局域网任意调用（甚至可触发回测/管线/读到持仓）风险不可接受；CORS `*`+credentials、token 进 URL/日志是已知高危/泄露面。
**Do this instead:** 默认 `127.0.0.1`；确有远程消费方时显式 env 开启 0.0.0.0，且**必须先有** X-API-Key（`hmac.compare_digest`，env > gitignored 文件），操作类路由 default-deny；密钥不进 URL/body/日志；浏览器消费方才需要 CORS（显式 origin 白名单，无浏览器客户端就不加 CORSMiddleware）；明文 HTTP 出本机前先想清楚 TLS。

### Anti-Pattern 6: 读文件长握句柄 / 自建非原子写

**What people do:** 读端 open 后长时间持有；写端直接 write 目标文件。
**Why it's wrong:** Windows 下 CPython 打开文件不带 FILE_SHARE_DELETE，读者握着的目标文件会让写方 `os.replace` 抛 WinError 5/32/33（PermissionError）—— API 的读会反过来阻塞既有脚本的原子写。
**Do this instead:** 读端 `open→json.load→close` 快开快关；写端绝不新增（API 只写 logs/api/，同样 tmp+replace）。

## Integration Points

### External Services（API 对外暴露面）

| Endpoint | 鉴权 | 语义 |
|----------|------|------|
| GET /health | 无 | 进程存活 + uptime_seconds + 数据 age 字段（LB 探活用） |
| GET /v1/state/{name} | 默认无（env 可收紧） | 原样透传 portfolio/market_state/auction_state/candidates/zt_pool_state… |
| POST /v1/actions/{kind} | **必填 X-API-Key** | pipeline(--fast可选)/morning-check/backtest-weights/health-check 触发 → 202 |
| GET /v1/jobs/{id} · DELETE /v1/jobs/{id} | **必填 X-API-Key** | 轮询/取消（taskkill 树杀） |

动作 kind 注册表（runner.py 一张 dict）：`pipeline → run_pipeline.py`（body 可选 fast），`morning-check → morning_check.py --quick`，`backtest-weights → backtest_v4.py`，`health-check → data_health_check.py`。新增脚本=注册表加一行，不改结构。

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| routers ↔ services | 直接调用（依赖注入） | services 无 FastAPI 依赖，可单测 |
| services ↔ scripts/daily | **无 import**；文件读 + subprocess argv | 本架构生命线 |
| runner ↔ 文件系统 | 写 `logs/api/`（job+stdout）；读只经 state_reader | API 写面最小化 |
| API ↔ data/ + logs/ 业务文件 | 只读 + mtime 透传 | 抓取数据唯一来源纪律同样适用于 API 汇报 |
| API 进程 ↔ OS | 子进程 cwd=BASE、`sys.executable` 同解释器 | 与 gui_dashboard 先例一致；不锁 venv 避免双端漂移 |

### 平台差异（Win 主 / Mac 兼容）

- **Windows 主跑**：线程 runner + CREATE_NO_WINDOW（`os.name=='nt'` 分支）；长驻建议 **NSSM** 包 uvicorn（真服务、开机自启、崩溃自重启、stdout/stderr 落文件）或"登录时计划任务"轻量方案（无自重启）；`--reload` 仅开发。
- **Mac 兼容**：同一代码直接跑（无 creationflags 分支、无 taskkill —— 用 `os.killpg` 或 `proc.terminate()`）；启动脚本 run_api.sh。**不要**因 Windows 细节把线程 runner 换成 asyncio 版，双端各有一套分支的维护成本高于共用一个线程实现。

## Suggested Build Order（依赖驱动）

1. **Phase A — 骨架 + /health**：config.py + main.py + routers/health.py + 启动脚本。零外部依赖，先验证"uvicorn 在 Win 上跑起来、路径自定位正确、NSSM/计划任务方案落地"。产出：可探活的空服务。
2. **Phase B — 只读状态透传**：state.py + state_routes.py（freshness 头）。只依赖 Phase A；对现有 JSON 零风险，先兑现 PROJECT.md"只读接口"价值；此阶段可对手工 curl 逐文件对拍本地 JSON（测试手段：与文件 diff）。
3. **Phase C — runner 最小闭环**：jobs.py + runner.py + 单飞锁，先只接 `pipeline --fast`（最短路径，gui 先例同款）+ GET /v1/jobs 轮询 + stdout 落日志。**Windows subprocess 语义风险全部集中在此阶段验证**（CREATE_NO_WINDOW/编码/树杀/锁），失败只影响一个新模块。
4. **Phase D — 鉴权 + 全动作**：security.py 挂 action 路由（在有任何暴露之前完成）+ 其余 kind 注册 + DELETE 取消 + 409 语义。依赖 Phase C。
5. **Phase E — 恢复与加固**：启动孤儿 job 恢复、/health 数据 age 字段、NSSM/计划任务正式化、.gitignore 增补（data/api_key.txt）、README（含"与 15:30 计划任务并发属已知限制"）。依赖全阶段。

**Phase ordering rationale:** 每阶段独立可验证可回滚；风险最高的 Windows 进程治理放在 Phase C 且被 B 阶段"只读价值先行"隔离 —— 若 runner 出问题，只读 API 仍可交付；鉴权（D）先于任何外部接入但在内部跑通触发闭环（C）之后，避免过早的密钥管理摩擦；恢复/部署最后，因为前四阶段手工启动即可验收。

## Sources

- FastAPI 官方文档 BackgroundTasks（含"重型任务另用 Celery"警告、sync 任务跑线程池）— fastapi.tiangolo.com/tutorial/background-tasks — 官方文档（MEDIUM 档，直接抓取）
- Python asyncio 平台支持（Win 默认 ProactorEventLoop、Selector 不支持子进程/管道）— docs.python.org（搜索引擎摘要转引，MEDIUM）
- uvicorn 事件循环（--reload/--workers 在 Windows 强制 SelectorEventLoop）— uvicorn.dev/concepts/event-loop（MEDIUM）
- Windows 进程树杀/隐藏窗口/Proactor terminate 挂死 — bpo-37381/43884、mesonbuild/mtest.py、hermes-agent process_registry（taskkill /F /T /PID 模式、CREATE_NO_WINDOW）（MEDIUM，多源一致）
- os.replace Windows PermissionError（WinError 5/32/33、FILE_SHARE_DELETE 语义、重试退避）— python-bugs 46003 线索 + 多实现修正（MEDIUM）
- portalocker（PidFileLock/fail_closed、4.2.0 前 LK_LOCK fallback 旧 bug、进程死锁自动释放）— github.com/wolph/portalocker（MEDIUM）
- FastAPI 局域网暴露/API key 安全（bind 语义、header 密钥、compare_digest、CORS `*`+credentials、CVE-2026-23996 计时侧信道）— trailofbits 等安全清单多源（MEDIUM）
- NSSM 运行 uvicorn 于 Windows 服务（绝对路径/venv、--workers 在 Win 的问题、I/O 日志）— Stack Overflow + 部署文多源（MEDIUM）
- gogo 仓库现状（分层/原子写/无跨进程锁/导入形态/gui subprocess 先例/sync 与 gitignore 纪律/安全隐患）— .planning/codebase/{ARCHITECTURE,STRUCTURE,CONCERNS,INTEGRATIONS}.md + gui_dashboard.py（HIGH，本地直接证据）

---
*Architecture research for: gogo main-wave API 服务层（FastAPI 包裹既有 CLI 系统）*
*Researched: 2026-09-02*
