"""
盘后选股 v3.0 — 集成六维动态权重 + Sigmoid概率 + 硬止损
基于 v2.1，借鉴 zhouyiqing8888/Quantitative 的六维评分思路
"""
import json, os, time, random, math, requests
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]

def em_get(url, params=None, headers=None, timeout=15, **kwargs):
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0: time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()

ZTB_UT = "7eea3edcaed734bea9cbfc24409ed989"

def _fmt_zt_time(t):
    s = str(int(t)).zfill(6)
    return f"{s[0:2]}:{s[2:4]}:{s[4:6]}"

def _em_zt_api(endpoint, sort, date):
    url = f"https://push2ex.eastmoney.com/{endpoint}"
    params = {"ut": ZTB_UT, "dpt": "wz.ztzt", "Pageindex": 0,
              "pagesize": 10000, "sort": sort, "date": date}
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        return (r.json().get("data") or {}).get("pool") or []
    except Exception as e:
        print(f"[Screen V3] Error: {e}")
        return []

def fetch_zt_pool(date_yyyymmdd):
    pool = _em_zt_api("getTopicZTPool", "fbt:asc", date_yyyymmdd)
    result = []
    for p in pool:
        code = p["c"]
        if code.startswith(('300', '301', '688')):
            continue
        result.append({
            'code': code, 'name': p["n"],
            'price': p["p"] / 1000, 'pct': round(p["zdp"], 2),
            'turnover': round(p["hs"], 2), 'limit_days': p["lbc"],
            'first_seal': _fmt_zt_time(p["fbt"]),
            'last_seal': _fmt_zt_time(p["lbt"]),
            'seal_fund': p["fund"], 'break_times': p["zbc"],
            'industry': p.get("hybk", ""), 'amount': p.get("amount", 0),
            'float_cap': p.get("ltsz", 0),
        })
    return result

def get_today():
    today = datetime.now()
    if today.hour < 15: today = today - timedelta(days=1)
    while today.weekday() >= 5: today = today - timedelta(days=1)
    return today.strftime('%Y-%m-%d')

def get_lp(code):
    return 0.20 if (code.startswith('30') or code.startswith('688')) else 0.10

def is_limit_up(close, prev_close, lpct):
    if prev_close is None or prev_close <= 0: return False
    return close >= round(prev_close * (1 + lpct), 2) - 0.005

def load_kline(name, code):
    # Try name_code format first, then code-only
    fpath = os.path.join(BASE, 'data', 'kline_data', f'{name}_{code}.json')
    if not os.path.exists(fpath):
        fpath = os.path.join(BASE, 'data', 'kline_data', f'{code}.json')
    if os.path.exists(fpath):
        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Unwrap dict format: {'metadata':..., 'data':[...]} -> list
        if isinstance(data, dict) and 'data' in data:
            data = data['data']
        # Normalize field names (old format uses volume_lots, new uses volume)
        for k in data:
            if 'volume' not in k and 'volume_lots' in k:
                k['volume'] = k['volume_lots'] * 100  # lots → shares
        return data
    return None

def sigmoid(x, k=0.1, x0=50):
    """Sigmoid: raw score → 0-1 probability. k=steepness, x0=midpoint."""
    return 1.0 / (1.0 + math.exp(-k * (x - x0)))

