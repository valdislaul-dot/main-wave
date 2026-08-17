"""
推荐回看 — 盘后结算前一交易日竞价池「可买前三名」的收益
判定标准:
  - 有实际交易: 按交易日志真实买卖价统计(部分卖出按已实现+剩余按T+1收盘估值)
  - 无实际交易: T日开盘模拟买入 → T+1按V4.0卖点规则模拟卖出
  - 盈亏>0 = 推荐正确
用法:
  python review_recommendations.py              # 结算上一交易日
  python review_recommendations.py --date 2026-08-13
  python review_recommendations.py --history 10 # 累计统计
"""
import sys, os, json, urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AUCTION_DIR = os.path.join(BASE, 'data', 'auction')
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
LOG_DIR = os.path.join(BASE, 'logs')
REVIEW_FILE = os.path.join(LOG_DIR, 'recommendation_review.json')


# ── 日期工具 ──
def _walk_dates(start, step):
    """从start按step天步进, 返回有竞价快照的日期列表 (跳过周末, 防止周六脏快照被当作交易日)"""
    out, d = [], start
    for _ in range(8):
        if d.weekday() < 5 and os.path.exists(os.path.join(AUCTION_DIR, f'{d.strftime("%Y-%m-%d")}.json')):
            out.append(d.strftime('%Y-%m-%d'))
        d += timedelta(days=step)
    return out


def prev_trading_day(date_str):
    d = datetime.strptime(date_str, '%Y-%m-%d')
    days = _walk_dates(d + timedelta(days=-1), -1)
    return days[0] if days else None


def next_trading_day(date_str):
    d = datetime.strptime(date_str, '%Y-%m-%d')
    days = _walk_dates(d + timedelta(days=1), 1)
    return days[0] if days else None


# ── 数据加载 ──
def load_auction(date_str):
    p = os.path.join(AUCTION_DIR, f'{date_str}.json')
    if not os.path.exists(p):
        return []
    with open(p, 'r', encoding='utf-8') as f:
        d = json.load(f)
    return d if isinstance(d, list) else d.get('stocks', d.get('data', []))


def load_candidate_scores(date_str):
    """candidates_YYYY-MM-DD.json → {code: score}"""
    p = os.path.join(LOG_DIR, f'candidates_{date_str}.json')
    if not os.path.exists(p):
        return {}
    with open(p, 'r', encoding='utf-8') as f:
        d = json.load(f)
    return {c['code']: c.get('score', 0) for c in d.get('candidates', [])}


def get_top3(date_str):
    """竞价池可买标的按评分排序取前三 (与morning_check同逻辑: 快照分>0用快照, 否则用前日候选分)"""
    stocks = load_auction(date_str)
    prev_d = prev_trading_day(date_str)
    cand_scores = load_candidate_scores(prev_d) if prev_d else {}
    buyable = []
    for s in stocks:
        if not isinstance(s, dict) or not s.get('buyable'):
            continue
        code = s.get('code', '')
        if code.startswith(('300', '301', '688', '8', '9')):
            continue
        # 优先用当日候选文件分(快照分曾被candidates_v过期文件污染, 2026-08-14修复)
        score = cand_scores.get(code, 0) or s.get('score', 0)
        buyable.append({
            'code': code, 'name': s.get('name', '?'),
            'score': score, 'gap': s.get('gap_pct'),
            'prev_close': s.get('prev_close'), 'open': s.get('open'),
        })
    buyable.sort(key=lambda x: x['score'], reverse=True)
    return buyable[:3]


def get_bars(code, days=40):
    """腾讯日K接口 → {date: {open,high,low,close}} (qfq前复权, 自含一致性)"""
    mkt = 'sz' if code.startswith(('0', '3', '1')) else 'sh'
    url = f'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={mkt}{code},day,,,{days},qfq'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=10).read().decode('utf-8')
        d = json.loads(resp)
        rows = (d.get('data', {}).get(f'{mkt}{code}', {}) or {}).get('qfqday') or []
        bars = {}
        for r in rows:
            # 腾讯格式: [date, open, close, high, low, volume]
            bars[r[0]] = {'date': r[0], 'open': float(r[1]), 'close': float(r[2]),
                          'high': float(r[3]), 'low': float(r[4])}
        return bars
    except Exception:
        return {}


# ── 模拟交易 (V4.0简化版) ──
def simulate(buy, t_limit_up, t_close, t1):
    """T日开盘买入 → T+1按V4.0规则卖 → (卖价, 说明)"""
    gap1 = round((t1['open'] - t_close) / t_close * 100, 2)
    # 硬止损 -10% 无条件全卖
    if t1['low'] <= buy * 0.9:
        return round(buy * 0.9, 3), '硬止损-10%'
    if t_limit_up:
        if gap1 < 0:
            return round(t1['open'], 3), f'昨涨停低开{gap1:+.2f}%→竞价全卖'
        return round(t1['close'], 3), f'昨涨停高开{gap1:+.2f}%→持有至收盘'
    if gap1 >= 4:
        return round(t1['close'], 3), f'断板高开{gap1:+.2f}%≥4%→持有至收盘'
    return round(t1['open'], 3), f'断板gap{gap1:+.2f}%<4%→开盘卖'


