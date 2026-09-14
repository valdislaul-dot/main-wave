"""进程启动 monotonic 锚点 + uptime 读数 (D-30, 05-01; 05-04 双身份陷阱修复)。

单一事实源模块: /health (api/main.py) 与 /health/details (api/health.py) 都经
本模块取 uptime, 绝不各自持有锚点。05-04 实机发现: `python -m api.main` 启动时
api/main.py 的文件身份是 __main__, 不会以 "api.main" 注册进 sys.modules ——
health.py 曾在 handler 内 `from api.main import uptime_seconds` 惰性 import,
该 import 把整个 main.py 按 "api.main" 身份二次执行, 模块级 _START 锚点被重置
(实机: /health/details uptime 从 0 重新计数, 与 /health 读数分叉 70s+)。锚点移进
本零依赖叶子模块 (只 import time) 后, main.py 无论以 __main__ 还是 api.main
身份加载, 两端点都命中同一模块同一锚点, 该陷阱在结构上不再可能。

monotonic: 免疫 NTP/手动改钟导致的墙钟跳变 (T-01-04)。模块导入零副作用。
"""
import time

_START = time.monotonic()  # 模块导入时刻 = 进程启动时刻 (uvicorn 绑定之前)


def uptime_seconds() -> int:
    """进程存活秒数 (monotonic): 自本模块首次导入 (即进程启动) 起算。"""
    return int(time.monotonic() - _START)
