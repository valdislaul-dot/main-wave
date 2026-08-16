"""
交易日历 (2026-08-16新增)
=============================
数据源: akshare tool_trade_date_hist_sina (失败降级为「周一~周五」)
缓存: data/trading_calendar.json (7天内有效, 过期自动刷新)

用途:
  - 采集守卫判断「今天是否交易日」, 避免周末/节假日采到垃圾快照
  - 提供 prev/next 交易日查询 (比「按文件存在性反推」更可靠)

用法:
  from trading_calendar import is_trading_day, prev_trading_day, next_trading_day
"""
import json, os
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CAL_PATH = os.path.join(BASE, 'data', 'trading_calendar.json')


def _fetch_calendar():
    """akshare 交易日历 → set of 'YYYY-MM-DD'；失败返回 None"""
    try:
        import akshare as ak
        df = ak.tool_trade_date_hist_sina()
        dates = set()
        for d in df['trade_date']:
            dates.add(d.strftime('%Y-%m-%d'))
        return dates
    except Exception:
        return None


def get_trading_days():
    """返回交易日集合(set)；优先读缓存(7天内)，过期刷新，失败降级"""
    cached = None
    if os.path.exists(CAL_PATH):
        try:
            with open(CAL_PATH, encoding='utf-8') as f:
                cached = json.load(f)
        except Exception:
            cached = None

    # 缓存有效(7天内) → 直接用
    if cached and cached.get('fetched_at'):
        try:
            fetched = datetime.fromisoformat(cached['fetched_at'])
            if (datetime.now() - fetched).days < 7:
                return set(cached.get('dates', []))
        except Exception:
            pass

    # 刷新
    dates = _fetch_calendar()
    if dates:
        try:
            with open(CAL_PATH, 'w', encoding='utf-8') as f:
                json.dump({'fetched_at': datetime.now().isoformat(),
                           'dates': sorted(dates)}, f, ensure_ascii=False)
        except Exception:
            pass
        return dates

    # 拉取失败 → 用过期缓存兜底
    if cached:
        return set(cached.get('dates', []))
    return None


def _to_date(d):
    """datetime/date/str → date"""
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, str):
        return datetime.strptime(d, '%Y-%m-%d').date()
    return d


def is_trading_day(d):
    """d: date/datetime/'YYYY-MM-DD' → bool"""
    d = _to_date(d)
    days = get_trading_days()
    if days is not None:
        return d.strftime('%Y-%m-%d') in days
    # 无日历可用 → 降级: 周一~周五
    return d.weekday() < 5


def _walk(d, delta, limit=30):
    days = get_trading_days()
    cur = d
    for _ in range(limit):
        cur = cur + delta
        if days is not None:
            if cur.strftime('%Y-%m-%d') in days:
                return cur
        elif cur.weekday() < 5:
            return cur
    return None


def prev_trading_day(d):
    """前一个交易日 (date/str)"""
    return _walk(_to_date(d), timedelta(days=-1))


def next_trading_day(d):
    """后一个交易日 (date/str)"""
    return _walk(_to_date(d), timedelta(days=1))


if __name__ == '__main__':
    today = datetime.now().date()
    print(f'今天 {today} 是否交易日: {is_trading_day(today)}')
    print(f'上一交易日: {prev_trading_day(today)}')
    print(f'下一交易日: {next_trading_day(today)}')