def compute_v3_score(code, klines, details_raw=None):
    """
    V3.0 六维动态权重评分 + Sigmoid概率映射

    六维: 上涨动能 | 封单强度 | 市场人气 | 形态溢价 | 资金结构 | 题材驱动
    首板: 题材(30%) + 人气(20%) + 资金(20%) + 动能(15%) + 封单(10%) + 形态(5%)
    连板: 动能(30%) + 封单(25%) + 资金(20%) + 人气(10%) + 形态(10%) + 题材(5%)
    """
    if len(klines) < 25: return None, None

    for k in klines:
        for field in ['open', 'close', 'high', 'low']:
            k[field] = round(k[field], 2)

    pdb = {}; prev_close = None; lpct = get_lp(code)

    for i, k in enumerate(klines):
        dt = k['date']; o = k['open']; c = k['close']
        h = k['high']; l = k['low']; v = k['volume']
        entry = {'open': o, 'close': c, 'high': h, 'low': l, 'volume': v,
                 'is_limit_up': False, 'prev_close': prev_close, 'gap_open_pct': 0}
        if prev_close and prev_close > 0:
            entry['is_limit_up'] = is_limit_up(c, prev_close, lpct)
            entry['gap_open_pct'] = round((o - prev_close) / prev_close * 100, 2)
        if i >= 5:
            entry['vol_ma5'] = sum(klines[j]['volume'] for j in range(i-4, i+1)) / 5
        else: entry['vol_ma5'] = v
        if i >= 20:
            entry['vol_ma20'] = sum(klines[j]['volume'] for j in range(i-19, i+1)) / 20
        else: entry['vol_ma20'] = v
        entry['vol_ratio5'] = round(v / entry['vol_ma5'], 2) if entry['vol_ma5'] > 0 else 1
        entry['vol_ratio20'] = round(v / entry['vol_ma20'], 2) if entry['vol_ma20'] > 0 else 1

        if h > 0 and l > 0:
            if abs(h - l) < 0.001: entry['is_one_line'] = True
            elif h > l:
                us = (h - max(o, c)) / (h - l); body = abs(c - o) / (h - l)
                entry['is_one_line'] = (us < 0.1 and body < 0.1)
            else: entry['is_one_line'] = False
        else: entry['is_one_line'] = False

        cons = 0
        for j in range(i-1, max(i-10, -1), -1):
            cd_ = klines[j]['date']
            if cd_ in pdb and pdb[cd_]['is_limit_up']: cons += 1
            else: break
        entry['cons_lu_before'] = cons
        pdb[dt] = entry; prev_close = c

    today_dt = klines[-1]['date']
    if today_dt not in pdb or not pdb[today_dt]['is_limit_up']:
        return None, None

    t1 = pdb[today_dt]; cons = t1['cons_lu_before']
    is_first_board = (cons == 0)

    # === 六维子分 (0-100每维) ===

    # 1. 上涨动能 (Upward Momentum) — gap + T-2 LU
    momentum = 0
    g = t1['gap_open_pct']
    if g >= 9.5: momentum += 50
    elif g >= 5: momentum += 35
    elif g >= 3: momentum += 20
    elif g >= 0: momentum += 10
    else: momentum -= 20
    if len(klines) >= 3:
        t2_date = klines[-3]['date']
        if t2_date in pdb and pdb[t2_date]['is_limit_up']: momentum += 20
    t2_lu = len(klines) >= 3 and klines[-3]['date'] in pdb and pdb[klines[-3]['date']]['is_limit_up']
    momentum = max(0, min(100, momentum + 30))

    # 2. 封单强度 (Seal Strength) — seal_time + break_times + one_line
    seal = 50
    if details_raw:
        st = details_raw.get('seal_time', '1459')
        if st and st != '?':
            try:
                t_int = int(st[:4])
                if t_int <= 930: seal += 30
                elif t_int <= 1000: seal += 15
                elif t_int <= 1030: seal += 5
                elif t_int >= 1400: seal -= 25
            except: pass
        zhaban = details_raw.get('zhaban', 0)
        seal -= zhaban * 10
    if t1.get('is_one_line', False): seal += 20
    seal = max(0, min(100, seal))

    # 3. 市场人气 (Market Sentiment) — turnover + volume
    sentiment = 40
    turnover = details_raw.get('turnover', 5) if details_raw else 5
    if 2 <= turnover <= 8: sentiment += 25
    elif 8 < turnover <= 15: sentiment += 10
    elif turnover > 15: sentiment -= 10
    if cons >= 2: vr = t1['vol_ratio5']
    else: vr = t1['vol_ratio20']
    if vr < 0.5: sentiment += 20
    elif vr < 1.0: sentiment += 10
    elif vr > 3.0: sentiment -= 15
    sentiment = max(0, min(100, sentiment))

    # 4. 形态溢价 (Pattern Premium) — 一字板 + 连板数
    pattern = 30
    if t1.get('is_one_line', False): pattern += 30
    if cons == 0: pattern += 10
    elif cons == 1: pattern += 25
    elif cons == 2: pattern += 20
    elif cons >= 3: pattern += 10
    pattern = max(0, min(100, pattern))

    # 5. 资金结构 (Capital Structure) — float_cap + volume
    capital = 40
    if details_raw:
        fcap = details_raw.get('float_cap', 0)
        if 0 < fcap < 5e9: capital += 25
        elif 5e9 <= fcap < 2e10: capital += 15
        elif fcap >= 5e10: capital -= 10
    if vr < 0.7: capital += 15
    capital = max(0, min(100, capital))

    # 6. 题材驱动 (Theme/Catalyst) — sector resonance + dow effect
    theme = 30
    if details_raw:
        sc = details_raw.get('sector_count', 1)
        if sc >= 5: theme += 30
        elif sc >= 3: theme += 15
        elif sc >= 2: theme += 5
    tomorrow = datetime.strptime(today_dt, '%Y-%m-%d') + timedelta(days=1)
    while tomorrow.weekday() >= 5: tomorrow += timedelta(days=1)
    dow = tomorrow.weekday()
    if dow == 0: theme += 20
    elif dow == 4: theme -= 10
    theme = max(0, min(100, theme))

    # === 动态权重 ===
    if is_first_board:
        # 首板: 题材30% + 人气20% + 资金20% + 动能15% + 封单10% + 形态5%
        score = (theme * 0.30 + sentiment * 0.20 + capital * 0.20 +
                 momentum * 0.15 + seal * 0.10 + pattern * 0.05)
    else:
        # 连板: 动能30% + 封单25% + 资金20% + 人气10% + 形态10% + 题材5%
        score = (momentum * 0.30 + seal * 0.25 + capital * 0.20 +
                 sentiment * 0.10 + pattern * 0.10 + theme * 0.05)

    # Sigmoid → 次日连板概率
    prob = sigmoid(score, k=0.08, x0=55)

    return score, prob, {
        'vr20': vr, 'gap': t1['gap_open_pct'],
        'cons': cons + 1, 'one_line': t1.get('is_one_line', False),
        'open': t1['open'], 'close': t1['close'],
        't2_lu': t2_lu, 'tomorrow_dow': dow,
        'momentum': momentum, 'seal': seal, 'sentiment': sentiment,
        'pattern': pattern, 'capital': capital, 'theme': theme,
        'is_first_board': is_first_board,
    }

