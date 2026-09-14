"""受保护触发/job HTTP 面 (ACT-01/02/03 + SEC-01; D-07..D-11; RESEARCH Pattern 5)。

router 级依赖 require_api_key: 本路由全部 POST /v1/actions/* 与
GET /v1/jobs/* 一律要 X-API-Key (D-10/D-11 豁免清单之外的一切); /health 族与
/v1/state 在公开路由上, 结构豁免 —— 无中间件、无 app 级依赖。

- ACT-01 (D-09): KIND_CMDS 固定四命令白名单 (唯一事实源)。kind 查表,
  未知名 404 且不产生任何 lock/claim/spawn 副作用; 请求体永不解析/回显/
  记录 (零参数面); 命令由 _cmd_for 纯参数表构造 [sys.executable, 脚本,
  *固定参数], shell=False 结构上成立, 用户输入到不了 argv。
- SC4 (D-26..D-28, 04-04): pipeline/morning-check 接受可选 ?date= 查询参数
  (YYYY-MM-DD / YYYYMMDD 白名单, 请求体仍零参数)。门序 (每道先于任何副作用):
  ① kind 白名单 404 -> ② date 格式/历法校验 (date_args.parse_date, 非法 422
  invalid_date_format) -> ③ date 能力检查 (仅 pipeline/morning-check, 其余
  kind 带 date -> 422 date_not_supported) -> ④ 构造命令: 解析后归一化的
  单 token --date=YYYY-MM-DD 附加在固定参数之后 (D-28 字面形态; 值来自 date
  对象而非原始查询串, 注入结构性不可能, T-04-13)。校验单源在
  scripts/daily/date_args.py —— 本模块不手写任何重复正则 (T-04-15)。
- ACT-02: POST 立即 202 {job_id, kind, status}; GET /v1/jobs/{job_id} 读
  registry (03-01 api/jobs.py), 轮询 pending->running->succeeded/failed 并
  暴露 log_path; job_id 过 ^[0-9a-f]{32}$ 门后才组合路径 (越界形状一律
  404 job not found, 零文件访问); 不可读/损坏文件 -> 503 job temporarily
  unavailable (read_job 的 OSError/ValueError 分类归本层)。
- ACT-03: 先取 OS 单飞锁 (scripts/daily/job_lock.acquire), 拿不到时按内存
  claim 区分 409 两种对象形状 (Open-question 1 裁定, RESEARCH Example 1
  claim order): claim 命中 -> {"message": "<kind> already running",
  "running_job_id": <id>}; 仅 OS 锁被占 (GUI/手动入口, 无 job_id 可报) ->
  {"message": "<kind> already running (another entry point)"}。

模块导入零副作用 (不起线程/不建目录/不打印); 控制台文本 ASCII-only。
"""
import os
import re
import sys

from fastapi import APIRouter, Depends, HTTPException

from api import jobs
from api.auth import require_api_key
from scripts.daily import date_args, job_lock
from scripts.daily.config import PROJECT_ROOT

# 依赖声明在 router 层: 公开路由 (/health 族、/v1/state) 结构上豁免 (D-11)
router = APIRouter(dependencies=[Depends(require_api_key)])

# 脚本目录根 (PROJECT_ROOT/scripts; 调用时读取 —— monkeypatch 缝, 测试把
# SCRIPTS_DIR 指到 tmp 假脚本树, KIND_CMDS 与参数原样流通)
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")

# D-09 固定命令表 (verbatim): kind -> (脚本名, 固定参数元组)。唯一事实源。
KIND_CMDS = {
    "pipeline": ("run_pipeline.py", ("--fast",)),
    "morning-check": ("morning_check.py", ("--quick",)),
    "backtest-weights": ("backtest_v4.py", ()),
    "health-check": ("data_health_check.py", ()),
}


def _cmd_for(kind, extra_args=()):
    """构造 [sys.executable, <SCRIPTS_DIR>/daily/<script>, *固定参数, *额外参数] (arg-list)。

    参数只来自 KIND_CMDS 常量表 + 调用方显式传入的额外参数元组 (SC4: 仅
    date 门校验通过后由解析出的 date 对象构造的归一化 token, 附加在固定参数
    之后 —— D-28); 请求数据结构上无法进入 argv (D-09, T-03-10 缓解);
    shell=False 由 arg-list 形态保证。
    """
    script, args = KIND_CMDS[kind]
    return [sys.executable, os.path.join(SCRIPTS_DIR, "daily", script), *args, *extra_args]


