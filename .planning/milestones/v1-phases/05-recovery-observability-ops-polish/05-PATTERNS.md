# Phase 5: Recovery, Observability & Ops Polish — Pattern Map

**Mapped:** 2026-09-04
**Files analyzed:** 14 (4 new + 7 modified + 2 doc + 1 conditional-no-change)
**Analogs found:** 13 / 14 (1 no-analog row carries machine-verified constraint facts instead)
**Windows facts machine-verified this session:** 2 experiments (see "Windows 文件共享约束" section — rotation mechanism constraint)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `api/log_housekeep.py` (NEW, D-32/D-33/D-34) | utility (pure functions) | file-I/O | `api/boot.py` (pure-function module, explicit paths, no prints) + `api/jobs.py:222-254` (prune-by-cap semantics to delegate to) | exact |
| `api/health.py` (NEW, discretion: module vs inline) | route/controller | request-response | `api/private.py:36-55` (secret-router skeleton, router-level gate) + `api/state.py` (module conventions) + `api/main.py:30-49` (uptime anchor + dict-return route) | exact |
| `tests/test_log_housekeep.py` (NEW) | test | file-I/O | `tests/test_boot.py:23-26,44-67` (pure-fn + tmp_path + monkeypatch) + `tests/test_jobs.py:239-335` (job-file seed helper + prune-cap test shape) | exact |
| `tests/test_health_details.py` (NEW) | test | request-response | `tests/test_private.py:68-116` (autouse isolation fixture + token helpers + contract sections) + `tests/test_jobs.py:239-261` (registry seeding) | exact |
| `api/main.py` (MOD) | config (boot + route registration) | — | itself (boot sequence L57-108; /health route L46-49; include region L52-54) | exact |
| `tests/test_auth.py` (MOD — MANDATORY) | test | — | itself — SC2 route-by-route audit L332-373 **breaks** when /health/details lands unless added to `expected_secret` | exact |
| `api/jobs.py` (MOD, conditional: D-33 cap 500→20) | service (registry) | file-I/O | itself — `PRUNE_CAP = 500` at L26; boot prune already implemented in `reload_registry` L219 | exact |
| `tests/test_jobs.py` (MOD, conditional on cap change) | test | file-I/O | itself — cap pin test L311-335 pins 500 semantics, must be rewritten if PRUNE_CAP changes | exact |
| `tests/test_boot.py` (MOD, conditional: LOG_DIR seam) | test | — | itself (main()-calling tests L118-218 patch `api.main.DATA_DIR`; gain LOG_DIR patch if main() imports LOG_DIR) | exact |
| `.planning/PROJECT.md` (MOD, doc — TRACKED) | doc (classification policy) | — | itself — 机密级 row L64 is the authoritative classification table README is checked against | exact |
| `README.md` (MOD, doc — **gitignored local-only** by policy) | doc (contract + known-limits) | — | itself (API section L69-98; endpoint table L73-83; known-limits L85-93) | exact |
| `run_api.bat` (NO CHANGE recommended) | config (launch) | — | itself (L5 `>> logs\api\console.log 2>&1` is the rotation constraint source — see machine facts) | exact |

**D-36 (15:30 task) and D-35 (Mac checklist) deliver command text / checklist records — no code file.** D-36's verify-only output records into STATE.md / phase SUMMARY (STATE.md:146 is the [P3→P5] tracker row).

## Pattern Assignments

### `api/log_housekeep.py` (utility, file-I/O) — NEW (D-32/D-33/D-34)

**Analog:** `api/boot.py` (pure-function layer conventions) + `api/jobs.py` `prune`/`reload_registry` (cap-prune semantics + OSError tolerance).

**Module docstring + purity conventions — copy `api/boot.py:1-13` shape verbatim:**
```python
"""启动辅助模块: 回环检测 / API token 读取与生成 (SEC-03, D-03/D-04/D-05)。

boot 序列中的纯函数层: 每个函数只依赖显式传入的路径参数与环境变量,
不计算路径常量、不做控制台输出 (D-05 的单句提示约束统一由 api/main.py 保证)。
...
"""
```
- 纯函数契约 (boot.py:3-4): 每个函数只依赖**显式传入的路径参数**; 模块不做控制台输出 —— 任何轮转告警 print 统一归 `api/main.py` 的 boot 块 (main.py:79-92 的 ERROR/WARNING print 是唯一出口; ASCII-only, Pitfall 5)。
- 模块导入零副作用 (boot.py 无 import 副作用; jobs.py:12-14 同纪律): 不建目录、不读文件、不 print; 常量定义除外。
- 工程常量直接写模块顶部 (05-CONTEXT specifics: "工程常量写进计划任务即可, 不需要配置化, 单用户工具"): 如 `MAX_CONSOLE_LOG_BYTES = 5 * 1024 * 1024`、`JOB_LOG_CAP = 20` —— 形态照抄 `api/jobs.py:26`:
```python
PRUNE_CAP = 500  # registry 上限: 只保留最新 500 个终态 job (json+log 对)
```

