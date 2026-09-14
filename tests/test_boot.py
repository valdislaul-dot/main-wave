"""SEC-03 / D-03 / D-04 / D-05 / WR-01(D-12) 启动决策测试。

纯函数 + tmp_path + monkeypatch: 不绑定真实 socket、不触碰真实 data/api_token.txt。
case 5 是 Pitfall-2 回归测试(承重): 非回环 + 无 token 的拒绝分支绝不能被自动生成掩盖。
case 8 是 WR-01 回归测试(承重): 文件 token 存在也绝不能满足非回环检查 (D-12 env 强制)。

WR-02 隔离 pin: main() 走到 jobs.reload_registry() 时 registry 目录经 api.jobs.LOG_DIR
调用时解析 (jobs_dir), 与 api.main.LOG_DIR 是两个缝 —— 全 boot 测试两个缝都 pin 到
tmp_path, 真实 logs/api/jobs 零触碰 (否则套件会改写真实 in-flight job 为 interrupted
并用 cap-20 prune 删真实终态对)。补丁只加在真正跑完 reload_registry 的 4 个测试上
(case 5/8 在 SEC-03 门提前 SystemExit, 到不了 registry)。

WR-04 隔离 pin (2026-09-05): 这 4 个全 boot 测试进程内跑完 housekeeping 块 —— 真
repoint_std_streams 会把 pytest 运行器自身的 fd 1/2 dup2 到 tmp_path 的
console.log, `-s` 调试模式下 11 dot 之后的进度/失败 traceback/汇总全部落进随测
删除的 tmp 文件 (静默失败窗, 只剩退出码)。故 4 个测试都在 main() 前把 repoint 置
no-op —— main() 调用时解析 log_housekeep.repoint_std_streams, 模块 attr 补丁即
生效; 真机 dup2 语义由 test_log_housekeep 的 subprocess 探针钉住, 零覆盖损失;
本模块无断言依赖 repoint 副作用 (boot 打印全在 housekeeping 之前)。

补丁机制说明: api/main.py 在 main() 内惰性 import uvicorn (函数局部名, 模块上无
uvicorn 属性), 因此用伪模块预置 sys.modules["uvicorn"] 使 main() 的 import 拿到
no-op run —— 断言内容与计划一致, 仅补丁方式按 main.py 实际导入形状调整。
"""
import sys
import types

import pytest

import api.boot
import api.jobs  # WR-02: 全 boot 测试 pin registry 缝 (jobs.LOG_DIR/DATA_DIR)
import api.log_housekeep  # WR-04: no-op repoint 的补丁缝 (main() 调用时解析模块 attr)
import api.main
from api.boot import ensure_token, has_token, is_loopback, read_token


# ---------- 工具: 让 main() 内惰性 import 的 uvicorn.run 变成 no-op ----------

def _patch_uvicorn_run(monkeypatch):
    fake = types.ModuleType("uvicorn")
    fake.run = lambda app=None, **kw: None  # uvicorn.run(app, host=..., ...) 首参位置传 app
    monkeypatch.setitem(sys.modules, "uvicorn", fake)


# ---------- 工具: WR-04 —— 全 boot 测试 no-op 掉 fd 重指向原语 ----------

def _noop_repoint(monkeypatch):
    # 进程内跑真 repoint 会把 pytest 自身的 fd 1/2 dup2 到 tmp console.log
    # (`-s` 模式静默失败窗)。main() 调用时解析 log_housekeep.repoint_std_streams
    # (模块 attr), 故 monkeypatch 即生效; 真机 dup2 语义由 test_log_housekeep 的
    # subprocess 探针钉住 (零覆盖损失)。
    monkeypatch.setattr(
        api.log_housekeep, "repoint_std_streams", lambda path=None: None
    )


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
    monkeypatch.setattr(api.main, "LOG_DIR", str(tmp_path))  # 05-02: housekeeping 只碰 tmp 树
    monkeypatch.setattr(api.jobs, "LOG_DIR", str(tmp_path))  # WR-02: reload_registry 的 jobs_dir 缝
    monkeypatch.setattr(api.jobs, "DATA_DIR", str(tmp_path))  # WR-02: 锁缝同 tmp (test_jobs 惯例)
    _patch_uvicorn_run(monkeypatch)
    _noop_repoint(monkeypatch)  # WR-04: 不把 pytest 的 fd 1/2 dup2 到 tmp console.log
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
    monkeypatch.setattr(api.main, "LOG_DIR", str(tmp_path))  # 05-02: housekeeping 只碰 tmp 树
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
    monkeypatch.setattr(api.main, "LOG_DIR", str(tmp_path))  # 05-02: housekeeping 只碰 tmp 树
    monkeypatch.setattr(api.jobs, "LOG_DIR", str(tmp_path))  # WR-02: reload_registry 的 jobs_dir 缝
    monkeypatch.setattr(api.jobs, "DATA_DIR", str(tmp_path))  # WR-02: 锁缝同 tmp (test_jobs 惯例)
    _patch_uvicorn_run(monkeypatch)
    _noop_repoint(monkeypatch)  # WR-04: 不把 pytest 的 fd 1/2 dup2 到 tmp console.log
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
    monkeypatch.setattr(api.main, "LOG_DIR", str(tmp_path))  # 05-02: housekeeping 只碰 tmp 树
    monkeypatch.setattr(api.jobs, "LOG_DIR", str(tmp_path))  # WR-02: reload_registry 的 jobs_dir 缝
    monkeypatch.setattr(api.jobs, "DATA_DIR", str(tmp_path))  # WR-02: 锁缝同 tmp (test_jobs 惯例)
    _patch_uvicorn_run(monkeypatch)
    _noop_repoint(monkeypatch)  # WR-04: 不把 pytest 的 fd 1/2 dup2 到 tmp console.log
    api.main.main()  # env token 满足检查 -> 不得 SystemExit
    assert not (tmp_path / "api_token.txt").exists()  # 已有 token, 不生成文件
    captured = capsys.readouterr()
    assert captured.out == ""  # 未生成 -> 不打印 D-05 提示 (D-12 警告走 stderr, 不影响此钉)


