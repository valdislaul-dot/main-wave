# Phase 3: Trigger Runner, Job Registry & Locks + Auth Enforcement - Research

**Researched:** 2026-09-03 (real-machine probes on this Windows 11 box, repo `C:\Users\Davis\Desktop\gogo`)
**Domain:** Windows subprocess governance / background job orchestration / single-flight locking / request auth (FastAPI)
**Confidence:** HIGH — every load-bearing claim below was probed on the real machine this session (Python 3.13.1, NTFS C:, cp936 locale, GBK console), not taken from training memory

## Summary

Phase 3 makes the resident FastAPI service able to **spawn the four existing scripts unmodified** (arg-list, no shell), return **202 + job_id** immediately, keep **single-flight per kind** across API + GUI entry points, survive **API kill/restart** with a durable registry, and enforce **X-API-Key** on every mutating/job endpoint. The phase boundary rule — "shell-boundary wrapper, never import pipeline modules, never modify the 116 pipeline files" — is preserved; the only pipeline-file edit in scope is the D-01 GUI lock join inside `gui_dashboard.py`'s refresh handler.

The core research question was Windows subprocess governance. Real-machine probes produced decisive answers: (1) **stdout encoding is the #1 silent-failure trap** — children spawned without a UTF-8 override write GBK and *crash with `UnicodeEncodeError` on emoji* (pipeline modules contain 80 print statements with emoji-range chars; morning-check would fail deterministically). Children must be spawned with `PYTHONIOENCODING=utf-8` in the env — not `PYTHONUTF8=1`, which would silently change default `open()` encoding repo-wide. (2) **`msvcrt.locking` byte-range locks work perfectly on this NTFS drive**: empty-file lock OK, cross-process contention raises `errno 13`, and the OS **auto-releases the lock when the holder process is killed** (`taskkill /F` probe) — no stale-lock cleanup protocol needed. A subtlety: the locked byte is *unreadable by other processes* (`errno 13` on read), so lock files must carry **no holder-info payload**. (3) **`thread + Popen` with stdout redirected to a file handle** is the right governance model (event loop never touched; no pipe-drain deadlock; deterministic exit-code semantics); `asyncio.create_subprocess_exec` on Windows Proactor remains a known-footgun area (bpo-37381 exit-cleanup class of bugs), giving no benefit here. (4) **PID liveness probes verified two ways**: `ctypes.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` (clean, stdlib) and raw-byte match on `tasklist /FI "PID eq N" /FO CSV /NH` output (tasklist emits localized GBK text on this machine — parsing its *text* is fragile, matching the ASCII PID bytes is not). (5) **The 15:30 scheduled task does not exist on this machine** — D-02's disable step reduces to a verify-only check; `auto_start.bat`/`install_scheduled_task.ps1` remain in the repo as stale-path dead files.

All four 定稿机制 sign-off gates listed in the ROADMAP research directive are resolved: writer-side atomicization deferred to Phase 4 (D-04..D-06), GUI lock join locked (D-01), trigger defaults `--fast`/`--quick`/no-arg locked (D-07..D-09), and the 15:30 task is machine-verified absent. Zero new packages are needed — the stack stays stdlib-only, matching Phase 2's precedent (`msvcrt`/`fcntl` locks, `hmac.compare_digest`, `subprocess.Popen`, `uuid`, atomic `os.replace` registry files).

**Primary recommendation:** new modules `api/jobs.py` (registry + spawn governance, pure functions, call-time path resolution for monkeypatch seams), `api/auth.py` (X-API-Key dependency), `api/actions.py` (protected router: POST /v1/actions/{kind}, GET /v1/jobs/{job_id}) and shared cross-platform lock helper `scripts/daily/job_lock.py` (msvcrt on win32 / fcntl.flock on posix) imported by both the API and the GUI. Main.py gains the standard two-line include + a one-line registry-reload call in `main()` — the Phase 1 SEC-03 boot ordering stays untouched and diff-auditable.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Phase Boundary (verbatim, 03-CONTEXT.md:8-12)

消费方经 HTTP 触发 gogo 现有四个脚本(pipeline/morning-check/backtest-weights/health-check)——POST 立即返回 202+job_id,未改动的脚本在后台运行,同 kind 永不重跑,事件循环永不冻结,无有效 API key 什么都起不了。

**In scope:** ACT-01 (POST /v1/actions/{kind} 四种触发,arg-list spawn 无 shell,只启动现有脚本不改其逻辑), ACT-02 (202+job_id 异步契约 + 持久化 job registry `logs/api/jobs/`,重启可恢复,GET /v1/jobs/{job_id} 轮询 pending→running→succeeded/failed 并暴露日志路径), ACT-03 (单飞锁:同 kind 重叠返回 409 带 running job_id,两个同 kind 运行永不并发写 data/), SEC-01 (X-API-Key 鉴权:constant-time 比较、header 传递、密钥永不上日志)。

**Not this phase:** 持仓/账本/候选读取 (STA-02, Phase 4), 数据分级政策 (SEC-02, Phase 4), 写侧原子化改造 (推迟 Phase 4 并绑入门槛, 见 D-07), 启动级鉴权加固 WR-01 (推迟 Phase 4, 见 D-12), job 取消 taskkill 树杀 (ACT-04 v2), 孤儿任务收养 (ACT-05 v2), 日志轮转/health/details (OPS-03, Phase 5), ETag/限流/CORS (v2/OOS)。

### Locked Decisions (verbatim, 03-CONTEXT.md:23-43)

#### 单飞锁边界与并发者 (ACT-03)
- **D-01:** GUI 一键刷新加入同一把锁文件。刷新按钮启动前先取锁,锁被占(API job 运行中)时禁用刷新并提示运行中,不抢跑。改 `scripts/daily/gui_dashboard.py:88` 的 subprocess 前置逻辑,保持"直接 subprocess 跑 run_pipeline --fast"的既有形态,只加锁检查。—— 最小改动达成 SC2 "any other entry point" 意图。
- **D-02:** 停用「主升浪每日选股流水线」计划任务。`scripts/daily/auto_start.bat` 硬编码 `BASE=C:\Users\Davis\Desktop\主升浪`(仓库已迁 `gogo`),任务每天 15:30 cd 失败静默退出;仓库更名以来无人发现,证明用户不依赖它。停用需一条提权命令(Phase 1 已验证 Unregister-ScheduledTask 需提权),盘后靠手动面板/管线 + API 触发。—— **Reversibility:** reversible — 重新注册即可恢复,但按 Phase 1 D-07 惯例重装时勿复制 stale 路径。
- **D-03:** 锁作用域 = Win 本机锁。锁文件放 Win 本机 data/ 下(gitignore),防本机 API/GUI/计划任务并发。Mac 端 crontab(15:00 盘后 / 9:26 竞价)不加锁,保持两机串行约定——跨机锁经 git 同步存在天然竞态(两机可同时 pull 到无锁状态再抢锁),不可靠。锁实现细节(portalocker/msvcrt/lockfile 选型、stale 锁处理)留给 research 在真机验证。

#### 写侧原子化 (ROADMAP 签字门)
- **D-04:** portfolio.json / trading_journal.json 的非原子写(`scripts/daily/trading_journal.py:46/58` 直接 `open('w')` 截断写)**推迟到 Phase 4**。依据:Phase 3 API 不读 portfolio(持仓读是 Phase 4 STA-02);Phase 2 读侧防御已保 3 个白名单文件 0×5xx;单飞锁已排除写写并发。本阶段不动实盘账本模块。
- **D-05:** 推迟执行的改造范围仅两个函数:save_portfolio + save_journal,照 `scripts/daily/zt_pool.py:75` 的 tmp+`os.replace` 原子写模式。不做 logs/ 全量扫描。
- **D-06:** 该写侧改造绑定为 Phase 4 STA-02 持仓读上线的前置任务——写入 Phase 4 计划,STA-02 上线前必须完成,避免遗漏。

#### 触发形态与参数 (ACT-01)
- **D-07:** POST /v1/actions/pipeline 固定跑 `--fast`(仅涨停池+评分,跳过 Step5-9 含 Step9 sync_cloud 自动 push)。全量管线保持手动/GUI 入口。API 不改 git 历史、不触发 push。—— 与上传纪律(2026-08-31:仅代码+行情数据上传)解耦。
- **D-08:** POST /v1/actions/morning-check 固定跑 `--quick`(决策摘要+持仓处置+买入开关三块),job log 快速出结论,表1-4 细则仍用 GUI/手动全量看。竞价 60 秒 SLA 窗口下 API 触发输出快照型结论。
- **D-09:** Phase 3 触发接口零参数——四种 kind 固定命令:pipeline=`run_pipeline.py --fast`、morning-check=`morning_check.py --quick`、backtest-weights=`backtest_v4.py`(无参=权重重搜)、health-check=`data_health_check.py`(无参)。请求体不接受任何参数。Phase 4 SC4 引入 date 白名单参数(YYYY-MM-DD / YYYYMMDD)时再扩参数面。—— **Reversibility:** costly — 参数面从零到有是契约扩展,一旦有消费方按固定命令接入,新增可选参数需保持向后兼容。
- 注意:backtest-weights 触发的权重重搜会写 `data/scoring_config.json` v4 权重 + `data/weight_history.json`(定稿机制内已定稿的月度流程,API 只是换入口,流程本身不变)。

