"""Phase 3 触发/job HTTP 契约测试 (ACT-01/02/03 + SEC-01, D-09/D-10/D-11)。

本文件钉 03-02 交付的受保护 HTTP 面 (api/actions.py + api/auth.py +
api/main.py 注册): 有效 key 触发 -> 202 + job_id 立即返回, GET 轮询到终态并
暴露 log_path; 缺 key 401 + WWW-Authenticate / 错 key 403 (D-10); 未知 kind
404 且零副作用; /health 与 /v1/state 公开面结构豁免 (D-11)。

CRITICAL 数据隔离 pin: 绝不触碰真实 data/ 与 logs/ —— autouse fixture 把
api.jobs.LOG_DIR/DATA_DIR、api.auth.DATA_DIR、api.state.DATA_DIR 指到 tmp_path
并清空 api.jobs._claims 与 api.state._CACHE (test_state.py / test_jobs.py 惯例);
触发类测试把 api.actions.SCRIPTS_DIR 指到 tmp 假脚本树 (真实命名的假脚本,
KIND_CMDS 原样流通 —— 真管线零触碰)。
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.actions  # noqa: F401  (被测模块; SCRIPTS_DIR 缝)
import api.auth  # noqa: F401  (被测模块; DATA_DIR 缝)
import api.jobs  # noqa: F401  (被测模块; _claims 清理)
import api.main  # noqa: F401  (/health + state 路由 —— 模块级 client 依赖)
import api.state  # noqa: F401  (公开面断言用; DATA_DIR 缝)
from api.main import app

client = TestClient(app)  # 模块级, 无 context manager (test_state.py 惯例)

TOKEN = "test-token-03-02-actions"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """每测试前: 全部 DATA_DIR/LOG_DIR -> tmp_path 子树 + 清空跨测试状态。

    jobs/auth/state 三个模块的路径缝同指一棵 tmp 树 (data/ 与 logs/ 语义分离);
    token 文件默认写入 (个别测试自删/自改)。真实 data//logs/ 零触碰。
    """
    monkeypatch.setattr(api.jobs, "LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(api.jobs, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(api.auth, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(api.state, "DATA_DIR", str(tmp_path / "data"))
    with api.jobs._claims_lock:
        api.jobs._claims.clear()
    api.state._CACHE.clear()
    write_token(tmp_path / "data", TOKEN)
    return tmp_path


def write_token(base, value):
    """写 api_token.txt 到 base 下 (auth 缝指到的 data 目录)。"""
    p = Path(base) / "api_token.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(value + "\n", encoding="utf-8")


_FAKE_BODY = (
    "import json, os, sys, time\n"
    "print('中文-测试-⚠️', flush=True)\n"
    "json.dump({'argv': sys.argv},\n"
    "          open(os.environ['FAKE_OUT'], 'w', encoding='utf-8'), ensure_ascii=False)\n"
    "if os.environ.get('FAKE_ENV_OUT'):\n"
    "    json.dump(dict(os.environ),\n"
    "              open(os.environ['FAKE_ENV_OUT'], 'w', encoding='utf-8'), ensure_ascii=False)\n"
    "time.sleep(float(os.environ.get('FAKE_SLEEP', {sleep!r})))\n"
    "sys.exit(int(os.environ.get('FAKE_RC', '0')))\n"
)


def fake_script_tree(base, kinds):
    """在 tmp base 下写真实命名的假脚本树; 返回应指给 api.actions.SCRIPTS_DIR 的目录。

    kinds: {kind: (script_name, default_sleep)} —— script_name 必须等于
    api.actions.KIND_CMDS[kind] 的真名 (D-09 名字原样流通, 假脚本只换内容);
    行为由 env 控制: FAKE_OUT (必写, 全量 sys.argv JSON dump), FAKE_ENV_OUT
    (选写, 全量 os.environ dump), FAKE_SLEEP / FAKE_RC。
    """
    daily = Path(base) / "scripts" / "daily"
    daily.mkdir(parents=True, exist_ok=True)
    for kind, (script_name, sleep) in kinds.items():
        assert api.actions.KIND_CMDS[kind][0] == script_name  # 真名钉
        # replace 而非 format: 假脚本体含字面 {…} (json.dump dict), format 会误解析
        (daily / script_name).write_text(
            _FAKE_BODY.replace("{sleep!r}", repr(sleep)), encoding="utf-8"
        )
    return str(Path(base) / "scripts")


def _headers(key=TOKEN):
    return {"X-API-Key": key}


def wait_job(job_id, predicate, key=TOKEN, what="", timeout=12.0):
    """GET /v1/jobs/{job_id} 轮询直到 predicate(JSON) 为真; 返回满足时的记录。

    瞬时 503 (写者 os.replace 的 µs 读碰撞窗口, WinError-5 类) 视为未就绪,
    下轮重试 —— HTTP 轮询读者容忍瞬时 replace 碰撞 (03-01 Summary 读侧契约)。
    """
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = client.get(f"/v1/jobs/{job_id}", headers=_headers(key))
        if r.status_code == 503:
            time.sleep(0.01)
            continue
        assert r.status_code == 200, f"GET /v1/jobs/{job_id} -> {r.status_code} {r.text}"
        last = r.json()
        if predicate(last):
            return last
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} 未满足 {what} ({timeout}s 超时, last={last!r})")


def wait_terminal(job_id, key=TOKEN):
    """轮询到终态 (succeeded/failed/interrupted) 并返回该记录。"""
    return wait_job(
        job_id,
        lambda j: j["status"] in ("succeeded", "failed", "interrupted"),
        key=key,
        what="终态",
    )


def _registry_files():
    """registry 目录现存文件名列表 (目录不存在 -> 空列表)。"""
    registry = api.jobs.jobs_dir()
    if not os.path.isdir(registry):
        return []
    return os.listdir(registry)


# ---------- 行为 1 (tracer): 端到端 happy path —— 202 -> running -> succeeded ----------

def test_trigger_pipeline_lifecycle_to_succeeded(tmp_path, monkeypatch):
    """有效 key POST pipeline -> 202 {job_id, kind, status}; GET 轮询到终态。

    D-09 pin: 假脚本记录的全量 sys.argv 与 registry cmd 都证明固定命令
    [sys.executable, <SCRIPTS_DIR>/daily/run_pipeline.py, --fast] 原样流通。
    """
    scripts = fake_script_tree(tmp_path, {"pipeline": ("run_pipeline.py", 0.3)})
    monkeypatch.setattr(api.actions, "SCRIPTS_DIR", scripts)
    out = tmp_path / "out.json"
    monkeypatch.setenv("FAKE_OUT", str(out))

    r = client.post("/v1/actions/pipeline", headers=_headers())
    assert r.status_code == 202
    body = r.json()
    assert re.fullmatch(r"[0-9a-f]{32}", body["job_id"])
    assert body["kind"] == "pipeline"
    assert body["status"] == "pending"
    job_id = body["job_id"]

    def _running_with_pid(j):
        return j["status"] == "running" and j.get("pid") is not None

    running = wait_job(job_id, _running_with_pid, what="running+pid")
    assert running["log_path"] and running["log_path"].endswith(job_id + ".log")

    term = wait_job(
        job_id, lambda j: j["status"] == "succeeded", what="succeeded"
    )
    assert term["exit_code"] == 0
    assert term["finished_at"] is not None
    # registry cmd 暴露完整固定 argv: [sys.executable, 假脚本, --fast]
    assert term["cmd"][0] == sys.executable
    assert term["cmd"][1].endswith(os.path.join("daily", "run_pipeline.py"))
    assert term["cmd"][2:] == ["--fast"]
    # 假脚本自己的视角: argv == [假脚本绝对路径, --fast] (D-09 尾部参数 pin)
    recorded = json.loads(Path(out).read_text(encoding="utf-8"))
    assert recorded["argv"] == [term["cmd"][1], "--fast"]
    # 日志 UTF-8 + emoji 字节回归钉 (V1: GBK mojibake/UnicodeEncodeError 即红)
    log_text = Path(term["log_path"]).read_text(encoding="utf-8")
    assert "中文-测试-⚠️" in log_text


# ---------- 行为 2 (tracer): 鉴权接线 —— 401 缺失 / 403 错误 ----------

def test_missing_and_wrong_key_rejected(tmp_path):
    """缺 X-API-Key -> 401 + WWW-Authenticate: ApiKey; 带错 key -> 403 (D-10)。"""
    r = client.post("/v1/actions/pipeline")  # 无头
    assert r.status_code == 401
    assert r.json() == {"detail": "missing API key", "code": "missing_api_key"}
    assert r.headers.get("www-authenticate") == "ApiKey"  # 挑战头只在 401

    r = client.post("/v1/actions/pipeline", headers={"X-API-Key": "wrong-key"})
    assert r.status_code == 403
    assert r.json() == {"detail": "invalid API key", "code": "invalid_api_key"}
    assert "www-authenticate" not in r.headers  # 403 无挑战头 (D-10)


# ---------- 行为 3 (tracer): 未知 kind -> 404, 且任何副作用都不发生 ----------

def test_unknown_kind_404_no_side_effects(tmp_path, monkeypatch):
    """白名单外 kind -> 404 信封 (code unknown_action_kind), registry 保持空 (无 spawn)。"""
    r = client.post("/v1/actions/nonsense", headers=_headers())
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found", "code": "unknown_action_kind"}
    assert _registry_files() == []  # 404 先于 lock/claim/spawn (ACT-01 白名单门)


# ---------- 行为 4 (tracer): 公开面豁免 —— /health 与 /v1/state 无头可用 ----------

def test_public_endpoints_unguarded(tmp_path):
    """/health、/health/ready、GET /v1/state/{name} 不带 key 应答 (D-11 豁免)。"""
    assert client.get("/health").status_code == 200  # HLT-01 纯度: 零依赖

    # /health/ready 与 /v1/state 需要白名单文件 (api.state.DATA_DIR 已指 tmp/data)
    for name in ("market_state.json", "auction_state.json", "zt_pool_state.json"):
        (tmp_path / "data" / name).write_text('{"ok": true}', encoding="utf-8")
    assert client.get("/health/ready").status_code == 200

    r = client.get("/v1/state/market_state")
    assert r.status_code == 200  # 结构豁免: 公开路由上, 非 401/403
    assert r.json() == {"ok": True}

    r = client.get("/v1/state/unknown_name")
    assert r.status_code == 404  # state 路由自己的 404, 不是鉴权 401/403
    assert r.json() == {"detail": "Not Found", "code": "unknown_state_name"}


# ---------- ACT-01: 四种 kind 全走 D-09 固定命令 (经真实 KIND_CMDS 表) ----------

@pytest.mark.parametrize(
    "kind,flag",
    [
        ("pipeline", "--fast"),
        ("morning-check", "--quick"),
        ("backtest-weights", None),
        ("health-check", None),
    ],
)
def test_all_four_kinds_spawn_fixed_commands(tmp_path, monkeypatch, kind, flag):
    """四种 kind: 202 -> succeeded; registry cmd 与假脚本 argv 双钉 D-09 命令。"""
    script_name = api.actions.KIND_CMDS[kind][0]  # 真名 (D-09 表原样流通)
    scripts = fake_script_tree(tmp_path, {kind: (script_name, 0.2)})
    monkeypatch.setattr(api.actions, "SCRIPTS_DIR", scripts)
    out = tmp_path / f"out-{kind}.json"
    monkeypatch.setenv("FAKE_OUT", str(out))

    r = client.post(f"/v1/actions/{kind}", headers=_headers())
    assert r.status_code == 202
    body = r.json()
    assert body["kind"] == kind and body["status"] == "pending"

    term = wait_terminal(body["job_id"])
    assert term["status"] == "succeeded"
    assert term["exit_code"] == 0
    # registry cmd == [sys.executable, <SCRIPTS_DIR>/daily/<脚本>, *固定参数]
    assert term["cmd"][0] == sys.executable
    assert term["cmd"][1].endswith(os.path.join("daily", script_name))
    recorded = json.loads(Path(out).read_text(encoding="utf-8"))
    assert recorded["argv"][0] == term["cmd"][1]  # 子进程视角: 脚本路径为 argv[0]
    if flag is None:
        assert recorded["argv"][1:] == []  # backtest-weights/health-check 无参 (D-09)
    else:
        assert recorded["argv"][1:] == [flag]
    # 日志 UTF-8 + emoji 回归钉 (经完整 HTTP 路径, V1)
    log_text = Path(term["log_path"]).read_text(encoding="utf-8")
    assert "中文-测试-⚠️" in log_text


# ---------- ACT-02: 非零退出码在 GET 体暴露 ----------

def test_failed_exit_code_surfaces_via_get(tmp_path, monkeypatch):
    scripts = fake_script_tree(tmp_path, {"pipeline": ("run_pipeline.py", 0.2)})
    monkeypatch.setattr(api.actions, "SCRIPTS_DIR", scripts)
    monkeypatch.setenv("FAKE_OUT", str(tmp_path / "out.json"))
    monkeypatch.setenv("FAKE_RC", "7")

    r = client.post("/v1/actions/pipeline", headers=_headers())
    assert r.status_code == 202
    term = wait_job(
        r.json()["job_id"], lambda j: j["status"] == "failed", what="failed"
    )
    assert term["exit_code"] == 7  # 非零退出码透传到 GET 体 (ACT-02)
    assert term["finished_at"] is not None


# ---------- ACT-03: 409 矩阵 (map-hit 形状 / 并行 kind / 跨进程持有者 / 再触发) ----------

def _retrigger_until_202(timeout=2.0):
    """重触发轮询: 终态文件落盘到 OS 锁释放之间是 µs 级窗口, 撞上则重试。

    run_job finally 顺序: 终态写 -> release(kind) -> 关锁。GET 轮询看到终态时
    锁几乎必已释放, 但调度器暂停可让窗口放大 —— 契约断言"终态后可再触发 202",
    过渡期 409(another entry point) 语义为真, 轮询重试保持确定性。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.post("/v1/actions/pipeline", headers=_headers())
        if r.status_code == 202:
            return r
        assert r.status_code == 409
        time.sleep(0.05)
    raise AssertionError("终态后重触发未在窗口内得到 202")


