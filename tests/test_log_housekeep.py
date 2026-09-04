"""05-02 D-34 契约测试: api/log_housekeep.py 纯函数原语 (rotate / repoint / prune)。

- rotate_console_log: 5MB+1 阈值轮转成 .1 (保留一份历史), 二次轮转覆盖旧 .1;
  阈值内/缺失 no-op; OSError 返回 (False, ascii err) 永不上抛。
- repoint_std_streams: 真实 fd 1/2 重指向 —— 经 subprocess 子进程探测 (pytest
  自身的 fd 1/2 转接不与 dup2 竞速); 子进程退出码 0、探针字节落进目标文件。
- prune_job_logs: 委托 api.jobs.prune; 默认 cap 在调用时取 jobs.PRUNE_CAP
  (monkeypatch 钉 call-time 解析); 显式 cap 生效; 二次调用 no-op (幂等)。

CRITICAL 数据隔离 pin: 绝不触碰真实 data/ 与 logs/ —— autouse fixture 把
api.jobs.LOG_DIR 指到 tmp_path (log_housekeep 的默认路径经 jobs.LOG_DIR 调用时
解析); 全部调用显式传路径或落在 tmp 树内; 子进程探针只写 tmp 目标文件。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import api.jobs
import api.log_housekeep


@pytest.fixture(autouse=True)
def _isolated_tree(tmp_path, monkeypatch):
    """每测试前: api.jobs.LOG_DIR -> tmp_path (log_housekeep 默认路径的 monkeypatch 缝)。

    log_housekeep 不持有自己的 config 导入 —— 默认 console.log 路径与 registry
    目录都经 api.jobs 的模块 attr 在调用时解析, patch 一处即全隔离。
    """
    monkeypatch.setattr(api.jobs, "LOG_DIR", str(tmp_path))
    return tmp_path


def _seed_pair(base, job_id, status, mtime=None):
    """手写 fixture job JSON + .log 陪衬 (test_jobs._seed_job_file 同形)。"""
    job = {
        "job_id": job_id,
        "kind": "pipeline",
        "status": status,
        "pid": None,
        "exit_code": None,
        "log_path": None,
        "cmd": ["python", "x.py"],
        "created_at": 1,
        "started_at": None,
        "finished_at": None,
    }
    p = base / f"{job_id}.json"
    p.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    (base / f"{job_id}.log").write_bytes(b"")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return job


def _seed_over_cap_registry(base):
    """25 终态 (mtime 递增, 最旧在前) + 3 inflight —— prune 的通用超限种子。"""
    for i in range(25):
        _seed_pair(base, f"{i:032x}", "succeeded", mtime=1_700_000_000 + i)
    for jid in ("f" * 32, "e" * 32, "d" * 32):
        _seed_pair(base, jid, "running")


def _stems(base):
    return sorted(p.name[: -len(".json")] for p in base.glob("*.json"))


# ---------- rotate: 阈值 / 一份历史 / no-op / 容错 ----------

def test_rotate_over_threshold_renames_to_dot1_overwrites_prev(tmp_path):
    path = tmp_path / "console.log"
    gen1 = bytes([65]) * (api.log_housekeep.MAX_CONSOLE_LOG_BYTES + 1)  # 5MB+1, 'A'
    path.write_bytes(gen1)

    rotated, err = api.log_housekeep.rotate_console_log(str(path))
    assert rotated is True and err is None
    assert not path.exists()  # 改名而非复制: 原文件消失
    assert (tmp_path / "console.log.1").read_bytes() == gen1  # 旧字节进 .1

    gen2 = bytes([66]) * (api.log_housekeep.MAX_CONSOLE_LOG_BYTES + 1)  # 'B'
    path.write_bytes(gen2)
    rotated2, err2 = api.log_housekeep.rotate_console_log(str(path))
    assert rotated2 is True and err2 is None
    assert (tmp_path / "console.log.1").read_bytes() == gen2  # 二次轮转覆盖旧 .1
    assert not path.exists()  # 只保留一份历史


def test_rotate_exactly_at_limit_is_noop(tmp_path):
    """size <= max_bytes 不轮转: 恰在 5MB 边界上 (含) 保持原样。"""
    path = tmp_path / "console.log"
    path.write_bytes(bytes([67]) * api.log_housekeep.MAX_CONSOLE_LOG_BYTES)
    rotated, err = api.log_housekeep.rotate_console_log(str(path))
    assert rotated is False and err is None
    assert path.exists() and not (tmp_path / "console.log.1").exists()


def test_rotate_under_threshold_and_missing_noop(tmp_path):
    path = tmp_path / "console.log"
    path.write_bytes(b"tiny")
    rotated, err = api.log_housekeep.rotate_console_log(str(path))
    assert rotated is False and err is None
    assert not (tmp_path / "console.log.1").exists()

    missing = tmp_path / "nope.log"
    rotated, err = api.log_housekeep.rotate_console_log(str(missing))
    assert rotated is False and err is None  # 缺失文件无错无崩溃


def test_rotate_default_path_resolves_via_jobs_log_dir(tmp_path):
    """默认路径 = api.jobs.LOG_DIR/api/console.log, 调用时解析 (monkeypatch 缝)。

    autouse fixture 把 api.jobs.LOG_DIR 指到 tmp_path —— 在 patch 后的路径下
    放一个超阈值文件, 无参调用必须命中它 (证明不是 config 导入时的旧值)。
    """
    target = tmp_path / "api" / "console.log"
    target.parent.mkdir(parents=True)
    target.write_bytes(bytes([68]) * (api.log_housekeep.MAX_CONSOLE_LOG_BYTES + 1))

    rotated, err = api.log_housekeep.rotate_console_log()  # path=None
    assert rotated is True and err is None
    assert not target.exists()
    assert (tmp_path / "api" / "console.log.1").exists()


def test_rotate_oserror_returns_ascii_error_never_raises(tmp_path, monkeypatch):
    path = tmp_path / "console.log"
    path.write_bytes(bytes([69]) * (api.log_housekeep.MAX_CONSOLE_LOG_BYTES + 1))

    def _boom(src, dst):
        raise OSError("denied by the test")

    monkeypatch.setattr(os, "replace", _boom)
    rotated, err = api.log_housekeep.rotate_console_log(str(path))
    assert rotated is False
    assert isinstance(err, str) and err  # 错误串非空
    assert err.isascii()  # GBK 控制台/日志不得炸编码 (Pitfall 5)
    assert path.exists()  # 失败时原文件未被改动


# ---------- prune_job_logs: 委托 + cap 边界 + 幂等 + call-time 解析 ----------

def test_prune_job_logs_default_cap_leaves_20_terminal_plus_inflight(tmp_path):
    base = tmp_path / "jobs"
    base.mkdir()
    _seed_over_cap_registry(base)

    api.log_housekeep.prune_job_logs(base=str(base))  # cap=None -> jobs.PRUNE_CAP(20)

    remaining = _stems(base)
    assert len(remaining) == 23  # 20 个最新终态 + 3 inflight (非终态永不删)
    for i in range(5):
        assert f"{i:032x}" not in remaining  # 最旧 5 对 (json+log) 被删
        assert not (base / f"{i:032x}.json").exists()
        assert not (base / f"{i:032x}.log").exists()
    for i in range(5, 25):
        assert f"{i:032x}" in remaining  # 最新 20 个终态对存活
    for jid in ("f" * 32, "e" * 32, "d" * 32):
        assert jid in remaining  # inflight 存活且未被改写
        assert api.jobs.read_job(jid, str(base))["status"] == "running"


def test_prune_job_logs_explicit_cap_and_second_call_noop(tmp_path):
    base = tmp_path / "jobs"
    base.mkdir()
    _seed_over_cap_registry(base)

    api.log_housekeep.prune_job_logs(base=str(base), cap=2)

    remaining = _stems(base)
    assert len(remaining) == 5  # 2 个最新终态 + 3 inflight
    for i in range(23):
        assert f"{i:032x}" not in remaining
    assert f"{23:032x}" in remaining and f"{24:032x}" in remaining

    api.log_housekeep.prune_job_logs(base=str(base))  # 二次默认调用
    assert _stems(base) == remaining  # no-op (幂等)


def test_prune_job_logs_cap_resolved_at_call_time(tmp_path, monkeypatch):
    base = tmp_path / "jobs"
    base.mkdir()
    _seed_over_cap_registry(base)

    monkeypatch.setattr(api.jobs, "PRUNE_CAP", 2)  # 调用后才改 cap

    api.log_housekeep.prune_job_logs(base=str(base))  # cap=None

    remaining = _stems(base)
    assert len(remaining) == 5  # 若 cap 在 def 时绑定, 这里会是 23 -> 红


# ---------- repoint: 真实 fd 探针 (subprocess, 不与 pytest fd 转接竞速) ----------

def test_repoint_real_fds_subprocess_probe(tmp_path):
    """子进程把 fd 1/2 dup2 到目标文件后写探针 —— 父进程断言字节落进文件。

    用子进程是因为 pytest 自身的 fd 1/2 转接 (捕获) 会与 dup2 竞速;
    子进程经 subprocess.run(capture_output=True) 拿全新管道, dup2 后探针
    只能落进目标文件 —— 退出码 0 + 管道空 + 文件含探针 = repoint 真生效。
    """
    target = tmp_path / "console.log"
    code = (
        "import os, sys\n"
        "from api import log_housekeep\n"
        "err = log_housekeep.repoint_std_streams(sys.argv[1])\n"
        "if err:\n"
        "    os.write(2, ('REPOINT-ERR: ' + err + chr(10)).encode('ascii', 'replace'))\n"
        "    sys.exit(3)\n"
        "os.write(1, b'OUT-PROBE\\n')\n"
        "os.write(2, b'ERR-PROBE\\n')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code, str(target)],
        capture_output=True,
        cwd=str(Path(api.jobs.PROJECT_ROOT)),
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr.decode("ascii", "replace")
    assert proc.stdout == b""  # dup2 后管道里没有字节
    assert proc.stderr == b""
    data = target.read_bytes()
    assert b"OUT-PROBE" in data  # fd 1 探针落进目标文件
    assert b"ERR-PROBE" in data  # fd 2 探针落进目标文件