#### 鉴权契约与加固范围 (SEC-01)
- **D-10:** 鉴权失败分工:缺失 X-API-Key 头 → 401 + `WWW-Authenticate` 头;带了但错误 → 403。两者均 constant-time 比较,响应体不泄露 token 值(沿 Phase 2 D-04 最小 JSON `{"detail": ...}` 风格,detail 不含 token/路径)。单 token 无用户枚举风险,403 精确表达"key 无效"。
- **D-11:** GET /health/ready 豁免鉴权,与 /health 同精神(HLT-01 纯度:探活/就绪类端点公开,仅 200/503 无数据泄露)。SEC-02 分级只针对数据端点。豁免清单 Phase 3 起为:/health、/health/ready、GET /v1/state/{name}(Phase 2 已公开);其余(全部 POST /v1/actions/*、GET /v1/jobs/*)一律 token。
- **D-12:** P2 遗留 WR-01 修复(非回环绑定只查 token 存在、回环默认运行自动生成 token 的启动意图检查缺陷)推迟到 Phase 4 与数据分级/暴露面硬化同批做(env 强制 token + 控制台警告)。Phase 3 只交付请求级 SEC-01,不动 Phase 1 启动序列(SEC-03 检查先于 token 生成的顺序是 Phase 1 载荷,保持 diff 可审计)。

### Claude's Discretion (verbatim, 03-CONTEXT.md:44-49)

- 锁文件机制选型、stale 锁(PID 探活确认持有者已死)处理策略——ROADMAP Research 段已列,research 真机验证后定。
- subprocess 治理方式(thread+Popen vs create_subprocess_exec, bpo-37381)、GBK/UTF-8 输出重定向矩阵、CREATE_NO_WINDOW——research 主题,按 SC3(P95<50ms 事件循环不阻塞)字面执行。
- job registry 落地格式(每 job 一文件 vs 聚合)与字段集、完成判定(退出码)、job log 路径约定(`logs/api/jobs/{job_id}/` 或同级)——ACT-02/SC1/SC5 字面内自定;退出码 0→succeeded 非 0→failed 是合理默认。
- job registry 文件保留策略(增长有界)——OPS-03 日志轮转属 Phase 5,但 registry 目录从 Phase 3 起就要有上限设计,至少按数量封顶。
- 401/403 错误体具体文案、X-API-Key 头名(与 hithink 的 `X-api-key` 区分,建议沿用 REQUIREMENTS.md 字面 `X-API-Key`)。

### Deferred Ideas / Out of Scope (verbatim, 03-CONTEXT.md:12, 109-117)

写侧原子化改造(save_portfolio/save_journal tmp+os.replace)——Phase 4 前置任务,绑 STA-02 上线门槛(D-04..D-06)。P2 REVIEW WR-01 启动级鉴权加固(env 强制 token + 控制台警告)——Phase 4 与数据分级同批(D-12)。date 白名单参数(YYYY-MM-DD/YYYYMMDD)——Phase 4 SC4(D-09 参数面届时扩展)。job 取消(taskkill /F /T 树杀)与孤儿任务收养打磨——REQUIREMENTS.md v2(ACT-04/ACT-05),仅当真实出现失控运行时。日志轮转 + 鉴权版 /health/details——Phase 5(OPS-03)。Mac 端 crontab 入锁/跨机锁——D-03 已否掉 git 同步方案;若未来需要,属独立决策。
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ACT-01 | POST /v1/actions/{kind} 四种触发(管线/竞价/回测/体检),只启动现有脚本不改逻辑,arg-list spawn 无 shell | Kind→command map (D-09 verbatim table); spawn recipe machine-verified (Pattern 3); all four entry-point flags read and quoted in-repo; backtest main guard verified `if '--show-history' in sys.argv: show_history() else: main()` ([VERIFIED: scripts/daily/backtest_v4.py:438-442]) |
| ACT-02 | 202+job_id 异步契约 + 持久化 job registry logs/api/jobs/(重启可恢复);GET /v1/jobs/{job_id} 轮询 pending→running→succeeded/failed,暴露日志路径 | Per-job-file registry + atomic os.replace (Pattern 2); startup reload sweep → interrupted (Pattern 4); log-path convention; retention cap; os.replace-on-NTFS probe OK; job_id = uuid4().hex with `^[0-9a-f]{32}$` gate before path composition |
| ACT-03 | 单飞锁:同 kind 重叠 409 带 running job_id;两个同 kind 运行永不并发写 data/ | msvcrt byte-range lock machine-verified (empty-file lock OK, cross-process errno 13, kill → OS auto-release); claim order pattern (Pattern 1); GUI joins same lock via shared helper (D-01); scheduled-task competitor machine-verified absent |
| SEC-01 | X-API-Key constant-time 比较、header 传递、永不上日志 | api/boot.read_token reuse ([VERIFIED: api/boot.py:30-47]); hmac.compare_digest (local stdlib docstring verified); 401/403 split + exemption list per D-10/D-11; router-level dependency keeps /health pure (SC3); uvicorn access_log=False already on ([VERIFIED: api/main.py:73]) |

## 定稿机制 Sign-off Gates — Status (collected 2026-09-03)

ROADMAP Phase 3 Research note lists four user sign-off gates. All four are resolved — three were already locked as decisions in the discuss phase (03-CONTEXT.md), one changed materially by machine evidence:

| Gate | Decision | Status |
|------|----------|--------|
| Writer-side atomicization (touches pipeline modules) | D-04..D-06: defer to Phase 4, bound as STA-02 precondition | Locked (no Phase 3 action; read-side defense from Phase 2 already covers the 3 whitelist files) |
| GUI one-key refresh joins the same lock | D-01: gui_dashboard.py:88 area adds lock check only, keeps direct subprocess | Locked (Win/Mac GUI share source; helper must be cross-platform — see job_lock.py below) |
| Liveness of the 15:30 scheduled task | D-02 assumed task exists and needs an elevated unregister | **Machine finding (this research): the task is ABSENT on this machine** — full task query by name (主升浪/选股/流水线/pipeline) and by action path (auto_start.bat / 主升浪 / Desktop gogo) over all 201 tasks returns only `gogo-api`. D-02's elevated command reduces to a verify-only check; `auto_start.bat` (stale `BASE=C:\Users\Davis\Desktop\主升浪` [VERIFIED: scripts/daily/auto_start.bat:7]) and `install_scheduled_task.ps1` remain as dead files in the repo — do NOT register them at reinstall |
| Trigger default --fast | D-07 (pipeline `--fast`), D-08 (morning-check `--quick`), D-09 (zero params) | Locked |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| HTTP trigger dispatch (POST /v1/actions/{kind}) | API / Backend | — | FastAPI router in api/actions.py; kind→command mapping is pure server-side config (D-09) |
| Background execution governance (spawn, wait, exit-code) | API / Backend (worker thread) | — | thread+Popen inside the resident API process; the spawned script is the pipeline's own process, not a tier |
| Single-flight per kind | API / Backend (in-memory claim) + shared OS lock file | GUI (client process, same machine) | Lock lives at the filesystem (data/locks/{kind}.lock) so API and GUI arbitrate equally; in-memory map gives instant 409 + running job_id |
| Durable job registry (logs/api/jobs/) | Database / Storage (file-based) | API writes via atomic os.replace | Files are the crash-safe source of truth; in-memory structures are derived, never authoritative |
| Auth enforcement (X-API-Key) | API / Backend (request layer) | — | Router-level dependency; /health family and /v1/state stay public (D-11); never in the browser tier (no browser consumer) |
| Run log capture | Storage (per-job log file) | Child stdout redirection | Log file is written directly by the child via inherited handle — no pipe, no proxy process |

## Real-Machine Verification Log (probes run 2026-09-03 on this box)

Every probe below was executed against the real machine (Python 3.13.1 `C:\Users\Davis\AppData\Local\Programs\Python\Python313\python.exe`, NTFS C:, locale `cp936`, cmd code page 936, git-bash probe harness under `%TEMP%\gsd_p3_probe`). Evidence bytes quoted so the plan-checker can re-run and compare.

### V1 — GBK/UTF-8 output matrix (API-style spawn: Popen child, stdout = open(log,'wb') file handle)

Child prints `ENC-START-ASCII` / `ENC-CN-中文测试` / `ENC-EMOJI-⚠️` / `ENC-END-ASCII` with plain `print()`, no reconfigure — the run_pipeline.py shape.

- **Variant A (clean env, no override): `rc=1`.** Log bytes are GBK: `b'ENC-CN-\xd6\xd0\xce\xc4\xb2\xe2\xca\xd4\r\nTraceback...'` followed by `UnicodeEncodeError: 'gbk' codec can't encode character '\u26a0' in position 10: illegal multibyte sequence`. The emoji print **crashes the child**.
- **Variant B (`PYTHONUTF8=1`): `rc=0`.** Clean UTF-8: `b'ENC-CN-\xe4\xb8\xad\xe6\x96\x87\xe6\xb5\x8b\xe8\xaf\x95\r\nENC-EMOJI-\xe2\x9a\xa0\xef\xb8\x8f\r\n...'`.
- **Variant C (`PYTHONIOENCODING=utf-8`): `rc=0`, byte-identical to B.**
- **GUI-style pipe (capture_output, clean env): `rc=1`**, GBK bytes in the pipe, same emoji UnicodeEncodeError — the GUI's current `subprocess.run(..., text=True)` at gui_dashboard.py:88-90 silently degrades to "部分失败" whenever the child hits an emoji print; pre-existing, out of Phase 3 scope (D-01 adds only the lock check).
- Locale confirmed `cp936`; default event loop on this box is `ProactorEventLoop`; `taskkill`/console output is GBK (`chcp` → 936).

**Consequence:** repo scan found 80 print statements carrying emoji-range chars across the four target scripts' paths (morning_check 32 incl. `print(f'  ║  🟡 观察 {pos["name"]}...')` class, data_health_check 24, zt_pool 4 conditional `⚠`, run_pipeline.py:83/85 `⚠` 连板数不一致 lines, yao_watch `⭐` 命中 lines, auction_pool 8). morning-check under GBK would crash on its first decision-summary block. **Every API spawn must force UTF-8 stdio in the child env.** `PYTHONIOENCODING=utf-8` is prescribed over `PYTHONUTF8=1`: UTF-8 mode would also flip the default `open()` text encoding repo-wide, and two repo sites call `open()` without an explicit encoding ([CITED: scripts/daily/screen_candidates.py:126 — write of `data/zt_pool/{YYYYMMDD}.json`; scripts/daily/capture_tboard_minute.py:73 — read]) whose locale-default behavior must not silently change between manual (GBK) and API-triggered (UTF-8-mode) runs. Stdio-only override has zero file-I/O side effects and still saves run_pipeline (which never calls `sys.stdout.reconfigure`; morning_check/data_health_check reconfigure at main start — [VERIFIED: scripts/daily/morning_check.py:425, scripts/daily/data_health_check.py:103]).

### V2 — msvcrt.locking byte-range lock semantics on this drive

Recipe: open `r+b`, `seek(0)`, `msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)`. Probe results:

- **Empty file (0 bytes), lock 1 byte at pos 0: OK.** No padding dance needed.
- Second handle, **same process**: `LOCK-FAIL errno=13 Permission denied` — in-process re-entrancy is denied (good: API's own double-trigger fails the OS lock too).
- **Cross-process** (child `lock_holder.py` holds): parent `LOCK-FAIL errno=13`.
- **Read denial subtlety:** while a child holds byte 0, another process's `read(1)@0` fails `errno=13`, but `seek(1); read(1)@1` succeeds (`b'o'`). Windows byte-range locks deny reads of the *locked byte only*.
- **Kill holder mid-hold** (`taskkill /F /PID`, rc=0): re-acquire by a fresh process **immediately succeeds** — the OS releases the lock on process death. No stale-lock cleanup protocol is needed; the v2 PID-probe design point dissolves for lock purposes.
- Owner can write file content after locking (same handle); explicit `LK_UNLCK` or `close()` both release.

**Consequence:** content-free lock files (`data/locks/{kind}.lock`, 0 bytes or a placeholder byte, locked byte 0). Because non-owners cannot read byte 0, **holder-info payloads must NOT live in the locked file** — holder info is unnecessary anyway: API-held runs are known from the in-memory map (409 carries running_job_id); GUI-held runs are reported as a generic 409.

### V3 — PID liveness probes (for stale-lock / orphan decisions)

- `tasklist /FI "PID eq {pid}" /FO CSV /NH`: live pid → `b'"python.exe","6764","Console","1","11,864 K"'`; dead pid → rc=0 with a **localized GBK info line** (`b'\xd0\xc5\xcf\xa2: ...'` = 信息: 没有运行的任务匹配指定标准). Matching the raw ASCII bytes `b'"{pid}"'` in the output is locale-robust; parsing the localized text is not.
- `ctypes.OpenProcess(0x1000 /* PROCESS_QUERY_LIMITED_INFORMATION */)`: live → handle returned; dead → `err=87` (ERROR_INVALID_PARAMETER); `err=5` would mean exists-but-inaccessible (treat as alive, fail-closed).

**Consequence:** Phase 3 does not need PID probes (OS auto-release covers locks; registry reload is deterministic-interrupted). When v2 ACT-05 orphan adoption arrives, prescribe ctypes OpenProcess as primary, tasklist raw-byte match as documented alternative.

### V4 — Spawn mechanics

- `subprocess.CREATE_NO_WINDOW == 0x8000000` (0x08000000) [VERIFIED: local Python 3.13.1 stdlib, subprocess.py]. Spawns with `creationflags=0x08000000`, stdout=file handle, exit-code propagation (`rc=1` crash / `rc=0` success both observed). Flag is Windows-only; posix callers must pass 0 (Mac-parity requirement for the shared spawn code path).
- `os.replace(tmp, dst)` over an existing target inside `logs/api/jobs/`: OK on NTFS (registry write pattern).
- Default event loop: `ProactorEventLoop`; `subprocess.run(communicate(timeout=...))` leaves the child alive on timeout (`TimeoutExpired; child alive: True`) — relevant to the GUI's `timeout=180` orphan hazard, not to API design (API jobs have no timeout).
- API-style open-file handle handoff (`open(path,'wb',buffering=0)` → `Popen(stdout=fh, stderr=subprocess.STDOUT)`) works; parent closes its copy after spawn (handle refcount; child keeps writing). No pipes anywhere → no pipe-buffer deadlock possible.
- Windows read handles held open block `os.replace` on the target (WinError 5 class) — already documented in-repo at api/state.py:62-63 ("Windows 上打开的读句柄会让管线的 os.replace 撞 WinError 5"); the registry reader (GET /v1/jobs) follows the Phase 2 open→read→close discipline.

### V5 — Machine state

- **Scheduled tasks:** of 201 tasks, the only relevant one is `gogo-api` (State Ready, last result `3221225786` = 0xC000013A Ctrl+C — the interactive-session shutdown pattern already recorded in STATE.md). The stale 主升浪 pipeline task is **absent** (see sign-off gate table).
- `logs/api/console.log` exists (api process writes there via run_api.bat); `logs/api/jobs/` does not exist yet; `data/api_token.txt` exists (content not read — never print it); API currently **not running** (curl /health refused; restart is part of deploy).
- Repo test baseline: `58 passed, 1 skipped in 2.26s` (pytest, pythonpath=., network-blocked autouse fixtures).
- streamlit 1.60.0 installed (GUI edits verifiable); pytest.ini: `pythonpath = .`, `testpaths = tests`.

## Standard Stack

### Core — zero new packages (Phase 2 precedent: "stdlib-only defensive layer"; package-legitimacy gate not triggered)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `subprocess.Popen` | 3.13.1 | Spawn pipeline scripts (arg-list, no shell) from a worker thread | Machine-verified this session; GUI precedent (sys.executable + script path + cwd=BASE) works today |
| Python stdlib `msvcrt.locking` / `fcntl.flock` | 3.13.1 | Cross-process single-flight lock file | Machine-verified semantics (V2); OS auto-release on holder death removes the entire stale-lock problem class |
| Python stdlib `hmac.compare_digest` | 3.13.1 | Constant-time token comparison (SEC-01) | Official stdlib constant-time primitive; docstring verified locally ("designed to prevent timing analysis") |
| Python stdlib `uuid.uuid4().hex` | 3.13.1 | job_id generation | Collision-free, URL-safe, path-composition-safe after regex gate |
| Python stdlib `os.replace` | 3.13.1 | Atomic job-file transitions (tmp + replace) | In-repo canonical pattern zt_pool.py:72-78 ([VERIFIED: scripts/daily/zt_pool.py:75-78] — `tmp = STATE_PATH + '.tmp'` … `os.replace(tmp, STATE_PATH)`); probe-verified over existing targets |
| fastapi 0.115.14 / starlette 0.46.2 | installed | Routers, dependencies, HTTPException, TestClient | Existing resident stack (phases 1-2), untouched |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `scripts.daily.config` LOG_DIR/DATA_DIR | in-repo | Path constants for jobs dir + token path (import chain os/sys/platform only, config.py precedent) | api modules import paths from config.py per D-02 discipline — never compute BASE |
| `api.boot.read_token` | in-repo | Token resolution (env `GOGO_API_TOKEN` first, `data/api_token.txt` fallback) | SEC-01 reuses the Phase 1 chain verbatim ([VERIFIED: api/boot.py:30-47]) — no new token loading code |
| `threading` + `threading.Lock` | stdlib | Per-kind claim mutex + job worker threads | One daemon thread per job; rare, short-lived, no pool sizing needed |
| `json` + `time` | stdlib | Registry payloads, epoch timestamps | Epoch seconds consistent with X-Data-Mtime convention |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `msvcrt.locking`/`fcntl.flock` (stdlib) | portalocker (PyPI) | portalocker is a thin wrapper over exactly these two primitives; not installed on this box; zero benefit for a 30-line helper. Stdlib keeps the zero-new-dependency discipline of phases 1-2 |
| `msvcrt.locking` (OS auto-release) | `O_CREAT|O_EXCL` lockfile / `filelock` package | O_EXCL leaves a stale file after a crash — needs PID-probe + delete races; OS byte-range locks auto-release on process death (probe V2) and deny nothing after death. Strictly superior for this use |
| thread + Popen (sync governance) | `asyncio.create_subprocess_exec` on Proactor | bpo-37381 family: subprocess+Proactor has exit-cleanup and transport bugs; sync endpoints already run on the Starlette threadpool so Popen never touches the event loop; asyncio gains nothing for a fire-and-forget job runner and complicates TestClient tests |
| Per-job JSON files + os.replace | Single aggregate registry file (one JSON list) | Per-job files give natural per-job write isolation (no cross-job contention), atomic per-transition replace, crash-safe partial state; aggregate file concentrates write contention and teardown risk. Directory scan cost is trivial at ≤500 files |
| Per-job file in `logs/api/jobs/{job_id}.json` + sibling `{job_id}.log` | Subdirectory per job `logs/api/jobs/{job_id}/` | Flat sibling files are simpler for pruning (count cap) and for the log-path contract; no per-job mkdir |

**Installation:** none. `npm`/`pip` install steps are not applicable — zero new packages (phase-level decision recorded in the Package Legitimacy Audit below).

**Version verification:** all stack versions verified on the live interpreter this session (Python 3.13.1, fastapi 0.115.14, uvicorn 0.51.0, starlette 0.46.2, streamlit 1.60.0, pytest suite green 58/1).

## Package Legitimacy Audit

> Gate protocol: this phase installs **zero** external packages — registry checks and postinstall scans are not triggered. The audit table records the considered-but-rejected candidates for the record.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| (none to install) | — | — | — | — | — | Approved — stdlib-only, matching Phase 2's zero-package decision |
| portalocker (considered only) | PyPI | mature | high | github.com/wolph/portalocker | not adopted | Rejected — thin wrapper over the exact msvcrt/flock primitives probed here; stdlib helper is 30 lines |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none.
*All [ASSUMED]-tagged recommendations: none — the stack is stdlib + already-installed framework code.*

## Architecture Patterns

### System Architecture Diagram

```
Consumer (curl / future scripts)
   │  POST /v1/actions/{kind}  + X-API-Key        GET /v1/jobs/{job_id}  + X-API-Key
   ▼                                                     │
