"""04-04 date_args 单源校验矩阵 (SC4, D-26..D-28; 04-CONTEXT 触发 date 参数面)。

parse_date/resolve_date_arg/format_token —— 白名单格式 + 真历法校验、argv
两种形态解析与歧义拒绝、规范 token 形态、import 纯度 (零副作用: 无 config
import、导入不打印/不建文件)。所有校验单源在 scripts/daily/date_args.py,
任何调用方不得手写重复正则 (T-04-15)。
"""
import sys
from datetime import date

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
    """导入 date_args 不拉 config (已知副作用模块)、不打印、不产生文件副作用。

    防止后续编辑加入 config import / import 期 print (T-04-15 单源纯度钉)。
    """
    sys.modules.pop("scripts.daily.date_args", None)  # 强制从磁盘重新导入
    import scripts.daily.date_args  # noqa: F401
    assert "scripts.daily.config" not in sys.modules  # 零 config import
    out, err = capsys.readouterr()
    assert out == "" and err == ""  # 导入期零输出
    # 导入后公共面齐备 (Task 2 GREEN 后断言; 缺 resolve/format 时下方 ImportError)
    from scripts.daily.date_args import DATE_RE, format_token, parse_date, resolve_date_arg
    assert DATE_RE.fullmatch("2026-09-03") and DATE_RE.fullmatch("20260903")
