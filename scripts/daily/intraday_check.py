# -*- coding: utf-8 -*-
"""盘中监控 — 开盘后5分钟判定 (2026-09-23)

落地 2026-09-23 验证通过的两条 A 盘中规则。

**双源验证**(2026-09-23, 两套独立数据源独立采集路径, 结论同向):
  | | 1分钟源 (minute_kline) | 5分钟源 (新浪全历史) |
  |---|---|---|
  | 窗口/样本 | 09-02~09-22, n=539 | 04-24~09-22, n=7910 |
  | 破0% 触发组涨停率 | 5% | 6.5% |
  | 破7% 未触发组涨停率 | 7% | 7% |
  | 破VWAP 触发率 | 98% | 93% |
  两源差异主要来自覆盖率: 1分钟源覆盖 56~90% 且采集到的偏强票 → 破7%触发组涨停率
  70% 被高估; 5分钟源接近全覆盖且**昨收与T+1收盘都取自同一份序列**(不依赖 K 线库,
  从根本上排除幸存者偏差) → 55% 更可信, 即 **1分钟版的幅度需按 7 折读**。

  ① 跌破 0%(昨收) → 走    触发率75%; 收盘涨停率 5% vs 未触发 59%(差 -54pt);
                           控制 gap 后三档仍是 6~7% vs 35~62%; 训练/检验段一致
  ③ 开盘后 5 分钟内破 +7% → 弱转强确认, 留
                           触发率25%; 收盘涨停率 57% vs 未触发 6%(差 +51pt);
                           控制 gap 后三档 45~52% vs 7~9%; 训练/检验段一致
     ⚠ 但 T+1 优势分档: gap 0-3% 档触发组 −0.58% vs 未触发 −0.50% **优势消失**,
       gap 3-5% −0.38% vs −2.57% / gap 5-8% +0.25% vs −4.98% 明显占优
       → 规则③保证"当日不卖是对的", 不保证次日, 次日仍按竞价面板重评

  ⚠ 未落地「跌破分时均线 → 走」: 触发率 93%(高开子样本 81%), 触发后到收盘 −0.60%
    vs 基线 −0.28%, 零区分度; 加强到"连续1小时在线下"触发率仍 57%。
    A 原意应是"有效跌破", 字面程序化会卖掉几乎所有持仓, 故保持人工判断。

  ⚠ 5分钟粒度固有近似: 破0%/破均线的**触发时刻精度 5 分钟**(1分钟源为 1 分钟);
    同一根 bar 内既破0%又破7%(振幅>7%巨震)无法分先后, 全窗口占 3.2%。

验证台: scripts/analysis_temp_intraday_rules_m5.py (5分钟全历史, 含 T+1 无偏列)
        scripts/analysis_temp_intraday_rules.py    (1分钟, 触发时刻精度更高)

用法:
  python scripts/daily/intraday_check.py                      # 实时(建议 9:36 跑)
  python scripts/daily/intraday_check.py --date 2026-09-22    # 复盘(读 data/minute_kline)
"""
import json, os, sys, io, urllib.request
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, 'scripts', 'daily'))

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
BREAK7 = 1.07          # 弱转强线 (+7%)
FIVE_MIN_END = '0935'  # 开盘后5分钟 = 09:31~09:35 这五根


# ---------------- 数据获取 ----------------

def fetch_quote(code):
    """腾讯实时: 昨收/今开/现价/涨跌幅"""
    mkt = 'sz' if code.startswith(('0', '3', '1')) else 'sh'
    try:
        req = urllib.request.Request(f'http://qt.gtimg.cn/q={mkt}{code}',
                                     headers={'User-Agent': UA})
        f = urllib.request.urlopen(req, timeout=10).read().decode('gbk').split('~')
        if len(f) < 33:
            return None
        return {'name': f[1], 'prev_close': float(f[4]), 'open': float(f[5]),
                'current': float(f[3]), 'change_pct': float(f[32])}
    except Exception:
        return None


def fetch_min1(code):
    """腾讯 mkline 1分钟 → [(HHMM, o, c, h, l), ...] 仅当日"""
    mkt = 'sz' if code.startswith(('0', '3', '1')) else 'sh'
    url = (f'https://ifzq.gtimg.cn/appstock/app/kline/mkline'
           f'?param={mkt}{code},m1,,320&_var=r')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA,
                                                   'Referer': 'https://gu.qq.com/'})
        d = urllib.request.urlopen(req, timeout=12).read().decode('gbk')
        rows = json.loads(d.split('=', 1)[1].strip())['data'][f'{mkt}{code}']['m1']
    except Exception:
        return None
    today = datetime.now().strftime('%Y%m%d')
    out = []
    for r in rows:
        t = str(r[0])
        if t[:8] != today:
            continue
        out.append((t[8:12], float(r[1]), float(r[2]), float(r[3]), float(r[4])))
    return out or None