┌────────────────────────── FastAPI (uvicorn, 127.0.0.1:8000, single process) ──────────────────────────┐
│  api/actions.py router ── dependencies=[Depends(require_api_key)] ── api/auth.py (compare_digest)     │
│                                                                                                        │
│  POST: kind in whitelist? ──no──► 404        GET: job_id matches ^[0-9a-f]{32}$? ──no──► 404           │
│        │yes                                          │yes                                             │
│        ▼                                              ▼                                                │
│  single-flight gate (Pattern 1):               read logs/api/jobs/{job_id}.json (open→read→close)      │
│   1. in-memory kind map hit → 409+job_id      → 200 {status, exit_code, log_path, ...}                 │
│   2. job_lock.acquire(kind) fails → 409       → 404 missing / 503 unreadable                            │
│   3. claim: map[kind]=job_id; write job file (pending, atomic)                                          │
│        ▼                                                                                                │
│  worker thread (per job): Popen([sys.executable, script, args], cwd=PROJECT_ROOT,                       │
│      env+PYTHONIOENCODING=utf-8, stdout=job log file handle, stderr=STDOUT,                             │
│      creationflags=CREATE_NO_WINDOW)  →  status running+pid (atomic)  →  proc.wait()                   │
│      →  status succeeded/failed + exit_code (atomic)  →  release lock + prune cap                      │
│  202 {job_id, kind, status} returned immediately by the request thread                                 │
└──────────────────────────────────┬─────────────────────────────────────────────────────────────────────┘
                                   │ lock file data/locks/{kind}.lock (byte-range, OS-auto-release)
                                   ▼
              scripts/daily/gui_dashboard.py refresh button (D-01): try same lock → held? st.warning,
              no run; free? run subprocess.run(..., timeout=180) → finally release
                                   │
              API kill/restart → api/main.main(): reload sweep marks pending/running → interrupted
