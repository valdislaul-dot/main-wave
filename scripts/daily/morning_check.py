"""竞价观察面板 v4.0 — 次日9:25使用
集成A的卖点引擎: 量能三态 + 封板质量 + 弱转强
"""
import json, os, sys
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(BASE, 'logs')


def load_latest_candidates():
    files = [f for f in os.listdir(LOG_DIR)
             if f.startswith('candidates_') and not f.startswith('candidates_v')]
    if not files: return None
    # 按文件名中日期排序(格式: candidates_YYYY-MM-DD.json)
    files.sort(key=lambda f: f.split('_')[1].replace('.json',''))
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
        for pos in pos_list:
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

                # ── K线新鲜度检查 (滞后→昨涨停/断板判断会失真) ──
                try:
                    _kp = os.path.join(BASE, 'data', 'kline_data', f'{code}.json')
                    if os.path.exists(_kp):
                        with open(_kp, 'r', encoding='utf-8') as _f:
                            _raw = json.load(_f)
                        _kl = _raw.get('data', _raw) if isinstance(_raw, dict) else _raw
                        _last = _kl[-1]['date'] if _kl else '?'
                        if _last < (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'):
                            print(f'  ║  ⚠ K线滞后(最新{_last}), 昨涨停/断板判断可能失真')
                except Exception:
                    pass

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
        if not pos_list:
            print(f'\n  --- 空仓 ---')

    # ── 加载今日竞价数据 ──
    today_auction_file = os.path.join(BASE, 'data', 'auction',
                                       f'{datetime.now().strftime("%Y-%m-%d")}.json')
    auction_stocks = []
    if os.path.exists(today_auction_file):
        with open(today_auction_file, 'r', encoding='utf-8') as f:
            auc_data = json.load(f)
        auction_stocks = auc_data.get('stocks', [])

    # ── 构建候选评分查找表 ──
    candidate_scores = {}
    if data:
        for c in data.get('candidates', []):
            candidate_scores[c['code']] = c

    # ── 今日竞价池买入候选（优先） ──
    buyable = []
    for s in auction_stocks:
        code = s.get('code', '')
        gap = s.get('gap_pct', 0)
        is_one_line = s.get('one_line', False)
        is_300 = code.startswith(('300', '301', '688'))

        if is_300 or is_one_line:
            continue
        if 4.0 <= gap <= 8.0:
            # 交叉候选评分（竞价池实时评分优先，无则用候选评分）
            cand = candidate_scores.get(code, {})
            auction_score = s.get('score', 0)
            cand_score = cand.get('score', 0)
            final_score = auction_score if auction_score > 0 else cand_score
            buyable.append({
                'code': code, 'name': s.get('name', ''),
                'gap': gap, 'score': final_score,
                'limit_days': s.get('limit_days', cand.get('cons', 1)),
                'vr20': cand.get('vr20', 0), 'turnover': cand.get('turnover', 0),
                'in_candidates': code in candidate_scores
            })

    buyable.sort(key=lambda x: x['score'], reverse=True)

    print(f'\n  ═══ 📊 今日竞价池 (gap 4%-8%, 非一字/非300) ═══')
    if buyable:
        for i, b in enumerate(buyable[:10]):
            score_str = f'{b["score"]:.0f}分' if b['score'] > 0 else '—'
            cand_mark = '★' if b['in_candidates'] else ' '
            print(f'  {cand_mark} {b["name"]}({b["code"]})  '
                  f'gap={b["gap"]:+.1f}%  {b["limit_days"]}板  '
                  f'score={score_str}')
    else:
        print(f'  (无符合条件的标的)')

    # ── 昨日候选（参考） ──
    if data:
        print(f'\n  --- 昨日候选参考 (T-1={data["date"]}, 已评分) ---')
        non_one_line = [c for c in data['candidates'][:15] if not c.get('one_line', False)]
        for i, c in enumerate(non_one_line[:5]):
            in_auction = any(a['code'] == c['code'] for a in buyable)
            mark = ' ← 今日竞价池内' if in_auction else ''
            print(f'  #{i+1} {c["name"]}({c["code"]})  {c["score"]:.0f}分  '
                  f'{c.get("cons",1)}板  T-1gap{c.get("gap",0):+.1f}%{mark}')

    # ── 一字板隔日关注 ──
    one_line_watch = data.get('one_line_watch', []) if data else []
    if one_line_watch:
        print(f'\n  ═══ ⚡ 一字板隔日关注 ═══')
        for r in one_line_watch[:5]:
            cons = r.get('cons', 1)
            warn = '⚠高危' if cons >= 4 else '★优先'
            print(f'  {r["name"]}({r["code"]}) {cons}板 {warn}')

    print(f'\n  --- 操作步骤 ---')
    print(f'  卖出: 看上方持仓判断')
    print(f'  买入: 从今日竞价池选, gap 4%-8%, 一字板跳过')
    print(f'  14:45 限价单未成交→市价兜底')
    print(f'=' * 65)

    # ── 竞价池采集 ──
    try:
        from auction_pool import capture_auction
        capture_auction()
    except Exception as e:
        print(f'\n[WARN] 竞价池采集失败: {e}')

    # ── 每日推荐记录（无论是否交易） ──
    try:
        today_str = datetime.now().strftime('%Y-%m-%d')
        rec_dir = os.path.join(BASE, 'logs', 'daily_recommendations')
        os.makedirs(rec_dir, exist_ok=True)
        rec_file = os.path.join(rec_dir, f'{today_str}.json')

        rec = {
            'date': today_str,
            'generated': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'total_in_pool': len(auction_stocks),
            'buyable_count': len(buyable),
            'top_pick': buyable[0] if buyable else None,
            'buyable': buyable,
            'position_status': (', '.join(p.get('name', '?') for p in pf.get('positions', [])) if pf and pf.get('positions') else (pf.get('position', {}).get('name', '空仓') if pf and pf.get('position') else '空仓')),
            'action_taken': None
        }
        # 每次运行覆盖写入(竞价9:25后才完整, 避免首次运行过早留下空数据)
        if datetime.now().strftime('%H:%M') >= '09:25' and buyable:
            with open(rec_file, 'w', encoding='utf-8') as f:
                json.dump(rec, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # 静默失败，不影响主流程


if __name__ == '__main__':
    main()
