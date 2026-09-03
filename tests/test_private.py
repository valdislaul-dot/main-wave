"""STA-02/SEC-02 私密读契约套 (04-03 tracer 切片 + SC1-3, D-01/D-03/D-04/D-05)。

GET /v1/private/{name} (portfolio/journal/candidates) —— 机密级 token 门控读:
- 无 key -> 401 {"detail": "missing API key", "code": "missing_api_key"} +
  WWW-Authenticate: ApiKey 挑战头 (只在 401); 错 key -> 403 invalid_api_key
  无挑战头 (D-10 契约与 actions/jobs 面同源, 04-01 信封形状)。
- 200 体 = 文件原始字节逐字透传 (D-01 raw-passthrough: 绝不重序列化,
  CRLF/中文原样), content-type application/json (无 charset),
  X-Data-Mtime = 文件真实 mtime (同读句柄 fstat), X-Data-Age-S 非负整数字符串;
  新鲜路径绝不带 X-Data-Stale (D-05)。
- 白名单 gate 先于一切路径组合 (D-03): 未知名 404 / 非法 date 422 /
  缺失不可读 503, 全说 04-01 冻结信封码; 错误体永不含路径 (SC3)。
- candidates 语义 (D-14): 无 ?date= -> 最新 candidates_*.json (排除
  candidates_v* 旧格式); ?date=YYYY-MM-DD/YYYYMMDD -> 精确日期文件
  (compact 归一化); 良构但无文件 -> 503; 形状/语义越界 (2026-13-99) -> 422。
- 撕裂窗 (D-05): 注入 reader 单测钉 get_private 孪生语义 —— 解码失败短重试,
  持续失败回退末次成功缓存 (体与缓存 mtime 同版本), 冷缓存 -> StateUnavailable
  -> 路由 503, 绝不给裸 500; 白名单外 decoy 文件永不可达 (body 永不等 decoy,
  str(tmp_path) 永不在错误体)。
- 公开面 (SC1): /health、/health/ready、GET /v1/state/*、/openapi.json 无 key
  照常 —— 私密路由并排注册后公开级不受扰动。

CRITICAL 数据隔离 pin (同 test_state/test_auth 惯例): autouse fixture 把
api.private.LOG_DIR 与 api.auth/api.state 的 DATA_DIR 指到 tmp_path 子树并清空
private/state 两 _CACHE —— 真实 logs/ 与 data/ 零触碰 (suite 结束时
git status --porcelain -- data/ logs/ 必须为空)。
"""
import asyncio
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.auth  # noqa: F401  (被测模块; DATA_DIR 缝)
import api.main  # noqa: F401  (路由注册 —— 一次 import 覆盖公开+私密路由族)
import api.private  # noqa: F401  (被测模块; LOG_DIR 缝 + _CACHE 清理)
import api.state  # noqa: F401  (公开面断言用; DATA_DIR 缝)
from api.main import app

client = TestClient(app)  # 模块级, 无 context manager (test_state.py 惯例)

TOKEN = "test-token-04-03-private"

# 真实形态 fixture: UTF-8 中文 + CRLF 行尾 + 合法 JSON (Pitfall 1 —— json.loads
# 验证门必须能过; 字节必须原样透传, 任何重序列化/换行翻译都会打破 byte pin)。
_PORTFOLIO = (
    '{\r\n'
    '  "cash": 1415.5,\r\n'
    '  "positions": [\r\n'
    '    {"code": "003040", "name": "楚天龙", "shares": 2900},\r\n'
    '    {"code": "000428", "name": "华天酒店", "shares": 5500}\r\n'
    '  ]\r\n'
    '}\r\n'
).encode("utf-8")
_JOURNAL = (
    '{\r\n'
    '  "trades": [\r\n'
    '    {"date": "2026-08-26", "action": "加仓楚天龙", "pnl": 0}\r\n'
    '  ]\r\n'
    '}\r\n'
).encode("utf-8")

