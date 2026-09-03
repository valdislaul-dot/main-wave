"""Phase 2 契约测试: STA-01 / STA-03 / HLT-02 / SC4 (tests/test_state.py)。

STA-01: /v1/state/{name} 逐字节透传 + X-Data-Mtime/X-Data-Age-S 精确头 + content-type。
STA-03: 防御性读层 —— 解码失败短重试 (注入 reader, 免计时)、末次成功缓存回退
        (X-Data-Stale: true + 缓存 mtime 一致)、冷缓存 503、OSError 不重试。
HLT-02: /health/ready 200/503 矩阵 (缺失/目录不可读/远古 mtime 仍 200)。
SC4:    源扫描回归 —— api/state.py + api/main.py 无网络能力 token。

CRITICAL 数据隔离 pin: 本文件绝不触碰真实 data/ —— autouse fixture 把
api.state.DATA_DIR 指到 tmp_path 并在每个测试前清空 api.state._CACHE,
否则模块级 TestClient 会命中真实被跟踪的 data/*.json 且暖缓存跨测试泄漏。
"""
import json
import os
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main  # noqa: F401  (注册 state 路由 —— 一次 import 覆盖两个路由族)
import api.state
from api.main import app

client = TestClient(app)  # 模块级, 无 context manager: 无 lifespan, 无 boot


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path, monkeypatch):
    """每个测试前: DATA_DIR -> tmp_path (monkeypatch 缝) + 清空 _CACHE。"""
    monkeypatch.setattr(api.state, "DATA_DIR", str(tmp_path))
    api.state._CACHE.clear()
    return tmp_path


def _write_state(tmp_path, name, raw, mtime):
    """按白名单文件名写 fixture (二进制 + 定 mtime), 返回路径。"""
    path = tmp_path / api.state.STATE_FILES[name]
    path.write_bytes(raw)
    os.utime(path, (mtime, mtime))
    return path


# ---------- STA-01: 逐字透传 + 精确头 ----------

def test_state_fresh_body_verbatim_and_exact_headers(tmp_path, monkeypatch):
    fixture = b'{\r\n  "ok": true\r\n}\r\n'  # CRLF + 有效 JSON (Pitfall 1)
    _write_state(tmp_path, "market_state", fixture, 1_700_000_000)
    monkeypatch.setattr(api.state.time, "time", lambda: 1_700_000_100)

    response = client.get("/v1/state/market_state")
    assert response.status_code == 200
    assert response.content == fixture  # 字节相等 = 逐字透传 (D-01/D-02)
    assert response.headers["content-type"] == "application/json"  # 无 charset
    assert response.headers["x-data-mtime"] == "1700000000"
    assert response.headers["x-data-age-s"] == "100"
    assert "x-data-stale" not in response.headers  # 新鲜路径绝不带 stale 头 (D-05)


def test_state_all_three_names_served_verbatim(tmp_path):
    market = b'{\r\n  "ok": true\r\n}\r\n'
    auction = b'{"auction": true}\r\n'
    zt_pool = ('{\r\n    "name": "涨停",\r\n    "up": true\r\n}\r\n').encode("utf-8")
    _write_state(tmp_path, "market_state", market, 1_600_000_000)
    _write_state(tmp_path, "auction_state", auction, 1_600_000_001)
    _write_state(tmp_path, "zt_pool_state", zt_pool, 1_600_000_002)

    for name, fixture in (
        ("market_state", market),
        ("auction_state", auction),
        ("zt_pool_state", zt_pool),
    ):
        response = client.get(f"/v1/state/{name}")
        assert response.status_code == 200
        assert response.content == fixture  # 各自字节逐字透传 (含 UTF-8 中文)
        assert response.headers["content-type"] == "application/json"


# ---------- STA-01/D-03/D-04: 白名单 404 三类 (经验钉死到已装栈) ----------

