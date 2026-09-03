"""api 包入口: FastAPI app + GET /health + main() 启动序列 (HLT-01, SEC-03, D-03/D-05/D-08)。

模块导入必须无副作用 (Pitfall 3): 不启动、不绑定端口、不写 data/api_token.txt ——
app 与 /health 路由在模块层创建, 启动逻辑全部在 main() 内, 由 __main__ 守卫调用,
这样测试 (TestClient) 可以安全地 import api.main。

路径常量来自 scripts/daily/config.py (D-02), 本模块不计算 BASE、不做 sys.path 操作。
所有控制台文本保持 ASCII-only (Pitfall 5: bat 重定向到 GBK 控制台/日志不得炸编码)。
"""
import os
import sys
import time

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from scripts.daily.config import DATA_DIR
from api.boot import ensure_token, has_token, is_loopback
from api.state import router as state_router
from api import jobs  # boot 序列用; import 无副作用 (03-02 D-12)
from api.actions import router as actions_router
from api.errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_error_handler,
)

# uptime 锚点: 模块导入时刻 (对 uvicorn.run 即进程启动时刻)。
# 用 monotonic —— 免疫 NTP/手动改钟导致的墙钟跳变 (T-01-04)。
_START = time.monotonic()

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
    return {"status": "ok", "uptime_seconds": int(time.monotonic() - _START)}


app.include_router(state_router)
app.include_router(actions_router)  # 03-02: 受保护触发/job 路由 (D-11 豁免之外)


def main() -> None:
    """启动序列: env 解析 -> SEC-03 fail-closed 检查 -> (回环分支) D-03 生成 -> uvicorn 绑定。

    顺序 CRITICAL (Pitfall 2): 非回环分支的 token 检查基于 env+文件现存状态,
    先于任何 ensure_token 调用 —— 该分支绝不生成 token, 否则拒绝逻辑永不可达。
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
        # SEC-03: 非回环绑定必须有已配置 token, 否则拒绝启动 (exit non-zero)。
        # 只评估 env/file 状态 —— 本分支绝不调用 ensure_token。
        if not has_token(token_path):
            print(
                f"ERROR: refusing to bind {host} without an API token. "
                "Set GOGO_API_TOKEN or create data/api_token.txt",
                file=sys.stderr,
            )
            sys.exit(1)
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

    # 惰性导入: 测试 import api.main 时无需 uvicorn 依赖, 也不触发任何绑定。
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