**console.log 轮转纯函数 — 无 repo 内 rename-rotate 前例** (最接近的原子改名是 `jobs.write_job` 的 tmp+os.replace, jobs.py:59-85, 但它同进程自持句柄场景不同)。函数形态必须容忍失败并返回状态 (调用方 main() 决定是否打警告), 参照 `prune` 的"绝不致命"纪律 (jobs.py:232 OSError → return; jobs.py:251-254 per-remove `except OSError: pass`):
```python
def rotate_console_log(path, max_bytes=MAX_CONSOLE_LOG_BYTES):
    """console.log 超过 max_bytes -> 重命名 console.log.1 (保留一份历史)。

    返回 (rotated: bool, error: str|None); 永不上抛 —— 轮转失败只降级为
    main() 的一句 ASCII stderr 警告, 绝不阻止 boot。
    """
```
- **Windows 硬约束 (本机实机验证, 见下节):** 以 run_api.bat / Task Scheduler (`cmd /c run_api.bat`) 启动时, console.log 被当前进程继承的 cmd `>>` 句柄持有 —— rename 必得 PermissionError [WinError 32]。函数本体保持"尝试 rename → OSError 记状态返回"; **真正让 rename 成功所需的 std-handle 关闭/重指 (fd 1/2 dance) 属于 main() 的编排职责** (main.py 已是 SEC-03 打印的编排者), 计划必须含一条真机验证步骤 (03-04 "adapt-and-record" 先例: 03-04-SUMMARY.md:191)。
- OSError 容错细节照抄 `jobs.prune` (jobs.py:227-232): `os.listdir` 的 OSError → 直接返回不致命。

**job 对修剪 — 委托 `jobs.prune`, 不复制逻辑** (`api/jobs.py:222-254` 已实现按 json mtime 保留最新 cap 个终态对、非终态永不删、逐文件 OSError 容错、json+log 成对删):
```python
def prune_job_logs(base=None, cap=JOB_LOG_CAP):
    """boot 时 job registry 修剪 (D-33): 委托 api.jobs.prune(base, cap)。"""
    import api.jobs  # 或模块顶部 import (jobs.py 无环: 不 import 本模块)
    return api.jobs.prune(base or api.jobs.jobs_dir(), cap)
```
- **D-33 cap=20 vs 现状 PRUNE_CAP=500 冲突 (必须由 planner 裁定, 事实如下):**
  - `reload_registry` (jobs.py:191-219) 每次 boot 尾部已调 `prune(base, cap)` (L219, 默认 500); `run_job` 终态 also 调 `prune(base, PRUNE_CAP)` (jobs.py:170)。"启动时 prune" 机制 Phase 3 已存在 —— D-33 的 N=20 是**收紧常量的决定**。
  - 只靠 housekeep boot 时传 cap=20 **不构成 20 对硬上限**: 连续运行数周无重启时, 每次 job 终态的 `run_job` prune 仍按 500 保留 → 会涨过 20 (SC2 "weeks of continuous running")。**要真满足 D-33, 唯一单源做法是 `jobs.PRUNE_CAP` 500→20** (jobs.py:26), 运行时 + boot 同步生效; log_housekeep 的 boot 修剪与 reload_registry 尾部 prune 同 cap 则幂等无害。
  - 连带必改: `tests/test_jobs.py:311-335` `test_reload_sweep_prune_cap_keeps_500_newest_terminal` (seed 505 断言 500) → 按 cap=20 重写 (seed 25, 断言保留最新 20、最旧 5 对 json+log 被删、非终态存活)。常数位 (常量 vs config) 是 CONTEXT 显式 discretion。
- 排序依据照抄 prune: json 文件 `os.path.getmtime` (jobs.py:243) 最旧在前 (jobs.py:248)。CONTEXT discretion "prune 排序依据——job 创建时间戳" 即此现成行为。

