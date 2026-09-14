"""A模式盘中确认回测 (2026-09-08晚, 用户拍板"先抓一个月的数据来回测")
================================================================
A真实买入: 分歧次日"开盘后股价上穿分时均价线"买入(不看竞价gap)
数据: 腾讯mkline m15(320根覆盖约20个交易日) — 无历史分时, 用15分钟粒度近似分时均线
口径: 每笔分歧信号独立; 触发买入价=上穿时刻分时均线(amount×10000/volume×100);
      无触发→不买(盘中过滤器); 卖出=日线规则(涨停持有/断板兑现/止损-10%)
对比: 同批信号的开盘价口径(无盘中过滤)
"""
import json, os, sys, time, urllib.request
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'daily'))
from backtest_common import FIXED_POS

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
THS_DIR = os.path.join(BASE, 'data', 'zt_pool_history_ths')
ZT_DIR = os.path.join(BASE, 'data', 'zt_pool')
M15_DIR = os.path.join(BASE, 'data', 'm15_research')
COST = 0.00125
BUY_START, BUY_END = '2026-08-12', '2026-09-07'  # 一个月窗口
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

os.makedirs(M15_DIR, exist_ok=True)


def load_klines():
    ktbl, cache = {}, {}
    def get(code):
        if code in cache:
            return cache[code]
        for enc in ('utf-8', 'gbk'):
            try:
                with open(os.path.join(KLINE_DIR, f'{code}.json'), encoding=enc) as f:
                    raw = json.load(f)
                kls = raw.get('data', raw) if isinstance(raw, dict) else raw
                cache[code] = kls
                return kls
            except Exception:
                continue
        cache[code] = None
        return None
    for fn in os.listdir(KLINE_DIR):
        if not fn.endswith('.json') or fn.startswith('._'):
            continue
        code = fn.replace('.json', '')
        if code.startswith(('300', '301', '688', '8', '9')):
            continue
        kls = get(code)
        if kls:
            ktbl[code] = kls
    return ktbl


def load_pools():
    files = {}
    for d in (THS_DIR, ZT_DIR):
        for fn in os.listdir(d):
            if fn.endswith('.json') and fn[:8].isdigit():
                files[fn[:8]] = os.path.join(d, fn)
    pools = {}
    for ymd, path in files.items():
        if not ('20260808' <= ymd <= '20260908'):
            continue
        try:
            with open(path, encoding='utf-8') as f:
                pools[ymd] = json.load(f)
        except UnicodeDecodeError:
            with open(path, encoding='gbk', errors='replace') as f:
                pools[ymd] = json.load(f)
    return pools


def is_lu(k, pk):
    if k.get('pct_change') is not None:
        return k['pct_change'] >= 9.8
    return pk and pk['close'] > 0 and (k['close'] - pk['close']) / pk['close'] >= 0.098


def bar_on(kls, date_fmt):
    if not kls:
        return None, None
    idx = next((i for i, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == date_fmt), None)
    if idx is None or idx < 1:
        return None, None
    return kls[idx], kls[idx - 1]


def vr20(kls, idx):
    vols = [kls[t]['volume'] for t in range(max(0, idx - 20), idx) if kls[t].get('volume', 0) > 0]
    return kls[idx]['volume'] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 1.0


def fetch_m15(code):
    """腾讯mkline m15, 320根; 缓存到 m15_research/"""
    cache_f = os.path.join(M15_DIR, f'{code}.json')
    if os.path.exists(cache_f):
        with open(cache_f, encoding='utf-8') as f:
            bars = json.load(f)
        if bars:
            return bars
    pre = 'sh' if code.startswith(('5', '6', '9')) else 'sz'
    url = f'https://ifzq.gtimg.cn/appstock/app/kline/mkline?param={pre}{code},m15,,320&_var=result'
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': 'https://gu.qq.com/'})
    for _ in range(3):
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            data = resp.read().decode('gbk')
            d = json.loads(data.split('=', 1)[1].strip())
            bars = d.get('data', {}).get(f'{pre}{code}', {}).get('m15', [])
            if bars:
                with open(cache_f, 'w', encoding='utf-8') as f:
                    json.dump(bars, f)
                return bars
        except Exception as e:
            time.sleep(0.5)
    return []


