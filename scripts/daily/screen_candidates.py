"""
盘后选股 v3.0：东财直连涨停池 → V2/V3评分(配置驱动) → 输出明日候选清单
数据源：东财 push2ex（替代 akshare，减少依赖）
"""
import json, os, time, random, requests
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# v3: use unified scoring module
from scoring import (
    score_v2, score_v3, load_config as load_scoring_config,
    score_to_prob, score_to_position, get_buy_window, get_score_min,
    load_config
)
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
    """V3评分 — 委托给 scoring.score_v3, 使用活跃配置"""
    cfg = load_scoring_config()
    version = cfg.get('active', 'v3')
    return score_v3(code, klines, details_raw) if version == 'v3' else score_v2(code, klines, details_raw)

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