_MTIME = 1_700_000_000  # 冻结 mtime: X-Data-Mtime/X-Data-Age-S 精确断言锚点


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """每测试前: private LOG_DIR + auth/state DATA_DIR -> tmp_path 子树 + 清缓存。

    private 文件 (portfolio.json/trading_journal.json/candidates_*.json) 在
    LOG_DIR 根 (真实 logs/ 布局的镜像); auth/state 缝指同一棵树的 data/ 子目录
    (token 文件 + 公开面 state 文件)。
    """
    monkeypatch.setattr(api.private, "LOG_DIR", str(tmp_path))
    monkeypatch.setattr(api.auth, "DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(api.state, "DATA_DIR", str(tmp_path / "data"))
    api.private._CACHE.clear()
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


def _write_logs(tmp_path, filename, raw, mtime):
    """按文件名写 logs/ 下的私密 fixture (二进制 + 定 mtime), 返回路径。"""
    path = tmp_path / filename
    path.write_bytes(raw)
    os.utime(path, (mtime, mtime))
    return path


def _write_state(tmp_path, name, raw):
    """按白名单文件名写公开 state fixture 到 DATA_DIR (tmp/data)。"""
    path = tmp_path / "data" / api.state.STATE_FILES[name]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def _write_candidates(tmp_path, date_part, raw, mtime):
    """写 candidates_{date_part}.json 到 LOG_DIR (镜像真实 logs/ 布局)。"""
    path = tmp_path / f"candidates_{date_part}.json"
    path.write_bytes(raw)
    os.utime(path, (mtime, mtime))
    return path


def _asgi_get(path):
    """原样 path 直呼 ASGI app (绕过 httpx 客户端规范化), 返回 (statuses, body_parts)。

    WR-03 同族 (04-01/04-02): TestClient 的 httpx 在传输前把字面 ".." 段折叠成
    规范化 URL, 拿不到真机 uvicorn 的路由答案; 本 helper 按服务器收到 scope 的
    原样 path 调用 app —— 服务器侧不折叠才是路由真值。
    """
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
        "root_path": "",
        "state": {},
    }
    statuses = []
    body_parts = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            statuses.append(message["status"])
        elif message["type"] == "http.response.body":
            body_parts.append(message.get("body", b""))

    async def run():
        await app(scope, receive, send)

    asyncio.run(run())
    return statuses, body_parts


# ---------- tracer 行为 1: 门矩阵 (401/403/200, portfolio 路径) ----------

def test_gate_matrix_no_key_401_wrong_key_403_valid_200(tmp_path):
    _write_logs(tmp_path, "portfolio.json", _PORTFOLIO, _MTIME)

    r = client.get("/v1/private/portfolio")  # 无 X-API-Key 头
    assert r.status_code == 401
    assert r.json() == {"detail": "missing API key", "code": "missing_api_key"}
    assert r.headers.get("www-authenticate") == "ApiKey"  # D-10 挑战头精确值

    r = client.get("/v1/private/portfolio", headers={"X-API-Key": "definitely-wrong"})
    assert r.status_code == 403
    assert r.json() == {"detail": "invalid API key", "code": "invalid_api_key"}
    assert "www-authenticate" not in r.headers  # 挑战头只在 401 (D-10)

    r = client.get("/v1/private/portfolio", headers=_headers())
    assert r.status_code == 200  # 有效 key 过门


# ---------- tracer 行为 2: 原始字节 + 精确新鲜头 (portfolio 路径) ----------

def test_raw_bytes_verbatim_and_exact_fresh_headers(tmp_path, monkeypatch):
    _write_logs(tmp_path, "portfolio.json", _PORTFOLIO, _MTIME)
    monkeypatch.setattr(api.private.time, "time", lambda: _MTIME + 100)

    r = client.get("/v1/private/portfolio", headers=_headers())
    assert r.status_code == 200
    assert r.content == _PORTFOLIO  # 字节相等 = D-01 逐字透传 (CRLF + 中文原样)
    assert r.headers["content-type"] == "application/json"  # 无 charset
    assert r.headers["x-data-mtime"] == str(_MTIME)  # 真实 mtime 字符串
    assert r.headers["x-data-age-s"] == "100"  # 冻结时间 -> 精确非负秒数
    assert "x-data-stale" not in r.headers  # 新鲜路径绝不带 stale 头 (D-05)


# ---------- tracer 行为 3: 公开面无 key 照常 (SC1) ----------

