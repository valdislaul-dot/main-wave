"""
连板延续概率统计（1年样本更新版）
区间: 2025-08-19 → 2026-08-19 (统计) + 往前15交易日预热连板数
数据源: 同花顺涨停揭秘 data.10jqka.com.cn (东财 push2ex 历史已失效, 2026-08-19实测)
输出: logs/full_market_lianban.txt
用法: python scripts/update_lianban_stats.py [--fetch-only|--analyze-only]
"""
import json
import os
import re
import sys
import time
import random
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'daily'))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

STAT_START = '2025-08-19'   # 统计起点
STAT_END = '2026-08-19'     # 统计终点
WARMUP_DAYS = 15            # 预热交易日数（回算连板用，不参与统计）
OUT_DIR = os.path.join(BASE, 'data', 'zt_pool_history_ths')

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
THS_FIELDS = ('199112,10,9001,330323,330324,330325,9002,330329,'
              '133971,133970,1968584,3475914,9003,9004')


def get_trading_days():
    """交易日列表（升序）: 统计区间 + 往前预热"""
    try:
        from trading_calendar import get_trading_days as gtd
        days = gtd()
        if days:
            start = (datetime.strptime(STAT_START, '%Y-%m-%d')
                     - timedelta(days=WARMUP_DAYS * 2 + 10)).strftime('%Y-%m-%d')
            return sorted(d for d in days if start <= d <= STAT_END)
    except Exception:
        pass
    # 降级: 工作日近似（节假日由同花顺返回空自动识别）
    days = []
    d = datetime.strptime(STAT_START, '%Y-%m-%d') - timedelta(days=WARMUP_DAYS * 2 + 10)
    end = datetime.strptime(STAT_END, '%Y-%m-%d')
    while d <= end:
        if d.weekday() < 5:
            days.append(d.strftime('%Y-%m-%d'))
        d += timedelta(days=1)
    return days


def ths_fetch_day(date_yyyymmdd):
    """同花顺涨停揭秘 — 分页拉取单日全量。返回 [{code,name,high_days,...}] 或 None(失败)"""
    import requests
    all_info = []
    page = 1
    while True:
        url = 'https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool'
        params = {
            'page': page, 'limit': 200,
            'field': THS_FIELDS, 'filter': 'HS,GEM2STAR',
            'order_field': '330324', 'order_type': '0', 'date': date_yyyymmdd,
        }
        try:
            r = requests.get(url, params=params, headers={'User-Agent': UA}, timeout=15)
            info = (r.json().get('data') or {}).get('info', [])
        except Exception as e:
            if page == 1:
                return None
            break
        if not info:
            break
        all_info.extend(info)
        if len(info) < 200:
            break
        page += 1
        time.sleep(0.6)
    return all_info


def parse_limit_days(high_days: str) -> int:
    """'3天3板' → 3；'首板' → 1；解析失败 → None"""
    if not high_days:
        return None
    m = re.search(r'(\d+)板', str(high_days))
    if m:
        return int(m.group(1))
    if '首板' in str(high_days):
        return 1
    return None


def fetch_all(trading_days):
    """逐日拉取（可续传），返回 {date: [codes]}"""
    os.makedirs(OUT_DIR, exist_ok=True)
    fetched, skipped, failed = 0, 0, 0
    for i, day in enumerate(trading_days):
        ymd = day.replace('-', '')
        out_path = os.path.join(OUT_DIR, f'{ymd}.json')
        if os.path.exists(out_path) and os.path.getsize(out_path) > 10:
            skipped += 1
            continue
        info = ths_fetch_day(ymd)
        if info is None:
            failed += 1
            print(f'  [{i+1}/{len(trading_days)}] {day} ← FAILED')
        else:
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(info, f, ensure_ascii=False)
            fetched += 1
            if fetched % 10 == 0:
                print(f'  [{i+1}/{len(trading_days)}] {day}: {len(info)}只 '
                      f'(累计拉取{fetched}, 跳过{skipped}, 失败{failed})')
        time.sleep(0.7 + random.uniform(0, 0.4))
    print(f'拉取完成: 新拉{fetched} 跳过{skipped} 失败{failed}')
    return fetched, failed


