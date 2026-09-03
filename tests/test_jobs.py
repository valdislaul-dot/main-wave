"""Phase 3 契约测试: 共享单飞锁 + 持久化 job registry + spawn 治理 (ACT-02/ACT-03, D-03)。

本文件是 ACT-02/ACT-03 核心契约套:
- 锁单元: 同进程二取拒绝、close 释放、三取成功、文件零字节 (content-free, probe V2)。
- 生命周期 succeeded/failed: 经真实 Popen 假子进程 (打印中文+emoji, 记录 argv/cwd,
  按 rc 退出), 钉 pending→running→succeeded/failed 迁移、UTF-8 emoji 日志字节 (V1
  回归钉)、log_path 暴露、claim 先落盘后入内存表的持久化顺序。
- is_running/claim/release: worker 终态后释放 claim。
- read_job: 存在返回 dict / 缺失返回 None / 损坏 JSON 抛 ValueError (分类归 03-02)。

CRITICAL 数据隔离 pin: 本文件绝不触碰真实 data/ 与 logs/ —— autouse fixture 把
api.jobs.LOG_DIR/DATA_DIR 指到 tmp_path 并在每测试前清空 _claims (test_state.py 惯例);
任务 2/3 追加的崩溃恢复套、跨进程锁套、SC3 延迟套同守此 pin。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.jobs  # noqa: F401  (被测模块; 注册 api.jobs 状态)
import api.main  # noqa: F401  (/health + state 路由 —— 模块级 client 依赖)
import scripts.daily.job_lock as job_lock
from api.main import app

client = TestClient(app)  # 模块级, 无 context manager (test_state.py 惯例)


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path, monkeypatch):
    """每测试前: LOG_DIR/DATA_DIR -> tmp_path (monkeypatch 缝) + 清空 _claims。

    模块级 TestClient 与 worker 线程永远只碰 tmp 树 —— 真实 data//logs/ 零触碰。
    """
    monkeypatch.setattr(api.jobs, "LOG_DIR", str(tmp_path))
    monkeypatch.setattr(api.jobs, "DATA_DIR", str(tmp_path))
    with api.jobs._claims_lock:
        api.jobs._claims.clear()
    return tmp_path


def fake_script(tmp_path, rc=0, sleep=0.3):
    """写一个真实可跑的假子进程脚本 (tmp_path 内)。

    行为: 打印中文+emoji 行 -> 把 {"argv": sys.argv[1:], "cwd": os.getcwd()} 以
    UTF-8 JSON 写到 env FAKE_OUT 指向的路径 -> sleep -> 以 rc 退出。
    子进程继承父进程 env + PYTHONIOENCODING=utf-8 (run_job 的 spawn env), 所以
    monkeypatch.setenv 的变量能到达子进程。
    """
    path = tmp_path / "fake_child.py"
    path.write_text(
        "import json, os, sys, time\n"
        "print('中文-测试-⚠️')\n"
        "json.dump({'argv': sys.argv[1:], 'cwd': os.getcwd()},\n"
        "          open(os.environ['FAKE_OUT'], 'w', encoding='utf-8'), ensure_ascii=False)\n"
        f"time.sleep({sleep!r})\n"
        f"sys.exit({rc})\n",
        encoding="utf-8",
    )
    return str(path)


def _wait_for(predicate, what, timeout=8.0):
    """轮询 predicate() 直到真或超时; 返回末次值 (None 且超时 -> AssertionError)。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(0.01)
    raise AssertionError(f"{what} 未在 {timeout}s 内满足 (last: {last!r})")


def wait_status(job_id, base, status, timeout=8.0):
    """轮询 read_job 直到 registry JSON 到达指定 status。"""

    def _probe():
        job = api.jobs.read_job(job_id, base)
        return job if job and job.get("status") == status else None

    return _wait_for(_probe, f"job {job_id} 到达 {status!r}", timeout)


def wait_terminal(job_id, base, timeout=8.0):
    """轮询 read_job 直到 status 进入终态 (succeeded/failed/interrupted); 返回终态 dict。"""

    def _probe():
        job = api.jobs.read_job(job_id, base)
        if job and job.get("status") in ("succeeded", "failed", "interrupted"):
            return job
        return None

    return _wait_for(_probe, f"job {job_id} 到达终态", timeout)


# ---------- 行为 1: 锁单元 —— acquire/同进程拒绝/close 释放/再取/content-free ----------

def test_job_lock_acquire_deny_reacquire_content_free(tmp_path):
    lock_dir = tmp_path / "locks"
    fd1 = job_lock.acquire("pipeline", str(lock_dir))
    assert fd1 is not None  # kind 空闲 -> 返回 open fd
    fd2 = job_lock.acquire("pipeline", str(lock_dir))
    assert fd2 is None  # 同进程二取被拒 (probe V2: 进程内重入拒绝)
    fd1.close()  # close 即释放 (OS 级)
    fd3 = job_lock.acquire("pipeline", str(lock_dir))
    assert fd3 is not None  # 释放后可再取
    fd3.close()
    # content-free pin: 锁文件存在且零字节 (probe V2: 被锁字节对其他进程不可读,
    # 任何 holder 信息都不可写进锁文件)
    lock_file = lock_dir / "pipeline.lock"
    assert lock_file.is_file()
    assert lock_file.read_bytes() == b""


