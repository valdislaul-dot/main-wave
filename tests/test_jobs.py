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


def _read_tolerant(job_id, base):
    """轮询式读: 与写者 os.replace 的瞬时竞态 (WinError 5 类) 视为"未就绪", 下轮再试。

    os.replace 在 Windows 上以独占删除访问短暂持有目标, 恰好同刻的 open 会撞
    PermissionError —— µs 级窗口; 轮询语义下吞掉重试是确定性行为 (读侧契约
    "OSError 上抛" 由 read_job 直接调用方承担, 见 test_read_job_present_missing_corrupt)。
    """
    try:
        return api.jobs.read_job(job_id, base)
    except OSError:
        return None


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
    """轮询 registry JSON 直到到达指定 status。"""

    def _probe():
        job = _read_tolerant(job_id, base)
        return job if job and job.get("status") == status else None

    return _wait_for(_probe, f"job {job_id} 到达 {status!r}", timeout)


def wait_terminal(job_id, base, timeout=8.0):
    """轮询 registry JSON 直到 status 进入终态 (succeeded/failed/interrupted)。"""

    def _probe():
        job = _read_tolerant(job_id, base)
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
    first = _read_tolerant(job["job_id"], base)
    assert first is not None and first["status"] in ("pending", "running")

    # running 迁移 (子进程 sleep 0.3s 的窗口内必被观察到) + pid 落盘。
    # 注: running 写两次 —— Popen 前 (pid=None) 与 Popen 后 (pid=实际值), 轮询须等 pid。
    def _running_with_pid():
        j = _read_tolerant(job["job_id"], base)
        return j if j and j.get("status") == "running" and j.get("pid") is not None else None

    running = _wait_for(_running_with_pid, f"job {job['job_id']} running + pid")
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


# ---------- 行为 6-10: 崩溃恢复套 (SC5; reload sweep + 终端修剪上限) ----------