def allowed(code: str) -> bool:
    """剔除 300/301/688 创业板科创板 + 8/9 北交所（与原统计口径一致）"""
    return not (code.startswith(('300', '301', '688', '8', '9')))


def load_day(day_ymd: str):
    """加载单日涨停池 → set(codes)，非交易日/缺失 → None"""
    p = os.path.join(OUT_DIR, f'{day_ymd}.json')
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding='utf-8') as f:
            info = json.load(f)
    except Exception:
        return None
    if not info:
        return None
    return {str(s['code']) for s in info if allowed(str(s['code']))}


def analyze(trading_days):
    """回算连板数 + 统计延续概率（与原 full_market_lianban.py 同口径）"""
    # 每日池: {date: set(codes)}
    pool = {}
    for day in trading_days:
        s = load_day(day.replace('-', ''))
        if s:
            pool[day] = s

    prev_streak = {}   # code -> 截至前一交易日的连续涨停天数
    # 预热期: 统计起点前更新连板状态, 不参与统计
    warmup_days = [d for d in trading_days if d < STAT_START and d in pool]
    for day in warmup_days:
        today_set = pool[day]
        new_streak = {}
        for code in today_set:
            new_streak[code] = prev_streak.get(code, 0) + 1
        prev_streak = new_streak

    stat_days = [d for d in trading_days if d >= STAT_START and d in pool]
    print(f'统计区间 {STAT_START}~{STAT_END}: {len(stat_days)} 个交易日有数据')

    transitions = defaultdict(lambda: {'next_lu': 0, 'total': 0})

    for day in stat_days:
        today_set = pool[day]
        nxt = pool.get(_next_day(day, stat_days), set())
        for code in today_set:
            cons = prev_streak.get(code, 0)
            transitions[cons]['total'] += 1
            if code in nxt:
                transitions[cons]['next_lu'] += 1
        # 更新连续涨停状态
        new_streak = {}
        for code in today_set:
            new_streak[code] = prev_streak.get(code, 0) + 1
        prev_streak = new_streak

    return transitions


def _next_day(day, stat_days):
    """stat_days 中的下一个交易日（不在区间内返回 None）"""
    i = stat_days.index(day) + 1
    return stat_days[i] if i < len(stat_days) else None


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    trading_days = get_trading_days()
    print(f'交易日列表: {len(trading_days)} 天 '
          f'({trading_days[0]} → {trading_days[-1]})')

    if mode != '--analyze-only':
        fetch_all(trading_days)

    transitions = analyze(trading_days)
    if not transitions:
        print('无数据，退出')
        return

    out_path = os.path.join(BASE, 'logs', 'full_market_lianban.txt')
    lines = []
    lines.append('=' * 65)
    lines.append('全市场连板延续概率 (2025-08至2026-08, 剔除300/301/688/8/9)')
    lines.append(f'数据源: 同花顺涨停揭秘 | 生成: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    lines.append('=' * 65 + '\n')
    lines.append(f"{'当前位置':<12} {'总样本':>8} {'延续':>8} {'概率':>10} {'趋势':>10}")
    lines.append('-' * 52)

    for cons in sorted(transitions.keys())[:12]:
        t = transitions[cons]
        if t['total'] >= 5:
            prob = t['next_lu'] / t['total'] * 100
            label = f'{cons+1}板->{cons+2}板' if cons > 0 else '首板->2板'
            bar = '#' * int(prob / 5)
            lines.append(f'{label:<12} {t["total"]:>8} {t["next_lu"]:>8} {prob:>9.1f}% {bar}')

    lines.append('')
    lines.append('结论:')
    lines.append('1年样本(2025-08-19~2026-08-19, 含预热回算连板):')
    lines.append('对比旧表(2026-03~07东财口径): 首板→2板13.6% | 2→3板23.2% | 3→4板40.9% | 4→5板33.3%')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print(f'Done: {out_path}')
    print('\n' + '\n'.join(lines[:14]))


if __name__ == '__main__':
    main()
