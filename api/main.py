"""api 包入口: FastAPI app + GET /health + main() 启动序列 (HLT-01, SEC-03, D-03/D-05/D-08)。

模块导入必须无副作用 (Pitfall 3): 不启动、不绑定端口、不写 data/api_token.txt ——
app 与 /health 路由在模块层创建, 启动逻辑全部在 main() 内, 由 __main__ 守卫调用,
这样测试 (TestClient) 可以安全地 import api.main。

路径常量来自 scripts/daily/config.py (D-02), 本模块不计算 BASE、不做 sys.path 操作。
所有控制台文本保持 ASCII-only (Pitfall 5: bat 重定向到 GBK 控制台/日志不得炸编码)。
"""
import os
import sys

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from scripts.daily.config import DATA_DIR, LOG_DIR
from api.boot import ensure_token, has_token, is_loopback
from api.state import router as state_router
from api import jobs  # boot 序列用; import 无副作用 (03-02 D-12)
from api import log_housekeep  # 05-02/05-04: boot 日志看护 (D-32/D-34, M-B); import 无副作用
from api.uptime import uptime_seconds  # D-30 单一锚点 (05-04: 双身份陷阱修复, 详见 uptime.py)
from api.actions import router as actions_router
from api.private import router as private_router
from api.health import router as health_router  # 05-01: 机密级 /health/details (OPS-03 SC1)
from api.errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_error_handler,
)

# uptime 锚点已移入 api/uptime.py (零依赖叶子模块): `python -m api.main` 启动时
# 本文件以 __main__ 身份执行、不注册进 sys.modules —— 锚点若留在本模块, health 的
# 惰性 import 会把本模块二次执行、重置锚点 (05-04 实机分叉, 详见 uptime.py 模块 docstring)。

# openapi 公开只读 (04-01): schema 服务自描述契约; docs 交互面仍关闭 (CLI-only)。
# 无中间件、无路由依赖 (HLT-01 纯度, Pitfall 6)。
app = FastAPI(title="gogo API", docs_url=None, redoc_url=None, openapi_url="/openapi.json")

# 统一错误信封 (04-01): 4xx/5xx 一律 {"detail", "code"}。StarletteHTTPException 键
# 经 MRO 同时罩住 fastapi.HTTPException raise sites 与框架 404/405; Exception 键
# 由 ServerErrorMiddleware 接管 -> 500 固定体, traceback 只进服务端 stderr。
app.add_exception_handler(StarletteHTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)


@app.get("/health")
def health():
    """探活 (HLT-01): 纯内存返回, 不读文件、不碰网络、不依赖交易日历 —— 任何时刻恒 200。"""
    return {"status": "ok", "uptime_seconds": uptime_seconds()}


app.include_router(state_router)
app.include_router(private_router)  # 04-03: 机密级私密读 /v1/private/* (router 自带 auth, SEC-02)
app.include_router(actions_router)  # 03-02: 受保护触发/job 路由 (D-11 豁免之外)
app.include_router(health_router)  # 05-01: 机密级 /health/details (router 自带 auth, SEC-02)


