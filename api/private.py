"""机密级私密读端点 (STA-02/SEC-02, D-13..D-16; 04-CONTEXT 敏感端点形态)。

GET /v1/private/{name}: 持仓/账本/候选的 token 门控读 —— router 级 require_api_key
依赖 (与 actions/jobs 同门, D-10/D-11), 独立 /v1/private/* 命名空间与公开
/v1/state/* 结构性隔离 (D-13): 鉴权配置失误不可能让敏感数据滑入公开树。

- 200 = 文件原始字节逐字透传 (D-01 raw passthrough 与 state 面同一契约:
  不 json.loads 重序列化、不用 FileResponse —— 持句柄跨流式持有会挡管线
  os.replace, Windows Pitfall 2); media_type application/json (无 charset);
  新鲜度用 X-Data-Mtime / X-Data-Age-S 头 (同一读句柄 fstat, D-01), 回退路径
  加 X-Data-Stale: true (D-05, 体与头永远描述同一版本)。
- 白名单 gate 先于一切路径组合 (D-03/D-04): 未知名 -> 404 unknown private name;
  ?date= 白名单格式 (YYYY-MM-DD | YYYYMMDD) + 月/日语义门 -> 非法 422
  date must be YYYY-MM-DD or YYYYMMDD; 缺失/不可读 -> 503 private data
  temporarily unavailable (冷缓存), 撕裂 -> 短重试 -> stale 回退 —— 全说
  04-01 冻结信封码, 绝不给裸 500; 错误体永不含路径 (SC3)。
- candidates 语义 (D-14): 无 ?date= -> logs/ 最新 candidates_*.json (排除
  candidates_v* 旧格式; 镜像 morning_check.py:11-18 选择规则 —— 只镜像规则,
  文件字节仍走 read_state_file, API 不改脚本逻辑); ?date= -> 精确日期文件
  (YYYYMMDD 归一化为 dashed 后再拼文件名)。?date= 对固定文件 (portfolio/
  journal) 不适用即忽略 —— 参数仅 candidates 语义。
- 读层 = api/state.py get_state 的文档化孪生 (同重试/缓存/回退语义, 目标
  LOG_DIR; _CACHE 槽按 (name[, date]) 键控, 独立于 api.state._CACHE)。
  state.py 签名核心 (D-01..D-05) 绝不重构为接受目录参数 (04-PATTERNS
  discretion —— 读侧孪生重复的风险低于触碰签名模块)。

模块导入无副作用 (不打印、不做文件 I/O、不绑端口); 无任何网络能力导入 (SC4:
只允许 import fastapi 与 scripts.daily.config —— 后者导入链仅 os/sys/platform);
LOG_DIR 仅在函数内按调用时引用 (monkeypatch 缝, 同 api/state.py:66 惯例);
不计算 BASE、不做 sys.path 操作; 控制台文本 (无) 保持 ASCII-only。
"""
import os
import re
import time

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from api.auth import require_api_key  # D-10 同一依赖对象 (router 级, 永不中间件)
from api.state import StateUnavailable, read_state_file  # 复用读层原语 (路径参数化)
from scripts.daily.config import LOG_DIR  # D-02 路径纪律 (导入链 os/sys/platform)

# D-03 白名单 —— 固定显式映射 + candidates 动态规则 (下方函数); 未知名 404,
# 绝无动态路径解析 (无穿越面)。candidates 文件名按日期变化, 不在此静态映射。
PRIVATE_FILES = {
    "portfolio": "portfolio.json",
    "journal": "trading_journal.json",
}

# D-14 白名单日期格式: YYYY-MM-DD | YYYYMMDD (fullmatch)。"2026-13-99" 形状过
# 正则但月/日语义越界 —— _valid_date 单独做语义区间门, 越界一律 422 (SC4)。
_DATE_RE = re.compile(r"^(?:\d{4}-\d{2}-\d{2}|\d{8})$")

_CACHE = {}  # (name[, date]) -> {"raw": bytes, "mtime": int}; 进程内 (D-05)
router = APIRouter(dependencies=[Depends(require_api_key)])  # SEC-02 机密级命名空间


def _valid_date(text):
    """白名单日期门: 格式 fullmatch + 月/日语义区间 (两种格式统一检查)。

    越界形状 (13 月 / 99 日 / 2026/09/01 / 2026091 / abc) -> False -> 端点 422,
    绝不进入文件名组合 (whitelist-before-compose, D-03)。
    """
    if not _DATE_RE.fullmatch(text):
        return False
    if "-" in text:
        parts = text.split("-")
    else:
        parts = (text[:4], text[4:6], text[6:])
    month, day = int(parts[1]), int(parts[2])
    return 1 <= month <= 12 and 1 <= day <= 31


def _normalize_date(text):
    """YYYYMMDD -> YYYY-MM-DD (dashed 原样返回)。调用前提: 已过 _valid_date 门。"""
    if "-" in text:
        return text
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _resolve_filename(name, date):
    """白名单 gate 之后的文件名解析: 固定映射查表 / candidates 动态规则 (D-14)。

    调用前提: name 已确认白名单、date 已过格式门 (端点在调用前完成) —— 本函数
    永不接触未验证输入; date 仅 candidates 语义, 固定文件忽略该参数。
    """
    if name in PRIVATE_FILES:
        return PRIVATE_FILES[name]
    if date is None:
        return _latest_candidates_file()
    return f"candidates_{date}.json"  # date 已归一化为 YYYY-MM-DD


