"""历史涨停池收盘价回填 — 补齐 data/daily_close/{date}/daily_data.json

背景 (2026-09-23, 盘中规则验证中发现的数据缺口):
  要回答"A的盘中规则触发后, 留到次日划不划算", 需要对 T-1 涨停池的票取 **T+1** 的收盘价。
  但本地 K 线库只更新「当日涨停池 + 持仓」 —— T 日没涨停的票, 其 T+1 bar 根本不存在。
  实测覆盖率仅 43%, 且缺的正是"没涨停"那些 → 有偏样本(幸存者偏差)。
  (第一次跑出「5分钟内破7% → T+1收盘 +5.23%/67%胜」即由此产生, 是假象。)

  与 backfill_auction_close.py 的分工:
    · backfill_auction_close  补「昨日涨停池」(=竞价池)在 T 日的价 —— 覆盖 pool(T-1)
    · 本脚本                   补「前2日涨停池」在 T 日的价 —— 覆盖 pool(T-2), 即 T-1 视角的"次日"
  两者并集后, 每日快照覆盖 前2日 ∪ 昨日 ∪ 当日 涨停池, T+1 口径才无偏。

做法: 扫描 data/zt_pool 收集 codes → 按【代码】拉一次腾讯不复权日线
     (与 kline_data 主库同口径, 非 qfq) → 再按日期分发补入各日快照。
     只补缺, 不改已有值。

用法:
  python scripts/daily/backfill_pool_close.py --dry          # 只统计不写盘
  python scripts/daily/backfill_pool_close.py                # 回填全部池日期
  python scripts/daily/backfill_pool_close.py --start 2026-09-01
"""
import json, os, re, glob, sys, io, time, argparse

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backfill_auction_close import tencent_unadj, load_json

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POOL_DIR = os.path.join(BASE, 'data', 'zt_pool')
DCLOSE_DIR = os.path.join(BASE, 'data', 'daily_close')
LOOKBACK = 2          # 回看几个交易日的涨停池


def pool_codes(path):
    """→ {code: name}

    ⚠ 必须带 GBK 回退: data/zt_pool 有 23 个文件(2026-07-27~09-02)是 GBK 编码,
      只试 utf-8 会静默跳过 → 那些日期的池不进回填范围, 缺口恰好集中在
      「未涨停」的票上(涨停票另有 K 线来源兜住), 伪装成"已回填完整"。
    """
    raw = None
    for enc in ('utf-8', 'gbk'):
        try:
            with open(path, encoding=enc) as f:
                raw = json.load(f)
            break
        except (UnicodeDecodeError, ValueError):
            continue
    if raw is None:
        return {}
    rows = raw.get('stocks', raw) if isinstance(raw, dict) else raw
    if isinstance(rows, dict):
        rows = list(rows.values())
    out = {}
    for r in (rows or []):
        if isinstance(r, dict) and r.get('code'):
            c = str(r['code']).zfill(6)
            if len(c) == 6:
                out[c] = r.get('name', '')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true', help='只统计不写盘')
    ap.add_argument('--start', default=None, help='起始日期 YYYY-MM-DD')
    ap.add_argument('--lookback', type=int, default=LOOKBACK)
    args = ap.parse_args()

    pools, skipped = {}, []
    for f in sorted(glob.glob(os.path.join(POOL_DIR, '*.json'))):
        if os.path.basename(f) == 'stock_index.json':
            continue
        m = re.search(r'(\d{4})(\d{2})(\d{2})\.json$', f)
        if not m:
            continue
        d = f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
        cm = pool_codes(f)
        if cm:
            pools[d] = cm
        else:
            skipped.append(d)
    if skipped:
        print(f'[PoolBackfill] ⚠ 无法解析(已跳过, 这些日期不会进回填范围): {skipped}')
    if not pools:
        print('[PoolBackfill] 无涨停池文件')
        return

    DAYS = sorted(pools)
    # 每天 D 需要: pool(D), pool(D-1) ... pool(D-lookback)
    need = {}
    for i, d in enumerate(DAYS):
        if args.start and d < args.start:
            continue
        cm = {}
        for k in range(args.lookback + 1):
            if i - k >= 0:
                cm.update(pools[DAYS[i - k]])
        need[d] = cm

    all_codes = sorted({c for cm in need.values() for c in cm})
    print(f'[PoolBackfill] {len(need)} 个交易日 ({min(need)} ~ {max(need)})'
          f', 回看 {args.lookback} 日, {len(all_codes)} 只 unique 代码')

    # 先看缺多少, 缺得少就不必全量抓
    miss = {}
    for d, cm in need.items():
        cur = load_json(os.path.join(DCLOSE_DIR, d, 'daily_data.json'), {})
        m = [c for c in cm if c not in cur]
        if m:
            miss[d] = m
    print(f'[PoolBackfill] 缺 {sum(len(v) for v in miss.values())} 条, 分布在 {len(miss)} 天')
    if not miss:
        print('[PoolBackfill] 无需回填')
        return
    if args.dry:
        for d in sorted(miss)[:10]:
            print(f'  {d}: 缺 {len(miss[d]):3d}')
        print('  (--dry, 未联网)')
        return

    hist = {}
    t0 = time.time()
    for i, c in enumerate(all_codes, 1):
        h = tencent_unadj(c)
        if h:
            hist[c] = h
        if i % 100 == 0:
            print(f'  ... {i}/{len(all_codes)} ({time.time()-t0:.0f}s)')
        time.sleep(0.05)
    print(f'[PoolBackfill] 历史日线 {len(hist)}/{len(all_codes)} 只 ({time.time()-t0:.0f}s)')

    total_add, total_skip, touched = 0, 0, 0
    for d in sorted(need):
        cm = need[d]
        day_dir = os.path.join(DCLOSE_DIR, d)
        fp = os.path.join(day_dir, 'daily_data.json')
        cur = load_json(fp, {})
        before = len(cur)
        add = {}
        for c in cm:
            if c in cur:
                continue
            bar = (hist.get(c) or {}).get(d)
            if not bar:
                total_skip += 1
                continue
            add[c] = {'name': cm[c] or '', **bar}
        if add:
            os.makedirs(day_dir, exist_ok=True)
            cur.update(add)
            with open(fp, 'w', encoding='utf-8') as f:
                json.dump(cur, f, ensure_ascii=False)
            touched += 1
            print(f'  {d}: 原有 {before:3d} + 补 {len(add):3d} = {before+len(add):3d}')
        total_add += len(add)
    print(f'\n[PoolBackfill] 回填 {total_add} 条 | 写盘 {touched} 天 | 无历史价跳过 {total_skip}')

    idx = load_json(os.path.join(DCLOSE_DIR, 'stock_index.json'), {})
    for d in sorted(need):
        for c, nm in need[d].items():
            if nm:
                idx[nm] = c
    with open(os.path.join(DCLOSE_DIR, 'stock_index.json'), 'w', encoding='utf-8') as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)
    print(f'[PoolBackfill] 名称索引 {len(idx)} 条')


if __name__ == '__main__':
    main()