def load_replay_bars(code, date):
    """复盘: 1分钟优先(精度高), 回退 5分钟全历史

    data/minute_kline 只有 09-02 起且覆盖 56~90%; data/m5_research 覆盖
    2026-04-24 起全票 → 加回退后任意历史日都能复盘。
    ⚠ 5分钟口径下"5分钟内破7%"用 09:35 那根bar判定, 与 1 分钟逐根等价;
      但触发**时刻**精度降到 5 分钟。
    """
    p = os.path.join(BASE, 'data', 'minute_kline', f'{code}_{date}.json')
    if os.path.exists(p):
        try:
            bars = json.load(open(p, encoding='utf-8')).get('min1') or []
            if bars:
                return [(str(b['t'])[8:12], float(b['o']), float(b['c']),
                         float(b['h']), float(b['l'])) for b in bars]
        except Exception:
            pass
    p = os.path.join(BASE, 'data', 'm5_research', f'{code}.json')
    if not os.path.exists(p):
        return None
    try:
        rows = json.load(open(p, encoding='utf-8')).get('m5') or []
    except Exception:
        return None
    # '2026-09-22 09:35' → '0935' 无冒号, 与 1 分钟源及 FIVE_MIN_END 同一格式
    return [(str(r[0])[11:13] + str(r[0])[14:16], float(r[1]), float(r[2]),
             float(r[3]), float(r[4]))
            for r in rows if str(r[0])[:10] == date] or None


def replay_prev_close(code, date, bars):
    """昨收: 优先 5分钟序列(与 bars 同源自洽), 回退 K 线库"""
    p = os.path.join(BASE, 'data', 'm5_research', f'{code}.json')
    if os.path.exists(p):
        try:
            rows = json.load(open(p, encoding='utf-8')).get('m5') or []
            prev = [r for r in rows if str(r[0])[:10] < date]
            if prev:
                return float(prev[-1][2])
        except Exception:
            pass
    kp = os.path.join(BASE, 'data', 'kline_data', f'{code}.json')
    if os.path.exists(kp):
        try:
            k = json.load(open(kp, encoding='utf-8'))
            k = k.get('data', k) if isinstance(k, dict) else k
            prev = [b for b in k if isinstance(b, dict) and str(b.get('date')) < date]
            if prev:
                return float(prev[-1]['close'])
        except Exception:
            pass
    return None


# ---------------- 规则判定 ----------------

def evaluate(bars, prev_close):
    """→ dict(break0=触发分钟或None, up7_5=触发分钟或None, high_pct, low_pct)

    bars: [(HHMM, o, c, h, l)] 升序
    """
    if not bars or prev_close <= 0:
        return None
    thr7 = prev_close * BREAK7
    t0 = t7 = None
    for hm, _o, _c, h, l in bars:
        if t0 is None and l <= prev_close:
            t0 = hm
        if t7 is None and h >= thr7 and hm <= FIVE_MIN_END:
            t7 = hm
    return {
        'break0': t0,
        'up7_5': t7,
        'last': bars[-1][0],
        'high_pct': (max(b[3] for b in bars) - prev_close) / prev_close * 100,
        'low_pct': (min(b[4] for b in bars) - prev_close) / prev_close * 100,
        'now_pct': (bars[-1][2] - prev_close) / prev_close * 100,
    }


def verdict(r, labeled=True):
    """规则 → 动作标签 (卖点动作是"走", 留是"留")"""
    if not r:
        return '—', '数据缺失'
    if r['break0'] and (not r['up7_5'] or r['break0'] < r['up7_5']):
        return '🔴 走', f"{r['break0'][:2]}:{r['break0'][2:]} 跌破0%(§7.1)"
    if r['up7_5']:
        return '🟢 留', f"{r['up7_5'][:2]}:{r['up7_5'][2:]} 破+7% 弱转强确认(§6.3)"
    if r['break0']:
        return '🟡 观察', f"{r['break0'][:2]}:{r['break0'][2:]} 破0%(先于弱转强)"
    return '⚪ 无触发', '按竞价面板原判'


