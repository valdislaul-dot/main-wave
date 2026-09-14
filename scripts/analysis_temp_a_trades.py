# -*- coding: utf-8 -*-
"""A的78笔逐笔特征 vs 我方推荐 — 找差距在哪一层"""
import json, os, sys, io, glob, statistics as st
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# name -> code 映射 (K线文件名 或 池文件)
def build_name_map():
    m = {}
    for p in glob.glob('data/kline_data/*.json'):
        b = os.path.basename(p)[:-5]
        if '_' in b:
            nm, _, cd = b.rpartition('_')
            m.setdefault(nm, cd)
        elif b.isdigit():
            m.setdefault(b, b)   # 纯代码文件, 跳过
    for f in sorted(os.listdir('data/zt_pool')):
        if not f.endswith('.json') or f == 'stock_index.json':
            continue
        try:
            data = json.load(open('data/zt_pool/' + f, encoding='utf-8'))
        except UnicodeDecodeError:
            data = json.load(open('data/zt_pool/' + f, encoding='gbk'))
        for x in (data if isinstance(data, list) else data.get('stocks', [])):
            if x.get('name') and x.get('code'):
                m.setdefault(x['name'], str(x['code']).zfill(6))
    try:
        idx = json.load(open('data/daily_close/stock_index.json', encoding='utf-8'))
        for nm, cd in idx.items():
            m.setdefault(nm, str(cd).zfill(6))
    except Exception:
        pass
    return m

def rd(p):
    try:
        return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError:
        return json.load(open(p, encoding='gbk'))

def kline(code):
    p = f'data/kline_data/{code}.json'
    if not os.path.exists(p):
        return None
    raw = rd(p)
    return raw.get('data', raw) if isinstance(raw, dict) else raw

def pool_on(d):
    """date -> {code: row}"""
    ymd = d.replace('-', '')
    for base in ('data/zt_pool/', 'data/zt_pool_history_ths/'):
        p = base + ymd + '.json'
        if os.path.exists(p):
            data = rd(p)
            rows = data if isinstance(data, list) else data.get('stocks', [])
            out = {}
            for x in rows:
                c = str(x.get('code', '')).zfill(6)
                out[c] = x
            return out
    return {}

def main():
    nm = build_name_map()
    a = rd('logs/trader_a.json')
    th = a['trade_history']
    print(f"A 交易 {len(th)} 笔  期间 {a['period']}")
    unmatched, out = [], []
    for t in th:
        name = t['name']
        code = nm.get(name)
        if not code or not code.isdigit():
            unmatched.append(name)
            continue
        kl = kline(code)
        if not kl:
            unmatched.append(name + '(无K线)')
            continue
        byd = {b['date']: b for b in kl}
        bd = t['buy_date']
        idx = next((i for i, b in enumerate(kl) if b['date'] == bd), None)
        if idx is None or idx < 1:
            unmatched.append(name + '(无买入日bar)')
            continue
        k_d, k_b = kl[idx - 1], kl[idx]      # D=涨停日, D+1=买入日
        gap = (k_b['open'] - k_d['close']) / k_d['close'] * 100
        # D 状态
        pd_ = pool_on(k_d['date'])
        row = pd_.get(code, {})
        vols = [b['volume'] for b in kl[max(0, idx - 21):idx - 1] if b.get('volume')]
        vr = (k_d['volume'] / st.mean(vols)) if vols and st.mean(vols) > 0 else None
        out.append(dict(name=name, code=code, buy_date=bd, sell_date=t['sell_date'],
                        pnl=t['pnl_pct'], gap=gap, vr=vr,
                        board=int(row.get('limit_days', 0) or 0) or None,
                        seal=row.get('first_seal') or row.get('first_limit_up_time'),
                        broke=row.get('break_times') or row.get('open_num'),
                        btype=row.get('board_type') or row.get('limit_up_type'),
                        in_pool=bool(row)))
    print(f"匹配到K线: {len(out)} 笔 | 未匹配 {len(unmatched)}: {unmatched}")
    known = [r for r in out if r['pnl'] is not None]
    print(f"有盈亏数据: {len(known)} 笔, 均 {st.mean([r['pnl'] for r in known]):+.2f}%, "
          f"胜率 {sum(1 for r in known if r['pnl']>0)/len(known)*100:.0f}%")
    print()
    print(f"{'日期':11s}{'名称':9s}{'gap%':>7s}{'vr':>6s}{'板':>4s}{'盈亏%':>8s}  板型")
    print('-' * 62)
    for r in out:
        g = f"{r['gap']:+7.2f}" if r['gap'] is not None else '      -'
        v = f"{r['vr']:6.2f}" if r['vr'] else '     -'
        b = f"{r['board']:4d}" if r['board'] else '   -'
        p = f"{r['pnl']:+8.2f}" if r['pnl'] is not None else '       -'
        print(f"{r['buy_date']:11s}{r['name']:9s}{g}{v}{b}{p}  {r['btype'] or '?'}")
    json.dump(out, open('data/_a_trades_enriched.json', 'w', encoding='utf-8'), ensure_ascii=False)

main()