def test_public_tier_untouched_beside_private(tmp_path):
    assert client.get("/health").status_code == 200  # 无 key (HLT-01 纯度)
    assert client.get("/openapi.json").status_code == 200  # 公开 schema

    for name in ("market_state", "auction_state", "zt_pool_state"):
        _write_state(tmp_path, name, b'{"ok": true}\r\n')
    assert client.get("/health/ready").status_code == 200
    r = client.get("/v1/state/market_state")  # 公开白名单读, 无 key 照常 (SC1)
    assert r.status_code == 200
    assert r.json() == {"ok": True}


# ---------- tracer 行为 4: journal 走同一切片 (raw + 头) ----------

def test_journal_rides_same_slice_raw_and_headers(tmp_path, monkeypatch):
    _write_logs(tmp_path, "trading_journal.json", _JOURNAL, _MTIME)
    monkeypatch.setattr(api.private.time, "time", lambda: _MTIME + 60)

    r = client.get("/v1/private/journal", headers=_headers())
    assert r.status_code == 200
    assert r.content == _JOURNAL  # 账本字节逐字透传 (D-01)
    assert r.headers["content-type"] == "application/json"
    assert r.headers["x-data-mtime"] == str(_MTIME)
    assert r.headers["x-data-age-s"] == "60"
    assert "x-data-stale" not in r.headers


# ---------- STA-02 扩展: candidates 语义 (D-14, 镜像 morning_check.py:11-18) ----------

def test_candidates_no_param_serves_newest_excluding_legacy(tmp_path):
    older = b'{"date": "2026-09-01", "pool": ["000428"]}\n'
    newest = b'{"date": "2026-09-03", "pool": ["003040"]}\n'
    _write_candidates(tmp_path, "2026-09-01", older, _MTIME)
    _write_candidates(tmp_path, "2026-09-03", newest, _MTIME)
    # 旧格式 decoy (candidates_v*): 文件真实存在且日期最新, 但永不入选 (D-14)
    legacy = b'{"date": "2026-09-03", "legacy": true}\n'
    _write_candidates(tmp_path, "v3_2026-09-03", legacy, _MTIME)

    r = client.get("/v1/private/candidates", headers=_headers())
    assert r.status_code == 200
    assert r.content == newest  # 最新 candidates_*.json (排除 candidates_v*)
    assert r.json() == {"date": "2026-09-03", "pool": ["003040"]}


def test_candidates_date_both_formats_serve_same_file_with_headers(tmp_path, monkeypatch):
    day1 = b'{"date": "2026-09-01", "pool": ["000428"]}\n'
    day3 = b'{"date": "2026-09-03", "pool": ["003040"]}\n'
    _write_candidates(tmp_path, "2026-09-01", day1, 1_700_000_001)
    _write_candidates(tmp_path, "2026-09-03", day3, 1_700_000_003)
    monkeypatch.setattr(api.private.time, "time", lambda: 1_700_000_100)

    # dashed 格式: 精确日期文件 + 其真实 mtime/age 头
    r = client.get("/v1/private/candidates?date=2026-09-01", headers=_headers())
    assert r.status_code == 200
    assert r.content == day1  # 日期命中 -> 绝不回退最新文件
    assert r.headers["x-data-mtime"] == "1700000001"
    assert r.headers["x-data-age-s"] == "99"

    # compact 格式: 归一化为同一文件, 同一 mtime/age 断言
    r = client.get("/v1/private/candidates?date=20260901", headers=_headers())
    assert r.status_code == 200
    assert r.content == day1  # YYYYMMDD -> 与 dashed 同一文件
    assert r.headers["x-data-mtime"] == "1700000001"
    assert r.headers["x-data-age-s"] == "99"


