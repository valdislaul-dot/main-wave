"""持久化 job registry + spawn 治理 (ACT-02/ACT-03 核心, D-03; RESEARCH Pattern 2/3/4)。

每 job 一个 JSON 文件 (logs/api/jobs/{job_id}.json), 每次状态迁移都是
tmp + os.replace 原子重写 (Pattern 2, zt_pool.py:72-78); 子进程 stdout/stderr
直接进同级 {job_id}.log 文件句柄 (无 pipe, Pattern 3); 每 job 一个 daemon worker
线程, 事件循环/请求路径永不等待子进程 (SC3)。

字段集 (Pattern 2, 消费方接口, additive-tolerant): job_id (uuid4 hex), kind,
status (pending|running|succeeded|failed|interrupted), pid, exit_code, log_path,
cmd (argv list), created_at, started_at, finished_at。

模块导入零副作用: 不起线程、不建目录、不打印 (控制台文本保持 ASCII-only);
LOG_DIR/DATA_DIR/PROJECT_ROOT 按名导入且只在函数内按调用时引用 (monkeypatch 缝)。
reload_registry 由 03-02 在 main() 启动序列调用, 绝不在 import 时执行。
"""
import json
import os
import subprocess
import sys
import threading
import time
import uuid

from scripts.daily.config import DATA_DIR, LOG_DIR, PROJECT_ROOT  # 仅在函数内引用

PRUNE_CAP = 500  # registry 上限: 只保留最新 500 个终态 job (json+log 对)
TERMINAL = ("succeeded", "failed", "interrupted")

_claims = {}  # kind -> job dict; 派生缓存, 永不权威 (文件才是真相)
_claims_lock = threading.Lock()


def jobs_dir():
    """registry 目录: LOG_DIR/api/jobs (调用时解析 —— monkeypatch 缝)。"""
    return os.path.join(LOG_DIR, "api", "jobs")


def locks_dir():
    """锁目录: DATA_DIR/locks (调用时解析 —— monkeypatch 缝)。"""
    return os.path.join(DATA_DIR, "locks")


def new_job(kind, cmd):
    """新 job dict, status=pending, 字段集见模块 docstring (Pattern 2)。"""
    return {
        "job_id": uuid.uuid4().hex,
        "kind": kind,
        "status": "pending",
        "pid": None,
        "exit_code": None,
        "log_path": None,
        "cmd": list(cmd),
        "created_at": int(time.time()),
        "started_at": None,
        "finished_at": None,
    }


def write_job(job, base=None):
    """原子迁移写 (Pattern 2): 同目录 tmp + os.replace, 永不截断写。

    tmp 名带 pid 后缀, 跨线程/跨进程不碰撞。读侧 open->read->close 的句柄窗口是
    µs 级, 但 Windows 上恰好同刻的 os.replace 会撞 PermissionError (WinError 5 类,
    api/state.py:62-63) —— 轮询读者 (GET 轮询/本套测试) 不得能把一次迁移打成失败:
    replace 短重试 (tmp 仍在, 重试幂等); 持久失败清理 tmp 后上抛, 由调用方兜底。
    """
    base = base or jobs_dir()
    os.makedirs(base, exist_ok=True)
    tmp = os.path.join(base, f".{job['job_id']}.tmp-{os.getpid()}")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False)
    dst = os.path.join(base, job["job_id"] + ".json")
    for attempt in range(4):  # 3 次重试, 每次让出 10ms (读句柄窗口 µs 级, 远够)
        try:
            os.replace(tmp, dst)
            return
        except PermissionError:
            if attempt < 3:
                time.sleep(0.01)
                continue
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise


def read_job(job_id, base=None):
    """读 registry 文件: 缺失 -> None; 损坏 JSON -> ValueError 上抛 (分类归调用方)。

    open->read->close (handle 纪律); 读的是 os.replace 的成品, 结构上不可能撕裂。
    """
    base = base or jobs_dir()
    path = os.path.join(base, job_id + ".json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def is_running(kind):
    """内存 claim 表查询 (instant 409 用); 无条目返回 None。"""
    with _claims_lock:
        return _claims.get(kind)


def claim(kind, job, base=None):
    """durable-first 认领: pending 文件先落盘 (原子), 内存条目后置。

    接受即持久的契约点: 任何 spawn 都发生在 pending 写成功之后 (truth 1)。
    """
    with _claims_lock:
        write_job(job, base)
        _claims[kind] = job


def release(kind):
    """worker 终态后释放内存 claim (文件已是终态, 先于本调用落盘)。"""
    with _claims_lock:
        _claims.pop(kind, None)


def run_job(job, lock_fd, base=None):
    """daemon worker 线程目标 (probe V1/V4 形态): spawn -> 迁移 -> 终态 -> 释放。

    spawn env = 继承 + PYTHONIOENCODING=utf-8 (V1: 绝不 PYTHONUTF8=1 —— 那会静默
    翻转仓库 open() 默认编码); GOGO_API_TOKEN 从 env 副本弹出 (SEC-01 密钥卫生,
    子进程永不收到 key); nt 上加 CREATE_NO_WINDOW (V4)。子进程 stdout/stderr 直接
    写 {job_id}.log 文件句柄 —— 无 pipe 无死锁。spawn 异常 -> failed, 线程不崩。
    """
    base = base or jobs_dir()
    job["log_path"] = os.path.join(base, job["job_id"] + ".log")
    job["status"] = "running"
    job["started_at"] = int(time.time())
    write_job(job, base)
    env = dict(os.environ)
    env.pop("GOGO_API_TOKEN", None)
    env["PYTHONIOENCODING"] = "utf-8"
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        # with 块内只做 Popen: 父进程的句柄副本随 with 退出关闭, 子进程继承的副本继续写
        with open(job["log_path"], "wb", buffering=0) as fh:
            proc = subprocess.Popen(
                job["cmd"],
                cwd=PROJECT_ROOT,
                env=env,
                stdout=fh,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
        job["pid"] = proc.pid
        write_job(job, base)
        job["exit_code"] = proc.wait()
        job["status"] = "succeeded" if proc.returncode == 0 else "failed"
    except Exception:
        job["status"], job["exit_code"] = "failed", None  # spawn 失败 -> failed, 线程不崩
    finally:
        job["finished_at"] = int(time.time())
        try:
            write_job(job, base)  # 终态落盘
        except OSError:
            pass  # 磁盘级失败: 文件留在 running, boot sweep 会收成 interrupted
        release(job["kind"])  # 释放必须永远执行 (锁/claim 不容许因写失败滞留)
        try:
            lock_fd.close()  # OS 级释放单飞锁
        except OSError:
            pass
        try:
            prune(base, PRUNE_CAP)
        except OSError:
            pass


def start_job(kind, cmd, lock_fd, base=None):
    """认领 + 起 daemon worker, 返回"接受时刻"的 pending job 快照 (202 语义的模块侧)。

    调用方 (03-02 POST handler) 必须先取得 OS 锁再调本函数; worker 在 finally 释放。
    返回 dict(job) 快照而非活引用: worker 线程在 Thread.start 后立即把同一 dict
    迁移成 running —— 活引用会让 202 响应体 (序列化发生在 start 之后) 竞态地
    出现 running/succeeded, 违反 202 {status: pending} 契约 (03-02 实测发现,
    Rule 1 修复); 快照即"接受即持久"的文件内容, 语义诚实。
    """
    job = new_job(kind, cmd)
    claim(kind, job, base)
    snapshot = dict(job)  # 浅拷贝: 字段全为标量 + 无人再改的 cmd 列表
    threading.Thread(target=run_job, args=(job, lock_fd, base), daemon=True).start()
    return snapshot


def reload_registry(base=None, cap=PRUNE_CAP):
    """启动恢复扫描 (SC5, RESEARCH Pattern 4): pending/running -> interrupted。

    deterministic-interrupted 是"API 在 job 飞行中死亡"的诚实终态 —— failed 意味着
    脚本真的跑过并出错; 无 PID 探针 (孤儿收养归 ACT-05 v2)。逐文件原子重写,
    不可解析文件与点文件跳过 (绝不中断扫描); 结尾 prune(base, cap) —— 刚收编的
    interrupted 与任何终态一样计入上限。纯函数, 由 03-02 在 main() 启动序列调用,
    绝不在 import 时执行。
    """
    base = base or jobs_dir()
    os.makedirs(base, exist_ok=True)
    try:
        names = os.listdir(base)
    except OSError:
        return
    for name in names:
        if not name.endswith(".json") or name.startswith("."):
            continue
        stem = name[: -len(".json")]
        try:
            job = read_job(stem, base)
        except (OSError, ValueError):
            continue  # 撕裂/损坏 -> 跳过, 不删不动
        if job is None or job.get("status") not in ("pending", "running"):
            continue
        job["status"] = "interrupted"
        job["finished_at"] = int(time.time())
        write_job(job, base)  # 原地原子重写 (Pattern 2)
    prune(base, cap)


def prune(base=None, cap=PRUNE_CAP):
    """只删终态 job 的 json+log 对, 按 json mtime 保留最新 cap 个; 缺文件跳过 (ENOENT 容忍)。

    永不动 pending/running 的文件 —— 另一线程 finalize 中的 job 不受影响;
    与并发 finalize 的竞态靠 except OSError: pass 消化。
    """
    base = base or jobs_dir()
    try:
        names = os.listdir(base)
    except OSError:
        return  # 目录缺失 -> 无事可做
    terminal = []  # (mtime, json_path, stem)
    for name in names:
        if not name.endswith(".json") or name.startswith("."):
            continue
        stem = name[: -len(".json")]
        json_path = os.path.join(base, name)
        try:
            job = read_job(stem, base)
            if job is None or job.get("status") not in TERMINAL:
                continue
            terminal.append((os.path.getmtime(json_path), json_path, stem))
        except (OSError, ValueError):
            continue  # 撕裂/缺失/竞态删除 -> 跳过, 绝不致命
    if len(terminal) <= cap:
        return
    terminal.sort(key=lambda e: e[0])  # 最旧在前
    for _, json_path, stem in terminal[: len(terminal) - cap]:
        for p in (json_path, os.path.join(base, stem + ".log")):
            try:
                os.remove(p)
            except OSError:
                pass