```

Entry points: POST /v1/actions/{kind} (202/404/409/401/403), GET /v1/jobs/{job_id} (200/404/401/403), public GET /health + /health/ready + /v1/state/{name} (untouched). Processing stages: auth gate → whitelist/claim gate → durable pending record → thread-spawned Popen → atomic status transitions. Data flow: job state lives only in `logs/api/jobs/{job_id}.json`; the in-memory map is a derived cache for instant 409s.

### Recommended Project Structure

```
api/
├── main.py          # +2-line router include; +1-line reload_registry() in main() before uvicorn.run
├── auth.py          # NEW require_api_key dependency (D-10/D-11; reuses api.boot.read_token)
├── actions.py       # NEW protected router: POST /v1/actions/{kind}, GET /v1/jobs/{job_id}; KIND_CMDS map
├── jobs.py          # NEW registry + spawn governance: claim/spawn thread/finalize/reload/prune (pure fns)
└── (state.py, boot.py unchanged)
scripts/daily/
└── job_lock.py      # NEW shared cross-platform lock helper (msvcrt/fcntl), imported by api + GUI
tests/
├── test_actions.py  # NEW ACT-01/03 contract suite (fake scripts in tmp_path)
├── test_auth.py     # NEW SEC-01 suite (401/403/exemptions/log-leak grep)
└── test_jobs.py     # NEW ACT-02/SC5 registry + reload suite
.gitignore           # + data/locks/  (jobs under logs/* already ignored; sync_cloud whitelist untouched)
```

### Pattern 1: Single-flight claim (per-kind, in-memory + OS lock)

**What:** two gates before any spawn — the in-process kind map (instant) and the cross-process byte-range lock file (arbiter vs GUI). **Claim order:** OS lock first (the arbiter), then in-memory claim, then write the pending job file, then hand the run to a worker thread.

**Example (semantics verified by probes V2):**
```python
# scripts/daily/job_lock.py  (stdlib-only, side-effect-free import; dirs created at acquire time)
import os
try:            # Windows: byte-range lock, OS auto-releases on process death (probe-verified)
    import msvcrt
    def _try(fh):
        fh.seek(0); msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1); return True
    def _release(fh):
        try: fh.seek(0); msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError: pass
except ImportError:  # posix (Mac GUI parity)
    import fcntl
    def _try(fh): fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB); return True
    def _release(fh):
        try: fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError: pass

def acquire(kind, lock_dir):          # lock_dir injected (tests -> tmp_path)
    os.makedirs(lock_dir, exist_ok=True)
    fh = open(os.path.join(lock_dir, kind + ".lock"), "a+b")   # a+b: creates if missing, no truncate
    try:
        _try(fh)
        return fh                     # caller holds fd; close() releases
    except OSError:
        fh.close()
        return None                   # held by another process (API job or GUI refresh)