### `api/health.py` (route/controller, request-response) — NEW (D-29..D-31; discretion: 独立模块 vs main.py 内联)

**推荐独立模块** (理由 + 形态): 与 state/private/actions 三模块一致 (main.py:20-23 import + 52-54 include_router 两行式, 04-PATTERNS 惯例); 测试隔离缝只落 api.health.* 模块 attr, 不污染 main.py 的缝面。**内联备选**: main.py:46-49 `/health` 旁直接加 `@app.get("/health/details")` —— anchor 直取零成本, 但 main.py 膨胀 + 测试缝面波及 test_auth/test_state 等 fixture。两种形态下列模式都适用。

**Router 骨架 — 抄 `api/private.py:32-55` (机密级路由样板, 逐行对照):**
```python
import os
import time
from datetime import datetime, timezone      # ISO 转换 (D-29) — 新增, 无先例 (纯 stdlib, SC4 允许)
from importlib.metadata import version       # D-30 versions — 新增, 无先例 (纯 stdlib)
from fastapi import APIRouter, Depends
from api.auth import require_api_key          # D-10 同一依赖对象 (router 级, 永不中间件)
from api import jobs                          # 读 registry; import 无副作用 (jobs.py:12-14)
from scripts.daily.config import DATA_DIR, LOG_DIR   # 调用时组合 (monkeypatch 缝, state.py:66 惯例)

router = APIRouter(dependencies=[Depends(require_api_key)])  # private.py:55 逐字; SEC-02 机密级
```
- **不**需要 Response/raw 透传 — body 是聚合 JSON (dict), FastAPI 序列化即可, 形态 = `/health` 的 dict 返回 (main.py:46-49) 与 GET /v1/jobs/{job_id} 返回 job dict (actions.py:145)。
- 模块导入零副作用 + ASCII (private.py:27-30 纪律逐字适用); 新 import 全部 stdlib/fastapi/既有 api 模块 — 无网络能力 (SC4)。

**uptime — 复用 main.py:30-32 锚点 (D-30), 两种接法 (planner 裁定):**
```python
# main.py:30-32 (现状, 不可移动的锚点定义)
# uptime 锚点: 模块导入时刻 (对 uvicorn.run 即进程启动时刻)。
_START = time.monotonic()
```
- 独立模块不能顶层 `from api.main import _START` (main.py import api.health 发生在 L23, 早于 L32 的 _START 赋值 → circular ImportError)。接法 A (零 main.py 改动): handler 内函数级惰性 import —— 先例 main.py:105-108 (`# 惰性导入: 测试 import api.main 时无需 uvicorn 依赖`), 请求时 api.main 已完整加载, sys.modules 命中无成本。接法 B (推荐, 消除下划线跨模块读): main.py 在 _START 旁加公开函数 `def uptime_seconds(): return int(time.monotonic() - _START)`, 原 /health (main.py:49) 与 details 共用。两法等价; 行为钉 = test_health.py:40-43 (uptime 单调不减)。
```python
def uptime_seconds():  # main.py, 紧邻 _START (L32); /health L49 改为调用它 (行为不变)
    return int(time.monotonic() - _START)
```

**last_check.health_job — registry 扫描, 两个现成骨架拼接:**
- listdir 过滤骨架: `jobs.prune` (jobs.py:227-237) — `os.listdir(base)`, `name.endswith(".json") and not name.startswith(".")`, stem = `name[:-len(".json")]`; listdir OSError → 无 job (null), 绝不致命。
- 逐文件读取: `jobs.read_job(stem, base)` (jobs.py:88-99) — 缺失 None / 损坏 ValueError → 跳过 (prune 的 except (OSError, ValueError): continue 在 jobs.py:244-245, 同形)。
- 文件选择 + 排序形态: `api/private.py:94-110` `_latest_candidates_file` (listdir → 条件过滤 → 排序取极值) 是"扫描目录选一"的模块内私有 helper 先例 — health.py 内写同形 `_latest_succeeded_health_check()`: 过滤 `kind == "health-check"` (kind 名在 `api/actions.py:55` KIND_CMDS) 且 `status == "succeeded"`, 按 `finished_at` (epoch int, jobs.py:54 字段集) 取最大; 无匹配 → null。目录 = `jobs.jobs_dir()` (jobs.py:33-35, 调用时解析 — 测试只需 patch `api.jobs.LOG_DIR`)。
- ISO 转换 (D-29 "ISO 或 null"): `datetime.fromtimestamp(finished_at, tz=timezone.utc).isoformat()` — 全库首个 ISO 输出 (state/private 用 epoch 秒头, state.py:93-94); 纯 stdlib, 无网络。