def test_candidates_invalid_date_422_missing_file_503(tmp_path):
    _write_candidates(tmp_path, "2026-09-03", b'{"date": "2026-09-03"}\n', _MTIME)

    # 形状越界 (斜杠/位数不足/字母) + 语义越界 (13 月) -> 一律 422 冻结信封 (SC4);
    # 注: 泛化月/日区间门 (1-12/1-31) 是契约, 逐月历法校验 (如 02-31) 不在白名单语义内
    for bad in ("2026/09/01", "2026091", "abc", "2026-13-99", "2026-00-10", "2026-09-00"):
        r = client.get("/v1/private/candidates", params={"date": bad}, headers=_headers())
        assert r.status_code == 422, bad
        assert r.json() == {
            "detail": "date must be YYYY-MM-DD or YYYYMMDD",
            "code": "invalid_date_format",
        }
        assert str(tmp_path) not in r.text  # 错误体永不含路径 (SC3)
        assert "\\" not in r.text  # D-04: 路径分隔符永不泄漏

    # 良构但无对应文件 (且缓存冷) -> 503, 绝不 500
    r = client.get("/v1/private/candidates", params={"date": "2026-09-05"}, headers=_headers())
    assert r.status_code == 503
    assert r.json() == {
        "detail": "private data temporarily unavailable",
        "code": "private_data_unavailable",
    }


def test_candidates_no_files_cold_503(tmp_path):
    # logs/ 下零 candidates 文件 (portfolio 存在也无济于事) -> 503 (D-14)
    _write_logs(tmp_path, "portfolio.json", _PORTFOLIO, _MTIME)
    r = client.get("/v1/private/candidates", headers=_headers())
    assert r.status_code == 503
    assert r.json() == {
        "detail": "private data temporarily unavailable",
        "code": "private_data_unavailable",
    }
    assert str(tmp_path) not in r.text


# ---------- STA-02 扩展: 白名单 gate 先于一切 (D-03/D-04) + decoy 守卫 ----------

def test_unknown_name_gate_first_over_date_404_not_422(tmp_path):
    # 名字门先于日期门: 未知名 + 非法日期 -> 404 (绝不落 422/路径组合)
    r = client.get("/v1/private/bogus", params={"date": "abc"}, headers=_headers())
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found", "code": "unknown_private_name"}
    assert "\\" not in r.text


def test_unknown_names_404_decoy_unreachable_no_paths(tmp_path):
    # 白名单外 decoy 文件真实存在于 LOG_DIR —— 永不 200, body 永不等 decoy (D-04)
    decoy_md = "# report\nportfolio=secret\n".encode("utf-8")
    decoy_dir = tmp_path / "daily_reports"
    decoy_dir.mkdir()
    (decoy_dir / "2026-09-03.md").write_bytes(decoy_md)
    decoy_bak = b'{"portfolio": {"cash": 99999}}'
    _write_logs(tmp_path, "portfolio.json.bak", decoy_bak, _MTIME)
    _write_logs(tmp_path, "portfolio.json", _PORTFOLIO, _MTIME)  # 白名单内文件正常

    bodies = []
    for name in ("daily_reports", "portfolio.json", "portfolio.json.bak"):
        r = client.get(f"/v1/private/{name}", headers=_headers())
        assert r.status_code == 404, name
        assert r.json() == {"detail": "Not Found", "code": "unknown_private_name"}
        assert r.content != decoy_md and r.content != decoy_bak  # 绝不回 decoy
        assert str(tmp_path) not in r.text  # 错误体无路径
        assert "\\" not in r.text
        bodies.append(r.content)

    # dot-segment 穿越形状: httpx 传输前折叠 ".." (WR-03 教训) -> 原样 scope 直呼
    # ASGI app 钉服务器真值: 跨段无路由匹配 -> 框架 404, 白名单 handler 零运行
    statuses, parts = _asgi_get("/v1/private/../portfolio")
    assert statuses == [404]
    asgi_body = b"".join(parts)
    assert json.loads(asgi_body) == {"detail": "Not Found", "code": "not_found"}
    bodies.append(asgi_body)

    # Decoy guard: 任何响应 body 都不得等于白名单外文件内容
    for body in bodies:
        assert body != decoy_md
        assert body != decoy_bak


def test_unknown_name_no_key_still_401_gate_first(tmp_path):
    # 鉴权门先于白名单: 未知名无 key -> 401 (白名单成员性不向无 key 者泄漏)
    r = client.get("/v1/private/daily_reports")
    assert r.status_code == 401
    assert r.json() == {"detail": "missing API key", "code": "missing_api_key"}


# ---------- STA-02 扩展: 撕裂窗 503/stale (D-05, get_state 孪生语义) ----------

