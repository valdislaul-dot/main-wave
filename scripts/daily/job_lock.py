"""共享跨平台单飞锁 helper (ACT-03, D-03; probe V2 语义, 真机验证 2026-09-03)。

消费方:
- API 侧:  from scripts.daily.job_lock import acquire   (scripts. 包链导入)
因此本模块保持零 scripts.* 导入、零导入副作用 (不建目录、不打印、不做 I/O)。
(2026-09-17: 原 GUI 侧消费方 gui_dashboard.py 已随 GUI 面板一同废弃删除)

实现: win32 用 msvcrt.locking 字节区间锁, posix (Mac parity) 用 fcntl.flock,
按 ImportError 分叉。锁文件 data/locks/{kind}.lock 零内容 —— 被锁字节对其他进程
不可读 (probe V2), holder 信息永远不进锁文件; OS 在持有进程死亡时自动释放
(probe V2 kill 验证), 无 stale 锁清理协议。
"""
import os

try:  # Windows: 字节区间锁, 进程死亡 OS 自动释放 (probe V2)
    import msvcrt

    def _try(fh):
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        return True

    def _release(fh):
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

except ImportError:  # posix (Mac GUI parity)
    import fcntl

    def _try(fh):
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True

    def _release(fh):
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


def acquire(kind, lock_dir):
    """取得 kind 的单飞锁, 成功返回 open fd (调用方持有, close 即释放), 否则 None。

    lock_dir 由调用方注入 (测试 -> tmp_path); 目录在 acquire 时才创建 (导入零副作用)。
    文件以 a+b 打开: 不存在则创建, 存在也不截断 —— 锁文件保持零内容。
    """
    os.makedirs(lock_dir, exist_ok=True)
    fh = open(os.path.join(lock_dir, kind + ".lock"), "a+b")
    try:
        _try(fh)
        return fh
    except OSError:  # 已被持有 (API job / GUI / 其他进程) -> 关 fd, 返回 None
        fh.close()
        return None
