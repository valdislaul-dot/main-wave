"""统一机器可读错误信封契约套 (04-CONTEXT 暴露面硬化清单 + SC3 + P2 UI-review Top-3)。

本文件钉 04-01 交付的 app 级统一错误信封 (api/errors.py + api/main.py 注册):
- 每个 4xx/5xx 响应体形如 {"detail": <原文或统一 404 文案>, "code": <稳定机器码>},
  键序固定 detail 先于 code (消费者按 code 分支, 绝不解析散文 —— UI-review #1)。
- 404 文案 API 全域单一定稿 "Not Found" (UI-review #2): handler raise 与框架
  route-miss 两类 body 字节相同, 语义差由 per-site code 携带
  (unknown_state_name / unknown_action_kind / job_not_found / not_found)。
- 405/422/500 框架类也走统一信封 (method_not_allowed / validation_error /
  internal_error); 未知名 detail 文本回退 http_{status} (D-04: 不 echo 内部细节)。
- 未处理异常的 traceback 只进服务端 stderr, 响应体永不含 Traceback/路径/token (SC3)。
- /openapi.json 公开可读 (无 key 200), schema 覆盖全部已注册路由 (UI-review #3)。

CRITICAL 数据隔离 pin (同 test_state/test_auth 惯例): autouse fixture 把
jobs/auth/state 三模块路径缝指到 tmp_path 子树并清空 _claims/_CACHE —— 真实
data//logs/ 零触碰。探针路由 (405/422/500/fallback 类) 在模块层注册一次,
include_in_schema=False, 不影响 /openapi.json 断言。
"""
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import api.actions  # noqa: F401  (模块级 client 依赖注册)
import api.auth  # noqa: F401  (DATA_DIR 缝)
import api.jobs  # noqa: F401  (LOG_DIR/DATA_DIR 缝 + _claims 清理)
import api.main  # noqa: F401  (/health + state + actions/jobs 路由 + 信封注册)
import api.state  # noqa: F401  (公开面断言用; DATA_DIR 缝)
from api.main import app

client = TestClient(app)  # 模块级, 无 context manager (test_state.py 惯例)
# ServerErrorMiddleware 发出 500 后无条件 re-raise (starlette/middleware/errors.py
# L184-187), 默认 TestClient(raise_server_exceptions=True) 会把它抛回测试线程
# (testclient.py L338-340) —— 拿不到 500 响应体。真机 uvicorn 吞掉 re-raise 只记
# 日志, 客户端拿到的恰是信封体; 500 契约断言钉真机线面, 用 no-raise client。
client_no_raise = TestClient(app, raise_server_exceptions=False)

TOKEN = "test-token-04-01-envelope"

# ---- 套件探针路由 (本文件专用; 框架 405/422/500 + fallback 类无现成端点) ----


def _probe_typed_query(count: int = 0):
    """声明式 int 查询参数 —— 触发框架 RequestValidationError 路径。"""
    return {"count": count}


def _probe_unhandled():
    """未处理异常路径: 由 app 级 Exception handler 转统一 500 (traceback 服务端)。"""
    raise RuntimeError("probe-boom-envelope")


def _probe_unmapped_404():
    """未入冻结表的 404 detail 文本 -> 统一文案 + http_404 回退码。"""
    raise HTTPException(404, "some unmapped text")


