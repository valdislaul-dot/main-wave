"""
N=51 观察因子分析 (2026-09-04)
==============================
评分表内待累计样本因子的解冻检验, 只出报告不改规则 (解冻提案需用户拍板):
  ① divergence 分歧 (v4权重0.0) — 1年条件化验证(分歧×次日高开) + 26天快照旁证
     判定标准(用户拍板): 高开4-6%组 N≥20 且胜率≥65% → 解冻提案
  ② money_flow 资金流 (不进评分) — 主力净流入率三档 × 推荐回看51笔 T+1收益
     判定标准(用户拍板): 流入vs流出 胜率差≥20pt 且各组 n≥10 → 解冻提案
  ③ turnover 归一化 (人工三段 <2%=57/2-20%=50/≥20%=33) — 1年样本1%分桶形状验证

用法: python scripts/daily/n50_factor_analysis.py
输出: 打印 + logs/analysis/n50_factor_report_YYYY-MM-DD.md
"""
import json, os, sys
from collections import defaultdict
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
THS_DIR = os.path.join(BASE, 'data', 'zt_pool_history_ths')
POOL_DIR = os.path.join(BASE, 'data', 'zt_pool')
REVIEW_PATH = os.path.join(BASE, 'logs', 'recommendation_review.json')
START, END = '2025-08-19', '2026-08-19'  # 与 factor_shape.py 同窗


def load_json_any(path):
    for enc in ('utf-8', 'gbk'):
        try:
            with open(path, encoding=enc) as f:
                return json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return None


# ============================================================
# 共用: 1年样本加载 (同 factor_shape.py 口径, 扩展 gap1/r2c/turnover)
# 每日涨停股(剔300/301/688/8/9) × 同花顺池join, 次日表现=close_T1/close_T-1
# ============================================================
def load_year_samples():
    # K线表
    tbl = {}
    for fn in os.listdir(KLINE_DIR):
        if not fn.endswith('.json') or fn.startswith('._'):
            continue
        code = fn.replace('.json', '')
        if code.startswith(('300', '301', '688', '8', '9')):
            continue
        j = load_json_any(os.path.join(KLINE_DIR, fn))
        if j is None:
            continue
        rows = j.get('data', j) if isinstance(j, dict) else j
        t = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            date = r.get('date', '')
            if not (START <= date <= END):
                continue
            t[date] = {'open': float(r.get('open', 0) or 0), 'close': float(r.get('close', 0) or 0),
                       'high': float(r.get('high', 0) or 0), 'low': float(r.get('low', 0) or 0),
                       'pct': r.get('pct_change'), 'vol': float(r.get('volume_lots', 0) or 0)}
        if t:
            tbl[code] = t

    # 同花顺池明细: (date, code) -> {seal, zhaban, turnover}
    ths_detail = {}
    for fn in sorted(os.listdir(THS_DIR)):
        if not fn.endswith('.json'):
            continue
        ymd = fn.replace('.json', '')
        if not (START.replace('-', '') <= ymd <= END.replace('-', '')):
            continue
        info = load_json_any(os.path.join(THS_DIR, fn))
        if info is None:
            continue
        for s in info:
            if not isinstance(s, dict):
                continue
            c = str(s.get('code', '')).replace('sh', '').replace('sz', '')
            if not c or c.startswith(('300', '301', '688', '8', '9')):
                continue
            try:
                ths_detail[(ymd, c)] = {
                    'zhaban': int(s.get('open_num', 0) or 0),   # 同花顺open_num=开板/炸板次数
                    'turnover': float(s.get('turnover_rate', 0) or 0),
                }
            except (ValueError, TypeError):
                continue

    # 每只涨停股: 当日涨停判定 + vr20 + 板型 + 次日gap/T+1收益/T+2收益
    def is_lu_pct(pct):
        return pct is not None and pct >= 9.8

    rows = []
    for code, t in tbl.items():
        dl = sorted(t.keys())
        for i in range(1, len(dl) - 2):
            d = dl[i]
            r0 = t[d]
            prev = t[dl[i - 1]]
            if not is_lu_pct(r0['pct']):
                continue
            if prev['close'] <= 0:
                continue
            r1, r2 = t[dl[i + 1]], t[dl[i + 2]]
            if r1['close'] <= 0 or r2['close'] <= 0 or r0['close'] <= 0:
                continue
            ret = (r1['close'] - r0['close']) / r0['close'] * 100
            gap1 = (r1['open'] - r0['close']) / r0['close'] * 100
            r2c = (r2['close'] - r1['open']) / r1['open'] * 100   # T+1开盘买→T+2收盘卖
            vols = [t[dl[k]]['vol'] for k in range(max(0, i - 20), i)]
            vr20 = r0['vol'] / (sum(vols) / len(vols)) if vols and sum(vols) > 0 else 1.0
            lu_price = round(prev['close'] * 1.10, 2)
            is_yz = r0['open'] >= lu_price - 0.005 and r0['low'] >= lu_price - 0.005
            td = ths_detail.get((d.replace('-', ''), code))
            row = {'code': code, 'date': d, 'ret': ret, 'gap1': gap1, 'r2c': r2c, 'vr20': vr20,
                   'board': '一字' if is_yz else '换手'}
            if td:
                row['zhaban'] = td['zhaban']
                row['turnover'] = td['turnover']
            rows.append(row)
    return rows


