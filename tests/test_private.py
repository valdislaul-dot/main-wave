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
- 公开面 (SC1): /health、/health/ready、GET /v1/state/*、/openapi.json 无 key
  照常 —— 私密路由并排注册后公开级不受扰动。

CRITICAL 数据隔离 pin (同 test_state/test_auth 惯例): autouse fixture 把
api.private.LOG_DIR 与 api.auth/api.state 的 DATA_DIR 指到 tmp_path 子树并清空
private/state 两 _CACHE —— 真实 logs/ 与 data/ 零触碰 (suite 结束时
git status --porcelain -- data/ logs/ 必须为空)。
"""
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