def main():
    today = get_today()
    print(f'[Screen V3] Target date: {today}')

    today_yyyymmdd = today.replace('-', '')
    pool = fetch_zt_pool(today_yyyymmdd)
    if not pool:
        print('[Screen V3] No LU stocks found')
        return
    print(f'[Screen V3] Eligible LU stocks: {len(pool)}')

    sector_counts = {}
    for s in pool:
        ind = s['industry']; sector_counts[ind] = sector_counts.get(ind, 0) + 1

    results = []
    for s in pool:
        code = s['code']; name = s['name']
        klines = load_kline(name, code)
        if klines is None: continue

        details_raw = {
            'seal_time': s['first_seal'].replace(':', ''),
            'final_seal_time': s['last_seal'].replace(':', ''),
            'zhaban': s['break_times'],
            'sector_count': sector_counts.get(s['industry'], 1),
            'industry': s['industry'], 'turnover': s['turnover'],
            'float_cap': s['float_cap'],
        }

        score, prob, details = compute_v3_score(code, klines, details_raw)
        if score is not None:
            results.append({
                'code': code, 'name': name,
                'score': round(score, 1), 'prob': round(prob * 100, 1),
                'vr20': details['vr20'], 'gap': details['gap'],
                'cons': details['cons'], 'one_line': details['one_line'],
                'open': details['open'], 'close': details['close'],
                'seal_time': s['first_seal'], 'industry': s['industry'],
                'turnover': s['turnover'],
                'dim_m': details['momentum'], 'dim_s': details['seal'],
                'dim_p': details['sentiment'], 'dim_t': details['pattern'],
                'dim_c': details['capital'], 'dim_d': details['theme'],
                'is_first': details['is_first_board'],
            })

    results.sort(key=lambda x: x['prob'], reverse=True)

    non_one_line = [r for r in results if not r['one_line']]
    if len(non_one_line) >= 3:
        top3 = sorted(non_one_line, key=lambda x: x['prob'], reverse=True)[:3]
    elif results:
        top3 = sorted(results, key=lambda x: x['prob'], reverse=True)[:3]
    else:
        top3 = []
    top3_pick = sorted(top3, key=lambda x: x['vr20'])[0] if top3 else None

    print(f'\n{"="*110}')
    print(f' V3.0 候选清单 | {today} | 六维动态权重 + Sigmoid概率 | 首板/连板分别加权')
    print(f'{"="*110}')
    print(f'{"#":<3} {"代码":<8} {"名称":<8} {"概率":>6} {"评分":>6} {"量比":>5} {"gap":>7} {"板":>3} {"一字":>4} {"换手":>5} {"动能":>5} {"封单":>5} {"人气":>5} {"形态":>5} {"资金":>5} {"题材":>5} {"行业":<10}')
    print(f'{"-"*110}')
    for i, r in enumerate(results[:15]):
        flag = ' <<<' if r == top3_pick else (' ◄' if r in top3 else '')
        first_mark = '首' if r['is_first'] else '连'
        print(f'{i+1:<3} {r["code"]:<8} {r["name"]:<8} {r["prob"]:>5.1f}% {r["score"]:>5.0f} {r["vr20"]:>4.1f}x {r["gap"]:>+6.1f}% {r["cons"]:>2}{first_mark} {"Y" if r["one_line"] else "N":>4} {r["turnover"]:>4.1f}% {r["dim_m"]:>4.0f} {r["dim_s"]:>4.0f} {r["dim_p"]:>4.0f} {r["dim_t"]:>4.0f} {r["dim_c"]:>4.0f} {r["dim_d"]:>4.0f} {r["industry"]:<10}{flag}')
    print(f'{"="*110}')

    if top3_pick:
        print(f'\n>> V3首选: {top3_pick["name"]}({top3_pick["code"]}) '
              f'连板概率{top3_pick["prob"]:.1f}% 评分{top3_pick["score"]:.0f}')
        lo = top3_pick["close"] * 1.04; hi = top3_pick["close"] * 1.08
        print(f'>> 买入区间: {lo:.2f} - {hi:.2f}')

    output = {
        'date': today, 'version': 'v3.0',
        'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_candidates': len(results),
        'top_pick': top3_pick,
        'candidates': results[:20],
    }
    fpath = os.path.join(LOG_DIR, f'candidates_v3_{today}.json')
    with open(fpath, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f'\n[Screen V3] Saved: {fpath}')

if __name__ == '__main__':
    main()
