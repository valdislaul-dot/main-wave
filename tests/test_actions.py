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
        (daily / script_name).write_text(
            _FAKE_BODY.format(sleep=sleep), encoding="utf-8"
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
    assert r.json() == {"detail": "missing API key"}
    assert r.headers.get("www-authenticate") == "ApiKey"  # 挑战头只在 401

    r = client.post("/v1/actions/pipeline", headers={"X-API-Key": "wrong-key"})
    assert r.status_code == 403
    assert r.json() == {"detail": "invalid API key"}
    assert "www-authenticate" not in r.headers  # 403 无挑战头 (D-10)


# ---------- 行为 3 (tracer): 未知 kind -> 404, 且任何副作用都不发生 ----------

def test_unknown_kind_404_no_side_effects(tmp_path, monkeypatch):
    """白名单外 kind -> 404 unknown action kind, registry 目录保持空 (无 spawn)。"""
    r = client.post("/v1/actions/nonsense", headers=_headers())
    assert r.status_code == 404
    assert r.json() == {"detail": "unknown action kind"}
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
    assert r.json() == {"detail": "unknown state name"}
