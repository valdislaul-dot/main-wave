# -*- coding: utf-8 -*-
"""补拉 2026-07-20~09-11 池内标的K线 → 独立缓存 (不动 data/kline_data 主库)
原因: K线仅在标的入池当天增量更新, 退池即停更 → 8/9月覆盖率仅52%/21%, 分析会幸存者偏差
"""
import json, os, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'daily'))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from update_data import _tencent_latest

OUT = 'data/_regime_klines_aug.json'
FROM, TO = '2026-07-18', '2026-09-11'

def rd(p):
    try:
        return json.load(open(p, encoding='utf-8'))
    except UnicodeDecodeError:
        return json.load(open(p, encoding='gbk'))

codes = set()
for f in sorted(os.listdir('data/zt_pool')):
    if not f.endswith('.json') or f == 'stock_index.json':
        continue
    d = f[:-5]
    if not ('20260720' <= d <= '20260911'):
        continue
    data = rd('data/zt_pool/' + f)
    rows = data if isinstance(data, list) else data.get('stocks', [])
    for x in rows:
        codes.add(str(x.get('code', '')).zfill(6))
codes = sorted(codes)
print(f'目标标的 {len(codes)} 只, 窗口 {FROM} ~ {TO}')

cache = {}
if os.path.exists(OUT):
    cache = json.load(open(OUT, encoding='utf-8'))
    print(f'已有缓存 {len(cache)} 只')

prev_lu = '2026-07-17'
ok = fail = skip = 0
for i, c in enumerate(codes):
    if c in cache and cache[c]:
        skip += 1
        continue
    rows = _tencent_latest(c, prev_lu, TO)
    mkt = 'sz' if c.startswith(('0', '3', '1')) else 'sh'
    if not rows:
        # 无 qfqday 时尝试 day 键 (函数内已兜底), 仍空则标记
        fail += 1
        cache[c] = []
    else:
        cache[c] = rows
        ok += 1
    time.sleep(0.06)
    if (i + 1) % 100 == 0:
        json.dump(cache, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
        print(f'  进度 {i+1}/{len(codes)}  ok={ok} fail={fail}', flush=True)

json.dump(cache, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
print(f'完成: ok={ok} fail={fail} 跳过={skip} → {OUT}')