# ---------- 行为 2: 生命周期 succeeded (真实子进程, UTF-8 日志回归钉) ----------

def test_lifecycle_succeeded_utf8_log_argv_cwd(tmp_path, monkeypatch):
    fake = fake_script(tmp_path, rc=0, sleep=0.3)
    out = tmp_path / "out.json"
    monkeypatch.setenv("FAKE_OUT", str(out))
    base = api.jobs.jobs_dir()

    lock_fd = job_lock.acquire("pipeline", api.jobs.locks_dir())
    assert lock_fd is not None
    job = api.jobs.start_job("pipeline", [sys.executable, fake, "--fast"], lock_fd, base)

    # durable-at-accept: claim 同步写 pending 文件后才 start 线程 -> 返回时文件必在
    job_file = os.path.join(base, job["job_id"] + ".json")
    assert os.path.isfile(job_file)
    first = api.jobs.read_job(job["job_id"], base)
    assert first is not None and first["status"] in ("pending", "running")

    # running 迁移 (子进程 sleep 0.3s 的窗口内必被观察到) + pid 落盘
    running = wait_status(job["job_id"], base, "running")
    assert running["pid"] is not None
    assert running["started_at"] is not None

    term = wait_terminal(job["job_id"], base)
    assert term["status"] == "succeeded"
    assert term["exit_code"] == 0
    assert term["finished_at"] is not None
    # 响应 dict 暴露 log_path (同级 {job_id}.log)
    assert term["log_path"] and term["log_path"].endswith(job["job_id"] + ".log")
    assert os.path.isfile(term["log_path"])
    # V1 回归钉: 日志按 UTF-8 解码且含 emoji 字节 (GBK mojibake / UnicodeEncodeError 即红)
    log_text = Path(term["log_path"]).read_text(encoding="utf-8")
    assert "中文-测试-⚠️" in log_text
    # spawn 治理钉: 子进程 argv = 固定参数 (arg-list, 无 shell 介入面), cwd = PROJECT_ROOT
    recorded = json.loads(Path(out).read_text(encoding="utf-8"))
    assert recorded["argv"] == ["--fast"]
    assert os.path.normcase(recorded["cwd"]) == os.path.normcase(api.jobs.PROJECT_ROOT)


# ---------- 行为 3: 生命周期 failed (非零退出码) ----------

def test_lifecycle_failed_exit_code_7(tmp_path, monkeypatch):
    fake = fake_script(tmp_path, rc=7, sleep=0.2)
    monkeypatch.setenv("FAKE_OUT", str(tmp_path / "out.json"))
    lock_fd = job_lock.acquire("pipeline", api.jobs.locks_dir())
    assert lock_fd is not None
    job = api.jobs.start_job("pipeline", [sys.executable, fake], lock_fd)
    term = wait_terminal(job["job_id"], api.jobs.jobs_dir())
    assert term["status"] == "failed"
    assert term["exit_code"] == 7
    assert term["finished_at"] is not None


# ---------- 行为 4: is_running / claim / release ----------

def test_claim_durable_pending_then_inmemory_release(tmp_path):
    """claim 顺序钉: pending 文件先落盘 (原子), 内存表条目后置 —— 接受的瞬间即持久。"""
    base = api.jobs.jobs_dir()
    job = api.jobs.new_job("pipeline", ["python", "x.py", "--fast"])
    assert job["status"] == "pending" and job["pid"] is None
    api.jobs.claim("pipeline", job, base)
    assert api.jobs.read_job(job["job_id"], base)["status"] == "pending"
    entry = api.jobs.is_running("pipeline")
    assert entry is not None and entry["job_id"] == job["job_id"]
    api.jobs.release("pipeline")
    assert api.jobs.is_running("pipeline") is None


def test_is_running_claim_until_worker_release(tmp_path, monkeypatch):
    fake = fake_script(tmp_path, rc=0, sleep=0.3)
    monkeypatch.setenv("FAKE_OUT", str(tmp_path / "out.json"))
    assert api.jobs.is_running("pipeline") is None
    lock_fd = job_lock.acquire("pipeline", api.jobs.locks_dir())
    assert lock_fd is not None
    job = api.jobs.start_job("pipeline", [sys.executable, fake], lock_fd)
    running = api.jobs.is_running("pipeline")
    assert running is not None and running["job_id"] == job["job_id"]
    term = wait_terminal(job["job_id"], api.jobs.jobs_dir())
    assert term["status"] == "succeeded"

    def _released():
        return api.jobs.is_running("pipeline") is None

    _wait_for(_released, "worker 释放 claim")  # worker 终态后 release(kind)


# ---------- 行为 5: read_job 分类 (存在/缺失/损坏) ----------

def test_read_job_present_missing_corrupt(tmp_path):
    base = tmp_path / "jobs"
    job = api.jobs.new_job("pipeline", ["python", "x.py"])
    api.jobs.write_job(job, str(base))
    parsed = api.jobs.read_job(job["job_id"], str(base))
    assert parsed == job  # 存在 -> 解析 dict (字段集逐字往返)
    assert api.jobs.read_job("f" * 32, str(base)) is None  # 缺失 -> None
    (base / "corrupt.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):  # 损坏 -> ValueError 上抛 (分类归 03-02 HTTP 层)
        api.jobs.read_job("corrupt", str(base))
