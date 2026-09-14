"""只读状态透传 + 防御性读层 (STA-01/STA-03/HLT-02, D-01..D-05)。

GET /v1/state/{name}: 白名单三名的原始文件字节逐字节透传 (D-01/D-02),
  新鲜度用 X-Data-Mtime / X-Data-Age-S 头表达 (同一读句柄 fstat, D-01);
  未知名一律 404 (D-03/D-04), 已知名但缺失/不可读 -> 503 (D-04)。
GET /health/ready: stat/access 只查存在性与可读性, 不看数据新旧 (HLT-02)。

防御性读层 (STA-03/D-05): 每次请求 open('rb') -> read -> fstat -> close,
  字节过 json.loads 校验门 (只验证不重序列化); JSONDecodeError/UnicodeDecodeError
  短重试读新快照, OSError 立即回退不重试; 持续失败回退进程内末次成功缓存,
  以 200 + X-Data-Stale: true + 缓存的真实 mtime 服务 (体与头永远描述同一版本),
  冷缓存则 503 —— 绝不给裸 500, 绝不把撕裂文件当新鲜数据发出。

模块导入无副作用 (不打印、不做文件 I/O、不绑端口); 无任何网络能力导入 (SC4:
  只允许 import fastapi 与 scripts.daily.config —— 后者导入链仅 os/sys/platform)。
DATA_DIR 仅在函数内按调用时引用 (monkeypatch 缝, 同 api/main.py 惯例);
本模块不计算 BASE、不做 sys.path 操作; 控制台文本 (无) 保持 ASCII-only。
"""
import json
import os
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from scripts.daily.config import DATA_DIR  # D-02 路径纪律 (导入链 os/sys/platform)

# D-03 白名单 —— 固定三名显式映射, 未知名 404, 绝无动态路径解析 (无穿越面)。
STATE_FILES = {
    "market_state": "market_state.json",
    "auction_state": "auction_state.json",
    "zt_pool_state": "zt_pool_state.json",
}
_CACHE = {}  # name -> {"raw": bytes, "mtime": int}; 每名一槽, 进程内 (D-05)
router = APIRouter()


def read_state_file(path):
    """open('rb') -> read 全部 -> 同一句柄 fstat -> close; 返回 (raw, mtime)。

    json.loads 只是验证门: 校验通过即丢弃解析对象, 绝不重序列化 (D-01/D-02
    字节逐字契约)。二进制约定不可谈判 (文本模式在 Windows 会把 CRLF 翻成 LF)。
    内部不做 try/except —— 错误分类由调用方 (get_state) 负责。
    """
    with open(path, "rb") as f:
        raw = f.read()
        mtime = int(os.fstat(f.fileno()).st_mtime)  # 同一版本字节的真实 mtime
    json.loads(raw)  # validate only —— 解析结果丢弃, 永不回写
    return raw, mtime


class StateUnavailable(Exception):
    """文件缺失/不可读 且 无末次成功缓存条目 (冷缓存)。"""


def get_state(name, retries=2, retry_delay=0.02, reader=read_state_file):
    """STA-03 防御读层: 解码失败短重试新快照; 持续失败回退末次成功缓存。

    - 仅 (ValueError, UnicodeDecodeError) 重试 (JSONDecodeError 是其子类,
      UnicodeDecodeError 覆盖截断多字节字符); OSError 立即 break 不回退重试
      (缺失/不可读对单次请求是确定的, 重试只拖延 503)。
    - 每次尝试都是完整 open->read->fstat->close (句柄绝不跨 sleep 持有,
      Windows 上打开的读句柄会让管线的 os.replace 撞 WinError 5)。
    - reader 参数是可注入的单次读取器 (确定性单测缝), 默认即真实读取函数。
    """
    path = os.path.join(DATA_DIR, STATE_FILES[name])  # 调用时组合 (monkeypatch 缝)
    for attempt in range(retries + 1):
        try:
            raw, mtime = reader(path)
            _CACHE[name] = {"raw": raw, "mtime": mtime}
            return "fresh", raw, mtime
        except (ValueError, UnicodeDecodeError):
            if attempt < retries:
                time.sleep(retry_delay)  # 写者的截断窗口是 ms 级
        except OSError:
            break  # 缺失/不可读 -> 立即走回退/503
    entry = _CACHE.get(name)
    if entry is not None:
        return "stale", entry["raw"], entry["mtime"]
    raise StateUnavailable


@router.get("/v1/state/{name}")
def get_state_endpoint(name: str):
    """透传白名单状态文件 (D-01..D-05)。白名单查表先于任何路径组合 (D-03)。"""
    if name not in STATE_FILES:
        raise HTTPException(status_code=404, detail="unknown state name")  # D-04
    try:
        kind, raw, mtime = get_state(name)
    except StateUnavailable:
        raise HTTPException(status_code=503, detail="state temporarily unavailable")
    headers = {
        "X-Data-Mtime": str(mtime),                               # D-01 epoch 秒
        "X-Data-Age-S": str(max(0, int(time.time() - mtime))),    # D-01 非负, 截断钳 0
    }
    if kind == "stale":
        headers["X-Data-Stale"] = "true"  # D-05: 仅在回退路径出现
    # media_type 决定 content-type 恰为 application/json (无 charset, Pitfall 6);
    # 永不 FileResponse (句柄跨流式持有会挡管线 os.replace, Pitfall 2)。
    return Response(content=raw, media_type="application/json", headers=headers)


@router.get("/health/ready")
def ready():
    """就绪 (HLT-02): 只查三个白名单文件存在且可读 (stat/access), 绝不 open()。

    open() 探针本身会制造挡住 os.replace 的读句柄窗口 (Pitfall 2);
    数据新旧永不参与判断 —— 夜间/周末/假期的新旧数据不 503。
    """
    for filename in STATE_FILES.values():
        path = os.path.join(DATA_DIR, filename)
        try:
            if not os.path.isfile(path) or not os.access(path, os.R_OK):
                raise HTTPException(status_code=503, detail="state file unavailable")
        except OSError:
            raise HTTPException(status_code=503, detail="state file unavailable")
    return {"status": "ready"}
