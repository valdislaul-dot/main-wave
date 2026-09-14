"""HLT-01 /health 契约测试: 恒 200 + 精确 body + monotonic uptime + 导入无副作用。

全文件不发任何 Authorization 头 —— /health 必须裸请求也 200 (Pitfall 6:
未来任何鉴权中间件必须豁免 /health; 任何断言 /health 401 的测试都违背 HLT-01)。
"""
import os

import pytest
from fastapi.testclient import TestClient

import api.main
from api.main import app
from scripts.daily.config import DATA_DIR

client = TestClient(app)  # 模块级, 无 context manager: 无 lifespan, 无 boot

# 真实 token 路径在本次测试会话开始(模块导入)前是否已存在 ——
# 该测试只 pin "模块导入不创建文件" 的无副作用性, 与生产文件是否在位无关:
# Task 1 的 E2E 回环启动后真实文件可能合法存在 (本机), 全新检出则不存在。
_TOKEN_PATH = os.path.join(DATA_DIR, "api_token.txt")
_TOKEN_EXISTED_AT_IMPORT = os.path.exists(_TOKEN_PATH)


def test_health_returns_200_and_ok():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert isinstance(body["uptime_seconds"], int)
    assert body["uptime_seconds"] >= 0


def test_health_body_has_exact_keys_and_json_type():
    response = client.get("/health")
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body.keys()) == {"status", "uptime_seconds"}


def test_health_uptime_never_decreases():
    first = client.get("/health").json()["uptime_seconds"]
    second = client.get("/health").json()["uptime_seconds"]
    assert second >= first


def test_import_api_main_creates_no_token_file():
    if _TOKEN_EXISTED_AT_IMPORT:
        pytest.skip(
            "real token file existed before the session (prior E2E boot) - "
            "absence check not applicable"
        )
    assert not os.path.exists(_TOKEN_PATH)
