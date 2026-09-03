"""SEC-01 契约套: X-API-Key 鉴权 + 密钥卫生 (D-10/D-11, RESEARCH Pattern 5)。

本文件钉 api/auth.py + api/actions.py 的鉴权合同:
- 缺失 X-API-Key 头 -> 401 {"detail": "missing API key", "code": "missing_api_key"} +
  WWW-Authenticate: ApiKey 挑战头 (只在 401); 带错 key -> 403
  {"detail": "invalid API key", "code": "invalid_api_key"} 无挑战头。
- env GOGO_API_TOKEN 优先于文件 (read_token 链路); 无 token 配置 -> fail-closed 403。
- /health、/health/ready、GET /v1/state/{name} 结构豁免 (D-11) —— 公开路由,
  无中间件, /health 纯度 (HLT-01)。
- 401/403/404 拒绝路径零 spawn / 零 registry 写 (被拒请求永不干扰运行中 job)。
- 密钥字节级缺席审计: job 日志、子进程 env dump、所有响应体 (T-03-09;
  run_job 的 GOGO_API_TOKEN pop 是机械半边, 真机 console.log grep 归 03-04)。
- query 参数篡改不能改变 401/403/202 结局 (?token_path=<decoy> 钉 request-only
  签名 —— prohibition #2, FastAPI 不得把依赖参数暴露成查询参数)。

CRITICAL 数据隔离 pin (同 test_actions.py): autouse fixture 把 jobs/auth/state
三模块路径缝指到 tmp_path, 清空 _claims/_CACHE, 真实 data//logs/ 零触碰。
"""
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

import api.actions  # noqa: F401  (被测模块; SCRIPTS_DIR 缝)
import api.auth  # noqa: F401  (被测模块; DATA_DIR 缝)
import api.jobs  # noqa: F401  (被测模块; _claims 清理)
import api.main  # noqa: F401  (/health + state 路由 —— 模块级 client 依赖)
import api.state  # noqa: F401  (公开面断言用; DATA_DIR 缝)
from api.main import app

client = TestClient(app)  # 模块级, 无 context manager (test_state.py 惯例)

TOKEN = "test-token-03-02-auth"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """每测试前: jobs/auth/state 路径缝 -> tmp_path 子树 + 清空跨测试状态。"""
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
    """真实命名的假脚本树 (KIND_CMDS 真名流通), 返回 SCRIPTS_DIR 应指的目录。"""
    daily = Path(base) / "scripts" / "daily"
    daily.mkdir(parents=True, exist_ok=True)
    for kind, (script_name, sleep) in kinds.items():
        assert api.actions.KIND_CMDS[kind][0] == script_name  # 真名钉
        (daily / script_name).write_text(
            _FAKE_BODY.replace("{sleep!r}", repr(sleep)), encoding="utf-8"
        )
    return str(Path(base) / "scripts")


def _headers(key=TOKEN):
    return {"X-API-Key": key}


