"""日志看护纯函数模块: console.log 轮转 / std 流重指向 / job 对修剪 (05-02, D-32/D-34)。

纯函数层纪律 (api/boot.py 同款): 每个函数只依赖显式传入的路径参数; 默认值一律
在调用时经 api.jobs 的模块 attr 解析 (LOG_DIR / PRUNE_CAP —— monkeypatch 缝, 本
模块零 config 导入、零重复常量); 模块不做任何控制台输出 (轮转告警统一由
api/main.py 的 boot 块打印, ASCII-only); 导入零副作用; 原语永不 raise ——
OSError 一律转成 ascii 错误串返回, 调用方决定是否告警。

Windows 硬约束 (2026-09-04/05 实机验证): cmd `>>` 的 console.log 句柄既未授
FILE_SHARE_WRITE 也未授 FILE_SHARE_DELETE, 且 cmd 自持副本在 python 整个
生命周期内不释放 (05-04 实测: 子进程关掉自己的 fd 后 rename 仍撞 WinError 32)
—— 继承句柄存活期间 open-for-write 撞 Errno 13, rename 撞 WinError 32, 进程内
轮转不可行。因此真机轮转的唯一落点是启动器 (run_api.bat M-B, python 启动前);
main() 的 boot 块先经 std_streams_on 探测: fd 1/2 指向 console.log (cmd >>
启动) 时继承句柄已指向 M-B 轮转后的新文件, 进程内零动作最安全; 未指向 (手动/
测试启动) 时才执行 rotate -> repoint。本模块只提供可测原语, 编排归 api/main.py。
"""
import os
import sys

from api import jobs  # LOG_DIR / PRUNE_CAP / prune 单源 (调用时解析, 模块导入零副作用)

MAX_CONSOLE_LOG_BYTES = 5 * 1024 * 1024  # 工程常量 (05-CONTEXT specifics: 不需配置化)


def _ascii_error(exc):
    """把 OSError 转成 ASCII 错误串 (GBK 控制台/日志不得炸编码, Pitfall 5)。"""
    return str(exc).encode("ascii", "replace").decode("ascii")


def rotate_console_log(path=None, max_bytes=MAX_CONSOLE_LOG_BYTES):
    """console.log 超过 max_bytes -> 重命名为 .1 (一份历史, os.replace 覆盖旧 .1)。

    path 缺省 = api.jobs.LOG_DIR/api/console.log (调用时解析)。缺失文件或
    size <= max_bytes -> (False, None); 轮转成功 -> (True, None);
    OSError -> (False, ascii 错误串)。永不上抛、绝不打印 —— 轮转失败只降级为
    main() 的一句 ASCII stderr 警告, 绝不阻止 boot (SEC-03 纪律不动)。
    """
    if path is None:
        path = os.path.join(jobs.LOG_DIR, "api", "console.log")
    try:
        if not os.path.exists(path) or os.path.getsize(path) <= max_bytes:
            return (False, None)
        os.replace(path, path + ".1")
        return (True, None)
    except OSError as exc:
        return (False, _ascii_error(exc))


def repoint_std_streams(path=None):
    """把进程 fd 1/2 重指向 path 的追加句柄 (非重定向启动的收尾步)。

    flush 先落当前缓冲; os.open(O_WRONLY | O_APPEND | O_CREAT) 后 dup2 到 fd 1/2,
    关闭多余 fd。绝不重建 sys.stdout/sys.stderr 对象、绝不碰 logging —— 打印对象
    归属不变, 只换落点。path 缺省 = jobs.LOG_DIR/api/console.log (调用时解析)。
    失败: 返回 ascii 错误串, 不还原 (流保持失败前指向), 永不 raise。

    05-04 适配: 若调用前 fd 1/2 已被关掉, os.open 会拿到最低空闲 fd (即 1 或 2)
    —— 此时绝不能再 os.close(fd), 否则刚 dup2 好的新流被自己关掉; 只有 fd > 2
    (dup2 前没碰过 std fd 的常规路径) 才需要关闭多余 fd。
    """
    if path is None:
        path = os.path.join(jobs.LOG_DIR, "api", "console.log")
    try:
        sys.stdout.flush()
        sys.stderr.flush()
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        try:
            os.dup2(fd, 1)
            os.dup2(fd, 2)
        finally:
            if fd not in (1, 2):
                os.close(fd)
        return None
    except OSError as exc:
        return _ascii_error(exc)


def std_streams_on(path=None):
    """探测 fd 1/2 是否指向 path (cmd `>>` 启动检测, 05-04 M-B 适配)。

    os.path.samestat(os.fstat(fd), os.stat(path)) 自持检测: 任一 std fd 与
    path 同文件 -> True (继承句柄启动, 文件被启动器 deny-share 持有, 进程内
    open/rename 均不可行 —— main() 据此走零动作分支)。手动控制台/测试管道
    启动的 fd 1/2 不是日志文件句柄 -> False。永不 raise: stat/fstat 失败
    一律按 False 处理 (fd 无效或文件缺失都不可能是"指向"状态)。
    path 缺省 = jobs.LOG_DIR/api/console.log (调用时解析)。
    """
    if path is None:
        path = os.path.join(jobs.LOG_DIR, "api", "console.log")
    try:
        st_path = os.stat(path)
    except OSError:
        return False
    for fd in (1, 2):
        try:
            if os.path.samestat(os.fstat(fd), st_path):
                return True
        except OSError:
            continue
    return False


def prune_job_logs(base=None, cap=None):
    """boot 期 job 对修剪 (D-33 承诺): 委托 api.jobs.prune, cap 调用时取 PRUNE_CAP。

    reload_registry 尾部已按同一 cap 修剪过 —— 本调用幂等无害 (belt-and-suspenders:
    boot 时 registry 至多 20 个终态对, 此处盖住 reload 修剪路径未来变化的可能)。
    base 缺省 = jobs.jobs_dir(), cap 缺省 = jobs.PRUNE_CAP, 均调用时解析。
    jobs.prune 全 OSError 容错 —— 本函数永不抛错、无返回值。
    """
    if base is None:
        base = jobs.jobs_dir()
    if cap is None:
        cap = jobs.PRUNE_CAP
    jobs.prune(base, cap)
