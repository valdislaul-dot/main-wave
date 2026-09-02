"""pytest 全局 autouse fixtures: 断网保护 + API 环境变量隔离。

_no_network: 任何测试若试图连接真实网络(非回环目的地), 立即抛 AssertionError
  (OPS-02, 套件级保证: 测试零外部网络访问)。回环地址放行 —— Windows 上
  asyncio ProactorEventLoop 初始化内部 socketpair 需要一次 127.0.0.1 connect,
  TestClient (anyio portal) 依赖该事件循环; 回环不是数据源, 放行不破坏断网意图。
_clean_env: 删除开发 shell 可能遗留的 GOGO_API_* 变量, 防止泄漏进断言 (Pitfall 3)。
"""
import ipaddress
import socket

import pytest


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