def _seed_job_file(base, job_id, status, mtime=None, pid=None):
    """直接 open('w') 手写 fixture job JSON (模拟崩溃遗留文件, 不走被测的 write_job)。

    可选: json 的 mtime (prune 按 json mtime 计龄) 与 .log 陪衬文件 (修剪成对删)。
    """
    job = {
        "job_id": job_id,
        "kind": "pipeline",
        "status": status,
        "pid": pid,
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


def test_reload_sweep_interrupts_inflight_keeps_terminal(tmp_path):
    base = tmp_path / "jobs"
    base.mkdir()
    _seed_job_file(base, "a" * 32, "pending")
    _seed_job_file(base, "b" * 32, "running", pid=4242)
    _seed_job_file(base, "c" * 32, "succeeded")
    succ_bytes = (base / ("c" * 32 + ".json")).read_bytes()

    api.jobs.reload_registry(str(base))

    swept_pending = api.jobs.read_job("a" * 32, str(base))
    assert swept_pending["status"] == "interrupted"
    assert swept_pending["finished_at"] is not None  # 确定性终态带时间戳
    assert swept_pending["pid"] is None  # 原地重写, 其余字段保留
    swept_running = api.jobs.read_job("b" * 32, str(base))
    assert swept_running["status"] == "interrupted"
    assert swept_running["finished_at"] is not None
    assert swept_running["pid"] == 4242  # 原 running 的 pid 保留 (只改状态+finished_at)
    assert (base / ("c" * 32 + ".json")).read_bytes() == succ_bytes  # 终态文件不动


def test_reload_sweep_idempotent_second_sweep(tmp_path):
    base = tmp_path / "jobs"
    base.mkdir()
    _seed_job_file(base, "a" * 32, "pending")
    api.jobs.reload_registry(str(base))
    path = base / ("a" * 32 + ".json")
    after_first = path.read_bytes()
    assert api.jobs.read_job("a" * 32, str(base))["status"] == "interrupted"
    api.jobs.reload_registry(str(base))  # 第二次扫描
    assert path.read_bytes() == after_first  # interrupted 不再重写 (无 finished_at churn)


def test_reload_sweep_tolerates_corrupt_and_dotfiles(tmp_path):
    base = tmp_path / "jobs"
    base.mkdir()
    _seed_job_file(base, "a" * 32, "running")
    (base / "corrupt.json").write_text("{not json", encoding="utf-8")
    (base / ".DS_Store").write_bytes(b"dotfile")  # .DS_Store 风格点文件

    api.jobs.reload_registry(str(base))  # 不得中断扫描

    assert api.jobs.read_job("a" * 32, str(base))["status"] == "interrupted"
    assert (base / "corrupt.json").exists()  # 不可解析 -> 跳过, 不删
    assert (base / ".DS_Store").exists()  # 点文件 -> 跳过


def test_reload_sweep_prune_cap_keeps_20_newest_terminal(tmp_path):
    """D-33 边界 (05-02): 25 终态 + 3 inflight -> sweep 收编后 prune 到恰好 20。

    PRUNE_CAP == 20 是唯一常量 (单源); 本测试在旧常量 500 上必红
    (28 <= 500, prune 无事可做) —— cap 收紧是唯一转绿路径。
    """
    assert api.jobs.PRUNE_CAP == 20  # 常量钉: 旧值 500 时此断言先红
    base = tmp_path / "jobs"
    base.mkdir()
    terminal_ids = []
    for i in range(25):
        jid = f"{i:032x}"
        _seed_job_file(base, jid, "succeeded", mtime=1_700_000_000 + i)
        terminal_ids.append(jid)
    inflight = ["f" * 32, "e" * 32, "d" * 32]
    for jid in inflight:  # 非终态 (seed 时) —— sweep 会先收成 interrupted
        _seed_job_file(base, jid, "running")

    api.jobs.reload_registry(str(base))

    remaining = [p.name[: -len(".json")] for p in base.glob("*.json")]
    assert len(remaining) == 20  # 25 终态 - 8 最旧 + 3 刚收编 = 20 (jobs.py L27 语义)
    for jid in inflight:
        assert jid in remaining  # 刚收编的 interrupted 计入上限且存活
        assert api.jobs.read_job(jid, str(base))["status"] == "interrupted"
    for i in range(8):
        assert f"{i:032x}" not in remaining  # 最旧 8 对 (json+log) 被删
    for i in range(8, 25):
        assert f"{i:032x}" in remaining  # 最新 17 个终态对存活
    assert not (base / f"{0:032x}.log").exists()  # log 与 json 成对删除
    assert not (base / f"{0:032x}.json").exists()

    # 幂等钉: 第二次 reload 无事可做 (20 <= cap, sweep 无 inflight)
    api.jobs.reload_registry(str(base))
    after_second = sorted(p.name[: -len(".json")] for p in base.glob("*.json"))
    assert len(after_second) == 20
    assert after_second == sorted(remaining)


def test_run_job_finally_prune_trims_to_cap_20(tmp_path, monkeypatch):
    """run_job finally-prune (03-01 承诺, jobs.py:170) 按 PRUNE_CAP=20 修剪超限 registry。"""
    base = tmp_path / "jobs"
    base.mkdir()
    for i in range(25):
        jid = f"{i:032x}"
        _seed_job_file(base, jid, "succeeded", mtime=1_700_000_000 + i)
    fake = fake_script(tmp_path, rc=0, sleep=0.1)
    monkeypatch.setenv("FAKE_OUT", str(tmp_path / "out.json"))
    lock_fd = job_lock.acquire("pipeline", api.jobs.locks_dir())
    assert lock_fd is not None
    job = api.jobs.start_job("pipeline", [sys.executable, fake], lock_fd, base)
    term = wait_terminal(job["job_id"], base)
    assert term["status"] == "succeeded"
    # prune 在 finally 的最后一步: 终态可见后仍需等修剪落地 (轮询到 20)

    def _pruned():
        return len(list(base.glob("*.json"))) == 20

    _wait_for(_pruned, f"finally-prune 把 registry 修到 20 (job {job['job_id']})")
    remaining = sorted(p.name[: -len(".json")] for p in base.glob("*.json"))
    assert len(remaining) == 20  # 25 种子终态 + 新终态 1 - 最旧 6 = 20
    for i in range(6):
        assert f"{i:032x}" not in remaining  # 最旧 6 对 (json+log) 被删
        assert not (base / f"{i:032x}.json").exists()
        assert not (base / f"{i:032x}.log").exists()
    for i in range(6, 25):
        assert f"{i:032x}" in remaining  # 最新 19 个种子终态存活
    assert job["job_id"] in remaining  # 刚完成的 job 是最新终态, 存活


def test_prune_skips_corrupt_json_still_trims_others(tmp_path):
    """逐文件容错不变: 最旧区一个损坏 .json 被跳过, 其余超限对照常修剪 (05-02 行为 3)。"""
    base = tmp_path / "jobs"
    base.mkdir()
    for i in range(23):  # 22 个有效终态 + 1 个损坏 (i=2, 最旧区)
        jid = f"{i:032x}"
        _seed_job_file(base, jid, "succeeded", mtime=1_700_000_000 + i)
    corrupt = base / f"{2:032x}.json"
    corrupt.write_text("{not json", encoding="utf-8")

    api.jobs.prune(str(base))

    # 损坏文件未被计数也未被动过 (含其 .log 陪衬 —— 不成对被删)
    assert corrupt.read_text(encoding="utf-8") == "{not json"
    assert (base / f"{2:032x}.log").exists()
    remaining = sorted(p.name[: -len(".json")] for p in base.glob("*.json"))
    assert len(remaining) == 21  # 22 个有效终态 - 最旧 2 个有效对 + 损坏 1 个留存 = 21
    for i in (0, 1):
        assert f"{i:032x}" not in remaining  # 最旧 2 个有效对 (json+log) 被删
        assert not (base / f"{i:032x}.json").exists()
        assert not (base / f"{i:032x}.log").exists()
    for i in range(3, 23):
        assert f"{i:032x}" in remaining  # 其余 20 个有效对 + 损坏 json 存活


def test_reload_sweep_missing_dir_creates_and_returns(tmp_path):
    base = tmp_path / "does" / "not" / "exist"
    api.jobs.reload_registry(str(base))  # makedirs exist_ok -> 无错返回
    assert base.is_dir()
    assert api.jobs.read_job("f" * 32, str(base)) is None  # 空目录可正常读


# ---------- 行为 11: 跨进程锁 —— 持有时父进程被拒, 杀死持有者 OS 立即释放 ----------

# 真实子进程: importlib 从 argv[1] 加载 job_lock.py, acquire(argv[2] kind, argv[3]
# lock_dir), 成功则打印 HELD 并睡 60s (期间锁一直持有) —— probe V2 kill 证据的套内孪生。
_CROSS_PROC_CHILD = (
    "import importlib.util, sys, time\n"
    "spec = importlib.util.spec_from_file_location('job_lock', sys.argv[1])\n"
    "m = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(m)\n"
    "fd = m.acquire(sys.argv[2], sys.argv[3])\n"
    "if fd is None:\n"
    "    sys.exit(3)\n"
    "print('HELD', flush=True)\n"
    "time.sleep(60)\n"
)


def _job_lock_path():
    """job_lock.py 绝对路径: repo/scripts/daily/job_lock.py (由 api/jobs.py 上溯两级)。"""
    return str(Path(api.jobs.__file__).resolve().parent.parent / "scripts" / "daily" / "job_lock.py")


def test_job_lock_cross_process_hold_and_kill_releases(tmp_path):
    lock_dir = tmp_path / "locks"
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(
        [sys.executable, "-c", _CROSS_PROC_CHILD, _job_lock_path(), "pipeline", str(lock_dir)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=flags,
    )
    try:
        # 子进程只输出一行 HELD (小管道读一行安全), 读完即不再读它的 stdout
        line = proc.stdout.readline()
        assert line.strip() == b"HELD", (
            f"子进程未能持有锁 (stderr: {proc.stderr.read()!r})"
        )
        # 跨进程拒绝: 父进程 acquire 同 kind 必 None
        assert job_lock.acquire("pipeline", str(lock_dir)) is None
        # 杀死持有者 -> OS 自动释放 (probe V2 发现, 套内钉死)
        proc.kill()
        proc.wait(timeout=10)
        fd = job_lock.acquire("pipeline", str(lock_dir))
        assert fd is not None  # 无需任何 stale-lock 清理协议
        fd.close()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


# ---------- 行为 12: SC3 —— job 运行期间 /health P95 < 50ms (TestClient 锤) ----------

def test_health_latency_during_running_job(tmp_path, monkeypatch):
    """活子进程 + worker 线程运行期间, /health 必须持续亚 50ms P95 应答 (SC3)。

    TestClient 是进程内客户端: 钉的是"活子进程 + 线程永不拖慢请求处理"的模块侧
    半场; 真 uvicorn 的 P95 确认在 03-04 smoke (A2/thread+Popen 治理)。
    """
    fake = fake_script(tmp_path, rc=0, sleep=2.0)
    monkeypatch.setenv("FAKE_OUT", str(tmp_path / "out.json"))
    lock_fd = job_lock.acquire("pipeline", api.jobs.locks_dir())
    assert lock_fd is not None
    job = api.jobs.start_job("pipeline", [sys.executable, fake], lock_fd)
    try:
        wait_status(job["job_id"], api.jobs.jobs_dir(), "running")
        client.get("/health")  # 预热: 首次 in-process 请求含框架暖启动, 不计时
        client.get("/health")
        times = []
        for _ in range(60):
            t0 = time.perf_counter()
            response = client.get("/health")
            times.append(time.perf_counter() - t0)
            assert response.status_code == 200
            assert response.json()["status"] == "ok"
        times.sort()
        assert times[57] < 0.05, f"p95 = {times[57]:.4f}s >= 0.05s 在 job 运行期间 (SC3)"
    finally:
        term = wait_terminal(job["job_id"], api.jobs.jobs_dir())
        assert term["status"] == "succeeded"  # worker 在自身 finally 释放锁与 claim
