"""
盘后选股 v2.1：东财直连涨停池 → V2评分 → 输出明日候选清单
数据源：东财 push2ex（替代 akshare，减少依赖）
"""
import json, os, time, random, requests
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(BASE, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# === 东财防封 ===
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

# === 涨停池 (东财 push2ex, 零鉴权) ===
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
        print(f"[Screen] Error fetching LU pool: {e}")
        return []

def fetch_zt_pool(date_yyyymmdd):
    """拉取涨停池，返回标准化列表"""
    pool = _em_zt_api("getTopicZTPool", "fbt:asc", date_yyyymmdd)
    result = []
    for p in pool:
        code = p["c"]
        # 排除 300/301/688
        if code.startswith(('300', '301', '688')):
            continue
        result.append({
            'code': code,
            'name': p["n"],
            'price': p["p"] / 1000,
            'pct': round(p["zdp"], 2),
            'turnover': round(p["hs"], 2),
            'limit_days': p["lbc"],
            'first_seal': _fmt_zt_time(p["fbt"]),
            'last_seal': _fmt_zt_time(p["lbt"]),
            'seal_fund': p["fund"],
            'break_times': p["zbc"],
            'industry': p.get("hybk", ""),
            'amount': p.get("amount", 0),
            'float_cap': p.get("ltsz", 0),
        })
    return result

def get_today():
    today = datetime.now()
    if today.hour < 15:
        today = today - timedelta(days=1)
    while today.weekday() >= 5:
        today = today - timedelta(days=1)
    return today.strftime('%Y-%m-%d')

def get_lp(code):
    return 0.20 if (code.startswith('30') or code.startswith('688')) else 0.10

def is_limit_up(close, prev_close, lpct):
    if prev_close is None or prev_close <= 0:
        return False
    return close >= round(prev_close * (1 + lpct), 2) - 0.005

def load_kline(name, code):
    fpath = os.path.join(BASE, 'data', 'kline_data', f'{name}_{code}.json')
    if os.path.exists(fpath):
        with open(fpath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def compute_v2_score(code, klines, details_raw=None):
    """V2.1 multi-board scoring with 5-day volume for 连板≥2"""
    if len(klines) < 25:
        return None, None

    # Round prices to 2 decimals
    for k in klines:
        for field in ['open', 'close', 'high', 'low']:
            k[field] = round(k[field], 2)

    pdb = {}
    prev_close = None
    lpct = get_lp(code)

    for i, k in enumerate(klines):
        dt = k['date']
        o = k['open']; c = k['close']
        h = k['high']; l = k['low']; v = k['volume']

        entry = {'open': o, 'close': c, 'high': h, 'low': l, 'volume': v,
                 'is_limit_up': False, 'prev_close': prev_close, 'gap_open_pct': 0}
        if prev_close and prev_close > 0:
            entry['is_limit_up'] = is_limit_up(c, prev_close, lpct)
            entry['gap_open_pct'] = round((o - prev_close) / prev_close * 100, 2)
        if i >= 5:
            entry['vol_ma5'] = sum(klines[j]['volume'] for j in range(i-4, i+1)) / 5
        else:
            entry['vol_ma5'] = v
        if i >= 20:
            entry['vol_ma20'] = sum(klines[j]['volume'] for j in range(i-19, i+1)) / 20
        else:
            entry['vol_ma20'] = v
        entry['vol_ratio5'] = round(v / entry['vol_ma5'], 2) if entry['vol_ma5'] > 0 else 1
        entry['vol_ratio20'] = round(v / entry['vol_ma20'], 2) if entry['vol_ma20'] > 0 else 1

        if h > 0 and l > 0:
            if abs(h - l) < 0.001:
                entry['is_one_line'] = True
            elif h > l:
                us = (h - max(o, c)) / (h - l)
                body = abs(c - o) / (h - l)
                entry['is_one_line'] = (us < 0.1 and body < 0.1)
            else:
                entry['is_one_line'] = False
        else:
            entry['is_one_line'] = False

        cons = 0
        for j in range(i-1, max(i-10, -1), -1):
            cd_ = klines[j]['date']
            if cd_ in pdb and pdb[cd_]['is_limit_up']:
                cons += 1
            else:
                break
        entry['cons_lu_before'] = cons
        pdb[dt] = entry
        prev_close = c

    today_dt = klines[-1]['date']
    if today_dt not in pdb or not pdb[today_dt]['is_limit_up']:
        return None, None

    t1 = pdb[today_dt]
    cons = t1['cons_lu_before']
    score = 0.0

    # Volume (v2.2: 6-tier data-driven, 44,590 samples/3yr)
    # 连板≥2用5日均量, 否则20日 (5日区分度-16.7% vs 20日-11.4%)
    if cons >= 2:
        vr = t1['vol_ratio5']
    else:
        vr = t1['vol_ratio20']

    if vr < 0.3: score += 37       # 极度缩量: 连板率71.0%, n=1,259
    elif vr < 0.5: score += 19      # 缩量: 48.0%, n=1,322
    elif vr < 0.7: score += 7       # 偏缩量: 33.2%, n=1,861
    elif vr < 1.0: score -= 1       # 正常偏低: 22.8%, n=4,155
    elif vr < 3.0: score -= 3       # 正常~放量: 20.8%, n=26,961(合并)
    else: score += 0                # 巨量: 24.0%, n=9,032(不扣不加)

    # Board strength (v2.2: 6-tier data-driven, 44,590 samples/3,284 stocks/3yr)
    g = t1['gap_open_pct']
    if g >= 9: score += 20       # 极强: 连板率49.0%, n=6,479
    elif g >= 7: score += 6      # 强: 32.3%, n=1,445
    elif g >= 3: score += 1      # 偏强: 25.0%, n=6,699
    elif g >= -1: score -= 5     # 死亡区[-1%,3%): 17.8%, n=25,471
    elif g >= -3: score -= 3     # 微低开: 21.0%, n=3,483
    else: score += 2             # 深低开<-3%反转: 27.3%, n=1,013

    # Board seal quality (v2.2: 区分一字板 vs T字板)
    if t1.get('is_one_line', False):
        if abs(t1['high'] - t1['low']) < 0.001:
            score += 20       # 真一字板: 全天封死, 连板率46.4%
        else:
            score += 10       # T字板: 炸板回封, 连板率22.6%(暂定, 待快照校准)

    # Consecutive boards (v2.2: 2板15%<基线, 3-4甜蜜区29%, 5板+36%高回撤)
    if cons == 0: score -= 4        # 2板: 连板率15.0%, n=32,237
    elif cons <= 2: score += 10     # 3-4板甜蜜区: 28.9%, n=8,078
    else: score += 15               # 5板+: 36.4%, 但日内亏损-5.5%

    # Day-of-week
    tomorrow = datetime.strptime(today_dt, '%Y-%m-%d') + timedelta(days=1)
    while tomorrow.weekday() >= 5:
        tomorrow = tomorrow + timedelta(days=1)
    dow = tomorrow.weekday()
    if dow == 0: score += 2       # v2.2: 周一连板率26.3%(+2.0%), n=8,492
    elif dow == 4: score -= 1      # v2.2: 周五22.9%(-1.4%), n=8,252

    # T-2 LU: removed (redundant with 连板数, already captured)
    t2_lu = False  # kept for details dict

    # Seal time factor
    if details_raw is None:
        details_raw = {}
    seal_time = details_raw.get('seal_time', '1459')
    if seal_time and seal_time != '?':
        try:
            st = int(seal_time[:4])
            if st <= 930: score += 12
            elif st <= 1000: score += 8
            elif st <= 1030: score += 4
            elif st <= 1100: score += 0
            elif st <= 1400: score -= 5
            else: score -= 10
        except: pass

    # 炸板 factor
    zhaban = details_raw.get('zhaban', 0)
    final_seal = details_raw.get('final_seal_time', seal_time)
    if zhaban > 0:
        try:
            fst = int(final_seal[:4]) if final_seal and final_seal != '?' else 1500
            vr20_val = t1.get('vol_ratio20', 2)
            if fst <= 1000:
                score -= zhaban * 2
            elif fst <= 1400:
                score -= zhaban * 6
            else:
                if vr20_val < 1.5:
                    score -= zhaban * 3
                elif vr20_val < 3.0:
                    score -= zhaban * 8
                else:
                    score -= zhaban * 15
        except:
            score -= zhaban * 5

    # Sector resonance
    sector_count = details_raw.get('sector_count', 1)
    if sector_count >= 5: score += 12
    elif sector_count >= 3: score += 6
    elif sector_count >= 2: score += 2

    return score, {
        'vr20': vr,
        'gap': t1['gap_open_pct'],
        'cons': cons + 1,
        'one_line': t1.get('is_one_line', False),
        'true_one_line': abs(t1['high'] - t1['low']) < 0.001,  # true one-line (h=l)
        'open': t1['open'],
        'close': t1['close'],
        't2_lu': t2_lu,
        'tomorrow_dow': dow,
    }

def main():
    today = get_today()
    print(f'[Screen] Target date: {today}')

    # Fetch limit-up pool via 东财直连 (replaces akshare)
    today_yyyymmdd = today.replace('-', '')
    pool = fetch_zt_pool(today_yyyymmdd)
    if not pool:
        print('[Screen] No LU stocks found or API error')
        return

    # Save raw snapshot for future calibration (炸板/封板时间/板块共振)
    snap_dir = os.path.join(BASE, 'data', 'zt_pool')
    os.makedirs(snap_dir, exist_ok=True)
    with open(os.path.join(snap_dir, f'{today_yyyymmdd}.json'), 'w') as fh:
        json.dump(pool, fh, ensure_ascii=False, indent=1)

    print(f'[Screen] Today LU stocks (eligible): {len(pool)}')

    # Pre-compute sector counts
    sector_counts = {}
    for s in pool:
        ind = s['industry']
        sector_counts[ind] = sector_counts.get(ind, 0) + 1

    # Score each
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
            'industry': s['industry'],
            'turnover': s['turnover'],
        }

        score, details = compute_v2_score(code, klines, details_raw)
        if score is not None:
            # Compute seal speed from 涨停池 data (for display, not scoring yet)
            seal_duration = 0  # minutes from first to last seal
            try:
                fbt = s['first_seal']; lbt = s['last_seal']
                fm = int(fbt[:2])*60 + int(fbt[3:5])
                lm = int(lbt[:2])*60 + int(lbt[3:5])
                seal_duration = lm - fm
            except: pass

            results.append({
                'code': code, 'name': name,
                'score': score,
                'vr20': details['vr20'],
                'gap': details['gap'],
                'cons': details['cons'],
                'one_line': details['one_line'],
                'true_one_line': details['true_one_line'],
                'open': details['open'],
                'close': details['close'],
                'seal_time': s['first_seal'],
                'seal_dur': seal_duration,
                'break_n': s['break_times'],
                'last_seal': s['last_seal'],
                'industry': s['industry'],
                'turnover': s['turnover'],
            })

    results.sort(key=lambda x: x['score'], reverse=True)

    # v2.2 风控: ①过滤真一字板(全天封死, 易天地板) ②过滤4板+T字板(高回撤)
    safe = [r for r in results if not r.get('true_one_line', False)]  # 真一字板全跳过
    safe = [r for r in safe if not (r.get('one_line') and r.get('cons', 1) >= 4)]  # 4板+T字板过滤
    non_one_line = [r for r in safe if not r['one_line']]  # T字板可买(评分已折价)

    if len(non_one_line) >= 3:
        top3_by_score = sorted(non_one_line, key=lambda x: x['score'], reverse=True)[:3]
    elif len(safe) >= 3:
        top3_by_score = sorted(safe, key=lambda x: x['score'], reverse=True)[:3]
    else:
        top3_by_score = sorted(results, key=lambda x: x['score'], reverse=True)[:3]
    top3_for_pick = sorted(top3_by_score, key=lambda x: x['vr20'])

    # Output
    print(f'\n{"="*85}')
    print(f' 明日候选清单 | {today} 涨停股筛选 (v2.2 全市场3年数据校准)')
    print(f' 排除300/301/688 | 一字板跳过 | 连板≥2用5日量比 | gap6档数据驱动')
    print(f'{"="*85}')
    print(f'{"#":<3} {"代码":<8} {"名称":<8} {"评分":>5} {"量比":>5} {"gap":>6} {"板":>3} {"一":>3} {"换手":>5} {"首封":>8} {"回封":>5}分 {"炸":>2}次 {"末封":>8} {"行业":<8}')
    print(f'{"-"*100}')
    for i, r in enumerate(results[:15]):
        flag = ' <<<' if r in top3_for_pick else ''
        dur = f'{r.get("seal_dur",0)}' if r.get('seal_dur',0) > 0 else '-'
        brk = r.get('break_n', 0)
        lseal = r.get('last_seal', '?')
        print(f'{i+1:<3} {r["code"]:<8} {r["name"]:<8} {r["score"]:>5.0f} {r["vr20"]:>4.1f}x {r["gap"]:>+5.1f}% {r["cons"]:>3} {"Y" if r["one_line"] else "N":>3} {r["turnover"]:>4.1f}% {str(r["seal_time"]):>8} {dur:>5} {brk:>3} {str(lseal):>8} {r["industry"]:<8}{flag}')
    print(f'{"="*85}')

    # Probability estimate based on score
    if top3_for_pick:
        preferred = top3_for_pick[0]
        # Rough probability mapping (from 全市场V2总分 vs 连板率)
        sc = preferred['score']
        # v2.2 概率映射 (44,395样本/3,273股/3年数据校准)
        if sc >= 75: prob = 40
        elif sc >= 55: prob = 33
        elif sc >= 35: prob = 30
        elif sc >= 20: prob = 25
        elif sc >= 10: prob = 20
        else: prob = 14
        # v2.2 仓位建议
        if sc >= 40: pos_pct = 100
        elif sc >= 20: pos_pct = 50
        else: pos_pct = 33

        print(f'\n>> 首选: {preferred["name"]}({preferred["code"]}) 评分{sc:.0f} 量比{preferred["vr20"]:.1f}x')
        print(f'>> 连板概率≈{prob}% | 建议仓位: {pos_pct}%')
        lo = preferred['close'] * 1.04; hi = preferred['close'] * 1.08
        print(f'>> 买入区间: {lo:.2f} - {hi:.2f} (竞价涨幅4%-8%)')
        if len(top3_for_pick) > 1:
            print(f'>> 备选: {top3_for_pick[1]["name"]}({top3_for_pick[1]["code"]}) | {top3_for_pick[2]["name"]}({top3_for_pick[2]["code"]})')
        risky_ol = [r for r in results if r.get('one_line') and r.get('cons', 1) >= 4]
        if risky_ol:
            names = ','.join(r['name'] for r in risky_ol[:3])
            print(f'>> [!] 已过滤高位一字板: {names}')

    # Save
    output = {
        'date': today,
        'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_candidates': len(results),
        'top_pick': top3_for_pick[0] if top3_for_pick else None,
        'candidates': results,  # 全量保存
    }
    fpath = os.path.join(LOG_DIR, f'candidates_{today}.json')
    with open(fpath, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f'\n[Screen] Results saved: {fpath}')

if __name__ == '__main__':
    main()
