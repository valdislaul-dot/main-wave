"""OPS-03 SC1 /health/details 契约套 (05-01 tracer 切片 + 全矩阵, D-29..D-31)。

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
- null 腿 (全 200, 绝不 5xx): registry 缺目录/空目录/仅 failed health-check/
  仅他种 succeeded job/损坏 json/点文件 -> health_job null; market_state.json
  缺失或 os.stat 失败 -> market_state_mtime null (数据缺席诚实回答)。
- 无 token 配置 (文件+env 全空) -> fail-closed 403 (api/auth.py 语义)。
- versions 兜底: importlib.metadata PackageNotFoundError -> "unknown"; 自洽断言
  (测试内同源 importlib.metadata.version 计算, 不硬编码版本串)。
- 泄漏卫生: 401/403/200 响应体永不含 str(tmp_path) 与 token 字节。
- uptime_seconds 与 /health 同一 monotonic 锚点 (api.uptime 单一锚点, 05-04 双身份
  修复后 main/health 同源), 非降。
- 公开面: 裸 /health 无 key 照常 200, 键集 {"status","uptime_seconds"} 不动 (HLT-01)。

CRITICAL 数据隔离 pin (同 test_private/test_auth 惯例): autouse fixture 把
api.health.DATA_DIR、api.jobs.LOG_DIR、api.auth.DATA_DIR 指到 tmp_path 子树并
write_token —— 真实 data/ 与 logs/ 零触碰 (suite 结束时
git status --porcelain -- data/ logs/ 必须为空)。
"""
import importlib.metadata
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
    assert up >= h_up  # 同一锚点 (api.uptime), 读数非降


def test_uptime_single_anchor_identity(tmp_path):
    """锚点单一身份 pin (05-04 实机修复): 两端点必须共用 api.uptime 同一函数对象。

    `python -m api.main` 启动时 main.py 以 __main__ 身份执行、不注册进 sys.modules
    —— health 若在 handler 内惰性 import api.main, 会触发整个 main.py 二次执行,
    模块级锚点被重置 (/health/details 与 /health 的 uptime 实机分叉 70s+)。断言
    main 与 health 的 uptime_seconds 是 api.uptime 的同一对象, 结构性杜绝再犯
    (TestClient 路径下旧惰性 import 恰好 sys.modules 命中, 套件测不出该陷阱)。
    """
    import api.uptime

    assert api.main.uptime_seconds is api.uptime.uptime_seconds
    assert api.health.uptime_seconds is api.uptime.uptime_seconds


# ---------- tracer 行为 5: 公开 /health 面不受扰 (HLT-01) ----------

def test_public_health_untouched_beside_details(tmp_path):
    r = client.get("/health")  # 无 key (HLT-01 纯度)
    assert r.status_code == 200
    assert set(r.json().keys()) == {"status", "uptime_seconds"}


# ---------- 矩阵: health_job null 腿 (全 200, 绝不 5xx) ----------

def test_health_job_null_missing_jobs_dir(tmp_path):
    # registry 目录不存在 -> listdir OSError -> null (与 jobs.prune 同容错)
    r = client.get("/health/details", headers=_headers())
    assert r.status_code == 200
    assert r.json()["last_check"]["health_job"] is None


def test_health_job_null_empty_jobs_dir(tmp_path):
    (Path(tmp_path) / "logs" / "api" / "jobs").mkdir(parents=True)
    r = client.get("/health/details", headers=_headers())
    assert r.status_code == 200
    assert r.json()["last_check"]["health_job"] is None


def test_health_job_null_only_failed_health_checks(tmp_path):
    _seed_registry_job(tmp_path, "a" * 32, "health-check", "failed",
                       finished_at=_FINISHED_AT)
    r = client.get("/health/details", headers=_headers())
    assert r.status_code == 200
    assert r.json()["last_check"]["health_job"] is None  # failed 永不入选


def test_health_job_null_only_other_kind_succeeded(tmp_path):
    _seed_registry_job(tmp_path, "a" * 32, "pipeline", "succeeded",
                       finished_at=_FINISHED_AT)
    r = client.get("/health/details", headers=_headers())
    assert r.status_code == 200
    assert r.json()["last_check"]["health_job"] is None  # 非 health-check 不入选项


def test_health_job_null_corrupt_registry_json_skipped(tmp_path):
    base = Path(tmp_path) / "logs" / "api" / "jobs"
    base.mkdir(parents=True, exist_ok=True)
    (base / "corrupt.json").write_text("{not json", encoding="utf-8")
    r = client.get("/health/details", headers=_headers())
    assert r.status_code == 200
    assert r.json()["last_check"]["health_job"] is None  # 损坏 -> 跳过, 绝不 5xx


def test_health_job_null_dotfile_only_registry(tmp_path):
    base = Path(tmp_path) / "logs" / "api" / "jobs"
    base.mkdir(parents=True, exist_ok=True)
    (base / ".DS_Store").write_bytes(b"dotfile")  # .DS_Store 风格点文件
    r = client.get("/health/details", headers=_headers())
    assert r.status_code == 200
    assert r.json()["last_check"]["health_job"] is None  # 点文件 -> 扫描跳过