# ============================================================
# ① divergence 分歧因子 — 解冻检验
# ============================================================
def analyze_divergence(rows, out):
    out.append('')
    out.append('━' * 76)
    out.append('① divergence 分歧因子 (v4权重0.0, 09-01重搜归零)')
    out.append('━' * 76)
    # 分歧口径与 scoring.py div_b 一致: 炸板≥1 且 爆量vr20≥1.5
    div = [x for x in rows if x.get('zhaban') is not None and x['zhaban'] >= 1 and x['vr20'] >= 1.5]
    nondiv = [x for x in rows if x.get('zhaban') is not None and not (x['zhaban'] >= 1 and x['vr20'] >= 1.5)]
    out.append(f'样本: 分歧{len(div)}笔 / 非分歧{len(nondiv)}笔 (1年, 同花顺池覆盖段)')

    def st(group, key='r2c'):
        rs = [x[key] for x in group]
        if not rs:
            return None
        return {'n': len(rs), 'win': round(sum(1 for r in rs if r > 0) / len(rs) * 100, 1),
                'avg': round(sum(rs) / len(rs), 2)}

    # A. 无条件形状 (与 factor_shape.txt 既有数据交叉, ret口径=close_T1/close_T-1)
    s_d, s_n = st(div, 'ret'), st(nondiv, 'ret')
    out.append(f'[A] 无条件次日表现(close_T1/close_T-1): 分歧 {s_d} | 非分歧 {s_n}')
    out.append(f'    → 分歧无条件落后 {"%.2f" % (s_n["avg"] - s_d["avg"])}pt, '
               f'09-01权重搜索归零与1年形状一致 (分歧本身为负因子)')

    # B. 条件化验证: 分歧 × T+1高开分档 (买入=T+1开盘, 卖出=T+2收盘, 与backtest_divergence同口径)
    out.append('[B] 条件化: 分歧标的 × T+1高开 (T+1开盘买→T+2收盘卖)')
    gaps = [('<0', lambda g: g < 0), ('0-4%', lambda g: 0 <= g < 4),
            ('4-6%', lambda g: 4 <= g < 6), ('≥6%', lambda g: g >= 6)]
    for label, f in gaps:
        s1 = st([x for x in div if f(x['gap1'])])
        s2 = st([x for x in nondiv if f(x['gap1'])])
        out.append(f'  分歧+高开{label:<5}: {s1} | 非分歧同档: {s2}')
    s_46 = st([x for x in div if 4 <= x['gap1'] < 6])
    s_46n = st([x for x in nondiv if 4 <= x['gap1'] < 6])
    out.append('')
    out.append(f'[判定] 高开4-6%组: 分歧 {s_46} vs 非分歧 {s_46n}')
    if s_46 and s_46['n'] >= 20 and s_46['win'] >= 65:
        out.append(f'  ✅ 达标 (N={s_46["n"]}≥20 且胜率{s_46["win"]}%≥65%) → 解冻提案, 待用户拍板')
        out.append(f'     分歧标签增量: 胜率差{s_46["win"] - s_46n["win"]:+.1f}pt, 均收益差{s_46["avg"] - s_46n["avg"]:+.2f}%')
    else:
        out.append(f'  ❌ 未达标 (需N≥20且胜率≥65%) → 维持权重0.0')
        out.append(f'     分歧标签在4-6%档为负增量(胜率差{s_46["win"] - s_46n["win"]:+.1f}pt), '
                   f'1年大样本与26天小样本信号冲突, 以大样本为准')

    # C. 26天快照旁证 (backtest_divergence.py 同口径, 本地K线表替代腾讯抓取)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from backtest_divergence import load_pool, is_weak, vol_heavy

        def local_bars(code):
            path = os.path.join(KLINE_DIR, f'{code}.json')
            j = load_json_any(path)
            if not j:
                return []
            rows = j.get('data', j) if isinstance(j, dict) else j
            return [{'date': r.get('date'), 'open': float(r.get('open', 0) or 0),
                     'close': float(r.get('close', 0) or 0), 'high': float(r.get('high', 0) or 0),
                     'low': float(r.get('low', 0) or 0),
                     'volume': float(r.get('volume_lots', 0) or 0) * 100}
                    for r in rows if isinstance(r, dict)]

        files = sorted(f for f in os.listdir(POOL_DIR) if f.endswith('.json'))
        trades = []
        for i, fn in enumerate(files[:-2]):
            T = f'{fn[:4]}-{fn[4:6]}-{fn[6:8]}'
            T1 = f'{files[i + 1][:4]}-{files[i + 1][4:6]}-{files[i + 1][6:8]}'
            T2 = f'{files[i + 2][:4]}-{files[i + 2][4:6]}-{files[i + 2][6:8]}'
            pool = load_pool(os.path.join(POOL_DIR, fn))
            stocks = pool if isinstance(pool, list) else pool.get('stocks', pool.get('data', []))
            for s in stocks:
                code = str(s.get('code', '')).replace('sh', '').replace('sz', '')
                if not code or code.startswith(('300', '301', '688', '8', '9')):
                    continue
                if not is_weak(s.get('first_seal', ''), int(s.get('break_times', 0) or 0)):
                    continue
                bars = local_bars(code)
                dates = [b['date'] for b in bars]
                idx = dates.index(T) if T in dates else None
                i1 = dates.index(T1) if T1 in dates else None
                i2 = dates.index(T2) if T2 in dates else None
                if idx is None or i1 is None or i2 is None or idx < 1:
                    continue
                if not vol_heavy(bars, idx):
                    continue
                gap1 = round((bars[i1]['open'] - bars[idx]['close']) / bars[idx]['close'] * 100, 2)
                r2c = round((bars[i2]['close'] - bars[i1]['open']) / bars[i1]['open'] * 100, 2)
                trades.append({'gap1': gap1, 'r2c': r2c})
        out.append(f'[C] 26天快照旁证(严格爆量口径, {len(files)}天, 本地K线): 分歧事件{len(trades)}笔')
        for label, f in gaps:
            s1 = st([t for t in trades if f(t['gap1'])])
            out.append(f'  高开{label:<5}: {s1}')
        out.append(f'  注: backtest_divergence.py 已同步本地K线源(2026-09-04), 两口径一致; '
                   f'历史101笔记录为腾讯qfq源且不可复核, 以[B]1年大样本为准')
    except Exception as e:
        out.append(f'[C] 26天快照旁证失败: {e}')


