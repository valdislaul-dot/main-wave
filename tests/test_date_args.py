"""04-04 date_args 单源校验矩阵 + 脚本会话日期门 subprocess 钉 (SC4, D-26..D-28)。

parse_date/resolve_date_arg/format_token —— 白名单格式 + 真历法校验、argv
两种形态解析与歧义拒绝、规范 token 形态、import 纯度 (零副作用: 无 config
import、导入不打印/不建文件)。所有校验单源在 scripts/daily/date_args.py,
任何调用方不得手写重复正则 (T-04-15)。

Task 3 (T-04-14): run_pipeline.py / morning_check.py 的真实拒绝路径 ——
非会话日期 (过去日期/非法值) 经 --date token 传入时, 子进程 exit 2、
stderr ASCII 拒绝消息含 "session date"、零 traceback、data/ 与 logs/ 零写。
只钉过去日期与非法值, 绝不 spawn 今日日期 (会跑实盘流水线/采集)。
"""
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest


# ---------- Task 2 行为 1: parse_date 双格式 + 真历法 ----------

def test_parse_date_accepts_both_whitelist_formats():
    from scripts.daily.date_args import parse_date
    assert parse_date("2026-09-03") == date(2026, 9, 3)
    assert parse_date("20260903") == date(2026, 9, 3)


def test_parse_date_rejects_bad_format_and_calendar():
    from scripts.daily.date_args import parse_date
    for bad in ("2026/09/03", "2026093", "abc", "2026-13-99", "2026-02-30", ""):
        with pytest.raises(ValueError, match=r"YYYY-MM-DD or YYYYMMDD"):
            parse_date(bad)


# ---------- Task 2 行为 2: resolve_date_arg argv 解析 ----------

def test_resolve_date_arg_absent_returns_none():
    from scripts.daily.date_args import resolve_date_arg
    assert resolve_date_arg(["run_pipeline.py", "--fast"]) is None
    assert resolve_date_arg(["morning_check.py", "--quick"]) is None


def test_resolve_date_arg_equals_and_space_forms():
    from scripts.daily.date_args import resolve_date_arg
    # API 附加的字面单 token 形态 (D-28): --date=YYYY-MM-DD
    assert resolve_date_arg(["x.py", "--fast", "--date=2026-09-03"]) == date(2026, 9, 3)
    # 手动 CLI 空格形态 (data_health_check.py:102-110 in-repo 惯例): --date YYYYMMDD
    assert resolve_date_arg(["x.py", "--quick", "--date", "20260903"]) == date(2026, 9, 3)


def test_resolve_date_arg_ambiguity_and_empty_rejected():
    from scripts.daily.date_args import resolve_date_arg
    # 两种形态同时出现 -> 歧义拒绝
    with pytest.raises(ValueError):
        resolve_date_arg(["x.py", "--fast", "--date=2026-09-03", "--date", "20260903"])
    # 两个 --date token -> 首匹配歧义拒绝
    with pytest.raises(ValueError):
        resolve_date_arg(["x.py", "--date=2026-09-03", "--date=2026-09-04"])
    with pytest.raises(ValueError):
        resolve_date_arg(["x.py", "--date", "2026-09-03", "--date", "2026-09-04"])
    # 空值 ("--date=") -> 解析失败
    with pytest.raises(ValueError):
        resolve_date_arg(["x.py", "--date="])


# ---------- Task 2 行为 3: format_token 规范形态 ----------

def test_format_token_canonical_shape():
    from scripts.daily.date_args import format_token
    assert format_token(date(2026, 9, 3)) == "--date=2026-09-03"
    assert format_token(date(2026, 12, 31)) == "--date=2026-12-31"


# ---------- Task 2 行为 4: import 纯度 (零副作用) ----------

def test_import_purity_no_side_effects(capsys):
    """导入 date_args 只拉自己的命名空间链 (不碰 config 等副作用模块)、不打印。

    防止后续编辑加入 config import / import 期 print (T-04-15 单源纯度钉)。
    测量 sys.modules 增量而非绝对状态: 全套件先跑时 config 可能已被他文件
    合法导入, 绝对断言会误报 —— 只断言 date_args 导入本身没新增任何
    scripts.* 模块 (命名空间父包 scripts/scripts.daily 除外)。
    """
    sys.modules.pop("scripts.daily.date_args", None)  # 强制从磁盘重新导入
    before = set(sys.modules)
    import scripts.daily.date_args  # noqa: F401
    added = set(sys.modules) - before
    # 命名空间父包 (scripts/scripts.daily 无 __init__.py) 随子模块导入而缓存,
    # 属正常; 除此之外任何 scripts.* 增量 (如 scripts.daily.config) 即违规
    extra = {
        m for m in added
        if m.startswith("scripts.")
        and m not in ("scripts", "scripts.daily", "scripts.daily.date_args")
    }
    assert not extra, f"date_args 导入拉入了额外 scripts 模块: {sorted(extra)}"
    assert "scripts.daily.config" not in added  # config 有 os.makedirs 副作用
    out, err = capsys.readouterr()
    assert out == "" and err == ""  # 导入期零输出
    # 导入后公共面齐备 (Task 2 GREEN 后断言; 缺 resolve/format 时下方 ImportError)
    from scripts.daily.date_args import DATE_RE, format_token, parse_date, resolve_date_arg
    assert DATE_RE.fullmatch("2026-09-03") and DATE_RE.fullmatch("20260903")


