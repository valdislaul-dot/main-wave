"""OPS-03 SC1 机密级健康详情端点 (05-01, D-29..D-31; SEC-02 分级表)。

GET /health/details —— 运维详情探针 (版本/uptime/最近检查), router 级
require_api_key 门 (与 private/actions/jobs 同一依赖对象身份, SC2 审计断言):

- versions: python 取 sys.version, uvicorn/fastapi 取 importlib.metadata.version
  (惰性读; PackageNotFoundError -> "unknown") —— 绝不硬编码版本串 (双机漂移容忍)。
- uptime_seconds: 复用 api/uptime.py uptime_seconds() —— 与 /health 同一 monotonic
  锚点 (模块级 import, 零依赖叶子模块无环形风险)。05-04 实机修复: `python -m
  api.main` 启动时 main.py 的文件身份是 __main__, 不会以 "api.main" 注册进
  sys.modules —— handler 内惰性 import api.main 会把整个 main.py 二次执行并重置
  锚点 (实机: details uptime 从 0 重计, 与 /health 分叉); 锚点移入 uptime.py 后
  该陷阱在结构上不可能 (详见 uptime.py 模块 docstring)。
- last_check.health_job: logs/api/jobs registry 中 kind == "health-check" 且
  status == "succeeded" 的最新 finished_at 的 ISO-8601 UTC; 无匹配 -> null。
  registry 经 api.jobs.jobs_dir()/read_job 只读 (单一事实源); 扫描镜像
  jobs.prune 的 OSError/ValueError 容错 —— 缺失/损坏文件绝不 5xx (T-05-03)。
- last_check.market_state_mtime: data/market_state.json 的 os.stat mtime ISO;
  缺失/不可 stat -> null (与 health_job 对称 —— 详情探针诚实回答数据缺席,
  绝不把缺失状态打成 5xx 掩盖自身要报告的条件)。

零参数面 (无 query/body —— 无攻击者可控输入进 handler); 纯读 handler:
零写、零 spawn、零 registry 变更、零网络 (SC4: import 链仅 stdlib + fastapi +
api.* + scripts.daily.config)。模块导入零副作用、无控制台输出。
DATA_DIR 仅在函数内按调用时引用 (monkeypatch 缝, 同 api/state.py:66 惯例);
registry 目录不持有本模块 LOG_DIR 副本 —— 一律经 jobs.jobs_dir() (单一事实源)。
"""
import importlib.metadata
import os
import sys
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from api import jobs  # registry 只读 (jobs_dir/read_job); import 无副作用 (jobs.py:12-14)
from api.auth import require_api_key  # D-10 同一依赖对象 (router 级, 永不中间件)
from api.uptime import uptime_seconds  # D-30 单一锚点 (05-04 双身份修复; 叶子模块零环形)
from scripts.daily.config import DATA_DIR  # 调用时组合 (monkeypatch 缝)

router = APIRouter(dependencies=[Depends(require_api_key)])  # SEC-02 机密级


def _version(dist):
    """importlib.metadata.version 单发行版读取: 缺失发行版 -> "unknown" (D-30)。"""
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _versions():
    """活环境版本 (D-30): python 取 sys.version, 两个发行版惰性读 —— 绝不硬编码。"""
    return {
        "python": sys.version,
        "uvicorn": _version("uvicorn"),
        "fastapi": _version("fastapi"),
    }


def _iso(value):
    """epoch -> ISO-8601 UTC 字符串 (D-29: datetime.fromtimestamp().isoformat())。"""
    return datetime.fromtimestamp(value, timezone.utc).isoformat()


def _latest_succeeded_health_check():
    """registry 扫描: kind == "health-check" 且 status == "succeeded" 的最大 finished_at job。

    容错镜像 jobs.prune (jobs.py:227-245): listdir OSError -> None (null, 绝不 5xx);
    逐文件 (OSError, ValueError) -> 跳过 (read_job 对损坏 JSON 上抛 ValueError);
    finished_at 非 int (畸形文件) -> 跳过 —— 扫描永不被外来字节打成 5xx (T-05-03)。
    """
    base = jobs.jobs_dir()
    try:
        names = os.listdir(base)
    except OSError:
        return None  # 目录缺失/不可列 -> null (prune 同形)
    best = None
    best_finished = None
    for name in names:
        if not name.endswith(".json") or name.startswith("."):
            continue
        stem = name[: -len(".json")]
        try:
            job = jobs.read_job(stem, base)
        except (OSError, ValueError):
            continue  # 撕裂/损坏 -> 跳过 (prune 同形)
        if job is None:
            continue
        if job.get("kind") != "health-check" or job.get("status") != "succeeded":
            continue
        finished = job.get("finished_at")
        if not isinstance(finished, int) or isinstance(finished, bool):
            continue  # 畸形 finished_at (如字符串) 不参与比较 —— TypeError 防护
        if best_finished is None or finished > best_finished:
            best, best_finished = job, finished
    return best


@router.get("/health/details")
def health_details():
    """健康详情 (OPS-03 SC1/D-29..D-31): 机密级, 纯读, 零参数面。

    200 体 = {"versions", "uptime_seconds", "last_check"}; 数据缺席以 null 诚实回答,
    永不以 5xx 掩盖 (缺失的 state 文件正是本端点要报告的条件之一)。
    """
    job = _latest_succeeded_health_check()
    try:
        market_mtime = os.stat(os.path.join(DATA_DIR, "market_state.json")).st_mtime
    except OSError:
        market_mtime = None  # 缺失/不可 stat -> null (与 health_job 对称)
    return {
        "versions": _versions(),
        "uptime_seconds": uptime_seconds(),
        "last_check": {
            "health_job": _iso(job["finished_at"]) if job is not None else None,
            "market_state_mtime": _iso(market_mtime) if market_mtime is not None else None,
        },
    }
