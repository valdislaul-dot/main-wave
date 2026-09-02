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

from scripts.daily.config import DATA_DIR
from api.boot import ensure_token, has_token, is_loopback

# uptime 锚点: 模块导入时刻 (对 uvicorn.run 即进程启动时刻)。
# 用 monotonic —— 免疫 NTP/手动改钟导致的墙钟跳变 (T-01-04)。
_START = time.monotonic()

# docs/openapi 关闭 (discretion)。无中间件、无路由依赖 (HLT-01 纯度, Pitfall 6)。
app = FastAPI(title="gogo API", docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/health")
def health():
    """探活 (HLT-01): 纯内存返回, 不读文件、不碰网络、不依赖交易日历 —— 任何时刻恒 200。"""
    return {"status": "ok", "uptime_seconds": int(time.monotonic() - _START)}


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

    # 惰性导入: 测试 import api.main 时无需 uvicorn 依赖, 也不触发任何绑定。
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)


if __name__ == "__main__":
    main()