@router.post("/v1/actions/{kind}", status_code=202)
def trigger_action(kind: str, date: str = None):
    """触发一种固定动作: 202 {job_id, kind, status} 立即返回 (ACT-02 SC1)。

    白名单查表先于一切副作用 (404 无 lock/claim/spawn); OS 锁先于内存 claim
    (RESEARCH Pattern 1 claim order) —— 锁被占时按 claim 区分 409 两种形状。

    SC4 门序 (date 非 None 时, 每道先于任何副作用; 422/404 绝不 spawn):
    ① kind 白名单 404 (date 永不先于 kind 门被咨询);
    ② date 格式/历法校验 -> 非法 422 invalid_date_format (date_args 单源);
    ③ date 能力门: 仅 pipeline/morning-check 接受 date, 其余 kind 422
       date_not_supported (零参数 kind 固定命令不变);
    ④ _cmd_for 把归一化单 token 附加在固定参数尾部 (D-28 字面形态)。
    """
    entry = KIND_CMDS.get(kind)
    if entry is None:
        raise HTTPException(404, detail="unknown action kind")  # T-03-10 门
    if date is not None:
        try:
            parsed = date_args.parse_date(date)  # 单源校验 (T-04-15)
        except ValueError:
            raise HTTPException(422, detail="date must be YYYY-MM-DD or YYYYMMDD")
        if kind not in ("pipeline", "morning-check"):
            raise HTTPException(422, detail="date not supported for this action kind")
        # token 由解析出的 date 对象构造 (归一化 dashed), 绝不来自原始查询串
        cmd = _cmd_for(kind, extra_args=(f"--date={parsed:%Y-%m-%d}",))
    else:
        cmd = _cmd_for(kind)  # 无 date: Phase 3 字节原样路径
    fd = job_lock.acquire(kind, jobs.locks_dir())
    if fd is None:  # 单飞锁被占 (ACT-03): API 自己的 claim 还是外部入口?
        running = jobs.is_running(kind)
        if running is not None:
            raise HTTPException(
                409,
                detail={
                    "message": f"{kind} already running",
                    "running_job_id": running["job_id"],
                },
            )
        raise HTTPException(
            409,
            detail={"message": f"{kind} already running (another entry point)"},
        )
    # WR-05 (04 修复): start_job 内 claim 落盘失败 (write_job OSError, 磁盘满/权限)
    # 或 Thread.start 失败会向上抛 —— 已持有的 OS 锁 fd 必须关, 否则 kind 永久假占用
    # (后续触发恒 409 already_running_other_entry, 无 registry 条目可查)。worker 侧
    # run_job 的 finally 无条件关锁 (api/jobs.py L165-168), 本侧异常路径补同一纪律。
    try:
        job = jobs.start_job(kind, cmd, fd)  # 202 语义: claim 落盘后才起 worker
    except Exception:
        try:
            fd.close()
        except OSError:
            pass
        raise
    return {"job_id": job["job_id"], "kind": job["kind"], "status": job["status"]}


@router.get("/v1/jobs/{job_id}")
def get_job(job_id: str):
    """读 job registry (ACT-02): 200 全记录 / 404 缺失 / 503 不可读。

    job_id 正则门先于任何路径组合 (T-03-11): 越界/穿越形状一律 404 job not
    found, 零文件访问; read_job 的 OSError (瞬时 replace 碰撞/不可读) 与
    ValueError (损坏 JSON) -> 503 job temporarily unavailable, 绝不给裸 500。
    """
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise HTTPException(404, detail="job not found")
    try:
        job = jobs.read_job(job_id)
    except (OSError, ValueError):
        raise HTTPException(503, detail="job temporarily unavailable")
    if job is None:
        raise HTTPException(404, detail="job not found")
    return job  # 200: 全记录 (status/exit_code/log_path/cmd/时间戳)
