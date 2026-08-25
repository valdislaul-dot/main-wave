"""V4因子形状数据 (2026-08-25) — 各因子取值分档 × 次日表现 (1年: 2025-08-19~2026-08-19)
因子: 量比/一字T字/周几/封板时间/炸板次数/板块共振/分歧质量 (gap/连板/跌停风险已有)
口径: 每日涨停股(剔除300/301/688/8/9), 次日表现=close_T1/close_T-1
  封板时间/炸板/板块/分歧 用同花顺池join(2025-09~10疯牛段缺失自然跳过)
输出: logs/factor_shape.txt
"""
import json, os
from datetime import datetime
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
THS_DIR = os.path.join(BASE, 'data', 'zt_pool_history_ths')
START, END = '2025-08-19', '2026-08-19'


def is_lu(pct, name):
    if pct is None:
        return False
    if 'ST' in (name or ''):
        return pct >= 4.85
    return pct >= 9.8


def main():
    # 1. K线加载
    tbl = {}
    for fn in os.listdir(KLINE_DIR):
        if not fn.endswith('.json') or fn.startswith('._'):
            continue
        code = fn.replace('.json', '')
        if code.startswith(('300', '301', '688', '8', '9')):
            continue
        j = None
        for enc in ('utf-8', 'gbk'):
            try:
                with open(os.path.join(KLINE_DIR, fn), encoding=enc) as f:
                    j = json.load(f)
                break
            except Exception:
                continue
        if j is None:
            continue
        name = (j.get('metadata') or {}).get('name', '')
        rows = j.get('data', j) if isinstance(j, dict) else j
        t = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            date = r.get('date', '')
            if not (START <= date <= END):
                continue
            t[date] = {'open': float(r.get('open', 0) or 0), 'close': float(r.get('close', 0) or 0),
                       'high': float(r.get('high', 0) or 0), 'low': float(r.get('low', 0) or 0),
                       'pct': r.get('pct_change'), 'vol': float(r.get('volume_lots', 0) or 0)}
        if t:
            tbl[code] = (name, t)
    print(f'K线: {len(tbl)}只')

    # 2. 同花顺池明细
    ths_detail = {}   # (date, code) -> {seal_hhmm, open_num, reason, turnover}
    for fn in sorted(os.listdir(THS_DIR)):
        if not fn.endswith('.json'):
            continue
        ymd = fn.replace('.json', '')
        if not (START.replace('-', '') <= ymd <= END.replace('-', '')):
            continue
        with open(os.path.join(THS_DIR, fn), encoding='utf-8') as f:
            info = json.load(f)
        for s in info:
            code = str(s.get('code', ''))
            if not code or code.startswith(('300', '301', '688', '8', '9')):
                continue
            try:
                seal = datetime.fromtimestamp(int(s.get('first_limit_up_time'))).strftime('%H%M')
            except Exception:
                seal = None
            ths_detail[(ymd, code)] = {
                'seal': seal, 'zhaban': int(s.get('open_num', 0) or 0),
                'reason': s.get('reason_type', ''),
                'turnover': float(s.get('turnover_rate', 0) or 0),
            }

    # 3. 样本构建: 每日涨停股 → 次日表现 + 因子标注
    pool = defaultdict(set)
    for code, (name, t) in tbl.items():
        for date, r in t.items():
            if is_lu(r['pct'], name):
                pool[date].add(code)
    days = sorted(pool.keys())

    rows = []
    for i, d in enumerate(days):
        if i + 1 >= len(days):
            continue
        d1 = days[i + 1]
        ymd = d.replace('-', '')
        industries = [ths_detail[(ymd, c)]['reason'] for c in pool[d] if (ymd, c) in ths_detail]
        for c in pool[d]:
            _, t = tbl.get(c, ('', {}))
            r0, r1 = t.get(d), t.get(d1)
            if not r0 or not r1 or r0['close'] <= 0 or r1['close'] <= 0:
                continue
            ret = (r1['close'] - r0['close']) / r0['close'] * 100
            # K线可算因子
            vols = []
            dl = sorted(t.keys())
            idx = dl.index(d)
            for k in range(max(0, idx - 20), idx):
                vols.append(t[dl[k]]['vol'])
            vr20 = r0['vol'] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 1.0
            prev_close = t[dl[idx - 1]]['close'] if idx > 0 else 0
            lu_price = round(prev_close * 1.10, 2) if prev_close > 0 else 0
            is_yz = lu_price > 0 and r0['open'] >= lu_price - 0.005 and r0['low'] >= lu_price - 0.005
            is_tz = lu_price > 0 and r0['open'] >= lu_price - 0.005 and r0['close'] >= lu_price - 0.005 \
                and r0['low'] < lu_price - 0.005
            dow = datetime.strptime(d, '%Y-%m-%d').weekday()
            td = ths_detail.get((ymd, c))
            row = {'ret': ret, 'vr20': vr20,
                   'board': '一字' if is_yz else ('T字' if is_tz else '换手'),
                   'dow': dow, 'lu_t1': is_lu(r1.get('pct'), '')}
            if td:
                row['seal'] = td['seal']
                row['zhaban'] = td['zhaban']
                row['reason'] = td['reason']
            rows.append(row)

    out = []
    out.append('=' * 84)
    out.append('V4因子形状: 取值分档 × 次日表现 (1年, 剔除300/301/688/8/9)')
    out.append(f'生成: {datetime.now().strftime("%Y-%m-%d %H:%M")} | 样本: {len(rows)}')
    out.append('=' * 84)

    def stat(title, key_fn, label_fn):
        out.append(f'\n【{title}】')
        groups = defaultdict(list)
        for x in rows:
            key = key_fn(x)
            if key is None:
                continue
            groups[key].append(x['ret'])
        for key in sorted(groups, key=lambda k: str(k)):
            items = groups[key]
            if len(items) < 30:
                continue
            m = sum(items) / len(items)
            up = sum(1 for r in items if r > 0) / len(items) * 100
            out.append(f'  {label_fn(key):<20} {len(items):>5}笔 次日均{m:>+6.2f}% 上涨率{up:>4.0f}%')

    def vr_bucket(x):
        v = x['vr20']
        return '<0.5' if v < 0.5 else ('0.5-1' if v < 1 else ('1-2' if v < 2 else ('2-4' if v < 4 else '≥4')))

    def seal_bucket(x):
        s = x.get('seal')
        if not s:
            return None
        return '<5min' if s <= '0935' else ('5-10min' if s <= '0940' else (
            '10-30min' if s <= '1000' else ('30-60min' if s <= '1030' else '>60min')))

    def zh_bucket(x):
        z = x.get('zhaban')
        if z is None:
            return None
        return '0次' if z == 0 else ('1次' if z == 1 else ('2次' if z == 2 else '3+次'))

    stat('量比vr20', vr_bucket, lambda k: f'vr20 {k}')
    stat('板型', lambda x: x['board'], lambda k: k)
    stat('周几', lambda x: x['dow'], lambda k: ['周一', '周二', '周三', '周四', '周五'][k])
    stat('封板时间', seal_bucket, lambda k: f'封板{k}')
    stat('炸板次数', zh_bucket, lambda k: f'炸{k}')
    # 板块共振: 主力题材热度 = 该股题材词中当日出现次数最多的词的热度
    # (衡量所处题材的当日强度, 比共享计数更直接)
    from collections import Counter as _C
    def sector_of(x):
        r = x.get('reason')
        if not r:
            return None
        ws = [w for w in str(r).replace('，', '+').split('+') if w.strip()]
        if not ws:
            return None
        all_words = [w for x2 in rows if x2.get('reason')
                     for w in str(x2['reason']).replace('，', '+').split('+') if w.strip()]
        freq = _C(all_words)
        heat = max(freq[w] for w in ws)
        return '<3' if heat < 3 else ('3-4' if heat < 5 else ('5-9' if heat < 10 else '≥10'))
    stat('板块共振(题材热度)', sector_of, lambda k: f'热度{k}')
    # 分歧质量: 爆量+炸板+涨停
    def div_of(x):
        z = x.get('zhaban')
        if z is None:
            return None
        return '分歧(炸≥1+爆量)' if (z >= 1 and x['vr20'] >= 1.5) else '非分歧'
    stat('分歧质量', div_of, lambda k: k)

    with open(os.path.join(BASE, 'logs', 'factor_shape.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(out))
    print('\n'.join(out))
    print('\nDone: logs/factor_shape.txt')


if __name__ == '__main__':
    main()