def _find_trades(code):
    """交易日志中该股票的实际买卖 → (buys, sells), 每条含date/price/shares"""
    jp = os.path.join(LOG_DIR, 'trading_journal.json')
    if not os.path.exists(jp):
        return [], []
    with open(jp, 'r', encoding='utf-8') as f:
        journal = json.load(f)
    buys, sells = [], []
    for e in journal:
        if not isinstance(e, dict) or str(e.get('code', '')) != code:
            continue
        a = str(e.get('action', ''))
        price, shares = float(e.get('price', 0) or 0), int(e.get('shares', 0) or 0)
        if price <= 0 or shares <= 0:
            continue
        d = str(e.get('date', ''))[:10]
        if a == 'BUY' or '买入' in a:
            buys.append({'date': d, 'price': price, 'shares': shares})
        elif a == 'SELL' or '卖出' in a:
            sells.append({'date': d, 'price': price, 'shares': shares})
    return buys, sells


# ── 结算 ──
def review_date(date_str, verbose=True):
    today_str = datetime.now().strftime('%Y-%m-%d')
    t1_str = next_trading_day(date_str)
    if not t1_str or t1_str > today_str:
        if verbose:
            print(f'  {date_str} 推荐前三: T+1={t1_str or "?"} 数据未到, 等该日盘后结算')
        return None

    top3 = get_top3(date_str)
    if not top3:
        if verbose:
            print(f'  {date_str} 竞价池无可买标的, 跳过')
        return None

    results, missing = [], []
    for st in top3:
        bars = get_bars(st['code'])
        t_bar = bars.get(date_str)
        t1_bar = bars.get(t1_str)
        if not t_bar or not t1_bar:
            missing.append(st['name'])
            continue
        prev_dates = [d for d in bars if d < date_str]
        prev_bar = bars[max(prev_dates)] if prev_dates else None
        prev_close = prev_bar['close'] if prev_bar else st.get('prev_close')
        if not prev_close or prev_close <= 0:
            missing.append(st['name'])
            continue
        pct_t = (t_bar['close'] - prev_close) / prev_close * 100
        t_limit = pct_t >= 9.9
        gap1 = round((t1_bar['open'] - t_bar['close']) / t_bar['close'] * 100, 2)
        t1_limit = t1_bar['close'] >= t_bar['close'] * 1.099

        # ── 有实际交易 → 按真实买卖价统计; 无实际交易 → 模型模拟 ──
        buys, sells = _find_trades(st['code'])
        act_buys = [b for b in buys if b['date'] == date_str]
        act_sells = [s for s in sells if s['date'] <= t1_str]
        if act_buys:
            total_cost = sum(b['price'] * b['shares'] for b in act_buys)
            total_sh = sum(b['shares'] for b in act_buys)
            avg_buy = round(total_cost / total_sh, 3) if total_sh else 0
            realized = sum(s['price'] * s['shares'] for s in act_sells)
            sold_sh = sum(s['shares'] for s in act_sells)
            remain_sh = total_sh - sold_sh
            value = realized + remain_sh * t1_bar['close']
            pnl = round((value - total_cost) / total_cost * 100, 2)
            if sold_sh > 0 and remain_sh > 0:
                note = (f'实际: 买{total_sh}股@{avg_buy:.2f} → 卖{sold_sh}股@{round(realized / sold_sh, 2):.2f}'
                        f' + 持{remain_sh}股按T+1收盘{t1_bar["close"]:.2f}估值')
            elif sold_sh > 0:
                note = f'实际: 买{total_sh}股@{avg_buy:.2f} → 全卖@{round(realized / sold_sh, 2):.2f}'
            else:
                note = f'实际: 买{total_sh}股@{avg_buy:.2f} → 未卖, 按T+1收盘{t1_bar["close"]:.2f}估值'
            results.append({
                'rank': len(results) + 1, 'code': st['code'], 'name': st['name'], 'score': st['score'],
                'rec_gap': st['gap'],
                'T': {'open': avg_buy, 'close': t_bar['close'], 'limit_up': t_limit, 'pct': round(pct_t, 2)},
                'T1': {'gap': gap1, 'close': t1_bar['close'], 'limit_up': t1_limit},
                'sell': round(realized / sold_sh, 2) if sold_sh else t1_bar['close'],
                'note': note, 'pnl_pct': pnl, 'actual': True,
                'verdict': '✅推荐正确' if pnl > 0 else '❌推荐错误',
            })
            continue

        # 无实际交易 → V4.0模型模拟
        buy = t_bar['open']
        sell, note = simulate(buy, t_limit, t_bar['close'], t1_bar)
        pnl = round((sell - buy) / buy * 100, 2)
        results.append({
            'rank': len(results) + 1, 'code': st['code'], 'name': st['name'], 'score': st['score'],
            'rec_gap': st['gap'],
            'T': {'open': buy, 'close': t_bar['close'], 'limit_up': t_limit, 'pct': round(pct_t, 2)},
            'T1': {'gap': gap1, 'close': t1_bar['close'], 'limit_up': t1_limit},
            'sell': sell, 'note': note, 'pnl_pct': pnl,
            'verdict': '✅推荐正确' if pnl > 0 else '❌推荐错误',
        })

    summary = {
        'date': date_str, 'settled_on': t1_str,
        'total': len(results), 'wins': sum(1 for r in results if r['pnl_pct'] > 0),
        'avg_pnl': round(sum(r['pnl_pct'] for r in results) / len(results), 2) if results else 0,
        'stocks': results,
    }
    if missing:
        summary['missing'] = missing

    # 入库
    store = {}
    if os.path.exists(REVIEW_FILE):
        with open(REVIEW_FILE, 'r', encoding='utf-8') as f:
            store = json.load(f)
    store.setdefault('reviews', {})[date_str] = summary
    _recalc_stats(store)
    with open(REVIEW_FILE, 'w', encoding='utf-8') as f:
        json.dump(store, f, ensure_ascii=False, indent=2)

    if verbose:
        _print_summary(summary)
        _print_stats(store['stats'])
    return summary