def test_state_unknown_names_404_whitelist_only(tmp_path):
    # Decoy guard: 白名单外文件真实存在也必须永不可达 (D-03 结构性防线)
    decoy = b'{"decoy": "portfolio"}\r\n'
    (tmp_path / "portfolio.json").write_bytes(decoy)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "portfolio.json").write_bytes(decoy)
    auction = b'{"auction": true}\r\n'
    _write_state(tmp_path, "auction_state", auction, 1_600_000_001)

    bodies = []

    # a. 路由能匹配白名单外名字 (命中 /v1/state/{name}) -> handler 404, detail 钉死
    for name in ("portfolio", "logs", "market_state.json"):
        response = client.get(f"/v1/state/{name}")
        assert response.status_code == 404
        assert response.json()["detail"] == "unknown state name"
        bodies.append(response.content)

    # b. 形状根本不匹配路由 (handler 之前框架 404) —— 只钉状态码, 不钉 body
    for url in ("/v1/state/", "/v1/state/..%2F..%2Flogs%2Fportfolio.json"):
        response = client.get(url)
        assert response.status_code == 404
        bodies.append(response.content)

    # c. dot-segment 别名被规范化进白名单 -> 按解析后的白名单名服务 200
    response = client.get("/v1/state/market_state/../auction_state")
    assert response.status_code == 200
    assert response.content == auction
    bodies.append(response.content)

    # Decoy guard: 任何响应的 body 都不得等于白名单外文件内容
    for body in bodies:
        assert body != decoy


# ---------- STA-03/D-04: 缺失文件 503, detail 无路径 ----------

def test_state_missing_file_503_detail_contains_no_path(tmp_path):
    response = client.get("/v1/state/market_state")  # 已知名但文件不存在
    assert response.status_code == 503
    assert response.json()["detail"] == "state temporarily unavailable"
    assert str(tmp_path) not in response.text  # D-04: 绝不泄露文件路径
    assert "\\" not in response.text


# ---------- STA-03: 注入 reader 的重试/缓存/OSError 单元 (免计时) ----------

def test_get_state_decode_retry_succeeds_and_warms_cache(tmp_path):
    calls = {"n": 0}

    def fake_reader(path):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise json.JSONDecodeError("torn", "doc", 0)
        return b'{"ok": true}', 123

    result = api.state.get_state("market_state", reader=fake_reader, retry_delay=0)
    assert result == ("fresh", b'{"ok": true}', 123)
    assert calls["n"] == 3  # retries=2 -> 共 3 次尝试
    assert api.state._CACHE["market_state"] == {"raw": b'{"ok": true}', "mtime": 123}


def test_get_state_persistent_decode_failure_warm_cache_returns_stale(tmp_path):
    api.state._CACHE["auction_state"] = {"raw": b'{"old": 1}', "mtime": 999}

    def fake_reader(path):
        raise json.JSONDecodeError("torn", "doc", 0)

    result = api.state.get_state("auction_state", reader=fake_reader, retry_delay=0)
    assert result == ("stale", b'{"old": 1}', 999)  # 缓存 mtime 跟随缓存体 (Pitfall 3)


def test_get_state_oserror_skips_retries(tmp_path):
    calls = {"n": 0}

    def fake_reader(path):
        calls["n"] += 1
        raise FileNotFoundError(path)

    with pytest.raises(api.state.StateUnavailable):
        api.state.get_state("market_state", reader=fake_reader, retry_delay=0)
    assert calls["n"] == 1  # OSError 立即回退, 不重试 (STA-03 字面)


def test_get_state_persistent_decode_failure_empty_cache_raises(tmp_path):
    def fake_reader(path):
        raise json.JSONDecodeError("torn", "doc", 0)

    with pytest.raises(api.state.StateUnavailable):  # 冷缓存 -> 503 路径信号
        api.state.get_state("market_state", reader=fake_reader, retry_delay=0)


