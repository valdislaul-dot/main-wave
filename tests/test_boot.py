"""SEC-03 / D-03 / D-04 / D-05 启动决策测试。

纯函数 + tmp_path + monkeypatch: 不绑定真实 socket、不触碰真实 data/api_token.txt。
case 5 是 Pitfall-2 回归测试(承重): 非回环 + 无 token 的拒绝分支绝不能被自动生成掩盖。

补丁机制说明: api/main.py 在 main() 内惰性 import uvicorn (函数局部名, 模块上无
uvicorn 属性), 因此用伪模块预置 sys.modules["uvicorn"] 使 main() 的 import 拿到
no-op run —— 断言内容与计划一致, 仅补丁方式按 main.py 实际导入形状调整。
"""
import sys
import types

import pytest

import api.boot
import api.main
from api.boot import ensure_token, has_token, is_loopback, read_token


# ---------- 工具: 让 main() 内惰性 import 的 uvicorn.run 变成 no-op ----------

def _patch_uvicorn_run(monkeypatch):
    fake = types.ModuleType("uvicorn")
    fake.run = lambda app=None, **kw: None  # uvicorn.run(app, host=..., ...) 首参位置传 app
    monkeypatch.setitem(sys.modules, "uvicorn", fake)


# ---------- case 1: is_loopback ----------

def test_is_loopback_true_for_loopback_hosts():
    for host in ("127.0.0.1", "localhost", "LOCALHOST", "::1", "127.0.0.2"):
        assert is_loopback(host) is True


def test_is_loopback_false_for_non_loopback_hosts():
    # 含空串 —— fail-closed: 无法识别的主机一律视为非回环, 触发 token 要求
    for host in ("0.0.0.0", "192.168.1.10", "10.0.0.5", "example.com", ""):
        assert is_loopback(host) is False


# ---------- case 2: D-04 优先级 (env 先于文件) ----------

def test_read_token_env_wins_over_file(monkeypatch, tmp_path):
    token_file = tmp_path / "api_token.txt"
    token_file.write_text("file-key", encoding="utf-8")
    monkeypatch.setenv("GOGO_API_TOKEN", "env-key")
    assert read_token(str(token_file)) == "env-key"


def test_read_token_file_used_when_env_absent(monkeypatch, tmp_path):
    token_file = tmp_path / "api_token.txt"
    token_file.write_text("file-key", encoding="utf-8")
    monkeypatch.delenv("GOGO_API_TOKEN", raising=False)
    assert read_token(str(token_file)) == "file-key"


def test_read_token_empty_file_is_no_token(monkeypatch, tmp_path):
    token_file = tmp_path / "api_token.txt"
    token_file.write_text("", encoding="utf-8")
    monkeypatch.delenv("GOGO_API_TOKEN", raising=False)
    assert read_token(str(token_file)) is None


def test_read_token_missing_file_and_no_env_is_none(monkeypatch, tmp_path):
    monkeypatch.delenv("GOGO_API_TOKEN", raising=False)
    assert read_token(str(tmp_path / "nonexistent.txt")) is None


def test_read_token_strips_newline(monkeypatch, tmp_path):
    token_file = tmp_path / "api_token.txt"
    token_file.write_text("key-with-newline\n", encoding="utf-8")
    monkeypatch.delenv("GOGO_API_TOKEN", raising=False)
    assert read_token(str(token_file)) == "key-with-newline"


def test_has_token_true_for_env_and_false_without(monkeypatch, tmp_path):
    monkeypatch.delenv("GOGO_API_TOKEN", raising=False)
    assert has_token(str(tmp_path / "missing.txt")) is False
    monkeypatch.setenv("GOGO_API_TOKEN", "env-key")
    assert has_token(str(tmp_path / "missing.txt")) is True


# ---------- case 3: D-03 生成 ----------