def test_health_job_null_non_object_json_skipped(tmp_path):
    """WR-03 形状守卫: 可解析但非对象 JSON (list/str/int/bool/null) 全跳过, 绝不 5xx。"""
    base = Path(tmp_path) / "logs" / "api" / "jobs"
    base.mkdir(parents=True, exist_ok=True)
    for stem, payload in (
        ("list_job", "[1, 2]"),
        ("num_job", "42"),
        ("str_job", '"hello"'),
        ("bool_job", "true"),
        ("null_job", "null"),
    ):
        (base / f"{stem}.json").write_text(payload, encoding="utf-8")
    r = client.get("/health/details", headers=_headers())
    assert r.status_code == 200  # 外来字节绝不打成 5xx (T-05-03)
    assert r.json()["last_check"]["health_job"] is None  # 非对象 -> 跳过


def test_health_job_non_object_files_do_not_shadow_valid_succeeded(tmp_path):
    """WR-03 混合矩阵: 非对象 JSON 与合法 succeeded health-check 并存 -> 扫描继续取后者。"""
    _seed_registry_job(tmp_path, "a" * 32, "health-check", "succeeded",
                       finished_at=_FINISHED_AT)
    base = Path(tmp_path) / "logs" / "api" / "jobs"
    (base / "list_job.json").write_text("[1, 2]", encoding="utf-8")
    (base / "bool_job.json").write_text("true", encoding="utf-8")
    r = client.get("/health/details", headers=_headers())
    assert r.status_code == 200
    expected_iso = datetime.fromtimestamp(_FINISHED_AT, timezone.utc).isoformat()
    assert r.json()["last_check"]["health_job"] == expected_iso  # 守卫不误伤合法 job


# ---------- 矩阵: market_state_mtime null 腿 (缺失/不可 stat -> null) ----------

def test_market_state_mtime_null_when_file_missing(tmp_path):
    _seed_registry_job(tmp_path, "a" * 32, "health-check", "succeeded",
                       finished_at=_FINISHED_AT)
    r = client.get("/health/details", headers=_headers())
    assert r.status_code == 200  # state 文件缺席绝不 5xx —— 这正是端点要报告的条件
    body = r.json()
    assert body["last_check"]["health_job"] is not None  # registry 侧照常
    assert body["last_check"]["market_state_mtime"] is None


def test_market_state_mtime_null_when_stat_fails(tmp_path, monkeypatch):
    _write_market_state(tmp_path, _MTIME)  # 文件在位, 但 stat 被拒
    real_stat = os.stat

    def raiser(path, *args, **kwargs):
        if str(path).endswith("market_state.json"):
            raise OSError("stat blocked")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", raiser)
    r = client.get("/health/details", headers=_headers())
    assert r.status_code == 200
    assert r.json()["last_check"]["market_state_mtime"] is None


# ---------- 矩阵: fail-closed 无 token 配置 (api/auth.py None 分支) ----------

def test_fail_closed_403_no_token_configured(tmp_path):
    # fixture 默认写了 token 文件 -> 移除; conftest _clean_env 已删 GOGO_API_TOKEN
    (Path(tmp_path) / "data" / "api_token.txt").unlink()
    for key in (TOKEN, "", "whatever"):
        r = client.get("/health/details", headers={"X-API-Key": key})
        assert r.status_code == 403, f"no-token 配置必须 fail-closed, got {r.status_code}"
        assert r.json() == {"detail": "invalid API key", "code": "invalid_api_key"}
        assert "www-authenticate" not in r.headers  # 403 无挑战头 (D-10)


# ---------- 矩阵: versions 兜底 + 自洽 (PackageNotFoundError -> unknown) ----------

def test_versions_unknown_on_packagenotfound(tmp_path, monkeypatch):
    real_version = importlib.metadata.version

    def fake_version(dist):
        if dist == "uvicorn":
            raise importlib.metadata.PackageNotFoundError(f"No package {dist}")
        return real_version(dist)

    monkeypatch.setattr(importlib.metadata, "version", fake_version)
    r = client.get("/health/details", headers=_headers())
    assert r.status_code == 200
    versions = r.json()["versions"]
    assert versions["uvicorn"] == "unknown"  # 缺失发行版兜底
    assert versions["python"]  # sys.version 仍填充
    assert versions["fastapi"] == real_version("fastapi")  # 其余发行版不受扰


def test_versions_self_consistency_with_importlib_metadata(tmp_path):
    # 自洽断言: 非 unknown 值 == 测试内同源计算 (绝不硬编码版本串 —— 双机漂移不假红)
    r = client.get("/health/details", headers=_headers())
    assert r.status_code == 200
    versions = r.json()["versions"]
    for dist in ("uvicorn", "fastapi"):
        if versions[dist] != "unknown":
            assert versions[dist] == importlib.metadata.version(dist)


# ---------- 矩阵: 泄漏卫生 (无路径 / 无 token 字节) ----------

def test_no_path_or_token_leak_in_bodies(tmp_path):
    bodies = []

    def _seen(r):
        bodies.append(r.content)
        return r

    _seen(client.get("/health/details"))  # 401 体
    _seen(client.get("/health/details", headers={"X-API-Key": "wrong"}))  # 403 体
    _seen(client.get("/health/details", headers=_headers()))  # 200 体
    for body in bodies:
        assert str(tmp_path).encode() not in body  # 错误体/响应体永不含路径 (SC3)
        assert TOKEN.encode() not in body          # 无 token 字节


# ---------- 矩阵: 公开 /health 字节级钉 (注册新路由后仍逐字节不动) ----------

def test_public_health_exact_pins_beside_details(tmp_path):
    r = client.get("/health")  # 无 key (HLT-01 纯度)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert set(r.json().keys()) == {"status", "uptime_seconds"}
    first = r.json()["uptime_seconds"]
    second = client.get("/health").json()["uptime_seconds"]
    assert second >= first  # monotonic 非降 (同一锚点)
