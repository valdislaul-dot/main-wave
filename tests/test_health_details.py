"""OPS-03 SC1 /health/details 契约套 (05-01 tracer 切片, D-29..D-31)。

GET /health/details —— 机密级 token 门控健康详情 (与 private/actions/jobs 同门,
SEC-02 分级表):
- 无 key -> 401 {"detail": "missing API key", "code": "missing_api_key"} +
  WWW-Authenticate: ApiKey 挑战头 (只在 401); 错 key -> 403 invalid_api_key 无挑战头
  (D-10 分工, 04-01 冻结信封 —— 本端点零新 raise 文本)。
- 200 体精确 D-29 形状: 顶层键集 == {"versions", "uptime_seconds", "last_check"};
  versions 子键 == {"python", "uvicorn", "fastapi"} (sys.version/importlib.metadata
  惰性读, 绝不硬编码 —— 测试内同源计算, 双机版本漂移不假红);
  last_check 子键 == {"health_job", "market_state_mtime"}。
- health_job = logs/api/jobs registry 最新 succeeded health-check job 的
  finished_at 的 ISO-8601 UTC (datetime.fromtimestamp(tz=utc).isoformat() 同式
  计算断言); market_state_mtime = data/market_state.json os.stat mtime 同式 ISO。
- uptime_seconds 与 /health 同一 monotonic 锚点 (api.main.uptime_seconds), 非降。
- 公开面: 裸 /health 无 key 照常 200, 键集 {"status","uptime_seconds"} 不动 (HLT-01)。

CRITICAL 数据隔离 pin (同 test_private/test_auth 惯例): autouse fixture 把
api.health.DATA_DIR、api.jobs.LOG_DIR、api.auth.DATA_DIR 指到 tmp_path 子树并
write_token —— 真实 data/ 与 logs/ 零触碰 (suite 结束时
git status --porcelain -- data/ logs/ 必须为空)。
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.auth  # noqa: F401  (被测模块; DATA_DIR 缝 —— token 门)
import api.health  # noqa: F401  (被测模块; DATA_DIR 缝)
import api.jobs  # noqa: F401  (registry 目录经 jobs_dir(); LOG_DIR 缝)
import api.main  # noqa: F401  (路由注册 —— /health 与 health_router 同 app)
from api.main import app

client = TestClient(app)  # 模块级, 无 context manager (test_private.py 惯例)

TOKEN = "test-token-05-01-health-details"

_FINISHED_AT = 1_789_459_479  # 冻结 finished_at (health_job ISO 精确断言锚点)
_MTIME = 1_789_459_500        # 冻结 market_state.json mtime 锚点


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """每测试前: health DATA_DIR + jobs LOG_DIR + auth DATA_DIR -> tmp_path 子树。

    registry (logs/api/jobs) 经 api.jobs.jobs_dir() 调用时解析 —— 缝 api.jobs.LOG_DIR;
    market_state.json 在 api.health.DATA_DIR 下; token 文件在 auth 缝指到的 data/ 子目录。
    """
    monkeypatch.setattr(api.health, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(api.jobs, "LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setattr(api.auth, "DATA_DIR", str(tmp_path / "data"))
    write_token(tmp_path / "data", TOKEN)
    return tmp_path


def write_token(base, value):
    """写 api_token.txt 到 base 下 (auth 缝指到的 data 目录)。"""
    p = Path(base) / "api_token.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(value + "\n", encoding="utf-8")


def _headers(key=TOKEN):
    return {"X-API-Key": key}


def _seed_registry_job(tmp_path, job_id, kind, status, finished_at=None):
    """直接 open('w') 手写 registry fixture JSON (test_jobs._seed_job_file 形状,
    扩展带 kind/finished_at 字段) + .log 陪衬。返回 registry 目录 Path。"""
    base = Path(tmp_path) / "logs" / "api" / "jobs"
    base.mkdir(parents=True, exist_ok=True)
    job = {
        "job_id": job_id,
        "kind": kind,
        "status": status,
        "pid": None,
        "exit_code": 0 if status == "succeeded" else 1,
        "log_path": None,
        "cmd": ["python", "x.py"],
        "created_at": 1,
        "started_at": None,
        "finished_at": finished_at,
    }
    (base / f"{job_id}.json").write_text(
        json.dumps(job, ensure_ascii=False), encoding="utf-8"
    )
    (base / f"{job_id}.log").write_bytes(b"")
    return base


def _write_market_state(tmp_path, mtime):
    """写 data/market_state.json 并 os.utime 冻结 mtime, 返回其真实 st_mtime
    (端点与断言同读 os.stat —— 自洽计算, 无时区漂移敏感字面量)。"""
    path = Path(tmp_path) / "data" / "market_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'{"ok": true}\n')
    os.utime(path, (mtime, mtime))
    return os.stat(path).st_mtime


# ---------- tracer 行为 1: 门矩阵 (401/403/200) ----------

def test_gate_matrix_no_key_401_wrong_key_403_valid_200(tmp_path):
    r = client.get("/health/details")  # 无 X-API-Key 头
    assert r.status_code == 401
    assert r.json() == {"detail": "missing API key", "code": "missing_api_key"}
    assert r.headers.get("www-authenticate") == "ApiKey"  # D-10 挑战头精确值

    r = client.get("/health/details", headers={"X-API-Key": "definitely-wrong"})
    assert r.status_code == 403
    assert r.json() == {"detail": "invalid API key", "code": "invalid_api_key"}
    assert "www-authenticate" not in r.headers  # 挑战头只在 401 (D-10)

    r = client.get("/health/details", headers=_headers())
    assert r.status_code == 200  # 有效 key 过门


# ---------- tracer 行为 2: 精确 D-29 键集 + JSON 类型 ----------

def test_exact_d29_shape_top_level_and_sub_key_sets(tmp_path):
    r = client.get("/health/details", headers=_headers())
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert set(body.keys()) == {"versions", "uptime_seconds", "last_check"}
    assert set(body["versions"].keys()) == {"python", "uvicorn", "fastapi"}
    assert set(body["last_check"].keys()) == {"health_job", "market_state_mtime"}


# ---------- tracer 行为 3: registry + market stat 接通 (冻结值 -> 精确 ISO) ----------

def test_registry_and_market_state_wired_iso(tmp_path):
    # 三个 job: 老 succeeded / 新 succeeded / 更新 failed —— health_job 取 succeeded
    # 中最新 finished_at; failed 即便 finished_at 更新也永不入选
    _seed_registry_job(tmp_path, "a" * 32, "health-check", "succeeded",
                       finished_at=_FINISHED_AT - 1000)
    _seed_registry_job(tmp_path, "b" * 32, "health-check", "succeeded",
                       finished_at=_FINISHED_AT)
    _seed_registry_job(tmp_path, "c" * 32, "health-check", "failed",
                       finished_at=_FINISHED_AT + 1000)
    st_mtime = _write_market_state(tmp_path, _MTIME)

    r = client.get("/health/details", headers=_headers())
    assert r.status_code == 200
    body = r.json()

    expected_job_iso = datetime.fromtimestamp(_FINISHED_AT, timezone.utc).isoformat()
    expected_mtime_iso = datetime.fromtimestamp(st_mtime, timezone.utc).isoformat()
    assert body["last_check"]["health_job"] == expected_job_iso
    assert body["last_check"]["market_state_mtime"] == expected_mtime_iso
    assert body["last_check"]["health_job"] != datetime.fromtimestamp(
        _FINISHED_AT + 1000, timezone.utc
    ).isoformat()  # failed 的 finished_at 不进 health_job


# ---------- tracer 行为 4: uptime 与 /health 同一 monotonic 锚点 ----------

def test_uptime_anchored_to_health(tmp_path):
    h = client.get("/health")
    assert h.status_code == 200
    h_up = h.json()["uptime_seconds"]

    r = client.get("/health/details", headers=_headers())
    assert r.status_code == 200
    up = r.json()["uptime_seconds"]
    assert isinstance(up, int)
    assert up >= 0
    assert up >= h_up  # 同一锚点 (api.main.uptime_seconds), 读数非降


# ---------- tracer 行为 5: 公开 /health 面不受扰 (HLT-01) ----------

def test_public_health_untouched_beside_details(tmp_path):
    r = client.get("/health")  # 无 key (HLT-01 纯度)
    assert r.status_code == 200
    assert set(r.json().keys()) == {"status", "uptime_seconds"}