def gen_signals(ktbl, pools):
    """一个月窗口内的分歧信号: {buy_date: [(code, vr)]}"""
    all_dates = sorted(pools.keys())
    fmt = [f'{y[:4]}-{y[4:6]}-{y[6:]}' for y in all_dates]
    signals = []
    for i, d in enumerate(fmt):
        if not (BUY_START <= d <= BUY_END) or i == 0:
            continue
        prev_d = fmt[i - 1]
        rows = pools.get(prev_d.replace('-', ''), [])
        if i >= 2:
            rows = rows + pools.get(fmt[i - 2].replace('-', ''), [])
        seen = set()
        for s in rows:
            code = str(s.get('code', ''))
            if code in seen or code.startswith(('300', '301', '688', '8', '9')):
                continue
            kls = ktbl.get(code)
            k1, k0 = bar_on(kls, prev_d)
            if not k1 or not k0:
                continue
            idx = next(j for j, x in enumerate(kls) if x.get('date') == prev_d)
            vr = vr20(kls, idx)
            if vr < 2.0:
                continue
            amp = (k1['high'] - k1['low']) / k0['close'] * 100 if k0['close'] else 0
            touch = k1['high'] >= k0['close'] * 1.098
            lu1 = is_lu(k1, k0)
            if not ((lu1 and amp >= 10) or (not lu1 and touch)):
                continue
            seen.add(code)
            # 买入日过滤: 开一字/开跌停
            k, pk = bar_on(kls, d)
            if not k or k['open'] <= 0:
                continue
            if k['open'] >= pk['close'] * 1.098 or k['open'] <= pk['close'] * 0.90:
                continue
            signals.append({'code': code, 'buy_date': d, 'div_vr': vr})
    return signals


def intraday_trigger(m15_bars, buy_date):
    """回放买入日当天的上穿分时均线触发; 返回买入价或None
    m15 bar: [time, open, close, high, low, volume, {}, amt字段单位因票而异不可用]
    分时均线 = Σ(Vi×典型价i)/ΣVi, 典型价=(H+L+C)/3 (绕开amt字段单位问题)"""
    day = buy_date.replace('-', '')
    bars = [b for b in m15_bars if str(b[0]).startswith(day)]
    if not bars:
        return None
    cum_pv, cum_v, vwap_prev = 0.0, 0.0, None
    for b in bars:
        o, c, h, l = float(b[1]), float(b[2]), float(b[3]), float(b[4])
        v = float(b[5])
        typical = (h + l + c) / 3.0
        # 触发判定: 用上根累计均线, bar内最高价上穿
        if vwap_prev is not None and h > vwap_prev:
            return max(vwap_prev, o)
        cum_pv += typical * v
        cum_v += v
        vwap_prev = cum_pv / cum_v if cum_v > 0 else o
    return None


def simulate_sell(kls, buy_date, buy_price):
    """卖出: 涨停持有 → 断板 H>=涨停价按涨停价卖 / 否则开盘价卖 / 止损-10%"""
    idx = next(i for i, x in enumerate(kls) if x.get('date') == buy_date)
    pnl, days, tag = None, 0, None
    j = idx
    while pnl is None and j + 1 < len(kls):
        j += 1
        days += 1
        kk, kp = kls[j], kls[j - 1]
        if (kk['low'] - buy_price) / buy_price <= -0.10:
            pnl, tag = (buy_price * 0.90 - buy_price) / buy_price * 100, '硬止损'
        elif is_lu(kk, kp):
            continue
        elif kk['high'] >= kp['close'] * 1.10 * 0.999:
            pnl, tag = (round(kp['close'] * 1.10, 2) * (1 - COST) - buy_price) / buy_price * 100, '摸板涨停价卖'
        else:
            pnl, tag = (kk['open'] * (1 - COST) - buy_price) / buy_price * 100, '断板开盘卖'
    if pnl is None and j + 1 >= len(kls) and j > idx:
        pnl, tag = (kls[j]['close'] * (1 - COST) - buy_price) / buy_price * 100, '期末估值'
    return pnl, days, tag


