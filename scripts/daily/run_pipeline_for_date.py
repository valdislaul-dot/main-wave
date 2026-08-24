"""以指定日期运行盘后流水线 (2026-08-22, 补跑08-21盘后用)
用法: python scripts/daily/run_pipeline_for_date.py 2026-08-21
实现: monkey-patch datetime.datetime.now/date.today 锚定目标日期后调用 run_pipeline.main()
"""
import sys
import datetime as _dt

TARGET = sys.argv[1] if len(sys.argv) > 1 else '2026-08-21'
_y, _m, _d = map(int, TARGET.split('-'))


class _FakeDT(_dt.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(_y, _m, _d, 15, 30)


class _FakeDate(_dt.date):
    @classmethod
    def today(cls):
        return cls(_y, _m, _d)


_dt.datetime = _FakeDT
_dt.date = _FakeDate

import sys as _sys
_sys.argv = ['run_pipeline.py']   # 清掉日期参数, 防run_pipeline按命令解析

import run_pipeline
run_pipeline.main()
