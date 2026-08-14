"""
盘后选股: 东财直连涨停池 → V2/V3评分(配置驱动) → 输出明日候选清单
"""
import json, os, sys, time, random, requests
# 强制utf-8输出, 避免Windows gbk崩溃
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scoring import (
    score_v2, score_v3, load_config as load_scoring_config,
    score_to_prob, score_to_position, get_buy_window, get_score_min,
    load_config
)
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
        print(f"[Screen] Error: {e}")
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

def load_kline(name, code):
    """加载K线: name_code.json 或 _code.json 或 code.json"""
    search_names = [f'{name}_{code}.json', f'_{code}.json', f'{code}.json']
    for fn in search_names:
        fp = os.path.join(BASE, 'data', 'kline_data', fn)
        if os.path.exists(fp):
            with open(fp, 'r', encoding='utf-8') as f:
                return json.load(f)
    # 模糊匹配
    import glob
    for fp in glob.glob(os.path.join(BASE, 'data', 'kline_data', f'*_{code}.json')):
        with open(fp, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def main():
    today = get_today()
    print(f'[Screen] Target date: {today}')

    today_yyyymmdd = today.replace('-', '')
    pool = fetch_zt_pool(today_yyyymmdd)
    if not pool:
        print('[Screen] No LU stocks found')
        return

    # Save snapshot
    snap_dir = os.path.join(BASE, 'data', 'zt_pool')
    os.makedirs(snap_dir, exist_ok=True)
    with open(os.path.join(snap_dir, f'{today_yyyymmdd}.json'), 'w') as fh:
        json.dump(pool, fh, ensure_ascii=False, indent=1)

    print(f'[Screen] Today LU stocks (eligible): {len(pool)}')

    sector_counts = {}
    for s in pool:
        ind = s['industry']; sector_counts[ind] = sector_counts.get(ind, 0) + 1

    cfg = load_scoring_config()
    version = cfg.get('active', 'v3')
    score_fn = score_v3 if version == 'v3' else score_v2

    results = []
    score_fail = 0
    fail_reasons = {}  # 评分失败原因统计 (2026-08-14新增, 便于定位根因)
    for s in pool:
        code = s['code']; name = s['name']
        klines = load_kline(name, code)
        if klines is None:
            score_fail += 1
            fail_reasons['无K线文件'] = fail_reasons.get('无K线文件', 0) + 1
            continue

        details_raw = {
            'seal_time': s['first_seal'].replace(':', ''),
            'final_seal_time': s['last_seal'].replace(':', ''),
            'zhaban': s['break_times'],
            'sector_count': sector_counts.get(s['industry'], 1),
            'industry': s['industry'], 'turnover': s['turnover'],
        }

        score, details = score_fn(code, klines, details_raw)
        if score is None:
            score_fail += 1
            kl = klines.get('data', klines) if isinstance(klines, dict) else klines
            if not kl or len(kl) < 25:
                reason = 'K线<25根'
            elif len(kl) >= 2 and kl[-2].get('close', 0) > 0 and \
                    (kl[-1].get('close', 0) - kl[-2]['close']) / kl[-2]['close'] < 0.098:
                reason = '末日非涨停(K线滞后)'
            else:
                reason = '活跃度过滤(近1年涨停<2)'
            fail_reasons[reason] = fail_reasons.get(reason, 0) + 1
            continue

        seal_duration = 0
        try:
            fbt = s['first_seal']; lbt = s['last_seal']
            fm = int(fbt[:2])*60 + int(fbt[3:5])
            lm = int(lbt[:2])*60 + int(lbt[3:5])
            seal_duration = lm - fm
        except: pass

        results.append({
            'code': code, 'name': name,
            'score': score, 'vr20': details['vr20'],
            'gap': details['gap'], 'cons': details['cons'],
            'one_line': details['one_line'],
            'true_one_line': details['true_one_line'],
            'open': details['open'], 'close': details['close'],
            'seal_time': s['first_seal'], 'seal_dur': seal_duration,
            'break_n': s['break_times'], 'last_seal': s['last_seal'],
            'industry': s['industry'], 'turnover': s['turnover'],
        })

    results.sort(key=lambda x: x['score'], reverse=True)

    # ⚡ 先保存JSON, 再打印(避免gbk编码崩溃导致文件丢失)
    one_line_today = [r for r in results if r.get('true_one_line', False)]
    preferred_pick_temp = None
    safe_temp = [r for r in results if not r.get('true_one_line', False)]
    safe_temp = [r for r in safe_temp if not (r.get('one_line') and r.get('cons', 1) >= 4)]
    non_one_temp = [r for r in safe_temp if not r['one_line']]
    if non_one_temp: preferred_pick_temp = non_one_temp[0]

    output = {
        'date': today, 'version': version,
        'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'total_candidates': len(results),
        'top_pick': preferred_pick_temp,
        'candidates': results,
        'one_line_watch': one_line_today[:10] if one_line_today else [],
    }
    fpath = os.path.join(LOG_DIR, f'candidates_{today}.json')
    with open(fpath, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Filter
    safe = [r for r in results if not r.get('true_one_line', False)]
    safe = [r for r in safe if not (r.get('one_line') and r.get('cons', 1) >= 4)]
    non_one_line = [r for r in safe if not r['one_line']]

    if len(non_one_line) >= 3:
        top3_by_score = sorted(non_one_line, key=lambda x: x['score'], reverse=True)[:3]
    elif len(safe) >= 3:
        top3_by_score = sorted(safe, key=lambda x: x['score'], reverse=True)[:3]
    else:
        top3_by_score = sorted(results, key=lambda x: x['score'], reverse=True)[:3]
    # V3.1: 直接选最高分 (回测验证 +11.2pp vs Top3最小量比)
    preferred_pick = top3_by_score[0] if top3_by_score else None

    # Output
    print(f'\n{"="*85}')
    print(f' 明日候选清单 | {today} 涨停股筛选 | {version}评分 | 6+年数据校准')
    print(f' 排除300/301/688/科创 | 一字板跳过 | 4板+一字过滤')
    print(f'{"="*85}')
    print(f'{"#":<3} {"代码":<8} {"名称":<8} {"评分":>5} {"量比":>5} {"gap":>6} {"板":>3} {"一":>3} {"换手":>5} {"首封":>8} {"回封":>5}分 {"炸":>2}次 {"末封":>8} {"行业":<8}')
    print(f'{"-"*100}')
    for i, r in enumerate(results[:15]):
        flag = ' <<<' if r == preferred_pick else (' <-' if r in top3_by_score else '')
        dur = f'{r.get("seal_dur",0)}' if r.get('seal_dur',0) > 0 else '-'
        brk = r.get('break_n', 0)
        lseal = r.get('last_seal', '?')
        print(f'{i+1:<3} {r["code"]:<8} {r["name"]:<8} {r["score"]:>5.0f} {r["vr20"]:>4.1f}x {r["gap"]:>+5.1f}% {r["cons"]:>3} {"Y" if r["one_line"] else "N":>3} {r["turnover"]:>4.1f}% {str(r["seal_time"]):>8} {dur:>5} {brk:>3} {str(lseal):>8} {r["industry"]:<8}{flag}')
    print(f'{"="*85}')

    if preferred_pick:
        preferred = preferred_pick
        sc = preferred['score']
        prob = score_to_prob(sc)
        pos = score_to_position(sc)
        lo = preferred['close'] * 1.04; hi = preferred['close'] * 1.08
        print(f'\n>> 首选: {preferred["name"]}({preferred["code"]}) 评分{sc:.0f} 量比{preferred["vr20"]:.1f}x')
        print(f'>> 连板概率≈{prob}% | 建议仓位: {pos}%')
        print(f'>> 买入区间: {lo:.2f} - {hi:.2f} (竞价涨幅4%-8%)')
        if len(top3_by_score) > 1:
            print(f'>> 备选: {top3_by_score[1]["name"]}({top3_by_score[1]["code"]}) | {top3_by_score[2]["name"]}({top3_by_score[2]["code"]})')
        risky_ol = [r for r in results if r.get('one_line') and r.get('cons', 1) >= 4]
        if risky_ol:
            names = ','.join(r['name'] for r in risky_ol[:3])
            print(f'>> [!] 已过滤高位一字板: {names}')

    # 一字板隔日关注
    one_line_today = [r for r in results if r.get('true_one_line', False)]
    if one_line_today:
        print(f'\n{"="*85}')
        print(f' [!] 一字板隔日关注 | 今日一字板({len(one_line_today)}只) -> 次日68%可交易, 连板率60.5%')
        print(f' 次日若竞价落入4-8%区间, 是重要加分项')
        print(f'{"="*85}')
        print(f'{"代码":<8} {"名称":<8} {"连板":>4} {"换手":>6} {"行业":<10} {"次日关注点"}')
        print(f'{"-"*65}')
        for r in one_line_today[:10]:
            cons = r.get('cons', 1)
            ref = r['close']
            lo = round(ref * 1.04, 2); hi = round(ref * 1.08, 2)
            warn = '[!]高危' if cons >= 4 else '[*]优先'
            print(f'{r["code"]:<8} {r["name"]:<8} {cons:>3}板 {r["turnover"]:>5.1f}% {r["industry"]:<10} {warn} 区间{lo}-{hi}')
        print(f'{"="*85}')

    min_score = get_score_min()
    filtered_count = sum(1 for r in results if r['score'] >= min_score)
    print(f'\n[Screen] 评分≥{min_score}: {filtered_count}/{len(results)}只 | 缺K线/评分失败: {score_fail}只')
    if fail_reasons:
        print(f'[Screen] 评分失败原因: {fail_reasons}')



if __name__ == '__main__':
    main()