def test_private_missing_file_cold_cache_503(tmp_path):
    # journal 已知名但文件缺失 -> 冷缓存 503 信封, 绝不裸 500
    r = client.get("/v1/private/journal", headers=_headers())
    assert r.status_code == 503
    assert r.json() == {
        "detail": "private data temporarily unavailable",
        "code": "private_data_unavailable",
    }
    assert str(tmp_path) not in r.text
    assert "\\" not in r.text


def test_private_torn_file_warm_cache_serves_stale_flagged(tmp_path):
    _write_logs(tmp_path, "portfolio.json", _PORTFOLIO, 111)
    r = client.get("/v1/private/portfolio", headers=_headers())
    assert r.status_code == 200
    assert r.content == _PORTFOLIO  # 缓存已暖

    # 写入器崩溃形态: 截断 JSON (D-04 撕裂窗)
    _write_logs(tmp_path, "portfolio.json", b'{"trunc', 111)

    r = client.get("/v1/private/portfolio", headers=_headers())
    assert r.status_code == 200  # 回退末次成功缓存, 绝不 500
    assert r.headers["x-data-stale"] == "true"  # 回退路径必带 stale 标记 (D-05)
    assert r.content == _PORTFOLIO  # 体 = 末次成功载荷
    assert r.headers["x-data-mtime"] == "111"  # 头 = 缓存体 mtime (版本不分裂)
    assert int(r.headers["x-data-age-s"]) >= 0


def test_private_torn_cold_cache_503(tmp_path):
    # 撕裂 + 冷缓存 -> 503 (缓存救不了 -> 服务端错误信封, 非 200/裸 500)
    _write_logs(tmp_path, "portfolio.json", b'{"trunc', _MTIME)
    r = client.get("/v1/private/portfolio", headers=_headers())
    assert r.status_code == 503
    assert r.json() == {
        "detail": "private data temporarily unavailable",
        "code": "private_data_unavailable",
    }


# ---------- STA-02 扩展: 注入 reader 单测钉 get_private 孪生语义 (D-05) ----------

def test_get_private_fresh_ok_warms_cache(tmp_path):
    calls = []

    def fake_reader(path):
        calls.append(path)
        return b'{"ok": true}', 123

    result = api.private.get_private("portfolio", reader=fake_reader, retry_delay=0)
    assert result == ("fresh", b'{"ok": true}', 123)
    assert len(calls) == 1  # 一次成功读 -> 不重试
    assert api.private._CACHE[("portfolio", None)] == {"raw": b'{"ok": true}', "mtime": 123}


def test_get_private_decode_retry_then_success(tmp_path):
    calls = {"n": 0}

    def fake_reader(path):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise json.JSONDecodeError("torn", "doc", 0)
        return b'{"ok": true}', 123

    result = api.private.get_private("portfolio", reader=fake_reader, retry_delay=0)
    assert result == ("fresh", b'{"ok": true}', 123)
    assert calls["n"] == 3  # retries=2: 撕裂窗口是 ms 级, 第 3 次成功


def test_get_private_persistent_decode_warm_cache_stale(tmp_path):
    api.private._CACHE[("portfolio", None)] = {"raw": b'{"old": 1}', "mtime": 999}
    calls = {"n": 0}

    def fake_reader(path):
        calls["n"] += 1
        raise json.JSONDecodeError("torn", "doc", 0)

    result = api.private.get_private("portfolio", reader=fake_reader, retry_delay=0)
    assert calls["n"] == 3  # 重试耗尽
    assert result == ("stale", b'{"old": 1}', 999)  # 缓存体与缓存 mtime 同版本


def test_get_private_persistent_decode_cold_cache_raises(tmp_path):
    def fake_reader(path):
        raise json.JSONDecodeError("torn", "doc", 0)

    with pytest.raises(api.state.StateUnavailable):
        api.private.get_private("portfolio", reader=fake_reader, retry_delay=0)


def test_get_private_oserror_no_retry_breaks(tmp_path):
    calls = {"n": 0}

    def fake_reader(path):
        calls["n"] += 1
        raise FileNotFoundError(path)

    with pytest.raises(api.state.StateUnavailable):  # 冷缓存 -> 503 信号
        api.private.get_private("portfolio", reader=fake_reader, retry_delay=0)
    assert calls["n"] == 1  # OSError 立即 break, 缺失对单次请求是确定的