def wait_terminal(job_id, key=TOKEN, timeout=12.0):
    """GET 轮询到终态; 瞬时 503 (replace 碰撞 µs 窗口) 视为未就绪重试。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        r = client.get(f"/v1/jobs/{job_id}", headers=_headers(key))
        if r.status_code == 503:
            time.sleep(0.01)
            continue
        assert r.status_code == 200, f"GET /v1/jobs/{job_id} -> {r.status_code} {r.text}"
        last = r.json()
        if last["status"] in ("succeeded", "failed", "interrupted"):
            return last
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} 未到终态 ({timeout}s 超时, last={last!r})")


# ---------- 测试 1: 缺失 key -> 401 + 挑战头 (POST 与 GET 同合同) ----------

def test_missing_key_401_post_and_get(tmp_path):
    r = client.post("/v1/actions/pipeline")  # 无 X-API-Key 头
    assert r.status_code == 401
    assert r.json() == {"detail": "missing API key", "code": "missing_api_key"}
    assert r.headers.get("www-authenticate") == "ApiKey"  # D-10 挑战头精确值

    r = client.get(f"/v1/jobs/{'a' * 32}")  # 合规形状 id, 无头
    assert r.status_code == 401
    assert r.json() == {"detail": "missing API key", "code": "missing_api_key"}
    assert r.headers.get("www-authenticate") == "ApiKey"


# ---------- 测试 2: 带错 key -> 403, 无挑战头 ----------

def test_wrong_key_403_without_challenge(tmp_path):
    r = client.post("/v1/actions/pipeline", headers={"X-API-Key": "definitely-wrong"})
    assert r.status_code == 403
    assert r.json() == {"detail": "invalid API key", "code": "invalid_api_key"}
    assert "www-authenticate" not in r.headers  # 挑战头只在 401 (D-10)


# ---------- 测试 3: env 优先于文件 (read_token 链路) ----------

def test_env_token_precedence_over_file(tmp_path, monkeypatch):
    write_token(tmp_path / "data", "file-token")  # 文件是 file-token
    monkeypatch.setenv("GOGO_API_TOKEN", "env-token")  # env 是 env-token
    scripts = fake_script_tree(tmp_path, {"pipeline": ("run_pipeline.py", 0.3)})
    monkeypatch.setattr(api.actions, "SCRIPTS_DIR", scripts)
    out = tmp_path / "out.json"
    monkeypatch.setenv("FAKE_OUT", str(out))

    r = client.post("/v1/actions/pipeline", headers=_headers("file-token"))
    assert r.status_code == 403  # 文件 token 在 env 存在时不生效
    assert r.json() == {"detail": "invalid API key", "code": "invalid_api_key"}

    r = client.post("/v1/actions/pipeline", headers=_headers("env-token"))
    assert r.status_code == 202  # env token 生效
    job_id = r.json()["job_id"]
    assert re.fullmatch(r"[0-9a-f]{32}", job_id)
    term = wait_terminal(job_id, key="env-token")  # 等终态, 避免 worker 跨测试残留
    assert term["status"] == "succeeded"


# ---------- 测试 4: 无任何 token 配置 -> fail-closed 403 ----------

def test_fail_closed_when_no_token_configured(tmp_path, monkeypatch):
    (tmp_path / "data" / "api_token.txt").unlink()  # 去掉 fixture 默认 token 文件
    # conftest _clean_env 已删 GOGO_API_TOKEN; 本测试不再 setenv -> 全空

    for headers in (_headers("whatever"), _headers(""), _headers(TOKEN)):
        r = client.post("/v1/actions/pipeline", headers=headers)
        assert r.status_code == 403, f"no-token 配置必须 fail-closed, got {r.status_code}"
        assert r.json() == {"detail": "invalid API key", "code": "invalid_api_key"}
        r = client.get(f"/v1/jobs/{'b' * 32}", headers=headers)
        assert r.status_code == 403  # 永不 200/202


# ---------- 测试 5: 公开面结构豁免 (D-11) ----------

def test_public_exemptions_no_key_needed(tmp_path):
    assert client.get("/health").status_code == 200  # HLT-01 纯度

    for name in ("market_state.json", "auction_state.json", "zt_pool_state.json"):
        (tmp_path / "data" / name).write_text('{"ok": true}', encoding="utf-8")
    r = client.get("/health/ready")  # 已注册 (state 路由) -> 无头 200
    assert r.status_code == 200

    r = client.get("/v1/state/market_state")  # 白名单文件 seeded
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    r = client.get("/v1/state/not_in_whitelist")
    assert r.status_code == 404  # state 路由自己的 404 —— 不是 401/403
    assert r.json() == {"detail": "Not Found", "code": "unknown_state_name"}


# ---------- 测试 6: 拒绝路径零副作用 (无 spawn / 无 registry / 无锁) ----------

def test_no_spawn_on_rejection(tmp_path):
    registry = api.jobs.jobs_dir()
    locks = api.jobs.locks_dir()

    assert client.post("/v1/actions/pipeline").status_code == 401  # 无头
    assert client.post(
        "/v1/actions/pipeline", headers={"X-API-Key": "wrong"}
    ).status_code == 403
    assert client.post("/v1/actions/nonsense", headers=_headers()).status_code == 404
    assert client.get(f"/v1/jobs/{'c' * 32}").status_code == 401
    assert client.get(
        f"/v1/jobs/{'d' * 32}", headers={"X-API-Key": "wrong"}
    ).status_code == 403

    # registry 目录零文件; 锁目录未产生 (401/403 无 acquire, 404 白名单先于 acquire)
    assert not os.path.isdir(registry) or os.listdir(registry) == []
    assert not os.path.isdir(locks) or os.listdir(locks) == []


# ---------- 测试 7: token 字节级缺席审计 (job 日志 / 子进程 env / 响应体) ----------

def test_token_never_leaks_to_log_env_or_bodies(tmp_path, monkeypatch):
    secret = "super-secret-token-abc123"
    write_token(tmp_path / "data", secret)
    monkeypatch.setenv("GOGO_API_TOKEN", secret)  # 走 env 分支 + 钉子进程 pop
    scripts = fake_script_tree(tmp_path, {"pipeline": ("run_pipeline.py", 0.3)})
    monkeypatch.setattr(api.actions, "SCRIPTS_DIR", scripts)
    out = tmp_path / "out.json"
    env_out = tmp_path / "env.json"
    monkeypatch.setenv("FAKE_OUT", str(out))
    monkeypatch.setenv("FAKE_ENV_OUT", str(env_out))

    bodies = []  # 测试全程见过的所有响应体

    def _seen(r):
        bodies.append(r.content)
        return r

    # 401/403/404 错误体
    assert _seen(client.post("/v1/actions/pipeline")).status_code == 401
    assert _seen(
        client.post("/v1/actions/pipeline", headers={"X-API-Key": "nope"})
    ).status_code == 403
    assert _seen(
        client.post("/v1/actions/pipeline", headers=_headers(secret + "x"))
    ).status_code == 403
    assert _seen(
        client.post("/v1/actions/bogus", headers=_headers(secret))
    ).status_code == 404
    # 真实触发 + 轮询 200/202 体
    r = _seen(client.post("/v1/actions/pipeline", headers=_headers(secret)))
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    term = wait_terminal(job_id, key=secret)
    _seen(client.get(f"/v1/jobs/{job_id}", headers=_headers(secret)))

    log_bytes = Path(term["log_path"]).read_bytes()
    env_bytes = Path(env_out).read_bytes()

    assert secret.encode() not in log_bytes, "token 出现在 job 日志字节"
    assert secret.encode() not in env_bytes, "token 出现在子进程 env dump"
    for body in bodies:
        assert secret.encode() not in body, f"token 出现在响应体: {body[:120]!r}"
    assert "GOGO_API_TOKEN" not in json.loads(env_bytes.decode("utf-8")), (
        "子进程 env 仍含 GOGO_API_TOKEN 键 (run_job pop 失效)"
    )
    assert term["status"] == "succeeded"  # 假脚本正常跑完, dump 完整


# ---------- 测试 8: ?token_path= 查询参数不能改变 401/403/202 结局 ----------

def test_query_param_tamper_cannot_alter_gate(tmp_path, monkeypatch):
    write_token(tmp_path / "data", "real-token")  # 真 token 在文件
    decoy = tmp_path / "decoy_token.txt"
    decoy.write_text("evil-token\n", encoding="utf-8")
    qs = f"?token_path={quote(str(decoy), safe='')}"
    scripts = fake_script_tree(tmp_path, {"pipeline": ("run_pipeline.py", 0.3)})
    monkeypatch.setattr(api.actions, "SCRIPTS_DIR", scripts)
    out = tmp_path / "out.json"
    monkeypatch.setenv("FAKE_OUT", str(out))

    # (b) decoy 文件 key + query 指向 decoy -> 403 (decoy 永不成为比较源)
    r = client.post(f"/v1/actions/pipeline{qs}", headers={"X-API-Key": "evil-token"})
    assert r.status_code == 403
    assert r.json() == {"detail": "invalid API key", "code": "invalid_api_key"}
    # (c) 无头 + query -> 401
    r = client.post(f"/v1/actions/pipeline{qs}")
    assert r.status_code == 401
    assert r.json() == {"detail": "missing API key", "code": "missing_api_key"}
    # (a) 真 token + query -> 202 (query 被忽略, 有效 key 不受影响)
    r = client.post(f"/v1/actions/pipeline{qs}", headers={"X-API-Key": "real-token"})
    assert r.status_code == 202
    term = wait_terminal(r.json()["job_id"], key="real-token")
    assert term["status"] == "succeeded"