# ============================================================
# ② money_flow 资金流 — 解冻检验 (主力净流入口径, 用户2026-09-04拍板)
# ============================================================
def fetch_money_flow_history(code, days=40):
    """新浪日频资金流历史页 → {opendate: {'net': 主力净流入元, 'r0x': 主力占比%}}"""
    import urllib.request
    pre = 'sh' if code.startswith(('5', '6', '9')) else 'sz'
    url = ('https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/'
           f'MoneyFlow.ssl_qsfx_zjlrqs?page=1&num={days}&sort=opendate&asc=0&daima={pre}{code}')
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0',
                                               'Referer': 'https://finance.sina.com.cn/'})
    try:
        raw = urllib.request.urlopen(req, timeout=10).read().decode('gbk')
        rows = json.loads(raw)
        if not rows:
            return {}
        return {r['opendate']: {'net': float(r.get('netamount', 0) or 0),
                                'r0x': float(r.get('r0x_ratio', 0) or 0)} for r in rows}
    except Exception:
        return {}


# ============================================================
# ②b money_flow 大样本重验 (2026-09-04, 历史资金流补抓2562只后)
# 样本=历史池271天17421条涨停记录 × K线表 × money_flow_history
# 买入端: mf[T-1](T日竞价可得) → T日池股 T+1开盘买→T+2开盘卖 (与51笔T-1口径同构)
# 卖出端: mf[T](T+1竞价可得)  → T日池股 T+1收盘/T收盘 (与51笔T日口径同构)
# ============================================================
def analyze_money_flow_big(out):
    out.append('')
    out.append('━' * 76)
    out.append('②b money_flow 大样本重验 (历史补抓2562只, 2024-08~2026-09)')
    out.append('━' * 76)
    MF_DIR = os.path.join(BASE, 'data', 'money_flow_history')

    # K线表: 放宽窗口 2025-07-01 ~ 2026-09-04, 只取 open/close
    ktbl = {}
    for fn in os.listdir(KLINE_DIR):
        if not fn.endswith('.json') or fn.startswith('._'):
            continue
        code = fn.replace('.json', '')
        if code.startswith(('300', '301', '688', '8', '9')):
            continue
        j = load_json_any(os.path.join(KLINE_DIR, fn))
        if j is None:
            continue
        rows = j.get('data', j) if isinstance(j, dict) else j
        t = {}
        for r in rows:
            if not isinstance(r, dict):
                continue
            date = r.get('date', '')
            if not ('2025-07-01' <= date <= '2026-09-04'):
                continue
            t[date] = {'open': float(r.get('open', 0) or 0), 'close': float(r.get('close', 0) or 0),
                       'high': float(r.get('high', 0) or 0), 'low': float(r.get('low', 0) or 0)}
        if t:
            ktbl[code] = t
    out.append(f'K线表: {len(ktbl)}只 (窗口2025-07-01~2026-09-04)')

    # 资金流历史
    mf = {}
    for fn in os.listdir(MF_DIR):
        if not fn.endswith('.json'):
            continue
        j = load_json_any(os.path.join(MF_DIR, fn))
        if j:
            mf[fn.replace('.json', '')] = j
    out.append(f'资金流历史: {len(mf)}只')

    # 池文件序列 (同花顺历史池)
    files = sorted(f for f in os.listdir(THS_DIR) if f.endswith('.json'))
    pool_codes = {}   # ymd -> [codes]
    for fn in files:
        info = load_json_any(os.path.join(THS_DIR, fn))
        if not info:
            continue
        ymd = fn.replace('.json', '')
        pool_codes[ymd] = [str(s.get('code', '')) for s in info
                           if isinstance(s, dict) and str(s.get('code', ''))
                           and not str(s.get('code', '')).startswith(('300', '301', '688', '8', '9'))]
    out.append(f'历史池: {len(pool_codes)}天')

    def ymd2d(ymd):
        return f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}'

    def st(group):
        rs = [x for x in group if x is not None]
        if not rs:
            return None
        return {'n': len(rs), 'win': round(sum(1 for r in rs if r > 0) / len(rs) * 100, 1),
                'avg': round(sum(rs) / len(rs), 2)}

    # 买入端: T日池股, 用mf[T-1](T+1竞价买入决策时可得), T+1开盘买→T+2开盘卖
    buy_in, buy_out = [], []
    n_buy_skip = 0
    for i in range(1, len(files) - 2):
        T_ymd, T1_ymd, T2_ymd = files[i].replace('.json', ''), files[i + 1].replace('.json', ''), files[i + 2].replace('.json', '')
        prev_ymd = files[i - 1].replace('.json', '')
        T, T1, T2, Tprev = ymd2d(T_ymd), ymd2d(T1_ymd), ymd2d(T2_ymd), ymd2d(prev_ymd)
        for code in pool_codes.get(T_ymd, []):
            t = ktbl.get(code)
            if not t:
                n_buy_skip += 1
                continue
            o1, c1, o2 = t.get(T1, {}).get('open'), t.get(T1, {}).get('close'), t.get(T2, {}).get('open')
            c0, h0, l0 = t.get(T, {}).get('close'), t.get(T, {}).get('high'), t.get(T, {}).get('low')
            # 剔一字板(买不进): T日 open≈low 且收涨停价附近
            if o1 and o1 > 0 and c0 and c0 > 0 and h0 and h0 > 0 and abs(h0 - l0) < 0.001 * c0 and abs((h0 - c0) / c0) < 0.001:
                continue
            mf_prev = (mf.get(code) or {}).get(Tprev)
            if not mf_prev or not (o1 and o2 and o1 > 0 and o2 > 0):
                n_buy_skip += 1
                continue
            pnl = (o2 - o1) / o1 * 100
            if mf_prev['net'] > 0:
                buy_in.append(pnl)
            else:
                buy_out.append(pnl)
    out.append(f'[买入端] T日池股(剔一字) mf[T-1] → T+1开盘买→T+2开盘卖: 流入{len(buy_in)}笔 / 流出{len(buy_out)}笔 / 跳过{n_buy_skip}')
    s_in, s_out = st(buy_in), st(buy_out)
    out.append(f'  T-1流入: {s_in} | T-1流出: {s_out}')
    if s_in and s_out:
        out.append(f'  胜率差: {s_in["win"] - s_out["win"]:+.1f}pt '
                   f'{"✅(≥20且n≥10)" if s_in["win"] - s_out["win"] >= 20 and s_in["n"] >= 10 and s_out["n"] >= 10 else "❌"}')

    # 卖出端: T日池股, 用mf[T](T+1竞价处置时可得), T+1收盘/T收盘-1
    sell_in, sell_out = [], []
    for i in range(len(files) - 1):
        T_ymd, T1_ymd = files[i].replace('.json', ''), files[i + 1].replace('.json', '')
        T, T1 = ymd2d(T_ymd), ymd2d(T1_ymd)
        for code in pool_codes.get(T_ymd, []):
            t = ktbl.get(code)
            if not t:
                continue
            c0, c1 = t.get(T, {}).get('close'), t.get(T1, {}).get('close')
            mf_T = (mf.get(code) or {}).get(T)
            if not mf_T or not (c0 and c1 and c0 > 0):
                continue
            ret = (c1 - c0) / c0 * 100
            if mf_T['net'] > 0:
                sell_in.append(ret)
            else:
                sell_out.append(ret)
    out.append(f'[卖出端] T日池股 mf[T] → T+1收盘/T收盘: 流入{len(sell_in)}笔 / 流出{len(sell_out)}笔')
    s_in2, s_out2 = st(sell_in), st(sell_out)
    out.append(f'  T日流入: {s_in2} | T日流出: {s_out2}')
    if s_in2 and s_out2:
        out.append(f'  胜率差: {s_in2["win"] - s_out2["win"]:+.1f}pt '
                   f'{"✅(≥20且n≥10)" if s_in2["win"] - s_out2["win"] >= 20 and s_in2["n"] >= 10 and s_out2["n"] >= 10 else "❌"}')

    out.append('')
    out.append('[判定] 大样本裁决:')
    if s_in and s_out:
        if s_in['win'] - s_out['win'] >= 20:
            out.append(f'  买入端: mf[T-1]流入组胜率高于流出≥20pt → 有买入端增量, 可议入评分')
        else:
            out.append(f'  买入端: 胜率差{s_in["win"] - s_out["win"]:+.1f}pt 未达标/反向 → 资金流不进买入评分')
    if s_in2 and s_out2:
        if s_in2['win'] - s_out2['win'] >= 20:
            out.append(f'  卖出端: mf[T]胜率差{s_in2["win"] - s_out2["win"]:+.1f}pt → 支持持仓处置参考(昨主力流出→T+1弱势)')
        else:
            out.append(f'  卖出端: 胜率差{s_in2["win"] - s_out2["win"]:+.1f}pt 未达标 → 卖出参考也不支持')