def _recalc_stats(store):
    all_r = [r for v in store['reviews'].values() for r in v['stocks']]
    stats = {
        'total': len(all_r),
        'wins': sum(1 for r in all_r if r['pnl_pct'] > 0),
        'avg_pnl': round(sum(r['pnl_pct'] for r in all_r) / len(all_r), 2) if all_r else 0,
        'by_rank': {},
    }
    for rank in ('1', '2', '3'):
        rs = [r for v in store['reviews'].values() for r in v['stocks'] if str(r.get('rank')) == rank]
        stats['by_rank'][rank] = {
            'n': len(rs),
            'wins': sum(1 for r in rs if r['pnl_pct'] > 0),
            'avg_pnl': round(sum(r['pnl_pct'] for r in rs) / len(rs), 2) if rs else 0,
        }
    stats['win_rate'] = round(stats['wins'] / stats['total'] * 100, 1) if stats['total'] else 0
    store['stats'] = stats


def _print_summary(s):
    print(f'  ── {s["date"]} 推荐前三 · T+1={s["settled_on"]} ──')
    for i, r in enumerate(s['stocks'], 1):
        print(f'  #{i} {r["name"]}({r["code"]}) 评分{r["score"]} 推荐gap{r["rec_gap"]:+.1f}% | '
              f'T日{"涨停" if r["T"]["limit_up"] else "断板"}({r["T"]["pct"]:+.1f}%) T+1 gap{r["T1"]["gap"]:+.2f}% | '
              f'卖@{r["sell"]} [{r["note"]}] → {r["pnl_pct"]:+.2f}% {r["verdict"]}')
    if s.get('missing'):
        print(f'  [数据缺失] {", ".join(s["missing"])}')
    print(f'  小计: {s["wins"]}/{s["total"]} 正确, 平均收益 {s["avg_pnl"]:+.2f}%')


def _print_stats(stats):
    if not stats or not stats['total']:
        return
    print(f'  ── 累计统计 ──')
    print(f'  总推荐 {stats["total"]} 只 | 正确 {stats["wins"]} | 准确率 {stats["win_rate"]}% | 平均收益 {stats["avg_pnl"]:+.2f}%')
    for rank, s in stats.get('by_rank', {}).items():
        if s['n']:
            print(f'    第{rank}名: {s["wins"]}/{s["n"]} 正确, 平均 {s["avg_pnl"]:+.2f}%')


def review_previous_day():
    """run_pipeline钩子: 结算上一交易日"""
    d = prev_trading_day(datetime.now().strftime('%Y-%m-%d'))
    if d:
        review_date(d)
    else:
        print('  无历史竞价快照, 跳过推荐回看')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    args = sys.argv[1:]
    if '--history' in args:
        i = args.index('--history')
        n = int(args[i + 1]) if len(args) > i + 1 else 10
        store = {}
        if os.path.exists(REVIEW_FILE):
            with open(REVIEW_FILE, 'r', encoding='utf-8') as f:
                store = json.load(f)
        _print_stats(store.get('stats', {}))
        for d in sorted(store.get('reviews', {}))[-n:]:
            _print_summary(store['reviews'][d])
    else:
        date_str = None
        if '--date' in args:
            i = args.index('--date')
            if len(args) > i + 1:
                date_str = args[i + 1]
        date_str = date_str or prev_trading_day(datetime.now().strftime('%Y-%m-%d'))
        if not date_str:
            print('无历史竞价快照可结算')
        else:
            review_date(date_str)