**last_check.market_state_mtime — os.stat:** `os.path.join(DATA_DIR, "market_state.json")` 调用时组合 (state.py:66 / STATE_FILES 映射 state.py:29-33); `os.stat(path).st_mtime` → ISO。缺失语义 planner 裁定: (a) null (与 health_job 对称, 最少新契约); (b) 503 `state file unavailable` — 冻结码表行已存在 (errors.py:46, /health/ready 同文)。**错误体约束 (D-31): 404/503 走 04-01 冻结信封, 冻结表不可加行 (errors.py:10-11) — auth 401/403 自动由 require_api_key raise, 文本 `missing API key`/`invalid API key` 已在表内 (errors.py:34-35), 本端点不需要任何新 raise 文本。**

**versions — D-30 惰性读, 无 repo 先例 (grep 验证: importlib.metadata / sys.version 零使用):**
```python
def _versions():  # handler 内/私有函数内调用 (惰性; 只读本地 dist-info, 无网络)
    return {
        "python": sys.version,                       # D-30 明确 sys.version
        "uvicorn": version("uvicorn"),               # importlib.metadata; PackageNotFoundError 兜底
        "fastapi": version("fastapi"),
    }
```
- PackageNotFoundError 兜底 (return e.g. "unknown" 或 None) 属 planner 决定; STACK.md:105 已机器验证 fastapi 0.115.14 / uvicorn 0.51.0 在机 (research/STACK.md, tracked)。

**响应形状 (D-29, 键序建议固定):**
```python
return {
    "versions": {...}, "uptime_seconds": N,
    "last_check": {"health_job": iso_or_null, "market_state_mtime": iso_or_null},
}
```

**SC2 审计连带 (必改, 否则套件红):** `tests/test_auth.py:349` `expected_secret` 集合加 `"/health/details"`, 同步 docstring L9-11 豁免名单说明 (该测试对未显式归级的新路由直接 AssertionError — test_auth.py:368-369, 是防"加路由忘挂门"的漂移守卫, 本次正好借它钉住新端点分级)。README 端点表 (README.md:75-83) + PROJECT.md 分级表 (PROJECT.md:64 机密级行) 同步加行 —— README:71 声明端点清单与 PROJECT.md 表"逐字节核对"。

### `api/main.py` (config: boot + route registration) — MOD

**Route 注册两行式 (独立模块时), 照抄 Phase 1-4 惯例 (main.py:20-23 imports + 52-54 include):**
```python
from api.health import router as health_router   # beside L20-23
...
app.include_router(health_router)  # beside L52-54 (机密级: router 自带 auth, 与 private L53 同注)
```