def main() -> None:
    """启动序列: env 解析 -> SEC-03 fail-closed 检查 -> (回环分支) D-03 生成 -> uvicorn 绑定。

    顺序 CRITICAL (Pitfall 2): 非回环分支的 token 检查只认 env 现存状态
    (WR-01/D-12: 文件 token 不再满足非回环检查), 先于任何 ensure_token 调用 ——
    该分支绝不生成 token, 否则拒绝逻辑永不可达。
    """
    sys.stdout.reconfigure(encoding="utf-8")  # repo CLI 惯例

    host = os.environ.get("GOGO_API_HOST", "127.0.0.1")  # D-08 回环默认
    try:
        port = int(os.environ.get("GOGO_API_PORT", "8000"))
    except ValueError:
        print("ERROR: GOGO_API_PORT must be an integer", file=sys.stderr)
        sys.exit(1)
    token_path = os.path.join(DATA_DIR, "api_token.txt")

    if not is_loopback(host):
        # SEC-03 (WR-01/D-12): 非回环绑定只接受环境变量 GOGO_API_TOKEN (strip 后非空)。
        # 文件 token (data/api_token.txt, 含自动生成) 不再满足检查 —— 自动生成的文件与
        # 误配无从区分 (WR-01 根因: has_token 曾被两种姿态共享)。本分支只评估 env 状态,
        # 绝不调用 ensure_token / 绝不创建任何文件 (fail-closed 检查先于一切 token 生成)。
        if not os.environ.get("GOGO_API_TOKEN", "").strip():
            print(
                f"ERROR: refusing to bind {host}: GOGO_API_TOKEN is required for "
                "non-loopback binds. A file token is not accepted - set the "
                "GOGO_API_TOKEN environment variable to authorize exposure",
                file=sys.stderr,
            )
            sys.exit(1)
        # D-12: 绑定暴露总是大声 —— 每次非回环启动都打印 ASCII 警告, 绝不回显 token 值。
        print(
            f"WARNING: binding {host} with API token from GOGO_API_TOKEN "
            "(non-loopback exposure)",
            file=sys.stderr,
        )
    else:
        # D-03: 回环/默认分支, 首次启动自动生成 token (写入 data/api_token.txt)。
        # D-05: 生成后只打印这一句固定 ASCII 提示, 绝不打印 token 值。
        if not has_token(token_path):
            ensure_token(token_path)
            print("API token generated at data/api_token.txt")

    # 启动恢复扫描 (SC5, 03-01 交付): pending/running job -> interrupted。
    # 放在 SEC-03/token 块之后、uvicorn.run 之前 —— Phase 1 boot 顺序不变
    # (Pattern 4; 必须在 main() 内, 测试用模块级 TestClient 无 lifespan)。
    jobs.reload_registry()

    # 日志看护 (05-02/05-04, D-32/D-34): 探测分流 + prune。
    # cmd `>>` 句柄 (含 cmd 自持副本, 子进程生命周期内不释放) 既无 FILE_SHARE_WRITE
    # 也无 FILE_SHARE_DELETE (05-04 真机实测): 继承句柄存活期间进程内 open 撞
    # Errno 13、rename 撞 WinError 32 —— 真机轮转只能由启动器 run_api.bat (M-B)
    # 在 python 启动前完成。故: fd 1/2 指向 console.log (cmd >> 启动) 时继承句柄
    # 已指向 M-B 轮转后的新文件, 进程内零动作最安全; 若 rotate 意外成功 (POSIX /
    # 授予 share-delete 的启动器: rename 可行) 则必须补 repoint 一步 —— 否则 fd 1/2
    # 悬在改名后的 .1 inode 上, 本会话输出全部错位落盘 (WR-01 修复); 手动/测试启动
    # (fd 未指向) 时文件无人持有, rotate -> repoint 全可行。失败至多一条 ASCII
    # WARNING, 绝不阻断 boot (SEC-03 的 fatal-exit 纪律不动)。
    console_log = os.path.join(LOG_DIR, "api", "console.log")
    jobs_dir_path = os.path.join(LOG_DIR, "api", "jobs")
    try:
        os.makedirs(os.path.dirname(console_log), exist_ok=True)
    except OSError:
        pass  # 目录建不出来 -> 原语各自容错告警, boot 照常继续
    if log_housekeep.std_streams_on(console_log):
        _rotated, rotate_err = log_housekeep.rotate_console_log(console_log)
        if _rotated:  # rename 成功 -> 愈合 fd 分叉 (POSIX / share-delete 启动器)
            repoint_err = log_housekeep.repoint_std_streams(console_log)
            if repoint_err:
                print(f"WARNING: log repoint failed - {repoint_err} - continuing boot", file=sys.stderr)
        elif rotate_err:
            print(f"WARNING: console.log rotation skipped - {rotate_err} - continuing boot", file=sys.stderr)
    else:
        _rotated, rotate_err = log_housekeep.rotate_console_log(console_log)
        repoint_err = log_housekeep.repoint_std_streams(console_log)
        if rotate_err or repoint_err:
            detail = "; ".join(e for e in (rotate_err, repoint_err) if e)
            print(f"WARNING: log housekeeping failed - {detail} - continuing boot", file=sys.stderr)
    log_housekeep.prune_job_logs(base=jobs_dir_path)

    # 惰性导入: 测试 import api.main 时无需 uvicorn 依赖, 也不触发任何绑定。
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
