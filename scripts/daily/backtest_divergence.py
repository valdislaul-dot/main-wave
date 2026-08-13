"""
分歧弱转强模式回测 (2026-08-13)
来源: 干货_怎么选.doc — T日爆量+烂板涨停(大分歧日) → T+1高开弱转强 → 缩量加速
样本: data/zt_pool/ 日快照(含炸板/封板时间), K线用腾讯qfq日线(完整历史)
模拟: T+1开盘买入(按高开分档) → 记录T+1收盘、T+2收盘收益
分组: 低开(不进) | 小高开0-4% | 高开4-6% | 大高开>=6% × 缩量/放量
"""
import json, os, sys, urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POOL_DIR = os.path.join(BASE, 'data', 'zt_pool')

_kline_cache = {}


def load_pool(p):
    try:
        return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError:
        return json.load(open(p, encoding='gbk'))


def fetch_bars(code, days=90):
    """腾讯qfq日线 → 按日期索引的bar列表"""
    if code in _kline_cache:
        return _kline_cache[code]
    mkt = 'sz' if code.startswith(('0', '3', '1')) else 'sh'
    url = f'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={mkt}{code},day,,,{days},qfq'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        d = json.loads(urllib.request.urlopen(req, timeout=10).read().decode('utf-8'))
        rows = (d.get('data', {}).get(f'{mkt}{code}', {}) or {}).get('qfqday') or []
        bars = [{'date': r[0], 'open': float(r[1]), 'close': float(r[2]),
                 'high': float(r[3]), 'low': float(r[4]), 'volume': float(r[5]) * 100} for r in rows]
        _kline_cache[code] = bars
        return bars
    except Exception:
        _kline_cache[code] = []
        return []


def is_weak(seal, zhaban):
    """烂板: 炸板>=1 或 封板>60min"""
    if zhaban > 0:
        return True
    try:
        st = str(seal).replace(':', '')
        if st and st != '?' and len(st) >= 4:
            mins = max(0, (int(st[:2]) - 9) * 60 + int(st[2:4]) - 30)
            return mins > 60
    except Exception:
        pass
    return False


def vol_heavy(bars, idx):
    """爆量: 近5日涨停量中最大 且 >=2x涨停日均量, 且 >=1.5x前日"""
    from scoring import classify_volume
    if idx is None or idx < 1:
        return False
    vol = bars[idx]['volume']
    prev_v = bars[idx - 1]['volume']
    if prev_v <= 0 or vol < prev_v * 1.5:
        return False
    return classify_volume(vol, bars, idx) == 'heavy'


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    files = sorted(f for f in os.listdir(POOL_DIR) if f.endswith('.json'))
    if len(files) < 3:
        print('涨停池日快照不足3天, 无法回测')
        return

    trades = []  # 每笔: {T, code, name, zhaban, gap1, shrink1, r1c, r2c}
    for i, fn in enumerate(files[:-2]):
        T = fn[:-5]
        T1 = files[i + 1][:-5]
        T2 = files[i + 2][:-5]
        T = f'{T[:4]}-{T[4:6]}-{T[6:8]}'
        T1 = f'{T1[:4]}-{T1[4:6]}-{T1[6:8]}'
        T2 = f'{T2[:4]}-{T2[4:6]}-{T2[6:8]}'
        pool = load_pool(os.path.join(POOL_DIR, fn))
        stocks = pool if isinstance(pool, list) else pool.get('stocks', pool.get('data', []))
        for s in stocks:
            code = str(s.get('code', '')).replace('sh', '').replace('sz', '')
            if not code or code.startswith(('300', '301', '688')):
                continue
            if not is_weak(s.get('first_seal', ''), int(s.get('break_times', 0) or 0)):
                continue
            bars = fetch_bars(code)
            dates = [b['date'] for b in bars]
            idx = dates.index(T) if T in dates else None
            i1 = dates.index(T1) if T1 in dates else None
            i2 = dates.index(T2) if T2 in dates else None
            if idx is None or i1 is None or i2 is None or idx < 1:
                continue
            if not vol_heavy(bars, idx):
                continue
            gap1 = round((bars[i1]['open'] - bars[idx]['close']) / bars[idx]['close'] * 100, 2)
            buy = bars[i1]['open']
            r1c = round((bars[i1]['close'] - buy) / buy * 100, 2)
            r2c = round((bars[i2]['close'] - buy) / buy * 100, 2)
            shrink1 = bars[i1]['volume'] < bars[idx]['volume']
            trades.append({'T': T, 'code': code, 'name': s.get('name', '?'),
                           'zhaban': int(s.get('break_times', 0) or 0), 'gap1': gap1,
                           'shrink1': shrink1, 'r1c': r1c, 'r2c': r2c})

    print(f'{"=" * 88}')
    print(f'  分歧弱转强回测 | 样本: {len(files)}个交易日快照 | 分歧日标的(爆量+烂板): {len(trades)}笔')
    print(f'{"=" * 88}')
    print(f'{"T日":>10} {"标的":<10} {"炸次":>3} {"T+1高开":>7} {"缩量":>3} {"T+1收盘":>8} {"T+2收盘":>8}')
    for t in sorted(trades, key=lambda x: (x['T'], -x['gap1'])):
        print(f'{t["T"]:>10} {t["name"]}({t["code"]}) {t["zhaban"]:>3} {t["gap1"]:+6.2f}% '
              f'{"是" if t["shrink1"] else "否":>3} {t["r1c"]:+7.2f}% {t["r2c"]:+7.2f}%')

    def stats(group, key):
        rs = [t[key] for t in group]
        if not rs:
            return None
        return {'n': len(rs), 'win': round(sum(1 for r in rs if r > 0) / len(rs) * 100, 1),
                'avg': round(sum(rs) / len(rs), 2)}

    print(f'\n  ── 按T+1高开分档 (买入=T+1开盘, 卖出=T+2收盘) ──')
    groups = [('低开 gap<0 (不进, 弱转强失败)', lambda t: t['gap1'] < 0),
              ('小高开 0~4%', lambda t: 0 <= t['gap1'] < 4),
              ('高开 4~6%', lambda t: 4 <= t['gap1'] < 6),
              ('大高开 >=6%', lambda t: t['gap1'] >= 6)]
    for label, f in groups:
        s1 = stats([t for t in trades if f(t)], 'r2c')
        print(f'  {label:<26} {s1 or "无样本"}')

    print(f'\n  ── 高开组内: 缩量 vs 放量 (文章: 弱转强板必须缩量) ──')
    for label, f in groups[1:]:
        g = [t for t in trades if f(t)]
        s_shrink = stats([t for t in g if t['shrink1']], 'r2c')
        s_heavy = stats([t for t in g if not t['shrink1']], 'r2c')
        print(f'  {label:<26} 缩量: {s_shrink or "无样本"} | 放量: {s_heavy or "无样本"}')

    print(f'\n  ⚠ 样本量小(快照仅{len(files)}天), 结论仅供参考, 持续累积后再定论')


if __name__ == '__main__':
    main()