def test_409_map_hit_object_shape_and_retrigger_after_terminal(tmp_path, monkeypatch):
    """(a) map 命中 -> 409 对象形状精确 (Open-question 1); (d) 终态后可再触发。"""
    scripts = fake_script_tree(tmp_path, {"pipeline": ("run_pipeline.py", 0.3)})
    monkeypatch.setattr(api.actions, "SCRIPTS_DIR", scripts)
    monkeypatch.setenv("FAKE_OUT", str(tmp_path / "out.json"))
    monkeypatch.setenv("FAKE_SLEEP", "1.2")  # 首 job 留出 409 窗口

    r1 = client.post("/v1/actions/pipeline", headers=_headers())
    assert r1.status_code == 202
    id1 = r1.json()["job_id"]
    wait_job(
        id1,
        lambda j: j["status"] == "running" and j.get("pid") is not None,
        what="running+pid",
    )

    # (a) 同 kind 运行中再触发: 409 信封, 对象 detail 逐字节保留 + code 兄弟键
    r2 = client.post("/v1/actions/pipeline", headers=_headers())
    assert r2.status_code == 409
    assert r2.json() == {
        "detail": {"message": "pipeline already running", "running_job_id": id1},
        "code": "already_running",
    }

    # (d) 终态后可再触发 (re-trigger after completion -> 202)
    term1 = wait_terminal(id1)
    assert term1["status"] == "succeeded"
    monkeypatch.setenv("FAKE_SLEEP", "0.2")  # 后续 job 快速收尾
    r3 = _retrigger_until_202()
    assert r3.json()["job_id"] != id1
    term3 = wait_terminal(r3.json()["job_id"])
    assert term3["status"] == "succeeded"


