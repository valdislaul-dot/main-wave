"""竞价观察面板 v4.0 — 次日9:25使用
集成A的卖点引擎: 量能三态 + 封板质量 + 弱转强
"""
import json, os, sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(BASE, 'logs')


def load_latest_candidates():
    files = sorted([f for f in os.listdir(LOG_DIR) if f.startswith('candidates_')])
    if not files: return None
    with open(os.path.join(LOG_DIR, files[-1]), 'r', encoding='utf-8') as f:
        return json.load(f)


def load_portfolio():
    pf = os.path.join(LOG_DIR, 'portfolio.json')
    if os.path.exists(pf):
        with open(pf, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def fetch_live_quote(code):
    """获取实时行情 (腾讯API)"""
    import urllib.request
    try:
        mkt = 'sz' if code.startswith(('0', '3', '1')) else 'sh'
        url = f'http://qt.gtimg.cn/q={mkt}{code}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode('gbk')
        fields = data.split('~')
        return {
            'name': fields[1],
            'open': float(fields[5]),
            'prev_close': float(fields[4]),
            'current': float(fields[3]),
            'high': float(fields[33]),
            'low': float(fields[34]),
            'change_pct': float(fields[32]),
            'limit_up': float(fields[47]) if len(fields) > 47 else 0,
        }
    except Exception as e:
        print(f'  [WARN] 无法获取{code}实时行情: {e}')
        return None


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    data = load_latest_candidates()
    pf = load_portfolio()

    print('=' * 65)
    print('  竞价观察面板 v4.0 — 集成A卖点引擎')
    print(f'  日期: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print('=' * 65)

    # ── 持仓 + 卖点判断 ──
    if pf:
        pos_list = pf.get('positions', [])
        if not pos_list:
            pos_single = pf.get('position')
            if pos_single:
                pos_list = [pos_single]
        pos = pos_list[0] if pos_list else None

        if pos:
            name = pos['name']; code = pos['code']
            cost = pos['buy_price']; shares = pos['shares']
            buy_date = pos.get('buy_date', '?')

            print(f'\n  ╔══ 当前持仓 ═══════════════════════════════╗')
            print(f'  ║  {name}({code})  成本:{cost:.2f}  股数:{shares}股')
            print(f'  ║  买入日: {buy_date}')

            # ── 获取实时行情 → 卖点判断 ──
            quote = fetch_live_quote(code)
            if quote:
                gap_pct = round((quote['open'] - quote['prev_close']) / quote['prev_close'] * 100, 2)

                # 调用卖点引擎
                try:
                    from sell_engine import sell_signal, sell_execution_price
                    signal = sell_signal(pos, {
                        'open': quote['open'],
                        'prev_close': quote['prev_close'],
                        'gap_pct': gap_pct,
                        'current_price': quote['current']
                    })
                    exec_info = sell_execution_price(signal, {
                        'open': quote['open'],
                        'high': quote['high'],
                        'close': quote['current'],
                        'prev_close': quote['prev_close'],
                        'limit_up_price': quote['limit_up']
                    }, pos)

                    urgency_mark = {'urgent': '🔴', 'normal': '🟡', 'now': '🔴'}.get(signal['urgency'], '⚪')

                    print(f'  ║')
                    print(f'  ║  今开: {quote["open"]:.2f} | 昨收: {quote["prev_close"]:.2f} | Gap: {gap_pct:+.2f}%')
                    print(f'  ║  现价: {quote["current"]:.2f} ({quote["change_pct"]:+.2f}%)')
                    print(f'  ║')
                    print(f'  ║  {urgency_mark} 卖点判断: {signal["reason"]}')
                    if signal['detail']:
                        print(f'  ║     └ {signal["detail"]}')
                    if signal['action'] in ('sell', 'sell_half'):
                        print(f'  ║  执行: {exec_info["note"]}')
                except Exception as e:
                    print(f'  ║  [ERR] 卖点引擎调用失败: {e}')
                    import traceback; traceback.print_exc()
            else:
                print(f'  ║  [WARN] 无法获取实时行情，跳过卖点判断')

            # ── 历史参考价 ──
            kline_path = os.path.join(BASE, 'data', 'kline_data', f'{name}_{code}.json')
            alt_path = os.path.join(BASE, 'data', 'kline_data', f'{code}.json')
            for kp in [kline_path, alt_path]:
                if os.path.exists(kp):
                    with open(kp, 'r', encoding='utf-8') as fh:
                        raw = json.load(fh)
                    klines = raw.get('data', raw) if isinstance(raw, dict) else raw
                    if len(klines) >= 2:
                        last = klines[-1]; prev = klines[-2]
                        ho2_prev = round((prev['high'] + prev['open']) / 2, 2)
                        ho2_last = round((last['high'] + last['open']) / 2, 2) if last['high'] > 0 else 0
                        print(f'  ║')
                        print(f'  ║  {prev["date"]} (H+O)/2=({prev["high"]}+{prev["open"]})/2={ho2_prev}')
                        print(f'  ║  {last["date"]} (H+O)/2=({last["high"]}+{last["open"]})/2={ho2_last}')
                    # 连板+高危检查
                    if len(klines) >= 3:
                        cons = 0; j = len(klines) - 2
                        while j >= 1:
                            if klines[j].get('pct_change', 0) >= 9.9 or \
                               (j > 0 and klines[j]['close'] >= round(klines[j-1]['close']*1.10, 2) - 0.005):
                                cons += 1; j -= 1
                            else: break
                        board_num = cons + 1
                        last_k = klines[-1]
                        is_ol = (last_k['high']>0 and last_k['low']>0 and
                                 (abs(last_k['high']-last_k['low'])<0.001 or
                                  (last_k['high']>last_k['low'] and abs(last_k['close']-last_k['high'])<0.001)))
                        if board_num >= 4 and is_ol:
                            print(f'  ║  ⚠ 高危: {board_num}板一字/T字板, 回撤风险极高')
                    break

            print(f'  ╚══════════════════════════════════════════╝')
        else:
            print(f'\n  --- 空仓 ---')

    # ── 候选标的 (盘后筛选, 仅作参考) ──
    if data:
        print(f'\n  --- 候选标的 (T-1={data["date"]}涨停股筛选, 仅供参考) ---')
        print(f'  规则: V2评分≥30 | 剔除300/301/688 | 一字板跳过')
        print(f'  买入区间: 竞价涨幅 4%-8%')
        print()

        for i, c in enumerate(data['candidates'][:8]):
            ref = c['close']
            lo = ref * 1.04; hi = ref * 1.08
            score = c['score']
            vr20 = c.get('vr20', 1)
            cons = c.get('cons', 1)
            one_line = c.get('one_line', False)
            turnover = c.get('turnover', 0)
            code = c['code']
            t1_gap = c.get('gap', 0)

            pos_type = '全仓' if score >= 30 else '半仓'
            mark = '[一字板 跳过]' if one_line else f'竞价目标: {lo:.2f}-{hi:.2f}'

            print(f'  #{i+1} {c["name"]}({code})  {score:.0f}分  '
                  f'量比{vr20:.1f}x  {cons}板  T-1gap{t1_gap:+.1f}%  换手{turnover:.1f}%  '
                  f'{pos_type}  {mark}')

        # Top pick
        non_one_line = [c for c in data['candidates'][:15] if not c.get('one_line', False)]
        if non_one_line:
            top3 = sorted(non_one_line, key=lambda x: x['score'], reverse=True)[:3]
            best = min(top3, key=lambda x: x.get('vr20', 99))
            bl = best['close'] * 1.04; bh = best['close'] * 1.08
            print(f'\n  >>> 首选: {best["name"]}({best["code"]}) '
                  f'评分{best["score"]:.0f}  量比{best.get("vr20",0):.1f}x  '
                  f'竞价目标: {bl:.2f}-{bh:.2f} (4%-8%)')
            for c2 in top3:
                if c2 != best:
                    bl2 = c2['close'] * 1.04; bh2 = c2['close'] * 1.08
                    print(f'  >>> 备选: {c2["name"]}({c2["code"]}) '
                          f'评分{c2["score"]:.0f}  量比{c2.get("vr20",0):.1f}x  '
                          f'竞价: {bl2:.2f}-{bh2:.2f}')
        else:
            print(f'\n  >>> 无非一字板候选，今日不买')

    # ── 一字板隔日关注 ──
    one_line_watch = data.get('one_line_watch', []) if data else []
    if one_line_watch:
        print(f'\n  ═══ ⚡ 一字板隔日关注 ═══')
        for r in one_line_watch[:5]:
            ref = r['close']
            lo = ref * 1.04; hi = ref * 1.08
            cons = r.get('cons', 1)
            warn = '⚠高危' if cons >= 4 else '★优先'
            print(f'  {r["name"]}({r["code"]}) {cons}板 {warn}  竞价目标: {lo:.2f}-{hi:.2f}')

    print(f'\n  --- 操作步骤 ---')
    print(f'  9:25 竞价结束 → 看卖点判断执行')
    print(f'  9:30: 涨停日→挂涨停价 | 不涨停日→70%(H+O)/2+30%收')
    print(f'  买入: 候选竞价4%-8%区间, 一字板跳过')
    print(f'  14:45 限价单未成交→市价兜底')
    print(f'=' * 65)

    # ── 竞价池采集 ──
    try:
        from auction_pool import capture_auction
        capture_auction()
    except Exception as e:
        print(f'\n[WARN] 竞价池采集失败: {e}')


if __name__ == '__main__':
    main()
