"""历史竞价池收盘价回填 — 补齐 data/daily_close/{date}/daily_data.json

背景 (2026-09-22 用户要求"盘后获取涨停数据后必须保存"):
  收盘快照的宇宙原只含 [昨日快照 ∪ 今日涨停池], 而竞价池候选 = 昨涨停股,
  当日多半不再涨停 → 不在K线更新范围 → 其当日收盘价永远缺失。
  后果: "若按开盘价买入, 当日收盘收益几何"无法复算; gap窗口上下限之争没有数据可答。

做法:
  扫描 data/auction/*.json 收集 (日期, 代码) → 按【代码】拉一次腾讯不复权日线
  (与 kline_data 主库同口径, 非qfq) → 再按日期分发补入各日快照。
  只补缺, 不改已有值; 数据落盘后可复现。

用法:
  python scripts/daily/backfill_auction_close.py --dry          # 只统计不写盘
  python scripts/daily/backfill_auction_close.py                # 全量回填
  python scripts/daily/backfill_auction_close.py --start 2026-09-14
"""
import json, os, re, glob, sys, time, argparse, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AUCTION_DIR = os.path.join(BASE, 'data', 'auction')
DCLOSE_DIR = os.path.join(BASE, 'data', 'daily_close')


def auction_codes(path):
    """→ {code: name}"""
    with open(path, encoding='utf-8') as f:
        a = json.load(f)
    rows = a.get('stocks', a) if isinstance(a, dict) else a
    if isinstance(rows, dict):
        rows = list(rows.values())
    out = {}
    for r in (rows or []):
        if isinstance(r, dict) and r.get('code'):
            c = str(r['code']).zfill(6)
            if len(c) == 6:
                out[c] = r.get('name', '')
    return out


def tencent_unadj(code, n=90):
    """腾讯【不复权】日线 → {date: {open,high,low,close,volume}}; volume 手→股"""
    mkt = 'sz' if code.startswith(('0', '3', '1')) else 'sh'
    url = f'http://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={mkt}{code},day,,,{n},'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        d = json.loads(urllib.request.urlopen(req, timeout=12).read().decode('utf-8'))
        node = (d.get('data', {}) or {}).get(f'{mkt}{code}', {}) or {}
        rows = node.get('day') or []
    except Exception:
        return None
    out = {}
    for r in rows:
        try:
            out[r[0]] = {'open': round(float(r[1]), 2), 'close': round(float(r[2]), 2),
                         'high': round(float(r[3]), 2), 'low': round(float(r[4]), 2),
                         'volume': round(float(r[5]) * 100, 2)}
        except (ValueError, IndexError):
            continue
    return out or None


def load_json(fp, default):
    if not os.path.exists(fp):
        return default
    try:
        with open(fp, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true', help='只统计不写盘')
    ap.add_argument('--start', default=None, help='起始日期 YYYY-MM-DD')
    args = ap.parse_args()

    day_maps = {}
    for f in sorted(glob.glob(os.path.join(AUCTION_DIR, '*.json'))):
        m = re.search(r'(\d{4}-\d{2}-\d{2})\.json$', f)
        if not m:
            continue
        d = m.group(1)
        if args.start and d < args.start:
            continue
        try:
            cm = auction_codes(f)
        except Exception:
            continue
        if cm:
            day_maps[d] = cm

    if not day_maps:
        print('[Backfill] 无竞价池文件')
        return

    all_codes = sorted({c for cm in day_maps.values() for c in cm})
    print(f'[Backfill] {len(day_maps)} 个交易日 ({min(day_maps)} ~ {max(day_maps)})'
          f', {len(all_codes)} 只 unique 代码')

    hist = {}
    t0 = time.time()
    for i, c in enumerate(all_codes, 1):
        h = tencent_unadj(c)
        if h:
            hist[c] = h
        if i % 100 == 0:
            print(f'  ... {i}/{len(all_codes)} ({time.time()-t0:.0f}s)')
        time.sleep(0.05)
    print(f'[Backfill] 历史日线 {len(hist)}/{len(all_codes)} 只 ({time.time()-t0:.0f}s)')

    total_add, total_skip, touched = 0, 0, 0
    for d in sorted(day_maps):
        day_dir = os.path.join(DCLOSE_DIR, d)
        fp = os.path.join(day_dir, 'daily_data.json')
        cur = load_json(fp, {})
        before = len(cur)
        add = {}
        for c, nm in day_maps[d].items():
            if c in cur:
                continue
            bar = (hist.get(c) or {}).get(d)
            if not bar:
                total_skip += 1
                continue
            add[c] = {'name': nm or '', **bar}
        if add and not args.dry:
            os.makedirs(day_dir, exist_ok=True)
            cur.update(add)
            with open(fp, 'w', encoding='utf-8') as f:
                json.dump(cur, f, ensure_ascii=False)
            touched += 1
        total_add += len(add)
        print(f'  {d}: 原有 {before:3d} + 补 {len(add):3d} = {before+len(add):3d}'
              f'{"" if add else "  (无新数据)"}')
    print(f'\n[Backfill] {"[DRY] " if args.dry else ""}回填 {total_add} 条'
          f' | 写盘 {touched} 天 | 无历史价跳过 {total_skip}')

    if args.dry or not total_add:
        return
    # 名称索引重建
    idx = load_json(os.path.join(DCLOSE_DIR, 'stock_index.json'), {})
    for d in sorted(day_maps):
        for c, nm in day_maps[d].items():
            if nm:
                idx[nm] = c
    with open(os.path.join(DCLOSE_DIR, 'stock_index.json'), 'w', encoding='utf-8') as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)
    print(f'[Backfill] 名称索引 {len(idx)} 条')


if __name__ == '__main__':
    main()