```
Lock files are **content-free** — probe V2 showed non-owners get `errno 13` reading the locked byte, so any holder-info payload in the file is unreadable anyway. The API's 409 `running_job_id` comes from its own in-memory map, not from the lock file. On a 409 where the map is empty but the lock is held, the holder is the GUI (or a manual run) — body carries no job_id (none exists).

**Kill-path notes (all probe-verified):** API killed → OS releases lock, thread dies, registry file stays `running` → next boot's reload sweep marks it `interrupted`. GUI killed → lock released. Manual console runs are outside the protocol (documented boundary; the roadmap's "any other entry point" = API + GUI + scheduled task, and the scheduled task is machine-verified absent).

### Pattern 2: Per-job registry file with atomic transitions

**What:** each job is one JSON file `logs/api/jobs/{job_id}.json`; every status transition rewrites it via tmp+`os.replace` in the same directory (zt_pool.py:72-78 pattern). GET reads the whole file open→read→close (Phase 2 handle discipline, api/state.py:62-63 WinError 5 note).

**Suggested fields** (research discretion per CONTEXT line 47; exit-code completion is the D-09-consistent default):
```json
{ "job_id": "<uuid4().hex>", "kind": "pipeline", "status": "pending|running|succeeded|failed|interrupted",
  "pid": null, "exit_code": null,
  "log_path": "<abs path to logs/api/jobs/<job_id>.log>",
  "cmd": ["python", "...\\scripts\\daily\\run_pipeline.py", "--fast"],
  "created_at": 0, "started_at": null, "finished_at": null }
