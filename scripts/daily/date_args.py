"""date 白名单校验单源模块 (04-04, D-09/SC4 扩展; 04-CONTEXT 触发 date 参数面)。

单源规则: 白名单正则 + 真历法校验只在本模块定义一次 —— api/actions.py 的
422 门、run_pipeline.py / morning_check.py 的会话日期门、以及全部测试都消费
本模块; 任何调用方不得手写重复校验 (T-04-15)。API 追加进 argv 的 token 由
解析后的 date 对象归一化而来, 永不用原始查询串 —— 注入结构性不可能 (T-04-13)。

零 import 副作用 (仅 re/sys/datetime, 无 config import, 导入不打印/不建文件),
ASCII-only 文本 —— API 导入链与 CLI 脚本可共同消费 (Pitfall 3 惯例)。

公共面:
  DATE_RE          白名单正则 (YYYY-MM-DD | YYYYMMDD), 唯一定义
  parse_date(v)    str -> datetime.date; 格式/历法非法 -> ValueError
  resolve_date_arg(argv)  扫描 --date=X 与 "--date X" 两种形态 -> date | None
  format_token(d)  date -> "--date=YYYY-MM-DD" (规范单 token 形态)
"""
import re
import sys
from datetime import date as _date

# 白名单: 仅 YYYY-MM-DD 或 YYYYMMDD 两种字面格式 (04-CONTEXT D-26/D-27)
DATE_RE = re.compile(r"^(?:\d{4}-\d{2}-\d{2}|\d{8})$")

_ERR_MSG = "date must be YYYY-MM-DD or YYYYMMDD (a real calendar date)"


def parse_date(value):
    """str -> datetime.date; 格式或历法非法 -> ValueError (ASCII 消息, 指名两种格式)。

    regex fullmatch 之后做真历法构造: dashed 形态走 date.fromisoformat,
    compact 形态显式 int 年月日 —— 2026-13-99 / 2026-02-30 之类在此拒绝。
    """
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        raise ValueError(_ERR_MSG)
    try:
        if "-" in value:
            return _date.fromisoformat(value)
        return _date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        raise ValueError(_ERR_MSG) from None
