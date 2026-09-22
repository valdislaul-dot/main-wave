"""抓取 T-1 涨停池股票的 5 分钟 K 线 → data/m5_research/{code}.json

背景 (2026-09-23):
  `data/minute_kline/` 的 1 分钟数据 09-02 起才覆盖「T-1 涨停池」宇宙
  (07-24~09-01 采的是「当日涨停池」= T字板采集器, 对我方规则是反向幸存者偏差,
   不可用)。1 分钟历史**无法补**: 腾讯 m1 硬顶 320 根(≈1.3天), 东财 klt=1 只给当天。

  可用替代 = 5 分钟。5 分钟足以验证 破0% / 破分时均线, 且 **09:35 那根 bar 恰好
  覆盖 09:31~09:35 即"开盘后5分钟"**, 「5分钟内破7%」可直接用该 bar 的 high 判定。

数据源深度实测(2026-09-23):
  | 源 | 深度 | 起点 |
  |----|------|------|
  | **新浪 scale=5** | **5001 根(硬顶)** | **2026-04-23** ← 主源 |
  | 东财 klt=5 | 1488 根 | 2026-08-11 (且实测限流, 873/924 失败) |
  | 腾讯 m5 | 640 根(硬顶) | 2026-09-03 |
  用户目标 04-08 距 04-23 差 11 个交易日, **四个源全试过, 无法再往前**。

用法:
  python scripts/daily/fetch_m5_pool.py --dry        # 只看要抓多少
  python scripts/daily/fetch_m5_pool.py              # 全量(已存在则跳过), 约 10 分钟
  python scripts/daily/fetch_m5_pool.py --force      # 忽略已存在
  python scripts/daily/fetch_m5_pool.py --source em  # 换东财(若已解封)
"""
import json, os, re, sys, io, glob, time, argparse, urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POOL_DIR = os.path.join(BASE, 'data', 'zt_pool')
OUT_DIR = os.path.join(BASE, 'data', 'm5_research')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

# 统一输出: [[time, open, close, high, low, volume, amount], ...]
# ⚠ 各源 volume 单位不同(新浪=股, 东财/腾讯=手), amount 仅东财有 → 价格规则不受影响,
#   若将来要用 5 分钟量能, 必须先按源归一。


def sina_m5(code, datalen=5001):
    sym = ('sh' if code.startswith(('5', '6', '9')) else 'sz') + code
    url = ('http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
           f'CN_MarketData.getKLineData?symbol={sym}&scale=5&ma=no&datalen={datalen}')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        rows = json.loads(urllib.request.urlopen(req, timeout=25).read().decode('utf-8'))
    except Exception:
        return None
    out = []
    for r in rows or []:
        try:
            out.append([str(r['day'])[:16], float(r['open']), float(r['close']),
                        float(r['high']), float(r['low']), float(r['volume']), 0.0])
        except (KeyError, TypeError, ValueError):
            continue
    return out or None


def eastmoney_m5(code):
    secid = ('1.' if code.startswith(('5', '6', '9')) else '0.') + code
    url = ('https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=%s' % secid +
           '&fields1=f1,f2,f3,f4,f5&fields2=f51,f52,f53,f54,f55,f56,f57'
           '&klt=5&fqt=0&beg=0&end=20500101&lmt=100000')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        j = json.loads(urllib.request.urlopen(req, timeout=20).read().decode('utf-8'))
        kl = (j.get('data') or {}).get('klines') or []
    except Exception:
        return None
    out = []
    for r in kl:
        p = r.split(',')
        if len(p) < 7:
            continue
        try:
            out.append([p[0], float(p[1]), float(p[2]), float(p[3]),
                        float(p[4]), float(p[5]), float(p[6])])
        except ValueError:
            continue
    return out or None


SOURCES = {'sina': sina_m5, 'em': eastmoney_m5}


def _read_codes(f):
    for enc in ('utf-8', 'gbk'):
        try:
            raw = json.load(open(f, encoding=enc))
            break
        except (UnicodeDecodeError, ValueError):
            continue
    else:
        return {}
    rows = raw if isinstance(raw, list) else (raw.get('stocks') or [])
    return {str(r.get('code', '')).zfill(6): r.get('name', '')
            for r in rows if isinstance(r, dict) and r.get('code')}


def load_pools():
    """合并两个池目录 → {date: {code: name}}

    两个目录各有一半历史, 单用任一都会把窗口砍短:
      · data/zt_pool_history_ths/  2025-06-03 ~ 2026-08-19 (同花顺原始格式)
      · data/zt_pool/              2026-07-24 ~ 2026-09-22 (本项目格式, 含 GBK 文件)
    并集 → 2026-01 ~ 2026-09 全覆盖。zt_pool 优先(格式新, 字段全)。
    """
    pools = {}
    for src in (os.path.join(BASE, 'data', 'zt_pool_history_ths'), POOL_DIR):
        if not os.path.isdir(src):
            continue
        for f in sorted(glob.glob(os.path.join(src, '*.json'))):
            if os.path.basename(f) == 'stock_index.json':
                continue
            m = re.search(r'(\d{4})[-_]?(\d{2})[-_]?(\d{2})\.json$', f)
            if not m:
                continue
            d = f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
            codes = _read_codes(f)
            if codes:
                pools.setdefault(d, {}).update(codes)
    return pools


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--force', action='store_true', help='重抓已存在的')
    ap.add_argument('--source', default='sina', choices=sorted(SOURCES))
    ap.add_argument('--start', default='2026-04-24', help='T 起始日(用其 T-1 池)')
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    pools = load_pools()
    DAYS = sorted(pools)
    want = {}
    for T in DAYS:
        if T < args.start:
            continue
        pv = [d for d in DAYS if d < T]
        if not pv:
            continue
        for c, n in pools[pv[-1]].items():
            if not c.startswith(('300', '301', '688', '8', '9')):
                want[c] = n
    todo = [c for c in sorted(want)
            if args.force or not os.path.exists(os.path.join(OUT_DIR, c + '.json'))]
    print(f'[m5] 源={args.source} T>={args.start} 需要 {len(want)} 只,'
          f' 已有 {len(want)-len(todo)}, 待抓 {len(todo)}')
    if args.dry or not todo:
        return

    fetch = SOURCES[args.source]
    t0, ok, bad, empty = time.time(), 0, 0, []
    for i, c in enumerate(todo, 1):
        k = fetch(c)
        if k:
            with open(os.path.join(OUT_DIR, c + '.json'), 'w', encoding='utf-8') as f:
                json.dump({'code': c, 'name': want[c], 'source': args.source, 'm5': k},
                          f, ensure_ascii=False)
            ok += 1
        else:
            bad += 1
            empty.append(c)
        if i % 50 == 0:
            print(f'  ... {i}/{len(todo)} ok={ok} ({time.time()-t0:.0f}s)')
        time.sleep(0.3)
    print(f'[m5] 完成 ok={ok} 失败={bad} ({time.time()-t0:.0f}s) → {OUT_DIR}')
    if empty:
        print(f'[m5] 失败代码(前20): {empty[:20]}')


if __name__ == '__main__':
    main()