# ---------- STA-03/SC2: HTTP 层 撕裂-暖缓存 / 撕裂-冷缓存 ----------

def test_state_persistent_torn_warm_cache_serves_stale_flagged(tmp_path):
    good = b'{\r\n  "ok": true\r\n}\r\n'
    _write_state(tmp_path, "market_state", good, 111)

    first = client.get("/v1/state/market_state")
    assert first.status_code == 200
    assert first.content == good  # 缓存已暖

    (tmp_path / api.state.STATE_FILES["market_state"]).write_bytes(b'{"trunc')  # 撕裂

    second = client.get("/v1/state/market_state")
    assert second.status_code == 200  # 绝不 5xx、绝不给裸 500
    assert second.headers["x-data-stale"] == "true"  # D-05: 回退路径必带 stale
    assert second.content == good  # 体 = 末次成功载荷
    assert second.headers["x-data-mtime"] == "111"  # 头 = 缓存体的真实 mtime
    assert int(second.headers["x-data-age-s"]) >= 0


def test_state_persistent_torn_cold_cache_503(tmp_path):
    (tmp_path / api.state.STATE_FILES["market_state"]).write_bytes(b'{"trunc')

    response = client.get("/v1/state/market_state")
    assert response.status_code == 503
    assert response.json()["detail"] == "state temporarily unavailable"


# ---------- HLT-02: /health/ready 矩阵 (stat-only, 永不 open, 永不看新旧) ----------

def test_ready_all_present_200(tmp_path):
    for name in api.state.STATE_FILES:
        _write_state(tmp_path, name, b'{"ok": true}\r\n', 1_700_000_000)
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert response.headers["content-type"] == "application/json"


def test_ready_missing_file_503(tmp_path):
    for name in api.state.STATE_FILES:
        _write_state(tmp_path, name, b'{"ok": true}\r\n', 1_700_000_000)
    missing = tmp_path / api.state.STATE_FILES["auction_state"]
    missing.unlink()
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["detail"] == "state file unavailable"
    _write_state(tmp_path, "auction_state", b'{"ok": true}\r\n', 1_700_000_000)
    assert client.get("/health/ready").status_code == 200  # 恢复 -> 200


def test_ready_directory_not_readable_503(tmp_path):
    for name in api.state.STATE_FILES:
        _write_state(tmp_path, name, b'{"ok": true}\r\n', 1_700_000_000)
    dir_path = tmp_path / api.state.STATE_FILES["zt_pool_state"]
    dir_path.unlink()
    dir_path.mkdir()  # 目录同名 -> isfile False -> 503 (可移植变体)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["detail"] == "state file unavailable"

    if os.name != "nt":  # Windows chmod 语义不同, 静默跳过 (目录变体已覆盖)
        dir_path.rmdir()
        file_path = tmp_path / api.state.STATE_FILES["market_state"]
        os.chmod(file_path, 0)
        try:
            if not os.access(file_path, os.R_OK):  # root 可能仍可读 —— 只在真实不可读时断言
                assert client.get("/health/ready").status_code == 503
        finally:
            os.chmod(file_path, 0o644)


def test_ready_ancient_mtime_still_200(tmp_path):
    for name in api.state.STATE_FILES:
        _write_state(tmp_path, name, b'{"ok": true}\r\n', 946_684_800)  # 2000-01-01
    response = client.get("/health/ready")
    assert response.status_code == 200  # 数据新旧永不 503 (HLT-02 字面)
    assert response.json() == {"status": "ready"}


# ---------- SC4: 源扫描回归 (独立 grep 审计的套内孪生) ----------

def test_sc4_source_scan_no_network_tokens():
    banned = re.compile(r"(requests|urllib|httpx|aiohttp|socket)(\.|\s*import|import)")
    for mod in (api.state, api.main):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        match = banned.search(src)
        assert match is None, (
            f"SC4 违规: {mod.__file__} 含网络能力 token {match.group(0)!r}"
        )
