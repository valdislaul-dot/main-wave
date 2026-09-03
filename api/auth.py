"""X-API-Key 鉴权依赖 (SEC-01, D-10/D-11; RESEARCH Pattern 5)。

router 级依赖 —— 只挂在 api/actions.py 的保护路由上, 绝不做中间件/不做
app 级依赖: /health、/health/ready、GET /v1/state/{name} 在公开路由, 结构上
豁免 (D-11 豁免清单); /health 纯度与 SC3 P95 不受影响 (HLT-01, RESEARCH
Anti-Patterns: auth middleware)。

契约 (D-10): 缺失 X-API-Key 头 -> 401 + WWW-Authenticate: ApiKey 挑战头;
带了但错误 -> 403; 均经 hmac.compare_digest constant-time 比较。无 token
配置 (env 与文件都没有) -> fail-closed 403 (绝不 200/202)。token 解析复用
Phase 1 api.boot.read_token 链路 (env GOGO_API_TOKEN 优先, data/api_token.txt
其次) —— 无第二个 token 加载器, 无会话/缓存/共享可变状态; 每次请求独立读
token (env 未设时旋转 token 无需重启即生效)。

签名规则 (硬性, prohibition #2): 依赖只收 request: Request, 绝不声明可选
字符串参数 —— FastAPI 会把可选参数暴露成攻击者可控的查询参数 (如
?token_path=<文件> 可把 token 解析重定向到任意路径)。token 路径在函数内按
调用时从模块 DATA_DIR 属性解析 (monkeypatch 缝, api/state.py 惯例)。

本模块零导入副作用、零日志输出; 错误体不含 token/路径文本 (Phase 2 最小
JSON 风格, D-10); 控制台文本 (无) ASCII-only。401/403 路径不产生任何
spawn / registry 写 (被拒请求永不干扰运行中 job)。
"""
import hmac
import os

from fastapi import HTTPException, Request

from api.boot import read_token
from scripts.daily.config import DATA_DIR  # 模块 attr = monkeypatch 缝, 仅函数内引用


def require_api_key(request: Request) -> str:
    """X-API-Key 门 (SEC-01/D-10): 缺失 401+挑战头, 错误 403, 成功返回 key 串。

    missing-header 路径直接 401, 不进入比较; expected 为 None (无 token 配置)
    或比较不等 -> 403。无任何 handler 消费返回值 (依赖只做门)。
    """
    provided = request.headers.get("X-API-Key")
    if provided is None:
        raise HTTPException(
            401, detail="missing API key", headers={"WWW-Authenticate": "ApiKey"}
        )
    expected = read_token(os.path.join(DATA_DIR, "api_token.txt"))  # 调用时解析
    if expected is None or not hmac.compare_digest(
        expected.encode(), provided.encode()
    ):
        raise HTTPException(403, detail="invalid API key")
    return provided