def _latest_candidates_file():
    """logs/ 下最新 candidates_*.json 的文件名 (排除 candidates_v* 旧格式)。

    镜像仓库内选择规则 (morning_check.py:11-18 / auction_pool.py:48-52:
    startswith 'candidates_' 且非 'candidates_v', 按文件名日期部分排序取最新)。
    无匹配文件 -> FileNotFoundError (与文件缺失同语义, 由 get_private 走回退/
    503); listdir 的 OSError 同样上抛由 get_private 消化 —— 文件名组合绝不
    发生在白名单 gate 之前。
    """
    files = [
        f for f in os.listdir(LOG_DIR)
        if f.startswith("candidates_") and not f.startswith("candidates_v")
    ]
    if not files:
        raise FileNotFoundError(os.path.join(LOG_DIR, "candidates_*.json"))
    files.sort(key=lambda f: f.split("_")[1].replace(".json", ""))
    return files[-1]


def get_private(name, date=None, retries=2, retry_delay=0.02, reader=read_state_file):
    """STA-03 防御读层的 private 孪生 (api/state.py get_state 形状, 目标 LOG_DIR)。

    - 与 get_state 相同语义: 仅 (ValueError, UnicodeDecodeError) 短重试
      (JSONDecodeError 是其子类, UnicodeDecodeError 覆盖截断多字节字符);
      OSError 立即 break 不回退重试 (缺失/不可读对单次请求是确定的)。
    - 每次尝试都是完整 open->read->fstat->close (句柄绝不跨 sleep 持有,
      Windows 上打开的读句柄会让写者的 os.replace 撞 WinError 5)。
    - 持续失败回退 (name, date) 槽的末次成功缓存 (体 == 缓存字节, mtime ==
      缓存 mtime —— 体与头永不分裂版本); 冷缓存 -> StateUnavailable (端点转 503)。
    - 本函数是 state.py 签名核心 (D-01..D-05) 的文档化孪生 —— 核心绝不重构
      成接受目录参数; 缓存槽键 (name, date) (date=None 即最新无参槽; 固定文件
      恒用 (name, None) 槽 —— ?date= 对固定文件不适用即忽略)。
    - reader 参数是可注入的单次读取器 (确定性单测缝), 默认即真实读取函数。
    - date 参数约定: 仅 candidates 参与文件名解析, 且调用前已过白名单门并
      归一化为 YYYY-MM-DD (端点负责; 直呼本函数的单测按此约定传参)。
    """
    key = (name, date) if name == "candidates" else (name, None)
    try:
        filename = _resolve_filename(name, date)
    except OSError:
        filename = None  # logs/ 缺失/不可列/无 candidates 文件 -> 与文件缺失同语义
    if filename is None:
        entry = _CACHE.get(key)
        if entry is not None:
            return "stale", entry["raw"], entry["mtime"]
        raise StateUnavailable
    path = os.path.join(LOG_DIR, filename)  # 调用时组合 (monkeypatch 缝)
    for attempt in range(retries + 1):
        try:
            raw, mtime = reader(path)
            _CACHE[key] = {"raw": raw, "mtime": mtime}
            return "fresh", raw, mtime
        except (ValueError, UnicodeDecodeError):
            if attempt < retries:
                time.sleep(retry_delay)  # 写者的截断窗口是 ms 级
        except OSError:
            break  # 缺失/不可读 -> 立即走回退/503
    entry = _CACHE.get(key)
    if entry is not None:
        return "stale", entry["raw"], entry["mtime"]
    raise StateUnavailable


@router.get("/v1/private/{name}")
def get_private_endpoint(name: str, date: str = None):
    """Token 门控透传私密文件 (STA-02/SEC-02)。白名单 gate 先于一切路径组合 (D-03)。

    顺序: 未知名 404 -> 日期格式门 422 -> 读层 (缺失/撕裂 -> stale/503) ->
    原始字节 + X-Data-* 头。date 仅 candidates 语义 (固定文件忽略该参数);
    合法 ?date= 打 portfolio/journal 返回其固定文件。
    """
    if name not in PRIVATE_FILES and name != "candidates":
        raise HTTPException(status_code=404, detail="unknown private name")  # D-04
    if date is not None:
        if not _valid_date(date):
            raise HTTPException(
                status_code=422, detail="date must be YYYY-MM-DD or YYYYMMDD"
            )  # D-09/SC4 (04-01 冻结文本)
        date = _normalize_date(date)
    try:
        kind, raw, mtime = get_private(name, date)
    except StateUnavailable:
        raise HTTPException(status_code=503, detail="private data temporarily unavailable")
    headers = {
        "X-Data-Mtime": str(mtime),                               # D-01 epoch 秒
        "X-Data-Age-S": str(max(0, int(time.time() - mtime))),    # D-01 非负, 截断钳 0
    }
    if kind == "stale":
        headers["X-Data-Stale"] = "true"  # D-05: 仅在回退路径出现
    # media_type 决定 content-type 恰为 application/json (无 charset, Pitfall 6);
    # 永不 FileResponse (句柄跨流式持有会挡管线 os.replace, Pitfall 2)。
    return Response(content=raw, media_type="application/json", headers=headers)