def test_409_parallel_kinds_run_simultaneously(tmp_path, monkeypatch):
    """(b) 不同 kind 并行安全: pipeline 运行中触发 morning-check -> 202。"""
    scripts = fake_script_tree(
        tmp_path,
        {
            "pipeline": ("run_pipeline.py", 0.3),
            "morning-check": ("morning_check.py", 0.3),
        },
    )
    monkeypatch.setattr(api.actions, "SCRIPTS_DIR", scripts)
    monkeypatch.setenv("FAKE_OUT", str(tmp_path / "out.json"))
    monkeypatch.setenv("FAKE_SLEEP", "0.8")

    r1 = client.post("/v1/actions/pipeline", headers=_headers())
    assert r1.status_code == 202
    r2 = client.post("/v1/actions/morning-check", headers=_headers())
    assert r2.status_code == 202  # 单飞锁按 kind 隔离, 不同 kind 互不挡
    assert r2.json()["kind"] == "morning-check"
    assert r1.json()["job_id"] != r2.json()["job_id"]

    assert wait_terminal(r1.json()["job_id"])["status"] == "succeeded"
    assert wait_terminal(r2.json()["job_id"])["status"] == "succeeded"


# 真实子进程: importlib 从 argv[1] 加载 job_lock.py, acquire(argv[2] kind,
# argv[3] lock_dir), 成功则打印 HELD 并睡 60s (test_jobs.py Task 3 先例)。
_CROSS_PROC_CHILD = (
    "import importlib.util, sys, time\n"
    "spec = importlib.util.spec_from_file_location('job_lock', sys.argv[1])\n"
    "m = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(m)\n"
    "fd = m.acquire(sys.argv[2], sys.argv[3])\n"
    "if fd is None:\n"
    "    sys.exit(3)\n"
    "print('HELD', flush=True)\n"
    "time.sleep(60)\n"
)