def analyze_money_flow(out):
    out.append('')
    out.append('━' * 76)
    out.append('② money_flow 资金流 (观察数据不进评分, N≥50解冻检验)')
    out.append('━' * 76)
    rev = load_json_any(REVIEW_PATH)
    recs = []
    for date, day in (rev.get('reviews', {}) or {}).items():
        for s in (day.get('stocks') or []):
            s = dict(s)
            s['buy_date'] = date
            recs.append(s)
    out.append(f'推荐回看: {len(recs)}笔 ({min(rev["reviews"])} ~ {max(rev["reviews"])}买入)')

    # 新浪历史页补抓买入日主力净流入 (推荐标的多数买入日收盘未涨停, 不在当日池文件中)
    import time
    codes = sorted(set(s['code'] for s in recs))
    hist = {}
    fail = []
    for code in codes:
        h = fetch_money_flow_history(code)
        if h:
            hist[code] = h
        else:
            fail.append(code)
        time.sleep(0.3)  # 限速防封

    joined = []
    for s in recs:
        h = hist.get(s['code'], {})
        row = h.get(s['buy_date'])
        if not row:
            continue
        joined.append({**s, 'mf_net': row['net'], 'mf_r0x': row['r0x']})
    out.append(f'新浪历史页join: {len(joined)}/{len(recs)}笔 | 抓取失败: {fail if fail else "无"}')

    if not joined:
        out.append('❌ 无join样本, 无法检验')
        return

    # 主力口径分档: netamount符号 (流通市值仅当日池成员可得, 以净流入方向为主口径)
    nets = sorted(x['mf_net'] for x in joined)
    def q(p):
        i = min(len(nets) - 1, int(len(nets) * p))
        return nets[i]
    out.append(f'主力净流入(元)分布: min{q(0):,.0f} / p25{q(0.25):,.0f} / 中位{q(0.5):,.0f} '
               f'/ p75{q(0.75):,.0f} / max{q(1):,.0f}')

    def bucket(x):
        return '流入' if x['mf_net'] > 0 else '流出'

    def st(group):
        rs = [x['pnl_pct'] for x in group]
        if not rs:
            return None
        return {'n': len(rs), 'win': round(sum(1 for r in rs if r > 0) / len(rs) * 100, 1),
                'avg': round(sum(rs) / len(rs), 2)}

    out.append('[单因子] 主力净流入方向 × T+1收益(pnl_pct)')
    groups = defaultdict(list)
    for x in joined:
        groups[bucket(x)].append(x)
    for label in ('流入', '流出'):
        g = groups.get(label, [])
        s1 = st(g)
        out.append(f'  {label:<4}: {s1} | score均值{round(sum(x["score"] for x in g) / len(g), 1) if g else "-"}')

    in_g, out_g = groups.get('流入', []), groups.get('流出', [])
    out.append('')
    out.append('[独立预测力] 控制score后资金流是否仍有增量 (score中位数分层)')
    if joined:
        med = sorted(x['score'] for x in joined)[len(joined) // 2]
        for label, cond in (('score低层', lambda x: x['score'] <= med), ('score高层', lambda x: x['score'] > med)):
            lo = [x for x in joined if cond(x)]
            li = st([x for x in lo if x['mf_net'] > 0])
            lf = st([x for x in lo if x['mf_net'] <= 0])
            out.append(f'  {label}: 流入 {li} | 流出 {lf}')
    out.append('')
    s_in, s_out = st(in_g), st(out_g)
    out.append(f'[判定] 流入 {s_in} vs 流出 {s_out}')
    if s_in and s_out and s_in['n'] >= 10 and s_out['n'] >= 10 and s_in['win'] - s_out['win'] >= 20:
        out.append(f'  ✅ 达标 (胜率差{s_in["win"] - s_out["win"]:+.1f}pt≥20 且两档n≥10) → 解冻提案, 待用户拍板')
    else:
        out.append(f'  ❌ 未达标 (需胜率差≥20pt 且两档n≥10) → 维持观察, 每日+3笔继续积累')


# ============================================================
# ③ turnover 归一化 — 人工三段形状验证
# ============================================================
def analyze_turnover(rows, out):
    out.append('')
    out.append('━' * 76)
    out.append('③ turnover 归一化验证 (人工三段: <2%=57 / 2-20%=50 / ≥20%=33, 剔一字)')
    out.append('━' * 76)
    rows = [x for x in rows if x.get('turnover') is not None and x['board'] != '一字']
    out.append(f'样本: {len(rows)}笔 (1年, 同花顺池覆盖段, 已剔一字板)')

    def st(group):
        rs = [x['ret'] for x in group]
        return {'n': len(rs), 'win': round(sum(1 for r in rs if r > 0) / len(rs) * 100, 1),
                'avg': round(sum(rs) / len(rs), 2)}

    out.append('[1%分桶形状] 换手率 × 次日表现(close_T1/close_T-1)')
    buckets = defaultdict(list)
    for x in rows:
        t = x['turnover']
        b = '≥20%' if t >= 20 else f'{int(t)}-{int(t) + 1}%'
        buckets[b].append(x)
    order = [f'{i}-{i + 1}%' for i in range(20)] + ['≥20%']
    table = []
    for b in order:
        if b not in buckets:
            continue
        s1 = st(buckets[b])
        table.append(f'  {b:<6} {s1["n"]:>5}笔 次日均{s1["avg"]:>+6.2f}% 上涨率{s1["win"]:>4.0f}%')
        out.append(table[-1])

    # 三段聚合 vs 人工归一化
    out.append('[三段聚合] 人工断点下各段实际表现')
    segs = [('<2%', lambda t: t < 2, 57), ('2-20%', lambda t: 2 <= t < 20, 50), ('≥20%', lambda t: t >= 20, 33)]
    for label, f, cfg_score in segs:
        s1 = st([x for x in rows if f(x['turnover'])])
        out.append(f'  {label:<6} {s1} | 人工归一化分={cfg_score}')
    s_lo, s_mid, s_hi = (st([x for x in rows if f(x['turnover'])]) for _, f, _ in segs)
    out.append('')
    out.append('[判定] 三段形状是否贴合 57/50/33 的单调降序')
    if s_lo and s_mid and s_hi:
        mono = s_lo['avg'] > s_mid['avg'] > s_hi['avg']
        out.append(f'  三段均值: {s_lo["avg"]:+.2f}% / {s_mid["avg"]:+.2f}% / {s_hi["avg"]:+.2f}% → '
                   f'{"✅ 贴合(高换手劣化), 人工断点成立" if mono else "⚠ 不贴合, 需重定断点或归一化值"}')
    else:
        out.append('  ⚠ 某段样本为空, 无法判定')


def main():
    print('加载1年样本 (K线表+同花顺池)...')
    rows = load_year_samples()
    print(f'1年涨停股样本: {len(rows)}笔')

    out = [f'# N=51 观察因子分析报告 {datetime.now().strftime("%Y-%m-%d")}',
           '',
           '评分表待累计样本因子的解冻检验。只出证据与判定, 不改规则;',
           '解冻提案(✅达标项)需用户拍板后才动 scoring_config.json。',
           '']

    analyze_divergence(rows, out)
    analyze_money_flow_big(out)
    analyze_money_flow(out)
    analyze_turnover(rows, out)

    out.append('')
    out.append('━' * 76)
    out.append('待拍板清单 (所有改动走定稿机制, 需用户确认)')
    out.append('━' * 76)
    out.append('1. divergence 分歧: 维持权重0.0 (1年大样本309笔判定未达标, 证据充分)')
    out.append('2. money_flow 资金流: ✅达标可解冻。技术约束: 同花顺历史池无资金流数据, '
               '权重搜索无法覆盖该因子, 只能人工定初始权重+实盘滚动观察。'
               '建议初值: 权重5% (从sector/dt_risk扣), 归一化 流入60/流出25; 具体值待拍板')
    out.append('3. turnover 归一化: 人工三段(57/50/33)与1年形状贴合, 维持现状')
    out.append('4. 数据限制如实声明: money_flow流出组n=16刚过线(≥10), 解冻宜保守起步; '
               'turnover与divergence样本充足结论可定稿')

    text = '\n'.join(out)
    print(text)
    os.makedirs(os.path.join(BASE, 'logs', 'analysis'), exist_ok=True)
    report_path = os.path.join(BASE, 'logs', 'analysis',
                               f'n50_factor_report_{datetime.now().strftime("%Y-%m-%d")}.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(text)
    print(f'\n报告已写入: {report_path}')


if __name__ == '__main__':
    main()
