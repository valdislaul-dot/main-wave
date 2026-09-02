"""pytest 全局 autouse fixtures: 断网保护 + API 环境变量隔离。

_no_network: 任何测试若试图连接真实网络(非回环目的地), 立即抛 AssertionError
  (OPS-02, 套件级保证: 测试零外部网络访问)。回环地址放行 —— Windows 上
  asyncio ProactorEventLoop 初始化内部 socketpair 需要一次 127.0.0.1 connect,
  TestClient (anyio portal) 依赖该事件循环; 回环不是数据源, 放行不破坏断网意图。
_clean_env: 删除开发 shell 可能遗留的 GOGO_API_* 变量, 防止泄漏进断言 (Pitfall 3)。
"""
import ipaddress
import os
import socket
import tempfile

import pytest


def pytest_configure(config):
    """Windows 环境修复: 重定向 pytest temproot, 绕开 ACL 损坏的遗留目录。

    本机 %TEMP%/pytest-of-Davis (2026-07 遗留) 拒绝枚举, 使默认 basetemp 的
    清理 scandir 抛 PermissionError。PYTEST_DEBUG_TEMPROOT 是 pytest 官方
    temproot 覆盖变量, 在首个 tmp_path 使用前(本钩子)设置即可生效;
    对目录健康的机器无副作用 (仅换一个干净的根目录)。
    """
    if not os.environ.get("PYTEST_DEBUG_TEMPROOT"):
        root = os.path.join(tempfile.gettempdir(), "pytest-temproot-gogo")
        os.makedirs(root, exist_ok=True)
        os.environ["PYTEST_DEBUG_TEMPROOT"] = root


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    real_connect = socket.socket.connect

    def guarded_connect(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = False
        if is_loopback or host == "localhost":
            return real_connect(self, address, *args, **kwargs)
        raise AssertionError(
            "test attempted an outbound network connection to %r - "
            "a data source was not patched; add monkeypatch" % (host,)
        )

    monkeypatch.setattr(socket.socket, "connect", guarded_connect, raising=False)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("GOGO_API_TOKEN", "GOGO_API_HOST", "GOGO_API_PORT"):
        monkeypatch.delenv(var, raising=False)
