"""回测对比: V3当前 vs V3改进(振幅+连板梯度)"""
import json, os, sys
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scoring import is_limit_up, get_lp, load_config, step_score_asc, step_score_desc

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
d = os.path.join(BASE, 'data', 'kline_data')
START = '2023-08-04'
END = '2026-08-05'
INIT = 200000

# Load all K-lines
files = [f for f in os.listdir(d) if f.endswith('.json') and '_' not in f]
all_klines = {}
for fn in files:
    fpath = os.path.join(d, fn)
    for enc in ['utf-8', 'gbk']:
        try:
            with open(fpath, 'r', encoding=enc) as f: raw = json.load(f)
            break
        except: pass
    else: continue
    if isinstance(raw, dict) and 'data' in raw: kls = raw['data']
    else: kls = raw
    if len(kls) < 25: continue
    if kls and 'volume_lots' in kls[0] and 'volume' not in kls[0]:
        for k in kls: k['volume'] = k.get('volume_lots', 0) * 100
    all_klines[fn.replace('.json', '')] = kls

print('{} stocks'.format(len(all_klines)))

# Trading days
trading_days = []
d0 = datetime.strptime(START, '%Y-%m-%d')
de = datetime.strptime(END, '%Y-%m-%d')
while d0 <= de:
    if d0.weekday() < 5: trading_days.append(d0.strftime('%Y-%m-%d'))
    d0 += timedelta(days=1)

cfg = load_config()
v3 = cfg['tables']['v3']

def score_current(code, sub_klines):
    """当前V3评分"""
    if len(sub_klines) < 25: return None
    lpct = get_lp(code)
    k = sub_klines[-1]; pk = sub_klines[-2]
    c=k['close']; o=k['open']; h=k['high']; l=k['low']; v=k['volume']; pc=pk['close']
    if not is_limit_up(c, pc, lpct): return None

    gap = (o-pc)/pc*100
    ma20 = sum(sub_klines[j]['volume'] for j in range(max(0,len(sub_klines)-21), len(sub_klines))) / min(len(sub_klines), 20)
    vr = v/ma20 if ma20>0 else 1

    cons = 0
    for j in range(len(sub_klines)-2, max(len(sub_klines)-15, -1), -1):
        if is_limit_up(sub_klines[j]['close'], sub_klines[j-1]['close'], lpct): cons += 1
        else: break

    # 一字板
    tol = False; ol = False
    if abs(h-l)<0.01: tol = ol = True
    elif h>l:
        us=(h-max(o,c))/(h-l); body=abs(c-o)/(h-l)
        if us<0.1 and body<0.1: ol=True

    weekday = datetime.strptime(sub_klines[-1]['date'],'%Y-%m-%d').weekday()
    return (step_score_asc(vr, v3['vr_tiers']) +
            step_score_desc(gap, v3['gap_tiers']) +
            (20 if tol else (10 if ol else 0)) +
            (-4 if cons==0 else (10 if cons<=2 else 15)) +
            (2 if weekday==0 else (-1 if weekday==4 else 0)))

def score_improved(code, sub_klines):
    """V3改进: 振幅因子 + 连板梯度"""
    base = score_current(code, sub_klines)
    if base is None: return None

    k = sub_klines[-1]; pk = sub_klines[-2]
    h=k['high']; l=k['low']; pc=pk['close']
    amp = (h-l)/pc*100 if pc>0 else 0
    amp_score = 3 if amp<2 else (-5 if amp<6 else (2 if amp<10 else 5))

    return base + amp_score

def run_sim(scorer, label):
    cash = INIT; holding = None; trades = []
    for ti, today in enumerate(trading_days):
        # Sell
        if holding:
            hkls = holding['klines']; code = holding['code']
            si = None
            for i in range(holding['idx']+1, min(holding['idx']+5, len(hkls))):
                if hkls[i]['date'] == today: si = i; break
            if si:
                sk = hkls[si]; pk = hkls[si-1]
                gap = (sk['open']-pk['close'])/pk['close']*100
                ylu = is_limit_up(pk['close'], hkls[si-2]['close'] if si>=2 else 0, get_lp(code))
                sp = sk['open']
                if sk['low'] <= holding['bp']*0.9:
                    sp = round(holding['bp']*0.9, 2)
                elif ylu and gap < 0: sp = sk['high']
                elif not ylu and gap < 4:
                    sp = 0.7*(sk['high']+sk['open'])/2+0.3*sk['close']
                if ti == len(trading_days)-1 or sk['low'] <= holding['bp']*0.9 or (ylu and gap < 0) or (not ylu and gap < 4):
                    pnl = (sp-holding['bp'])/holding['bp']*100
                    cash = holding['shares'] * sp
                    trades.append({'pnl':pnl})
                    holding = None

        # Buy
        if not holding and cash > 0 and ti > 0:
            prev = trading_days[ti-1]
            candidates = daily_candidates.get(prev, [])
            if candidates:
                candidates.sort(key=lambda x: x[1], reverse=True)
                top3 = candidates[:3]
                best = top3[0]  # Just top score for simplicity
                code, score, bkls, idx = best
                bi = None
                for i in range(idx+1, min(idx+5, len(bkls))):
                    if bkls[i]['date'] == today: bi = i; break
                if bi and bi < len(bkls):
                    bp = bkls[bi]['open']
                    if bp > 0:
                        shares = int(cash/bp/100)*100
                        if shares >= 100:
                            cash -= shares*bp
                            holding = {'code':code, 'klines':bkls, 'idx':bi, 'bp':bp, 'shares':shares}

    if holding:
        sp = holding['klines'][-1]['close']
        pnl = (sp-holding['bp'])/holding['bp']*100
        cash = holding['shares']*sp
        trades.append({'pnl':pnl})

    ret = (cash-INIT)/INIT*100
    wr = sum(1 for t in trades if t['pnl']>0)/max(len(trades),1)*100
    print('  {}: {:,.0f} ({:+.1f}%) {}笔 {:.0f}%胜'.format(label, cash, ret, len(trades), wr))
    return ret

# Pre-scan candidates
print('Pre-scanning...')
daily_candidates_v3 = {}
daily_candidates_imp = {}
for ti, day in enumerate(trading_days):
    if ti % 100 == 0: print('  {}/{}...'.format(ti, len(trading_days)), end='\r')
    cands_v3 = []; cands_imp = []
    for code, kls in all_klines.items():
        for i in range(max(25,len(kls)-5), len(kls)):
            if kls[i]['date'] == day:
                s1 = score_current(code, kls[:i+1])
                if s1 and s1 >= 10:
                    cands_v3.append((code, s1, kls, i))
                s2 = score_improved(code, kls[:i+1])
                if s2 and s2 >= 10:
                    cands_imp.append((code, s2, kls, i))
                break
    daily_candidates_v3[day] = cands_v3
    daily_candidates_imp[day] = cands_imp

print('\nRunning V3 current...')
daily_candidates = daily_candidates_v3
r1 = run_sim(score_current, 'V3当前')
print('Running V3 improved...')
daily_candidates = daily_candidates_imp
r2 = run_sim(score_improved, 'V3改进')
print('\n差异: {:+.1f}%'.format(r2-r1))