app.add_api_route("/probe/typed-query", _probe_typed_query, methods=["GET"], include_in_schema=False)
app.add_api_route("/probe/unhandled", _probe_unhandled, methods=["GET"], include_in_schema=False)
app.add_api_route("/probe/unmapped-404", _probe_unmapped_404, methods=["GET"], include_in_schema=False)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """每测试前: jobs/auth/state 路径缝 -> tmp_path 子树 + 清空跨测试状态。

    信封测试不写文件, 但沿用兄弟套件的隔离纪律 —— 真实 data//logs/ 零触碰;
    token 文件默认写入 (错误 key 与 404 类断言需要真实比较源)。
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


def _headers(key=TOKEN):
    return {"X-API-Key": key}


# ---------- 行为 1: 401/403 信封 + 挑战头 ----------

def test_401_403_envelope_shape_and_challenge_header(tmp_path):
    """缺头 401 {missing_api_key} + WWW-Authenticate: ApiKey; 错 key 403 无挑战头。"""
    r = client.post("/v1/actions/pipeline")  # 无 X-API-Key 头
    assert r.status_code == 401
    body = r.json()
    assert body == {"detail": "missing API key", "code": "missing_api_key"}
    assert r.headers.get("www-authenticate") == "ApiKey"  # D-10 挑战头精确值 (只在 401)

    r = client.post("/v1/actions/pipeline", headers={"X-API-Key": "definitely-wrong"})
    assert r.status_code == 403
    assert r.json() == {"detail": "invalid API key", "code": "invalid_api_key"}
    assert "www-authenticate" not in r.headers  # 403 无挑战头 (D-10)


# ---------- 行为 2: 404 文案统一 —— handler 与框架 route-miss 同一 copy ----------

def test_404_unified_copy_with_per_site_codes(tmp_path):
    """404 detail 全域恰为 "Not Found"; handler raise 与框架 miss 的语义差进 code。"""
    cases = [
        ("GET", "/v1/state/unknown_name", None, "unknown_state_name"),
        ("POST", "/v1/actions/nonsense", _headers(), "unknown_action_kind"),
        ("GET", f"/v1/jobs/{'a' * 32}", _headers(), "job_not_found"),
        ("GET", "/v1/nonexistent_route", None, "not_found"),
    ]
    details = []
    for method, url, headers, code in cases:
        r = client.request(method, url, headers=headers)
        assert r.status_code == 404, (url, r.status_code, r.text)
        body = r.json()
        assert body == {"detail": "Not Found", "code": code}, (url, body)
        assert body["detail"] == "Not Found"
        details.append(body["detail"])
    assert len(set(details)) == 1  # 四类 404 的 detail 字节完全相同 (UI-review #2)


# ---------- 行为 3: 405/422/500 框架类统一信封 ----------

def test_405_422_500_framework_handlers(tmp_path):
    """框架 method-miss 405 / validation 422 / 未处理 500 全走信封。"""
    r = client.post("/health")  # GET-only 路由 -> 框架 405
    assert r.status_code == 405
    assert r.json() == {"detail": "Method Not Allowed", "code": "method_not_allowed"}

    r = client.get("/probe/typed-query?count=abc")  # 声明式 int 参数校验失败
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error"
    assert isinstance(body["detail"], list) and len(body["detail"]) >= 1

    r = client_no_raise.get("/probe/unhandled")  # RuntimeError -> 统一 500 体
    assert r.status_code == 500
    assert r.json() == {"detail": "internal server error", "code": "internal_error"}
    assert "Traceback" not in r.text  # SC3: traceback 永不进响应体


# ---------- 行为 4: 未入表文本回退 http_{status} + detail/code 键序 ----------

def test_unmapped_text_fallback_code_and_key_order(tmp_path):
    """冻结表外 404 文本 -> 统一文案 + http_404 回退; JSON 键序 detail 先于 code。"""
    r = client.get("/probe/unmapped-404")
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found", "code": "http_404"}  # 回退码 (T-04-04)

    r = client.post("/v1/actions/pipeline")  # 401 信封体
    assert list(r.json().keys()) == ["detail", "code"]  # 键序钉死 (消费者契约)
    r = client.get("/probe/typed-query?count=abc")
    assert list(r.json().keys()) == ["detail", "code"]


# ---------- 行为 5: traceback 只进服务端 stderr, 体无路径/无 token ----------

def test_unhandled_traceback_stays_server_side(tmp_path, capsys):
    """未处理异常: stderr 有 ASCII marker + traceback; body 无路径/无异常内部。"""
    secret = "super-secret-token-04-01"
    write_token(tmp_path / "data", secret)

    r = client_no_raise.get("/probe/unhandled")
    assert r.status_code == 500
    assert r.json() == {"detail": "internal server error", "code": "internal_error"}

    captured = capsys.readouterr()
    assert "probe-boom-envelope" in captured.err  # 异常名只出现在服务端控制台
    assert str(tmp_path) not in r.text  # D-04: 路径永不进错误体
    assert secret.encode() not in r.content  # SC3: token 永不进错误体
    assert "Traceback" not in r.text


# ---------- 行为 6: /openapi.json 公开可读, schema 覆盖全部路由 ----------

def test_openapi_schema_served_publicly(tmp_path):
    """GET /openapi.json 无 key 200; paths 含 health/state/actions/jobs 全族。"""
    r = client.get("/openapi.json")  # 公开分类路由 (04-03 SC2 审计对象)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/json"
    schema = r.json()
    assert schema["openapi"].startswith("3.")
    paths = schema["paths"]
    for p in (
        "/health",
        "/health/ready",
        "/v1/state/{name}",
        "/v1/actions/{kind}",
        "/v1/jobs/{job_id}",
    ):
        assert p in paths, f"openapi paths 缺 {p}"