**Boot 序列插入点 (D-32/D-34 "SEC-03 检查后、uvicorn.run 前, 顺序 diff 可审计"):** 现序列 main.py:66-108: env 解析 → SEC-03/token 分支 (L74-98) → `jobs.reload_registry()` (L103, 带注释 L100-102) → 惰性 import uvicorn (L105-108)。新增 housekeeping 调用放 **reload_registry 之后、uvicorn.run 之前** (L103 与 L105 之间), 注释风格照抄 L100-102:
```python
    jobs.reload_registry()
    # OPS-03 (D-32/D-34): 日志轮转 + job 对修剪 (console.log >5MB -> .1)。
    # 放 reload_registry 之后 (cap 与扫描先定), uvicorn.run 之前 —— boot 顺序 diff 可审计。
    housekeep.prune_job_logs()          # D-33 (若 cap 走常量则与 reload 幂等)
    result = housekeep.rotate_console_log(os.path.join(LOG_DIR, "api", "console.log"))
    if result.error:
        print(f"WARNING: console.log rotation skipped: {result.error}", file=sys.stderr)
```
- main.py 若需 LOG_DIR: L18 `from scripts.daily.config import DATA_DIR` 扩展为 `DATA_DIR, LOG_DIR`。**连带测试缝**: `tests/test_boot.py` 所有调用 `api.main.main()` 的用例 (L118-218) patch `api.main.DATA_DIR` (L120 等) — 须加 `monkeypatch.setattr(api.main, "LOG_DIR", str(tmp_path))`, 否则 boot 测试会 stat 真实 logs/api/console.log (现 1.8KB < 5MB 惰性无害, 但真机一旦 >5MB 测试会动真实文件 — 不可接受, 必须缝)。或者 housekeep 提供 `console_log_path()` 类 helper 把 LOG_DIR 留在本模块 — planner 裁定。
- stdout 重指 (若 M-A 机制) 亦在此处、uvicorn.run 之前完成 — 是 main() 的编排职责 (见 Windows 约束节)。main() 的 print 纪律 (main.py:88-92 stderr + ASCII) 适用于新增 WARNING。
- **/health 纯度零影响**: housekeeping 不在 /health 请求路径, /health 仍纯内存 (main.py:48 注释 HLT-01); /health/details 在 /health/* 前缀下但机密级 (D-31), 与 D-11 豁免清单 (test_auth.py:8-9) 不冲突 — 豁免是逐路径列举, 不是前缀通配 (SC2 审计集合即证据)。

### `tests/test_log_housekeep.py` (NEW) — scaffold from test_boot + test_jobs

- 纯函数直测 (不绑 socket/不建真实目录): tmp_path 构造 console.log (os.utime/写字节控制大小), 形态 = test_boot.py:44-67 (tmp_path + monkeypatch + 无 client)。
- 用例集 (对齐 157+ 目标, 基线 148 passed 1 skipped — STATE.md:136): 低于阈值不动作 / 超阈值 rename 成 .1 且原文件消失 / 缺失文件无错 / 目标 .1 已存在时覆盖语义 (os.replace vs rename — planner 定, Windows 上 rename 目标存在会 FileNotFoundError? 不 — 目标存在 rename 报 FileExistsError; os.replace 覆盖) / OSError 返回状态不抛 / prune_job_logs 委托 cap 生效 (seed helper 同 test_jobs `_seed_job_file` L239-261: 直接 open 写 fixture JSON + 可选 os.utime + .log 陪衬)。
- prune 断言形态照抄 test_jobs.py:311-335 (seed N>cap → 断言保留最新 cap、最旧对 json+log 双删、非终态存活)。

### `tests/test_health_details.py` (NEW) — scaffold from test_private + test_jobs

- **autouse 隔离 fixture 抄 test_private.py:68-101** (每测试: 路径缝 → tmp_path 子树 + 清缓存 + write_token):
```python
@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(api.health, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(api.health, "LOG_DIR", str(tmp_path / "logs"))   # 若 health 模块持有
    monkeypatch.setattr(api.jobs, "LOG_DIR", str(tmp_path / "logs"))     # registry 经 jobs_dir()
    monkeypatch.setattr(api.auth, "DATA_DIR", str(tmp_path / "data"))
    write_token(tmp_path / "data", TOKEN)
    return tmp_path
```
- registry fixture: `_seed_job_file` (test_jobs.py:239-261) 形态写 logs/api/jobs/{id}.json — 需带 kind/finished_at/status 字段; market_state fixture: test_private.py:104-108 `_write_state` + :65 冻结 mtime 手法 (`os.utime(path, (m, m))`)。
- 契约段 (对齐 test_auth.py gate matrix L119-176 + test_health.py body pins L24-43): 无 key 401 + 挑战头 (detail/code 精确体, test_auth.py:124) / 错 key 403 无挑战头 / 有效 key 200 + 精确键集 `{"versions","uptime_seconds","last_check"}` 与子键 / health_job null (空目录; 无 succeeded; 有 failed 的 health-check) / health_job ISO (seed succeeded + finished_at 冻结值 → 断言等值 ISO) / market_state_mtime ISO (冻结 os.utime) / versions 自洽 (assert 等于测试内 importlib.metadata.version 计算值, 不硬编码版本号 — 双机漂移容忍) / uptime 与 /health 同源单调 / 裸 /health 仍 200 (公开面不受扰, test_private.py:20-21 同注)。401/403/200 响应体密钥缺席审计可省 (无 token 入体路径, 但 body 含 uptime/时间戳非密钥 — 不需要 test_auth.py:224-300 的重型审计)。
- 模块级 `client = TestClient(app)` (test_private.py:42 惯例); import api.health + api.main (路由注册)。

### `tests/test_auth.py` (MOD — MANDATORY)
- L349 `expected_secret` 集合加 `"/health/details"`; L350 expected_public 不动。测试自身 (L332-373) 逻辑零改 — 集合相等断言 (L372-373) 自动验证新端点确实带 `require_api_key` 同一依赖对象身份 (router 级 Depends 注入逐条 route.dependencies)。docstring L8-11 "豁免名单封闭" 措辞补一句 /health/details 机密级。

### `README.md` (MOD, doc) — D-35/D-37 + 端点表
- 端点表加行: `| GET | /health/details | X-API-Key | 版本/uptime/最近健康检查 (机密级) |` (README.md:75-83 表)。
- known-limits 段 (README.md:85-98 现有 "已知限制：单飞锁只约束 API 触发入口") 追加部署注意子段 (D-37): Ctrl+C 现象原文证据在 `.planning/STATE.md:149` ("交互会话启动的服务实例随会话结束收到 Ctrl+C (2026-09-03 晚 4 次 ^C 观察, LastTaskResult 0xC000013A); AtStartup 自启路径不受影响") — 照 README:85-93 的实录风格 (现象 + 影响 + 无代码改动声明)。
- Mac 验证清单 (D-35) 同段或 SUMMARY: 内容来自 05-CONTEXT specifics L73 (拉取 → pytest -q 全量 → conftest 网络封锁生效证明 (任何触网测试必失败, conftest.py:31-48) → 预期 157+ passed, 1 env-conditional skip (test_health.py:46-52 的 skip 是唯一环境条件跳过))。跨机 rollout: 用户执行后回填 (Phase 3 模式 — 03-04-SUMMARY.md:191 "adapt and record")。
- **README.md 是 gitignored 本地文档 (.gitignore:30; CLAUDE.md:328 政策: README 不上传) — 编辑目标合法 (Phase 4 04-06 同款), 但内容永不达 Mac — Mac 清单恰以"用户在 Mac 端从 git 拉代码"为前提, 无冲突。**

### `.planning/PROJECT.md` (MOD, doc — TRACKED)
- 分级表 L63-64: 机密级行 (L64) 追加 `/health/details`, 逐字节核对承诺保持 (README:71); L34 ROADMAP 行已标 Phase 5。D-31 引用此表 ("机密级 (Phase 4 分级表定稿)") — 本行即权威落点。

### `api/jobs.py` + `tests/test_jobs.py` (MOD, conditional) — 见 log_housekeep 节的 D-33 cap 分析。若 PRUNE_CAP→20: jobs.py:26 + docstring L1-15 "500" 字样; test_jobs.py:311-335 重写; 03-01-SUMMARY.md:135/143-144 历史记录不改 (git 历史如实)。

### `run_api.bat` — **推荐不改** (机制 M-A 下轮转在 main() 内完成, bat L5 原样)。仅当 planner 选 M-B (bat 侧轮转) 才改: 在 L5 前插 `for %%A in ("logs\api\console.log") do if %%~zA GTR 5242880 ren "logs\api\console.log" console.log.1` — 此时文件未被打开, rename 必然成功; 但 M-B 与 D-34 "boot 序列内调用纯函数模块" 字面冲突, 且 5MB 阈值失去 python 单源。

## Shared Patterns

### 机密级 router 门 (SEC-02)
**Source:** `api/private.py:55` / `api/actions.py:44` — `router = APIRouter(dependencies=[Depends(require_api_key)])`; 依赖对象身份被 SC2 审计断言 (test_auth.py:346-347 `route.dependencies[].dependency is gate`)。
**Apply to:** api/health.py。绝不做中间件/app 级依赖 (auth.py:3-7 设计约束)。

### 401/403 分工 + 冻结信封
**Source:** `api/auth.py:39-49` (缺头 401 + WWW-Authenticate: ApiKey 挑战头, 错 key 403 无挑战头, fail-closed) + `api/errors.py:34-35` 冻结码行 (missing_api_key / invalid_api_key)。**Apply to:** /health/details — 复用 require_api_key 即自动获得; **零新 raise 文本, 冻结表零新增** (errors.py:10-11 禁加行)。

### 纯函数模块纪律 (boot 层)
**Source:** `api/boot.py:3-4` (显式路径参数), boot.py:55-77 (mkdir exist_ok + 原子单行写), `api/jobs.py:12-14` (import 零副作用), `api/state.py:14-17` + `api/main.py:8` (ASCII-only 控制台 + 无 sys.path 操作)。**Apply to:** log_housekeep.py, main.py 新增 boot 行。新控制台文本 ASCII-only (Pitfall 5, GBK bat 重定向)。

### 调用时路径组合 (monkeypatch 缝)
**Source:** `api/state.py:66`、`api/private.py:140`、`api/jobs.py:33-41`、`api/main.py:72` — 模块 import config 目录常量, 函数内 `os.path.join` 调用时组合; 测试 patch 模块 attr。**Apply to:** api/health.py (DATA_DIR/LOG_DIR), 所有新测试 fixture。

### OSError 容错, boot 绝不致命
**Source:** `api/jobs.py:229-232` (listdir OSError → return), `:244-245` (损坏/竞态 → continue), `:251-254` (per-remove except OSError: pass), `reload_registry` "绝不中断扫描" (jobs.py:198 注释)。**Apply to:** log_housekeep 全部函数 (返回状态不上抛), main() 对轮转失败只打 WARNING 继续 boot (SEC-03 的 fatal-exit 纪律只属于鉴权失败, main.py:79-86)。

### Windows 句柄纪律 (Pitfall 2 家族)
**Source:** `api/jobs.py:62-65` + `api/state.py:62-63` (os.replace 撞 PermissionError → 短重试), state.py:45-49 (读句柄绝不跨 sleep 持有), state.py:99 注释 (永不 FileResponse)。**Apply to:** health.py 的 os.stat (瞬时调用不持句柄 — stat 无句柄窗口, 安全); log_housekeep 的 rename 失败路径 (见下节, 不允许重试循环 — 句柄持有者不退让, 重试无意义, 一次尝试 + 状态返回)。

### 测试隔离纪律
**Source:** `tests/conftest.py:31-48` (autouse 断网), 各套件 autouse fixture (test_private.py:68-82: 缝 tmp + 清 _CACHE/_claims + write_token; test_jobs.py:33-43), 模块级 TestClient 无 context manager (test_private.py:42), worker 必等终态 (test_auth.py:102-116)。**Apply to:** 两个新测试文件; 真实 data//logs/ 零触碰 (suite 结束 git status --porcelain -- data/ logs/ 为空 — test_private.py:25-27 钉)。

### SC2 逐路由分级审计 (分类漂移守卫)
**Source:** `tests/test_auth.py:332-373`。**Apply to:** 新增机密级路由必改 L349 集合, 否则套件红 —— 这是功能性的 (审计即契约), 不是维护负担。

## Windows 文件共享约束 — 实机验证事实 (2026-09-04, D-32 机制的关键约束)

**实验 1 (cmd `>>` 句柄 vs rename):** cmd 启动子进程 `python rot_sleep.py >> rot_test.log` (子进程 sleep 30s 持句柄), 另一进程 `os.rename('rot_test.log', 'rot_test.log.1')` → **PermissionError [WinError 32]** (共享冲突, 文件未被改名)。rm 同报 "Device or resource busy"。

**实验 2 (cmd `>>` 句柄 vs 外部截断):** 同场景 `open('rot_t.log','r+b')` + `truncate(0)` → **PermissionError [Errno 13]**。

**推论 (对 D-32 的机制含义):**
1. run_api.bat L5 (`>> logs\api\console.log 2>&1`) 及 Task Scheduler 动作 (`cmd /c run_api.bat`, 03-04-SUMMARY 记录) 启动的常驻服务, console.log 自进程诞生即被当前进程继承的 cmd 句柄持有, 该句柄未授 FILE_SHARE_DELETE/WRITE。
2. **main() 内裸 `os.rename(console.log, console.log.1)` 在主启动路径上必然 WinError 32** — D-32 的字面机制在此路径不可行。可行的两条机制 (planner 与 executor 裁定, 需真机验证步骤 + 记录, 03-04 先例):
   - **M-A (进程内, 推荐主案, 保持 D-32/D-34 落点):** main() boot 在调用 rotate 前先关闭/重指继承的 std 句柄 (os.close(1)/os.close(2) + 重新 os.open console.log 追加 + dup2/sys.stdout-sys.stderr 重建, 顺序细节 executor 真机验证), 然后 rename 成功, 后续输出进新 console.log; uvicorn.run 在其后, 继承新句柄。失败路径: rotate 函数返回 error 状态, main() 打 ASCII WARNING, boot 继续 — 服务照常起, 磁盘有界退化为"下次 boot 再试"。
   - **M-B (launcher 侧):** run_api.bat 在 python 启动前轮转 (文件未开, rename 必成) — 与 D-34 纯函数 boot 调用字面冲突, 备选。
3. 纯函数 `rotate_console_log` 的"尝试 rename + 返回状态"形态因此是**必要设计** (非防御性装饰): 它必须在句柄约束下可测 (tmp_path 下无句柄持有 → rename 成功路径; 测试内用真实 open 句柄可复现 WinError 32 路径 — os.open 默认 Python CRT 共享模式含 delete, 复现需模拟 cmd 共享模式, executor 可选做)。

## No Analog Found

| File / Concern | Role | Data Flow | Reason |
|----------------|------|-----------|--------|
| `api/health.py` versions 字段 (importlib.metadata + sys.version) | route 内读取 | request-response | grep 验证: 全库零 `importlib.metadata`/`sys.version` 使用。stdlib-only, 惰性读 (D-30); 形态自由, 测试用自洽断言 (测试内同源计算) 防双机版本漂移 |
| ISO 8601 时间输出 (datetime.fromtimestamp().isoformat()) | utility | — | 全库新鲜度一律 epoch 秒头 (state.py:93-94 X-Data-Mtime); D-29 契约首次要求 ISO — 纯 stdlib, 无网络 |
| console.log rename-rotate | utility | file-I/O | repo 无 rename-rotate 先例; 最接近的 os.replace 原子写 (jobs.py:59-85) 不覆盖"自持句柄目标"场景 — 约束事实见上节, 设计源 = 实机验证 + 03-04 adapt-and-record 文化 |
| Mac 验证清单内容 (D-35) | doc | — | repo 无 Mac 侧验证文档 (README 本地化 + gitignored; 03/04 阶段的 Mac 事实散在 SUMMARY/RESEARCH)。内容源 = 05-CONTEXT specifics L73 + conftest.py:31-48 行为描述; 落点 README/SUMMARY |
| D-36 15:30 任务确认命令 (D-02 闭环) | doc/record | — | 代码零改动。命令先例: `Unregister-ScheduledTask -TaskName "主升浪每日选股流水线" -Confirm:$false` 于提权 PowerShell (03-CONTEXT.md:101); 预期现状: Phase 3 已观察任务缺席 (03-RESEARCH.md:142 "of 201 tasks, the only relevant one is gogo-api; the stale 主升浪 pipeline task is absent") → Get-ScheduledTask 全量列举复确认, 在册才交付命令; 结果记录 STATE.md:146 ([P3→P5] 行) / 本阶段 SUMMARY |

## Metadata

**Analog search scope:** `api/` 全 9 模块 (main/boot/auth/jobs/state/private/actions/errors/__init__ 全读), `tests/` (conftest + test_health/test_boot/test_auth/test_jobs/test_private/test_errors 全读; test_state/test_actions 抽样), `scripts/daily/config.py` 全读, root (run_api.bat, README.md 全读, .gitignore L30), `.planning/` (05-CONTEXT 全读, 04-CONTEXT 全读, 03-CONTEXT/03-RESEARCH/03-04-SUMMARY 关键段, 04-PATTERNS.md 全读, PROJECT.md 分级表段, STATE.md 关键行, ROADMAP/REQUIREMENTS 关键行)
**Files scanned:** 28
**Tracked-source gate (#3645):** 所有具名 code analog 已验证 git-tracked (`git ls-files`: api/*.py, tests/*.py, scripts/daily/config.py, run_api.bat, pytest.ini, .planning/PROJECT.md 全部非空)。例外并明示: `README.md` 是 gitignored 本地文档 (.gitignore:30, CLAUDE.md:328 政策) — 它是 D-35/D-37 的编辑目标而非模式源, Phase 4 04-06 同款编辑先例; `api/health.py`/`api/log_housekeep.py` 为新建文件。无任何 gitignored 安装/镜像路径被引用。
**Machine-verified facts (2026-09-04, 本机):** cmd `>>` 重定向句柄持有期间 rename → WinError 32, 外部 truncate → Errno 13 (两实验均在本机 %TEMP% 完成, scratch 已清理); console.log 现 1.8KB; logs/api/jobs 现 10 文件 = 5 job 对 (05-CONTEXT code_context); 套件基线 148 passed 1 skipped (STATE.md:136) → 本阶段目标 157+ (05-CONTEXT L73, 新增约 9-12 测: log_housekeep 5-6 + health_details 6-7, 内含 SC2 集合更新)
**Pattern extraction date:** 2026-09-04