# ---------- case 8/9: WR-01/D-12 回归 (env 强制 token + 控制台警告) ----------

def test_non_loopback_file_token_only_refuses_without_uvicorn(monkeypatch, tmp_path, capsys):
    """WR-01 回归 (D-12): 文件 token 不再满足非回环检查。

    旧行为 (WR-01): has_token 对 (自动生成的) 文件返回 True -> 0.0.0.0 绑定静默放行。
    新行为: 非回环绑定只接受 env GOGO_API_TOKEN; 文件存在也必须拒绝, 且拒绝先于
    ensure_token (文件不被改写) 与 uvicorn.run (boot 顺序, T-04-19)。
    """
    monkeypatch.delenv("GOGO_API_TOKEN", raising=False)
    monkeypatch.setenv("GOGO_API_HOST", "0.0.0.0")
    monkeypatch.setattr(api.main, "is_loopback", lambda host: False)
    monkeypatch.setattr(api.main, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(api.main, "LOG_DIR", str(tmp_path))  # 05-02: housekeeping 只碰 tmp 树
    token_file = tmp_path / "api_token.txt"
    token_file.write_text("file-key\n", encoding="utf-8")  # 文件 token 已存在 (与自动生成等价)
    uvicorn_calls = []
    fake = types.ModuleType("uvicorn")
    fake.run = lambda app=None, **kw: uvicorn_calls.append(app)
    monkeypatch.setitem(sys.modules, "uvicorn", fake)
    with pytest.raises(SystemExit) as excinfo:
        api.main.main()
    assert excinfo.value.code == 1
    assert uvicorn_calls == []  # 拒绝先于 uvicorn.run
    assert token_file.read_text(encoding="utf-8") == "file-key\n"  # 拒绝路径绝不改写文件
    captured = capsys.readouterr()
    assert "0.0.0.0" in captured.err  # 报错点名绑定主机
    assert "GOGO_API_TOKEN" in captured.err  # 报错给出补救指引


def test_env_token_non_loopback_proceeds_with_ascii_warning_no_token_echo(monkeypatch, tmp_path, capsys):
    """D-12 警告钉 (T-04-18): env token 放行非回环绑定, 但警告绝不回显 token 值。"""
    monkeypatch.setenv("GOGO_API_TOKEN", "boot-test-token-abc")
    monkeypatch.setenv("GOGO_API_HOST", "0.0.0.0")
    monkeypatch.setattr(api.main, "is_loopback", lambda host: False)
    monkeypatch.setattr(api.main, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(api.main, "LOG_DIR", str(tmp_path))  # 05-02: housekeeping 只碰 tmp 树
    monkeypatch.setattr(api.jobs, "LOG_DIR", str(tmp_path))  # WR-02: reload_registry 的 jobs_dir 缝
    monkeypatch.setattr(api.jobs, "DATA_DIR", str(tmp_path))  # WR-02: 锁缝同 tmp (test_jobs 惯例)
    _patch_uvicorn_run(monkeypatch)
    _noop_repoint(monkeypatch)  # WR-04: 不把 pytest 的 fd 1/2 dup2 到 tmp console.log
    api.main.main()  # env token 满足 -> 不得 SystemExit, 正常走到 uvicorn.run
    assert not (tmp_path / "api_token.txt").exists()  # 非回环分支绝不生成文件
    captured = capsys.readouterr()
    assert captured.out == ""  # 无 D-05 生成提示
    assert "0.0.0.0" in captured.err  # 警告点名绑定主机
    assert "GOGO_API_TOKEN" in captured.err
    assert "boot-test-token-abc" not in captured.out
    assert "boot-test-token-abc" not in captured.err  # 绝不回显 token 值 (T-04-18)