# ---------------- 主流程 ----------------

def main():
    args = sys.argv[1:]
    date = None
    if '--date' in args:
        date = args[args.index('--date') + 1]
    replay = date is not None
    today = date or datetime.now().strftime('%Y-%m-%d')
    now_hm = datetime.now().strftime('%H:%M')

    print('=' * 65)
    print(f'  盘中监控{"(复盘)" if replay else ""}  日期: {today}'
          + ('' if replay else f'  {now_hm}'))
    print('=' * 65)

    # 可买池: 复用 9:25 竞价面板的落盘结果, 不重算评分
    rec_p = os.path.join(BASE, 'logs', 'daily_recommendations', f'{today}.json')
    buyable = []
    if os.path.exists(rec_p):
        try:
            buyable = json.load(open(rec_p, encoding='utf-8')).get('buyable') or []
        except Exception:
            pass
    else:
        print(f'  ⚠ 无 {today} 的可买池记录 — 请先跑 morning_check')

    pf_p = os.path.join(BASE, 'logs', 'portfolio.json')
    positions = []
    if os.path.exists(pf_p):
        try:
            pf = json.load(open(pf_p, encoding='utf-8'))
            positions = pf.get('positions') or ([pf['position']] if pf.get('position') else [])
        except Exception:
            pass

    def probe(code, name=''):
        if not replay:
            q = fetch_quote(code)
            return ((name or (q['name'] if q else '')), (q['prev_close'] if q else None),
                    fetch_min1(code))
        bars = load_replay_bars(code, today)
        return name, (replay_prev_close(code, today, bars) if bars else None), bars

    # 判定来自"开盘后5分钟", 结果来自"走完全天" —— 两者必须分列,
    # 否则复盘时会看到「🟢留 … 当日 −3.61%」像是规则出错了。
    rlab = '当日收' if replay else '现价'
    if replay:
        print('  (复盘: 左侧判定用开盘后5分钟, 右侧 %s 是该判定之后走完的结果)' % rlab)

    # ── 持仓 ──
    print()
    print('  ╔══ 📌 持仓处置 ════════════════════════════════════════╗')
    if not positions:
        print('  ║  空仓                                                 ║')
    for p in positions:
        code = str(p.get('code', '')).zfill(6)
        nm, pc, bars = probe(code, p.get('name', ''))
        r = evaluate(bars, pc) if (bars and pc) else None
        act, why = verdict(r)
        pct = (f'{rlab}{r["now_pct"]:+.2f}%') if r else '—'
        print(f'  ║  {act:<8} {nm}({code}) {pct:>14}  {why}')
    print('  ╚═══════════════════════════════════════════════════════╝')

    # ── 可买池 ──
    print()
    print('  🎯 今日可买池盘中状态 (来自 9:25 面板, 共 %d 只)' % len(buyable))
    for b in buyable:
        code = str(b.get('code', '')).zfill(6)
        nm, pc, bars = probe(code, b.get('name', ''))
        r = evaluate(bars, pc) if (bars and pc) else None
        act, why = verdict(r)
        pct = (f'{rlab}{r["now_pct"]:+.2f}%') if r else '—'
        star = '🧊' if b.get('ice') else '  '
        print(f'    {star}{act:<8} {nm}({code}) {pct:>14}  {why}')

    print()
    print('  规则依据 (2026-09-23 双源验证: 1分钟 n=539 / 5分钟全历史 n=7910; 跨期方向均一致)')
    print('    ① 跌破0%        → 走    触发75% | 收盘涨停率 5% vs 未触发 59%')
    print('                            控制gap后 6~7% vs 35~62% (gap0-3/3-5/5-8 三档)')
    print('    ③ 5分钟内破+7%  → 留    触发25% | 收盘涨停率 57% vs 未触发 6%')
    print('                            控制gap后 45~52% vs 7~9% (三档同向)')
    print('    ⚠ 破分时均线未落地: 触发率93%(近全体), 触发后到收盘 -0.60% vs 基线 -0.28%')
    print('      —— 字面程序化零区分度, 保持人工判断')
    print('    ⚠ 规则③在 gap 0-3% 档的 T+1 优势消失(-0.58% vs -0.50%),')
    print('      优势集中在 gap 3-8%(-0.38%/+0.25% vs -2.57%/-4.98%); 次日仍需重评')
    print('=' * 65)


if __name__ == '__main__':
    main()