```
- Statuses: `pending` (file written, thread starting) → `running` (Popen returned, pid recorded) → `succeeded` (exit 0) / `failed` (non-zero exit or spawn exception). `interrupted` is the terminal state assigned by the startup reload sweep to anything left `pending`/`running` after a crash — deterministic, no PID probe needed (ACT-05 v2 owns orphan adoption).
- Job log path: sibling flat file `logs/api/jobs/{job_id}.log` (CONTEXT discretion: "同级"). Response exposes the absolute log_path (local single-user consumer; error bodies stay path-free per D-10 style).
- **Retention cap (count-based, Phase 3 duty per CONTEXT line 48):** keep the newest 500 job files (json+log pairs); prune oldest **terminal-only** entries at finalize time and at the startup sweep. ~500 × tens-of-KB logs ≈ bounded tens of MB; OPS-03 rotation stays Phase 5.

**Example transition writer:**
```python
def write_job(jobs_dir, job):                       # atomic: tmp + os.replace (same dir = same volume)
    tmp = os.path.join(jobs_dir, f".{job['job_id']}.tmp-{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False)
    os.replace(tmp, os.path.join(jobs_dir, job["job_id"] + ".json"))
```

### Pattern 3: thread + Popen governance (event loop never touched; SC3)

**What:** the POST handler (a sync endpoint — Starlette runs sync endpoints on its threadpool) does the fast bookkeeping and returns 202; a dedicated **daemon worker thread** per job performs the slow sequence (Popen ~tens of ms, `proc.wait()` minutes). The event loop only ever handles dispatch; GET /health remains a pure in-memory endpoint with no middleware in front (auth is a router-level dependency on api/actions.py only — /health has no dependency, preserving HLT-01 purity and the Phase 1 suite).

**Example (spawn shape verified by probes V1/V4):**
```python
env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"   # V1: GBK+emoji crash matrix
flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0   # V4: 0x08000000
with open(log_path, "wb", buffering=0) as fh:               # no pipes -> no pipe-fill deadlock
    proc = subprocess.Popen(cmd, cwd=PROJECT_ROOT, env=env,
                            stdout=fh, stderr=subprocess.STDOUT, creationflags=flags)
# fh closed here; child keeps the inherited handle. Worker thread then: proc.wait() -> finalize.
```
- `cmd = [sys.executable, <abs path to scripts/daily/<script>>, *kind_args]` — arg list only, **never** `shell=True`; kind args come from the fixed D-09 map, no request data ever reaches argv (injection structurally impossible, Phase 4 SC4 keeps this property).
- `sys.executable` guarantees the same interpreter that runs the API (and the daily pipeline); GUI precedent uses `sys.executable` + `cwd=BASE` (gui_dashboard.py:88-90) — keep `cwd=PROJECT_ROOT`.
- The four fixed commands (D-09): pipeline → `run_pipeline.py --fast` (fast flag parse `'--fast' in sys.argv`, [VERIFIED: scripts/daily/run_pipeline.py:20]); morning-check → `morning_check.py --quick` ([VERIFIED: scripts/daily/morning_check.py:426]); backtest-weights → `backtest_v4.py` (guard: `if '--show-history' in sys.argv: show_history() else: main()` — no-arg runs the search, [VERIFIED: scripts/daily/backtest_v4.py:438-442]); health-check → `data_health_check.py` (no-arg main, [VERIFIED: scripts/daily/data_health_check.py:102-113]).

### Pattern 4: Startup reload sweep (SC5)

**What:** `api/jobs.reload_registry(jobs_dir)` — pure function: list `*.json`, load each, atomically rewrite any `pending`/`running` → `interrupted` (finished_at now), prune beyond cap. Called from `api/main.py main()` as a single added line **after** the SEC-03/token block and **before** `uvicorn.run` (boot ordering and diff-auditability preserved; no FastAPI lifespan change — the existing test convention is module-level `TestClient(app)` without a context manager, so boot-time behavior must live in `main()` or in directly-callable functions, not in lifespan hooks).

**Why interrupted (not failed):** the job never produced an exit code; failed implies the script ran and errored. `interrupted` is the honest terminal state for "API died while this was in flight" and makes SC5's "queryable in a terminal state" deterministic. Residual edge (documented, ACT-05 v2): if the API was killed without tree-kill, the child may survive as an orphan and could still be writing when a same-kind job is re-triggered after restart — the registry cannot distinguish this without PID adoption (v2 scope). The verification harness should kill the API with `taskkill /F /T /PID` (tree-kill) to keep the scenario clean.

### Pattern 5: Auth dependency with a public exemption list (SEC-01)

**What:** one dependency used at the router level; exemption is structural (public router vs protected router), not per-route middleware — no middleware touches /health at all.

```python
# api/auth.py — reuses the Phase 1 token chain; nothing is logged, nothing echoes the token
from fastapi import HTTPException, Request
from api.boot import read_token
def require_api_key(request: Request, token_path=None):
    provided = request.headers.get("X-API-Key")            # D: header name per REQUIREMENTS.md literal
    if provided is None:
        raise HTTPException(401, detail="missing API key",
                            headers={"WWW-Authenticate": "ApiKey"})   # D-10
    expected = read_token(token_path)                      # env GOGO_API_TOKEN first, file second
    if expected is None or not hmac.compare_digest(expected.encode(), provided.encode()):
        raise HTTPException(403, detail="invalid API key") # D-10: present-but-wrong -> 403
```
- Missing header → **401 + WWW-Authenticate**; present-but-wrong → **403** (D-10). Both constant-time via `hmac.compare_digest` (stdlib, locally docstring-verified). No token configured at all → fail-closed 403 (never 200; loopback boot auto-generates, so this is defensive only).
- `token_path = os.path.join(DATA_DIR, "api_token.txt")` resolved at call time (Phase 2 monkeypatch seam convention — tests point DATA_DIR at tmp_path and write their own token file).
- Exemption list (D-11): /health, /health/ready, GET /v1/state/{name} stay on the public routers; the new router (all POST /v1/actions/*, GET /v1/jobs/*) carries the dependency.
- Key hygiene: uvicorn `access_log=False` already set ([VERIFIED: api/main.py:73]) — no access log to leak headers; children never receive the key (not in spawn env, not in argv); error details never echo the token. Executor adds a grep-audit test asserting the token value appears nowhere in `logs/api/console.log` and in no job log after a real trigger.

### Recommended kind → script map (single source of truth in api/actions.py)

```python
KIND_CMDS = {
    "pipeline":        ("run_pipeline.py",     ("--fast",)),
    "morning-check":   ("morning_check.py",    ("--quick",)),
    "backtest-weights": ("backtest_v4.py",     ()),
    "health-check":    ("data_health_check.py", ()),
}
```
Unknown kind → 404 (`detail` path-free). Zero request-body parameters (D-09) — no body schema declared; a request body is ignored, not echoed, not logged.

### Anti-Patterns to Avoid

- **[ASSUMED] Pipes for child stdout:** capturing via `PIPE` without a draining reader deadlocks once the child fills the 64 KB pipe buffer. Redirect to a file handle instead (Pattern 3). The GUI's `capture_output=True` survives only because it is short-lived with `timeout=180`.
- **PYTHONUTF8=1 in the child env:** flips default `open()` encoding repo-wide; two pipeline sites rely on locale-default `open()` ([CITED: screen_candidates.py:126, capture_tboard_minute.py:73]). Manual runs stay GBK-default; API runs would silently write a second file dialect. `PYTHONIOENCODING=utf-8` only touches stdio — the observed crash vector.
- **Holder info inside the lock file:** probe V2 — other processes cannot read the locked byte (`errno 13`). Keep lock files content-free; carry holder context in the registry/in-memory map instead.
- **`O_EXCL` lockfiles:** stale-file races after crashes; the OS byte-range lock auto-release (probe V2) eliminates the whole class.
- **Single aggregate registry JSON:** write contention across jobs, no atomic per-job transitions, whole-file teardown risk. Per-job files (Pattern 2).
- **Auth middleware instead of router dependency:** a middleware would run on /health too, risking HLT-01 purity and P95 (SC3). Router-level dependency leaves the public surface structurally untouched.
- **Long-lived read handles on registry files:** blocks `os.replace` (WinError 5 class, api/state.py:62-63). Open→read→close per GET.
- **`job_id` composed into a path unchecked:** `GET /v1/jobs/../api_token.txt` class. Gate with `^[0-9a-f]{32}$` before composing the path; the kind whitelist is the equivalent gate on the trigger side.
- **Spawning on the event loop / async subprocess:** FastAPI sync endpoints already run on the threadpool; async create_subprocess_exec on Windows Proactor adds the bpo-37381 bug class for zero benefit. thread + Popen.
- **GUI orphan on timeout (pre-existing, D-01 scope):** `subprocess.run(..., timeout=180)` raises TimeoutExpired and **leaves the child running** (probe V4) with no lock release unless the GUI change wraps the call in try/finally around the lock fd. The lock change must release in `finally`, and on timeout the GUI should warn that a pipeline may still be running (v2 ACT-04 owns taskkill cleanup).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cross-process single-flight (API vs GUI vs task) | PID-probed O_EXCL lockfiles, in-process-only flags | OS byte-range lock: `msvcrt.locking` (win) / `fcntl.flock` (posix), one file per kind under `data/locks/` | Kernel auto-release on holder death (probe V2) removes stale-lock cleanup entirely; cross-process semantics verified incl. same-process denial |
| Constant-time key comparison | `==` or `secrets.compare_digest` hand-rolling | `hmac.compare_digest` | stdlib constant-time primitive, ASCII-safe, docstring-verified locally; `==` leaks timing |
| Durable job persistence | sqlite/aggregate JSON/process-memory-only | Per-job JSON files + atomic tmp+os.replace | Matches the repo's existing atomic-write pattern (zt_pool.py:72-78); crash-safe; no new engine; memory is a derived cache only |
| Job log capture | Pipe + read threads, temp files | Child stdout → per-job log file handle | File is written directly by the child; log path is the contract (SC1); zero buffer management |
| Token loading | New env/file parsing | `api.boot.read_token` (Phase 1 chain) | Already implements env-first-file-second, strip, failure→None ([VERIFIED: api/boot.py:30-47]) — reusing it keeps one token source of truth |
| Async task off the event loop | `asyncio.create_subprocess_exec` / `loop.run_in_executor` wrappers | Plain worker thread per job (sync endpoints already off-loop) | Proactor subprocess carries bpo-37381-class bugs; a thread is deterministic, testable with TestClient, and jobs are rare |

**Key insight:** every "hard" part of this phase (stale locks, pipe deadlock, encoding crashes, torn registry writes, loop blocking) has a machine-verified stdlib primitive or an in-repo canonical pattern that already solves it — the work is composition and discipline, not new machinery. Phase 2's zero-package decision is the right precedent; the Out-of-Scope table (Celery/Redis/RQ) is the confirmation that a queue is not wanted.

## Common Pitfalls

### Pitfall 1: Silent GBK job logs and emoji crashes (the #1 failure mode)
**What goes wrong:** job log files are GBK mojibake, or the child dies `rc=1` with `UnicodeEncodeError: 'gbk' codec can't encode character '\u26a0'` mid-run and the job is marked failed with a traceback that looks like a script bug.
**Why it happens:** children inherit the parent env; an interactively started API (no PYTHONUTF8 from run_api.bat) passes nothing down, and Python uses locale cp936 for redirected stdout. 80 print statements across the four scripts carry emoji-range chars; morning-check's decision-summary block prints them unconditionally.
**How to avoid:** always spawn with `env["PYTHONIOENCODING"] = "utf-8"` (probe V1, variants B/C byte-identical, rc=0). Never rely on inheritance from run_api.bat.
**Warning signs:** job log first bytes are `\xd6\xd0`-style GBK, or the log ends in a UnicodeEncodeError traceback.

### Pitfall 2: Locked-byte read denial surprises holder-info designs
**What goes wrong:** a process holding the lock cannot have its holder JSON read by others; readers get `PermissionError: [Errno 13]` (probe V2).
**Why it happens:** Windows byte-range locks deny reads of the locked byte from other processes.
**How to avoid:** content-free lock files; the 409's running_job_id comes from the API's own map; GUI-held locks return a generic 409. Never design a "read the lock file to see who holds it" protocol.

### Pitfall 3: Crash/restart leaves orphans that re-trigger double-runs
**What goes wrong:** killing only the API process (no tree-kill) leaves the child pipeline alive; after restart the reload sweep marks the job interrupted, a consumer re-triggers, and two runs of the same kind write data/ concurrently — violating SC2 in the crash edge.
**Why it happens:** Windows does not kill children when the parent dies; the registry cannot tell a live orphan from a dead one without PID adoption (v2 ACT-05).
**How to avoid:** document the edge; use `taskkill /F /T /PID <api>` for the SC5 kill scenario in verification; Phase 3's deterministic `interrupted` marking is the accepted contract (SC5 wording: terminal + queryable). ACT-05 v2 (PID-liveness adoption) is the backlogged remedy.
**Warning signs:** a job file says `interrupted` while `tasklist` still shows its pid.

### Pitfall 4: Event-loop or worker-thread blockage breaks P95 < 50 ms (SC3)
**What goes wrong:** /health latency spikes during a pipeline run.
**Why it happens:** any synchronous subprocess wait on a request path, or middleware added in front of /health.
**How to avoid:** Popen + wait live in a worker thread; auth is router-level; /health keeps zero dependencies (HLT-01 purity, Phase 1 suite pins it). Verification measures /health wall-time during a real run.

### Pitfall 5: Registry torn writes / replace failures
**What goes wrong:** a GET /v1/jobs/{job_id} sees a half-written JSON (500) or a finalize transition fails with WinError 5.
**Why it happens:** truncate-write instead of atomic replace; a concurrently open read handle on the target file.
**How to avoid:** every write is tmp+os.replace in the same directory; every read is open→read→close with no handle held across awaits (Phase 2 Pitfall 2 discipline, api/state.py:62-63).

### Pitfall 6: Encoding/locale assumptions in tests and parsing
**What goes wrong:** tasklist output parsing breaks or job-log assertions fail on a different console codepage.
**Why it happens:** tasklist emits localized GBK text on this machine (`信息: 没有运行的任务匹配指定标准。` for a dead PID — probe V3).
**How to avoid:** match raw ASCII pid bytes `b'"{pid}"'` in `/FO CSV /NH` output, or use ctypes OpenProcess (probe V3); tests write/read fake-script logs as UTF-8 (the API forces it).

### Pitfall 7: GUI changes breaking Mac parity
**What goes wrong:** the D-01 GUI edit imports a Windows-only lock module, or crashes streamlit on Mac (same source file both machines).
**Why it happens:** job_lock must run on both platforms.
**How to avoid:** the helper splits msvcrt/flock by ImportError (Pattern 1 skeleton); Mac keeps its no-crontab-lock convention (D-03). GUI must also release the lock in `finally` so the streamlit `timeout=180` path cannot strand a held lock (probe V4: TimeoutExpired leaves the child alive).

## Code Examples

Verified patterns from this session's probes + in-repo reads.

### Example 1: job_lock.py cross-platform helper (semantics probe-verified)
See Pattern 1 skeleton above. API usage (api/jobs.py, per kind):
```python
fd = job_lock.acquire(kind, LOCK_DIR)          # LOCK_DIR = data/locks (module attr, call-time read)
if fd is None:
    running = _map.get(kind)                   # in-memory claim table
    if running:
        raise HTTPException(409, detail={"message": f"{kind} already running",
                                          "running_job_id": running["job_id"]})
    raise HTTPException(409, detail={"message": f"{kind} already running (another entry point)"})
```

### Example 2: job runner thread (spawn + transitions; probe V1/V4 shapes)
```python
def _run_job(job):
    log_path = os.path.join(JOBS_DIR, job["job_id"] + ".log")
    job["log_path"], job["status"] = log_path, "running"          # atomic write
    env = dict(os.environ); env["PYTHONIOENCODING"] = "utf-8"     # V1 finding — mandatory
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0 # V4 finding
    try:
        with open(log_path, "wb", buffering=0) as fh:
            proc = subprocess.Popen(job["cmd"], cwd=PROJECT_ROOT, env=env,
                                    stdout=fh, stderr=subprocess.STDOUT,
                                    creationflags=flags)
        job["pid"] = proc.pid                                     # atomic write
        job["exit_code"] = proc.wait()
        job["status"] = "succeeded" if proc.exit_code == 0 else "failed"
    except Exception as e:                                        # spawn failure -> failed, no crash
        job["status"], job["exit_code"] = "failed", None
    job["finished_at"] = int(time.time())                         # atomic write; release lock; clear map
```

### Example 3: startup reload sweep (SC5; pure, unit-testable)
```python
def reload_registry(jobs_dir):
    """Scan logs/api/jobs/*.json; pending/running -> interrupted (terminal); prune beyond cap."""
    for name in os.listdir(jobs_dir):
        if not name.endswith(".json") or name.startswith("."):
            continue
        path = os.path.join(jobs_dir, name)
        try:
            with open(path, encoding="utf-8") as f: job = json.load(f)
        except (OSError, ValueError):
            continue
        if job.get("status") in ("pending", "running"):
            job["status"] = "interrupted"; job["finished_at"] = int(time.time())
            _write_job_atomic(jobs_dir, job)      # tmp + os.replace (Pattern 2)
    _prune(jobs_dir, cap=500)                     # terminal-only, oldest by mtime, json+log pairs
```

### Example 4: SEC-01 test shapes (fake-script based, CONTEXT-prescribed)
```python
# fake script (tmp_path, written by the test): records argv, sleeps briefly, exits with given code
FAKE = "import json,sys,time;json.dump(sys.argv[1:],open(sys.argv[1],'w'));time.sleep(0.2);sys.exit(int(sys.argv[2]))"
# trigger with monkeypatched KIND script path -> fake script; poll GET /v1/jobs/{id} to terminal;
# assert log_path exists; assert argv == [script, '--fast'] proves arg-list spawn w/o shell.
# 409 test: first trigger a fake that sleeps 2s; second POST same kind -> 409 + running_job_id.
# auth tests: no header -> 401 + WWW-Authenticate; wrong -> 403; valid -> 202; /health and
# /v1/state stay 200 without a header; token string absent from job log and console log bytes.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| asyncio subprocess unsupported on Windows Selector loop | ProactorEventLoop supports subprocesses (default since 3.8); exit-cleanup bugs tracked (bpo-37381 family, e.g. gh-81562) | Python 3.8 | Proactor subprocess is usable but still not worth it for fire-and-forget job runners — sync thread + Popen stays deterministic; cited for the research question "thread+Popen vs create_subprocess_exec" |
| Lockfile packages with stale-lock cleanup (portalocker, filelock, O_EXCL recipes) | OS byte-range locks (msvcrt/flock) with kernel auto-release | (design decision, this phase) | Stale-lock/PID-probe machinery unnecessary on Windows — verified by kill probe |
| `open('w')` truncate writes for mutable single-point state | tmp + `os.replace` atomic writes | established in-repo (zt_pool.py:72-78), extended this phase to registry transitions | Registry can never be observed torn; crash leaves last-good state |
| Locale-default stdio for spawned scripts | Explicit `PYTHONIOENCODING=utf-8` child env | this phase (probe V1) | Job logs are deterministic UTF-8; GBK emoji-crash class eliminated |
| GUI/timeout leaves orphan children | finally-release lock + warning (D-01 scope); taskkill tree-kill when v2 ACT-04 lands | this phase / v2 | Single-flight holds across GUI path; orphan reaping is backlog |

**Deprecated/outdated:**
- `auto_start.bat` + `install_scheduled_task.ps1` (stale `C:\Users\Davis\Desktop\主升浪` BASE): the task they installed is machine-verified absent; the files are dead repo artifacts — leave untouched this phase (part of the 116-file boundary), do not re-register.
- GUI's `capture_output=True, text=True` refresh: silently degrades to "部分失败" on emoji prints (probe V1 pipe variant); not fixed this phase (D-01 lock-only scope) but flagged for Phase 4/5 hardening consideration.

## Assumptions Log

> All claims tagged [ASSUMED] in this research. Everything else carries probe/repo/doc evidence inline.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | A console-less spawn of python.exe without CREATE_NO_WINDOW flashes a visible window under the Task Scheduler context (could not be observed from this probe session — flag value, acceptance, and rc propagation were verified; the window-flash symptom itself is standard documented Windows behavior) | Real-Machine V4 | Wrong → cosmetic console flash during API-triggered runs; CREATE_NO_WINDOW is harmless if unnecessary |
| A2 | Starlette runs sync (def) endpoints on a threadpool, so the POST handler's bookkeeping never blocks the event loop | Patterns / SC3 | Wrong → need explicit run_in_threadpool; design review + P95 verification catches it |
| A3 | fcntl.flock on macOS behaves equivalently (advisory, auto-release at process death) to the probed Windows semantics; Mac GUI lock join is parity-only | Pattern 1 / D-01 | Wrong → Mac GUI lock could misbehave; Mac is a GUI-manual machine (no crontab lock), impact low; verify at Mac-side rollout |
| A4 | Child stdout bytes never contain the API key (children are unmodified scripts that never see the key) | Pitfall 6 / SEC-01 | Wrong → key-in-log leak; covered by the grep-audit test the executor adds |
| A5 | The 4 fake-script test approach fully exercises spawn/409/auth without touching real pipelines or network | Validation | Wrong → real-machine smoke verify step (per SC1-SC5) catches integration gaps before phase gate |
| A6 | Registry JSON files written by this phase remain readable by consumers across restarts even if a future phase changes the schema (schema is additive-tolerant) | Pattern 2 | Wrong → schema change breaks pollers; keep field set additive; documented as consumer surface |

## Open Questions

1. **409 response body shape for the "running job" case**
   - What we know: D-10 pins 401/403 detail style to minimal `{"detail": ...}`; ACT-02/SC2 require the 409 to carry the running job_id; Phase 2 used plain-string details; WR-02 (machine-readable error codes) is deferred pending user confirmation.
   - What's unclear: whether 409's detail should be a plain string with the id interpolated, or an object `{"message": ..., "running_job_id": ...}`.
   - Recommendation: object detail on 409 only (`{"detail": {"message": "pipeline already running", "running_job_id": "..."}}`) — the id is a machine-consumed value (the consumer polls it), which a prose string would force consumers to parse; 401/403 stay plain-string per D-10. Planner should pin this in the plan and mirror it in tests; no user sign-off needed (discretion area).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python interpreter | Spawning all four scripts | ✓ (sys.executable) | 3.13.1 @ AppData\Local\Programs\Python | — |
| fastapi / starlette / uvicorn | API endpoints, TestClient | ✓ | 0.115.14 / 0.46.2 / 0.51.0 | — |
| pytest | Suite | ✓ | 58 passed, 1 skipped baseline (2.26s) | — |
| streamlit | GUI D-01 edit verification | ✓ | 1.60.0 | — |
| msvcrt / fcntl | Lock helper | ✓ (msvcrt on win; fcntl posix-only, not present on win — ImportError split) | stdlib | — |
| Task Scheduler | gogo-api autostart | ✓ task Ready | — | manual `run_api.bat` (console Ctrl+C exit pattern noted, 0xC000013A — Phase 5 ops item) |
| Running API service | End-to-end verification of new endpoints | ✗ currently down | — | restart via task/manual as part of phase verification |
| NTFS C: | Byte-range locks, os.replace | ✓ | NTFS (probe-verified) | — |
| network (data sources) | Real pipeline/morning-check runs (job content) | ✓ for real runs; tests must stay offline (autouse fixture) | — | fake scripts for the suite |

**Missing dependencies with no fallback:** none — the phase is stdlib + already-installed stack.
**Missing dependencies with fallback:** the resident API is not running at research time; phase verification restarts it (Task Scheduler task exists, or `run_api.bat`).

## Validation Architecture

> nyquist_validation: true in .planning/config.json — included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (pythonpath=., testpaths=tests) on Python 3.13.1 |
| Config file | pytest.ini (no plugin config needed) |
| Quick run command | `python -m pytest tests/test_actions.py tests/test_auth.py tests/test_jobs.py -q` |
| Full suite command | `python -m pytest -q` (baseline 58 passed, 1 skipped in 2.26s) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ACT-01 | Four kinds spawn the right script with fixed arg list, no shell; 202+job_id immediate; log path exists | unit/integration (fake scripts in tmp_path; monkeypatched JOBS_DIR + script paths) | `pytest tests/test_actions.py -x` | ❌ Wave 0 |
| ACT-02 | Job lifecycle pending→running→succeeded/failed via GET /v1/jobs/{job_id}; exit 0 vs non-0; unknown id 404; log path in body | unit/integration | `pytest tests/test_actions.py -x` | ❌ Wave 0 |
| ACT-03 | Overlap → 409 with running job_id; re-trigger after completion → 202; lock held by a *separate process* (spawned child holding job_lock) → 409; after holder kill → 202 | unit/integration (real cross-process lock via spawned python) | `pytest tests/test_actions.py -x` | ❌ Wave 0 |
| SEC-01 | Missing key → 401 + WWW-Authenticate; wrong → 403; valid → 202; public endpoints (health/ready/state) still open; no process spawn on 401/403 (assert via job dir empty); token value absent from job logs + console.log (grep audit) | unit/integration | `pytest tests/test_auth.py -x` | ❌ Wave 0 |
| ACT-02/SC5 | reload_registry: fixture registry with pending/running files → interrupted terminal; cap pruning keeps ≤500; GET queryable after simulated restart | unit (pure function on tmp_path) | `pytest tests/test_jobs.py -x` | ❌ Wave 0 |
| SC3 | GET /health answers during a real (fake long-sleep) job; P95 < 50 ms | smoke/perf (TestClient loop or live uvicorn) | `pytest tests/test_jobs.py::test_health_latency_during_job -x` + live verify step | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_actions.py tests/test_auth.py tests/test_jobs.py -q`
- **Per wave merge:** `python -m pytest -q` (full suite)
- **Phase gate:** full suite green before `/gsd-verify-work`, plus the real-machine SC5 verify (start real pipeline job via API → `taskkill /F /T` the API → restart → GET job shows interrupted; SC1-SC4 manual smoke per success criteria).

### Wave 0 Gaps
- [ ] `tests/test_actions.py` — covers ACT-01/02/03 contract (fake scripts, cross-process lock child)
- [ ] `tests/test_auth.py` — covers SEC-01 (401/403/exemptions/spawn-block/no-leak grep)
- [ ] `tests/test_jobs.py` — covers registry transitions, reload sweep (SC5), pruning cap, /health latency during job
- [ ] `tests/conftest.py` — optional additions: tmp token-file helper; `api.jobs.JOBS_DIR`/`LOCK_DIR` monkeypatch helpers (existing network-block + env-clean fixtures are reused as-is)
- No framework install needed (pytest present, baseline green).

## Security Domain

> security_enforcement: true, security_asvs_level: 1 (.planning/config.json) — included.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Single API key (no user model — REQUIREMENTS Out-of-Scope: JWT/OAuth/用户管理). X-API-Key header, `hmac.compare_digest` constant-time compare (stdlib, locally verified). 401 missing + WWW-Authenticate / 403 wrong per D-10; fail-closed when no token configured |
| V3 Session Management | no | Stateless API key per request; no sessions/cookies exist anywhere in the stack |
| V4 Access Control | yes (route classification) | D-11 exemption list is structural: public routers (/health, /health/ready, /v1/state) vs protected router (POST /v1/actions/*, GET /v1/jobs/*) with router-level dependency. No per-route drift possible |
| V5 Input Validation | yes | kind → fixed whitelist map (unknown → 404, nothing reaches argv); job_id gated `^[0-9a-f]{32}$` before path composition; request body not accepted (D-09 zero-param); error bodies path-free (D-10 style) |
| V6 Cryptography | partial | compare_digest for timing resistance; token generation already `secrets.token_urlsafe(32)` (Phase 1, api/boot.py:71); no TLS needed on loopback bind (documented deployment posture; off-loopback is fail-closed by SEC-03 boot check) |

### Known Threat Patterns for FastAPI-on-Windows subprocess trigger

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Token timing side-channel on header compare | Information Disclosure | `hmac.compare_digest` (constant-time); missing-header path skips compare with straight 401 |
| Token leak via logs/errors | Information Disclosure | `access_log=False` already ([VERIFIED: api/main.py:73]); no header/token logging anywhere; error details never echo token/paths; children never receive the key; executor grep-audit test asserts absence |
| Key/secret at rest | Information Disclosure | Reuses Phase 1 chain: env `GOGO_API_TOKEN` first, `data/api_token.txt` (gitignored, same-commit) — [VERIFIED: api/boot.py:30-47, .gitignore entry `data/api_token.txt`] |
| Spawn/command construction via kind | Tampering / RCE | Kind is a fixed-map lookup; command argv is constants only — user input never reaches argv; `shell=False` always (arg-list spawn, SC1) |
| Path traversal via job_id | Tampering | `^[0-9a-f]{32}$` gate before any path join; unknown → 404 |
| Registry/log tampering or stale data served | Tampering | Atomic replace transitions; GET reads whole file fresh; consumers see last-good state |
| Unauthorized re-trigger / double execution | DoS / integrity | Single-flight per kind (in-memory + OS lock); GUI and scheduled-task competitors covered (task machine-verified absent); auth blocks all trigger paths |
| LAN exposure | Spoofing | Default bind 127.0.0.1; non-loopback requires pre-existing token at boot (SEC-03 ordering preserved); residual WR-01 hardening is Phase 4 (D-12) |
| Crash-state inconsistency | DoS | Durable per-job registry + deterministic interrupted sweep (SC5); OS lock auto-release on death |

## Sources

### Primary (HIGH confidence — real-machine probes, this session)
- Real-machine probe suite 2026-09-03 under `%TEMP%\gsd_p3_probe`: encoding matrix (variants A/B/C + GUI-style pipe; quoted byte evidence), msvcrt lock suite (empty-file lock, same-process denial, cross-process errno 13, read-denial of locked byte, taskkill /F auto-release, re-acquire), tasklist/ctypes PID probes, CREATE_NO_WINDOW spawn + rc propagation, os.replace-over-existing in logs/api/jobs, default `ProactorEventLoop`, `locale cp936`
- In-repo reads (Read tool, this session): api/main.py, api/boot.py, api/state.py, scripts/daily/config.py, scripts/daily/run_pipeline.py, tests/conftest.py, scripts/daily/morning_check.py:415-444, scripts/daily/data_health_check.py:95-119, scripts/daily/gui_dashboard.py:60-99, scripts/daily/backtest_v4.py:376-389 + 419-443, scripts/daily/auto_start.bat, scripts/daily/zt_pool.py:66-83, scripts/daily/sync_cloud.py (whitelist grep), .gitignore, .planning/config.json, 03-CONTEXT.md, REQUIREMENTS.md, ROADMAP.md, STATE.md, 02-RESEARCH.md (format), pytest.ini
- Machine state queries: scheduled-task enumeration (201 tasks; only gogo-api relevant), gogo-api LastTaskResult 0xC000013A, filesystem NTFS, api_token.txt existence, API not running, baseline pytest 58 passed/1 skipped

### Secondary (MEDIUM confidence)
- WebSearch: bpo-37381 = ProactorEventLoop subprocess exit-cleanup bug family (cpython gh-81562, 2019, Windows 3.7); asyncio platform docs — subprocess support on ProactorEventLoop is default-on since Python 3.8; bpo-45896 doc-conflict cleanup (https://github.com/python/cpython/issues/81562)
- Local stdlib docstrings/constants (Python 3.13.1): `subprocess.CREATE_NO_WINDOW == 0x8000000`, `msvcrt.locking` semantics ("The locked region of the file extends from the current file position for nbytes bytes"), `hmac.compare_digest` ("uses an approach designed to prevent timing analysis")

### Tertiary (LOW confidence — flagged)
- None used for load-bearing claims; remaining unknowns are in the Assumptions Log / Open Questions.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every primitive machine-verified or already installed and running
- Architecture: HIGH — spawn/registry/lock/auth patterns composed from verified primitives and in-repo precedents; residual crash-edge (orphan) explicitly bounded to ACT-05 v2
- Pitfalls: HIGH for encoding/lock/PID findings (probe evidence quoted); MEDIUM for window-flash and Mac-flock parity (A1/A3)

**Research date:** 2026-09-03
**Valid until:** ~2026-10-03 (30 days; fast-moving items: none — stack is pinned stdlib + installed versions)
