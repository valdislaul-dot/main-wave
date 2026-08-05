"""竞价观察面板 v2.1 — 次日9:25使用"""
import json, os
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

def is_low_open(today_open, yesterday_close):
    return today_open < yesterday_close

def main():
    data = load_latest_candidates()
    pf = load_portfolio()

    print('=' * 65)
    print('  竞价观察面板 v2.1')
    print(f'  日期: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print('=' * 65)

    # --- 持仓 ---
    if pf:
        # 兼容新旧格式: position(单对象) 或 positions(数组)
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

            # v2.1 卖出规则
            print(f'  ║')
            print(f'  ║  卖出规则 (v2.1):')
            print(f'  ║    昨涨停 + 今不低开(开≥昨收) → 持有')
            print(f'  ║    昨涨停 + 今低开(开<昨收)   → 卖出')
            print(f'  ║    昨断板 + 今gap<4%            → 卖出')
            print(f'  ║    昨断板 + 今gap≥4%            → 持有')
            print(f'  ║')
            print(f'  ║  执行: 涨停日→涨停价 | 不涨停日→70%(H+O)/2+30%收')

            # Show yesterday's reference prices + risk check
            kline_path = os.path.join(BASE, 'data', 'kline_data', f'{name}_{code}.json')
            if os.path.exists(kline_path):
                with open(kline_path) as fh: klines = json.load(fh)
                if len(klines) >= 2:
                    last = klines[-1]; prev = klines[-2]
                    ho2_prev = round((prev['high'] + prev['open']) / 2, 2)
                    ho2_last = round((last['high'] + last['open']) / 2, 2) if last['high'] > 0 else 0
                    print(f'  ║')
                    print(f'  ║  {prev["date"]} (H+O)/2=({prev["high"]}+{prev["open"]})/2={ho2_prev}')
                    print(f'  ║  {last["date"]} (H+O)/2=({last["high"]}+{last["open"]})/2={ho2_last}')
                if len(klines) >= 3:
                    cons = 0; j = len(klines) - 2
                    while j >= 1:
                        if klines[j]['close'] >= round(klines[j-1]['close']*1.10, 2) - 0.005:
                            cons += 1; j -= 1
                        else: break
                    board_num = cons + 1
                    last = klines[-1]
                    is_ol = (last['high']>0 and last['low']>0 and
                             (abs(last['high']-last['low'])<0.001 or
                              (last['high']>last['low'] and abs(last['close']-last['high'])<0.001)))
                    if board_num >= 4 and is_ol:
                        print(f'  ║')
                        print(f'  ║  [!] 高危持仓: {board_num}板一字/T字板, 回撤风险极高')
                        print(f'  ║  建议: 不低开则持有但需高度警惕, 一旦低开立即卖出')

            print(f'  ╚══════════════════════════════════════════╝')
        else:
            print(f'\n  --- 空仓 ---')

    # --- 候选 ---
    if data:
        print(f'\n  --- 候选标的 (T-1={data["date"]}涨停股筛选) ---')
        print(f'  规则: V2评分≥30 | 剔除300/301/688 | 一字板跳过 | 连板≥2用5日量比')
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
            t1_gap = c.get('gap', 0)  # T-1 day's open gap

            pos_type = '全仓' if score >= 30 else '半仓'

            # T-1 one-line → likely still one-line on buy day → can't execute
            if one_line:
                mark = '[一字板 跳过]'
            else:
                mark = f'竞价目标: {lo:.2f}-{hi:.2f}'

            print(f'  #{i+1} {c["name"]}({code})  {score:.0f}分  '
                  f'量比{vr20:.1f}x  {cons}板  T-1gap{t1_gap:+.1f}%  换手{turnover:.1f}%  '
                  f'{pos_type}  {mark}')

        # Top pick: use screen_candidates logic → Top3 by score → lowest vol ratio
        non_one_line = [c for c in data['candidates'][:15] if not c.get('one_line', False)]
        if non_one_line:
            # Sort by score desc, take top 3, then pick lowest volume
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

    print(f'\n  --- 操作步骤 ---')
    print(f'  9:25 竞价结束 → 判断持仓:')
    print(f'    昨涨停? → 是→不低开→持 | 否→断板→gap<4%→卖')
    print(f'  9:30 执行:')
    print(f'    卖出: 涨停日挂涨停价 | 不涨停日挂半程价')
    print(f'    买入: 候选竞价4%-8%区间, 一字板跳过')
    print(f'  14:45 限价单未成交→市价兜底')
    print(f'=' * 65)

    # ====== 保存今日竞价快照（全量涨停池+候选） ======
    try:
        from auction_pool import capture_auction
        capture_auction()
    except Exception as e:
        print(f'\n[WARN] 竞价池采集失败: {e}')

if __name__ == '__main__':
    main()