def _job_lock_path():
    """job_lock.py 绝对路径: repo/scripts/daily/job_lock.py (api/jobs.py 上溯两级)。"""
    return str(
        Path(api.jobs.__file__).resolve().parent.parent
        / "scripts" / "daily" / "job_lock.py"
    )


def test_409_cross_process_holder_object_shape(tmp_path, monkeypatch):
    """(c) OS 锁被外部入口 (GUI/手动) 持有 -> 409 another-entry-point, 无 job_id。

    子进程持真 job_lock.py 的锁 (test_jobs.py Task 3 先例); API 内存 claim 为
    空 -> 对象形状无 running_job_id 键; 杀持有者 -> OS 自动释放 (probe V2)
    -> 同路径再触发 202 (跨进程释放经全 HTTP 路径钉死)。
    """
    scripts = fake_script_tree(tmp_path, {"pipeline": ("run_pipeline.py", 0.3)})
    monkeypatch.setattr(api.actions, "SCRIPTS_DIR", scripts)
    monkeypatch.setenv("FAKE_OUT", str(tmp_path / "out.json"))
    monkeypatch.setenv("FAKE_SLEEP", "0.2")
    lock_dir = str(tmp_path / "data" / "locks")  # = api.jobs.locks_dir() (DATA_DIR 缝)

    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(
        [sys.executable, "-c", _CROSS_PROC_CHILD, _job_lock_path(), "pipeline", lock_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=flags,
    )
    try:
        line = proc.stdout.readline()
        assert line.strip() == b"HELD", (
            f"子进程未能持有锁 (stderr: {proc.stderr.read()!r})"
        )
        r = client.post("/v1/actions/pipeline", headers=_headers())
        assert r.status_code == 409
        body = r.json()
        assert body == {
            "detail": {"message": "pipeline already running (another entry point)"},
            "code": "already_running_other_entry",
        }
        assert "running_job_id" not in body["detail"]  # GUI/手动持有, 无 job_id 可报
        proc.kill()  # 杀持有者 -> OS 自动释放锁
        proc.wait(timeout=10)
        r = client.post("/v1/actions/pipeline", headers=_headers())
        assert r.status_code == 202
        assert wait_terminal(r.json()["job_id"])["status"] == "succeeded"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


# ---------- ACT-02: 404/503 边界 (未知 kind / 缺失 / 越界 id / 损坏文件) ----------

def test_404_and_503_edges_no_side_effects(tmp_path, monkeypatch):
    """404 边界零副作用 + 损坏 registry 文件 -> 503 (绝不 500)。"""
    r = client.post("/v1/actions/unknown", headers=_headers())
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found", "code": "unknown_action_kind"}

    r = client.get(f"/v1/jobs/{'e' * 32}", headers=_headers())  # 合规形状但缺失
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found", "code": "job_not_found"}

    # 越界形状 (无斜杠, 必达 handler): 短 id / 31-hex / 非小写 32-hex / 33-hex
    # —— 正则门 ^[0-9a-f]{32}$ 先于任何路径组合 (T-03-11)。
    # 注: 字面点段 ".." 会被 httpx 规范化折叠 (与 %2F 同族), 归入下方路由层 404
    for bad in ("abc", "f" * 31, "A" * 32, "f" * 33):
        r = client.get(f"/v1/jobs/{bad}", headers=_headers())
        assert r.status_code == 404, f"{bad!r} -> {r.status_code} (must be 404)"
        assert r.json() == {"detail": "Not Found", "code": "job_not_found"}
    # 穿越形状 (..%2F..%2Fdata%2Fapi_token): httpx/uvicorn 把 %2F 解码成字面
    # 斜杠 -> scope path 含斜杠, Starlette 路由先 404 ({job_id} 不含 /) ——
    # 同一道门的更早一层: 仍 404、零文件访问、绝不 500 (T-03-11 字面达成)
    r = client.get("/v1/jobs/..%2F..%2Fdata%2Fapi_token", headers=_headers())
    assert r.status_code == 404
    assert r.status_code != 500 and "Traceback" not in r.text
    assert _registry_files() == []  # 上述 404 全部零副作用

    # 损坏 registry 文件 -> 503 job temporarily unavailable (分类归 HTTP 层)
    registry = api.jobs.jobs_dir()
    Path(registry).mkdir(parents=True, exist_ok=True)
    (Path(registry) / ("0" * 32 + ".json")).write_text("{not json", encoding="utf-8")
    r = client.get(f"/v1/jobs/{'0' * 32}", headers=_headers())
    assert r.status_code == 503
    assert r.json() == {"detail": "job temporarily unavailable", "code": "job_temporarily_unavailable"}


# ---------- 04-04 (SC4, D-26..D-28): 触发 date 白名单参数 ----------
# 行为 1: 白名单格式 date 达脚本 = 固定 arg-list 尾部单一 token (注入结构性不可能);
# 行为 2: 非法格式 -> 422 invalid_date_format, registry 恒空 (零 spawn);
# 行为 3: 零参数 kind + date -> 422 date_not_supported (固定命令不变, 无回归由
#         test_all_four_kinds_spawn_fixed_commands 等既有 no-date 钉保证);
# 行为 4: 未知 kind 先于任何 date 逻辑 -> 404 (D-09 白名单门).

def test_date_param_valid_delivery_appended_argv_pins(tmp_path, monkeypatch):
    """?date= 白名单格式 -> 202; date 以单 token 附加在固定参数尾部 (argv 字节钉)。

    pipeline ?date=2026-09-03 -> [..., --fast, --date=2026-09-03];
    morning-check ?date=20260903 (compact) -> [..., --quick, --date=2026-09-03]
    (归一化为 dashed)。registry cmd 与假脚本自身记录的 argv 双钉。
    """
    scripts = fake_script_tree(tmp_path, {"pipeline": ("run_pipeline.py", 0.3)})
    monkeypatch.setattr(api.actions, "SCRIPTS_DIR", scripts)
    out1 = tmp_path / "out-date1.json"
    monkeypatch.setenv("FAKE_OUT", str(out1))

    r = client.post("/v1/actions/pipeline?date=2026-09-03", headers=_headers())
    assert r.status_code == 202
    term1 = wait_terminal(r.json()["job_id"])
    assert term1["status"] == "succeeded"
    # registry cmd == [sys.executable, 假脚本, --fast, --date=2026-09-03] (D-09 固定参数原样 + 尾部附加)
    assert term1["cmd"][0] == sys.executable
    assert term1["cmd"][2:] == ["--fast", "--date=2026-09-03"]
    recorded1 = json.loads(Path(out1).read_text(encoding="utf-8"))
    assert recorded1["argv"] == [term1["cmd"][1], "--fast", "--date=2026-09-03"]

    # morning-check compact 格式 -> 归一化 dashed 单 token (CONTEXT 字面形态)
    scripts2 = fake_script_tree(tmp_path, {"morning-check": ("morning_check.py", 0.3)})
    monkeypatch.setattr(api.actions, "SCRIPTS_DIR", scripts2)
    out2 = tmp_path / "out-date2.json"
    monkeypatch.setenv("FAKE_OUT", str(out2))
    r2 = client.post("/v1/actions/morning-check?date=20260903", headers=_headers())
    assert r2.status_code == 202
    term2 = wait_terminal(r2.json()["job_id"])
    assert term2["status"] == "succeeded"
    assert term2["cmd"][2:] == ["--quick", "--date=2026-09-03"]
    recorded2 = json.loads(Path(out2).read_text(encoding="utf-8"))
    assert recorded2["argv"] == [term2["cmd"][1], "--quick", "--date=2026-09-03"]


def test_date_invalid_formats_422_zero_spawn(tmp_path, monkeypatch):
    """非法格式 (格式/历法) -> 422 信封; registry 每次 422 后恒空 (无 lock/claim/spawn)。"""
    scripts = fake_script_tree(tmp_path, {"pipeline": ("run_pipeline.py", 0.3)})
    monkeypatch.setattr(api.actions, "SCRIPTS_DIR", scripts)
    monkeypatch.setenv("FAKE_OUT", str(tmp_path / "out-invalid.json"))
    for bad in ("2026/09/03", "2026093", "abc", "2026-13-99", "2026-02-30"):
        r = client.post(f"/v1/actions/pipeline?date={bad}", headers=_headers())
        assert r.status_code == 422, f"{bad!r} -> {r.status_code} (must be 422)"
        assert r.json() == {
            "detail": "date must be YYYY-MM-DD or YYYYMMDD",
            "code": "invalid_date_format",
        }
        assert _registry_files() == []  # 422 先于 lock/claim/spawn (SC4)


def test_date_on_zero_param_kinds_422_not_supported(tmp_path, monkeypatch):
    """backtest-weights/health-check 零参数不变: 带 date -> 422 date_not_supported。"""
    for kind, script_name in (
        ("backtest-weights", "backtest_v4.py"),
        ("health-check", "data_health_check.py"),
    ):
        scripts = fake_script_tree(tmp_path, {kind: (script_name, 0.2)})
        monkeypatch.setattr(api.actions, "SCRIPTS_DIR", scripts)
        monkeypatch.setenv("FAKE_OUT", str(tmp_path / f"out-{kind}.json"))
        r = client.post(f"/v1/actions/{kind}?date=2026-09-03", headers=_headers())
        assert r.status_code == 422, f"{kind}?date -> {r.status_code} (must be 422)"
        assert r.json() == {
            "detail": "date not supported for this action kind",
            "code": "date_not_supported",
        }
        assert _registry_files() == []  # 422 先于任何 spawn
    # 无 date 回归钉由既有 test_all_four_kinds_spawn_fixed_commands 承担 (本文件未动)


def test_unknown_kind_with_date_404_kind_gate_first(tmp_path, monkeypatch):
    """未知 kind + date -> 404 unknown_action_kind (kind 白名单先于一切 date 逻辑)。"""
    r = client.post("/v1/actions/nonsense?date=2026-09-03", headers=_headers())
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found", "code": "unknown_action_kind"}
    assert _registry_files() == []