def stat(ts, name):
    n = len(ts)
    if n == 0:
        print(f'{name}: 0笔')
        return
    wr = sum(1 for t in ts if t['pnl'] > 0) / n * 100
    avg = sum(t['pnl'] for t in ts) / n
    print(f'{name}: {n}笔 | 胜率{wr:.1f}% | 均笔{avg:+.2f}% | '
          f'最大赢{max(t["pnl"] for t in ts):+.1f}% 最大亏{min(t["pnl"] for t in ts):+.1f}%')


def main():
    ktbl = load_klines()
    pools = load_pools()
    print(f'K线{len(ktbl)}只, 池{len(pools)}天')
    signals = gen_signals(ktbl, pools)
    print(f'一个月信号: {len(signals)}笔 ({signals[0]["buy_date"] if signals else "-"} ~ {signals[-1]["buy_date"] if signals else "-"})')

    # 抓m15
    codes = sorted(set(s['code'] for s in signals))
    print(f'抓取m15: {len(codes)}只...')
    m15_cache = {}
    for n, code in enumerate(codes):
        m15_cache[code] = fetch_m15(code)
        if (n + 1) % 50 == 0:
            print(f'  {n+1}/{len(codes)}')
        time.sleep(0.15)
    ok = sum(1 for c in codes if m15_cache[c])
    print(f'm15抓取完成: {ok}/{len(codes)}只有数据')

    # 口径1: 开盘价买入(无盘中过滤)
    trades_open = []
    for s in signals:
        kls = ktbl[s['code']]
        k, pk = bar_on(kls, s['buy_date'])
        buy = k['open'] * (1 + COST)
        pnl, days, tag = simulate_sell(kls, s['buy_date'], buy)
        if pnl is not None:
            trades_open.append({'code': s['code'], 'buy': s['buy_date'], 'pnl': pnl, 'tag': tag, 'days': days})

    # 口径2: 盘中上穿分时均线买入(A口径)
    trades_intra = []
    no_trigger = []
    for s in signals:
        m15 = m15_cache.get(s['code'], [])
        px = intraday_trigger(m15, s['buy_date'])
        if px is None:
            no_trigger.append(s)
            continue
        buy = px * (1 + COST)
        kls = ktbl[s['code']]
        pnl, days, tag = simulate_sell(kls, s['buy_date'], buy)
        if pnl is not None:
            trades_intra.append({'code': s['code'], 'buy': s['buy_date'], 'pnl': pnl, 'tag': tag, 'days': days,
                                 'open': bar_on(kls, s['buy_date'])[0]['open'], 'trig': px})

    print()
    print('=' * 60)
    print(f'同一批{len(signals)}笔信号, 两种口径对比:')
    print('=' * 60)
    stat(trades_open, '开盘价买入(无盘中过滤)')
    stat(trades_intra, '上穿分时均线买入(A口径) ')
    print(f'A口径无触发(全天未上穿均线, 不买): {len(no_trigger)}笔')
    if trades_intra:
        # 触发价 vs 开盘价的平均差
        diffs = [(t['trig'] - t['open']) / t['open'] * 100 for t in trades_intra]
        print(f'触发价 vs 开盘价: 平均高{sum(diffs)/len(diffs):+.2f}%')
    # A两笔验证
    print()
    print('A两笔案例检查:')
    for t in trades_intra + trades_open:
        if t['code'] in ('601086', '605577') and t['buy'] >= '2026-09':
            src = 'A口径' if 'trig' in t else '开盘'
            print(f'  {t["code"]} {t["buy"]} [{src}] {t["tag"]} 持有{t["days"]}天 {t["pnl"]:+.2f}%')
    for s in no_trigger:
        if s['code'] in ('601086', '605577') and s['buy_date'] >= '2026-09':
            print(f'  {s["code"]} {s["buy_date"]} [A口径] 无触发(未买)')


if __name__ == '__main__':
    main()