# ---------- Task 3: 脚本侧会话日期门拒绝路径 (真实子进程, T-04-14) ----------
# 只 spawn 过去日期/非法值 —— 子进程无 conftest 网络猴补丁, 今日日期会跑
# 实盘流水线/竞价采集, 绝对禁止出现在本段。

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DAILY = REPO_ROOT / "scripts" / "daily"


def _git_porcelain():
    """data/ 与 logs/ 的 git 可见变更行 (拒绝路径零写 = spawn 前后 diff 钉)。

    WR-01 (04 修复): 每交易日晨跑 (morning_check 9:25-9:35) 会留下已跟踪
    data/auction_state.json 改动与未跟踪 data/auction/YYYY-MM-DD.json ——
    绝对干净的前置断言 (原 _git_data_logs_clean) 在未推送日恒红, 把 4 个
    spawn 钉乃至整套件带红。改为返回 porcelain 文本, 由测试比对 spawn
    前后相等: 起点脏不脏无所谓, 拒绝路径零新增变更即通过 (repo 常态绿)。
    """
    out = subprocess.run(
        ["git", "status", "--porcelain", "--", "data/", "logs/"],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=30,
    )
    assert out.returncode == 0, f"git status failed: {out.stderr!r}"
    return out.stdout.strip()


def _spawn_refusal(script, argv_extra):
    """spawn 真实脚本 + 拒绝态 argv; 返回 subprocess.CompletedProcess。"""
    return subprocess.run(
        [sys.executable, str(SCRIPTS_DAILY / script), *argv_extra],
        capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=90,
        encoding="utf-8", errors="replace",
    )


@pytest.mark.parametrize("script,flag", [
    ("run_pipeline.py", "--fast"),
    ("morning_check.py", "--quick"),
])
def test_real_script_refuses_past_session_date_exit2(script, flag):
    """过去会话日期 -> exit 2 + ASCII 拒绝 (含 "session date") + 零 traceback。

    消息必须在 stderr (stdout 零污染: 拒绝发生在任何 banner/采集之前)。
    WR-01 (04 修复): 零写证据改为 spawn 前后 porcelain diff —— 晨跑留下的
    data/ 改动是 repo 常态, 不要求绝对干净起点, 只钉拒绝路径零新增变更。
    """
    before = _git_porcelain()
    proc = _spawn_refusal(script, [flag, "--date=2026-01-01"])
    assert proc.returncode == 2, f"{script} rc={proc.returncode}: {proc.stdout!r}"
    assert proc.stdout == "", f"{script} stdout 应有零输出, 得: {proc.stdout!r}"
    assert "session date" in proc.stderr, f"{script} stderr: {proc.stderr!r}"
    assert "Traceback" not in proc.stderr and "Traceback" not in proc.stdout
    after = _git_porcelain()
    assert after == before, (f"{script} 拒绝路径不得改 data/ 或 logs/ "
                             f"(before={before!r}, after={after!r})")


@pytest.mark.parametrize("script,flag", [
    ("run_pipeline.py", "--fast"),
    ("morning_check.py", "--quick"),
])
def test_real_script_refuses_invalid_date_exit2(script, flag):
    """非法 --date 值 -> 同一 exit-2 拒绝路径 (parse 阶段, 先于会话比较)。

    WR-01 (04 修复): 零写证据 = spawn 前后 porcelain diff (见上)。
    """
    before = _git_porcelain()
    proc = _spawn_refusal(script, [flag, "--date=not-a-date"])
    assert proc.returncode == 2, f"{script} rc={proc.returncode}: {proc.stdout!r}"
    assert "session date" in proc.stderr, f"{script} stderr: {proc.stderr!r}"
    assert "Traceback" not in proc.stderr
    after = _git_porcelain()
    assert after == before, (f"{script} 拒绝路径不得改 data/ 或 logs/ "
                             f"(before={before!r}, after={after!r})")
