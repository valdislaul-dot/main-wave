"""统一机器可读错误信封: 冻结 code 表 + 三个 app 级异常处理器 (04-01, 04-CONTEXT 硬化清单)。

每个 4xx/5xx 响应体形如 {"detail": <原文或统一 404 copy>, "code": <冻结机器码>},
键序恒为 detail 先于 code —— 消费者按 code 分支, 绝不解析散文 (04-CONTEXT
机器可读错误码 + P2 UI-review #1)。

- 404 文案 API 全域单一定稿 "Not Found" (P2 UI-review #2): 语义差由 per-site
  code 携带; 非 404 detail 字节原样透传 (D-04/D-05 既有 wire 契约不变)。
- CODE_BY_DETAIL 冻结且完整: 本阶段全部 raise-site 文本 (含 04-03/04-04 私有
  端点与日期参数文本) 今日入表, 后续计划绝不追加行 —— 表外文本回退 http_{status}
  (T-04-04: 任何新 raise 文本也产出良构体)。
- traceback 只进服务端 stderr (SC3); 错误体永不含路径/token/异常内部 (D-04)。
- 本模块零 import 副作用 (Pitfall 3): 纯查表 + JSONResponse 构造。

分发语义 (starlette 0.46.2 实测): fastapi.HTTPException 是 starlette HTTPException
的子类 —— 注册在 starlette.exceptions.HTTPException 键上的 handler 经 ExceptionMiddleware
的 MRO 上溯命中 raise-site 与框架两类 (route-miss 404 / method 405); Exception 键由
build_middleware_stack 路由到 ServerErrorMiddleware (500 由它发出, 并 re-raise 供
服务端记日志 —— 真机 uvicorn 吞掉 re-raise, 客户端拿到信封体)。
"""
import sys
import traceback

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# 冻结 code 表: 本阶段每个 raise-site 文本一行 (key = detail 原文 byte 精确匹配)。
# 行序按状态码族分块; 追加行被冻结规则禁止 —— 表外文本走 http_{status} 回退。
CODE_BY_DETAIL = {
    # 401/403 (api/auth.py raise sites; 非 404 类 detail 原样透传 + code 兄弟键)
    "missing API key": "missing_api_key",
    "invalid API key": "invalid_api_key",
    # 404-origin 文本: 在 copy 统一为 "Not Found" 之前查表, 语义差进 code
    "unknown state name": "unknown_state_name",
    "unknown action kind": "unknown_action_kind",
    "job not found": "job_not_found",
    "unknown private name": "unknown_private_name",  # 04-03 raise 文本, 今日入表冻结
    "Not Found": "not_found",  # 框架 route-miss 原文本 (恰等于统一 copy —— 仅此一行命中)
    # 405: 框架 method-miss 的 detail 原样透传 (只统一 404 copy), 行须在表内而非回退
    "Method Not Allowed": "method_not_allowed",
    # 503 族
    "state temporarily unavailable": "state_temporarily_unavailable",
    "state file unavailable": "state_file_unavailable",
    "private data temporarily unavailable": "private_data_unavailable",  # 04-03 文本, 冻结
    "job temporarily unavailable": "job_temporarily_unavailable",
    # 400 日期参数族 (04-03/04-04 raise 文本, 今日入表冻结)
    "date must be YYYY-MM-DD or YYYYMMDD": "invalid_date_format",
    "date not supported for this action kind": "date_not_supported",
}

# 409 双形态按形状分键 (kind 名随动作变化, 不能文本键): 内存 claim 命中带
# running_job_id -> already_running; OS 锁独占 (另一入口) 不带 -> already_running_other_entry。
# 两形 detail dict 均含 "message" 键 (api/actions.py raise sites, 字节不变)。


def _code_for(status: int, detail: object) -> str:
    """查冻结表: str 文本查 CODE_BY_DETAIL; 409 形状查 message/running_job_id; 余下 http_{status}。

    永不 raise, 永不把 detail 内部细节带进 code 之外的位置。
    """
    if isinstance(detail, str):
        return CODE_BY_DETAIL.get(detail, f"http_{status}")
    if isinstance(detail, dict) and "message" in detail:
        if "running_job_id" in detail:
            return "already_running"
        return "already_running_other_entry"
    return f"http_{status}"


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """HTTPException 统一信封: 404 copy 单一定稿, 其余 detail 原样 + code 兄弟键。

    MRO 分发使本处理器同时覆盖 raise-site 的 fastapi.HTTPException 与框架
    route-miss 404 / method-miss 405 (starlette HTTPException)。
    """
    original_detail = exc.detail
    code = _code_for(exc.status_code, original_detail)
    if exc.status_code == 404 and isinstance(original_detail, str):
        body_detail = "Not Found"  # 全域单一 404 copy (P2 UI-review #2)
    else:
        body_detail = original_detail
    content = {"detail": body_detail, "code": code}  # 键序钉死: detail 先于 code
    return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)


async def validation_error_handler(request: Request, exc: RequestValidationError):
    """框架 RequestValidationError -> 422 信封; detail 列表按 starlette 渲染透传。"""
    return JSONResponse(
        status_code=422,
        content={"detail": jsonable_encoder(exc.errors()), "code": "validation_error"},
    )


async def unhandled_exception_handler(request: Request, exc: Exception):
    """未处理异常 -> 500 固定信封; traceback 只进服务端 stderr (SC3, D-04)。

    console 输出 ASCII-only (Pitfall 5); 不打印请求头/路径/token; body 固定文案,
    永不含异常内部。ServerErrorMiddleware 发出本响应后会 re-raise 供服务器记日志。
    """
    print("[gogo-api] unhandled exception -> 500 (traceback follows)", file=sys.stderr)
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": "internal server error", "code": "internal_error"},
    )