def test_ensure_token_creates_single_line_token_file(tmp_path, monkeypatch):
    monkeypatch.delenv("GOGO_API_TOKEN", raising=False)
    token_path = str(tmp_path / "api_token.txt")
    token = ensure_token(token_path)
    assert len(token) >= 40
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert set(token) <= allowed  # secrets.token_urlsafe 字符集
    content = (tmp_path / "api_token.txt").read_text(encoding="utf-8")
    assert content.strip() == token
    assert content.count("\n") == 1  # 单行


def test_ensure_token_does_not_rewrite_existing_file(tmp_path, monkeypatch):
    monkeypatch.delenv("GOGO_API_TOKEN", raising=False)
    token_path = str(tmp_path / "api_token.txt")
    first = ensure_token(token_path)
    second = ensure_token(token_path)
    assert second == first
    content = (tmp_path / "api_token.txt").read_text(encoding="utf-8")
    assert content.strip() == first


# ---------- case 4: D-05 提示纪律 ----------

def test_ensure_token_never_prints(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GOGO_API_TOKEN", raising=False)
    ensure_token(str(tmp_path / "api_token.txt"))
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_loopback_boot_prints_only_notice_and_creates_token(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("GOGO_API_TOKEN", raising=False)
    monkeypatch.setattr(api.main, "DATA_DIR", str(tmp_path))
    _patch_uvicorn_run(monkeypatch)
    api.main.main()  # 不得抛 SystemExit
    assert (tmp_path / "api_token.txt").exists()
    captured = capsys.readouterr()
    assert captured.out == "API token generated at data/api_token.txt\n"
    assert captured.err == ""
    token = (tmp_path / "api_token.txt").read_text(encoding="utf-8").strip()
    assert token not in captured.out  # 提示语绝不携带 token 值 (D-05/T-01-01)


# ---------- case 5: SEC-03 拒绝 (Pitfall-2 承重回归) ----------

def test_non_loopback_without_token_refuses_and_creates_no_file(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("GOGO_API_TOKEN", raising=False)
    monkeypatch.setenv("GOGO_API_HOST", "0.0.0.0")
    monkeypatch.setattr(api.main, "is_loopback", lambda host: False)
    monkeypatch.setattr(api.main, "DATA_DIR", str(tmp_path))
    with pytest.raises(SystemExit) as excinfo:
        api.main.main()
    assert excinfo.value.code != 0
    assert not (tmp_path / "api_token.txt").exists()  # 拒绝分支绝不生成 (Pitfall 2)
    captured = capsys.readouterr()
    assert "0.0.0.0" in captured.err  # 报错点名绑定主机
    assert "GOGO_API_TOKEN" in captured.err  # 报错给出补救指引


# ---------- case 6: 回环默认分支继续到绑定 ----------

def test_loopback_boot_generates_token_and_exits_normally(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("GOGO_API_TOKEN", raising=False)
    monkeypatch.setattr(api.main, "DATA_DIR", str(tmp_path))
    _patch_uvicorn_run(monkeypatch)
    api.main.main()  # 默认 host=127.0.0.1 -> 回环分支, 不得 SystemExit
    assert (tmp_path / "api_token.txt").exists()  # D-03 在回环分支生成
    captured = capsys.readouterr()
    assert captured.out == "API token generated at data/api_token.txt\n"
    token = (tmp_path / "api_token.txt").read_text(encoding="utf-8").strip()
    assert token not in captured.out


# ---------- case 7: has_token env-first 在 main 层生效 ----------

def test_env_token_satisfies_non_loopback_check(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GOGO_API_TOKEN", "env-key")
    monkeypatch.setenv("GOGO_API_HOST", "0.0.0.0")
    monkeypatch.setattr(api.main, "is_loopback", lambda host: False)
    monkeypatch.setattr(api.main, "DATA_DIR", str(tmp_path))
    _patch_uvicorn_run(monkeypatch)
    api.main.main()  # env token 满足检查 -> 不得 SystemExit
    assert not (tmp_path / "api_token.txt").exists()  # 已有 token, 不生成文件
    captured = capsys.readouterr()
    assert captured.out == ""  # 未生成 -> 不打印 D-05 提示
