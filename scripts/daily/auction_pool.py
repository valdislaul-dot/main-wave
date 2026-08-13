"""
竞价池管理器 — 每日9:25采集，独立于涨停池
数据流:
  T-1盘后: 涨停池已更新，候选已筛选
  T日9:25: capture_auction() → 获取全市场竞价(腾讯API) → 保存快照 + 更新状态
  T日9:30: 参考竞价池做买入决策

文件:
  data/auction/YYYY-MM-DD.json  — 每日竞价快照（全量涨停池标的+候选）
  data/auction_state.json       — 竞价池状态（当前+历史汇总）
"""
import json, os, sys, urllib.request, time, random
from datetime import datetime, timedelta
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AUCTION_DIR = os.path.join(BASE, 'data', 'auction')
STATE_PATH = os.path.join(BASE, 'data', 'auction_state.json')
ZT_STATE_PATH = os.path.join(BASE, 'data', 'zt_pool_state.json')
LOG_DIR = os.path.join(BASE, 'logs')

os.makedirs(AUCTION_DIR, exist_ok=True)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def load_zt_pool_state():
    """加载当前涨停池标的列表"""
    if os.path.exists(ZT_STATE_PATH):
        with open(ZT_STATE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'stocks': [], 'as_of_date': ''}


def load_latest_candidates():
    """加载最新候选清单"""
    files = sorted([f for f in os.listdir(LOG_DIR) if f.startswith('candidates_')])
    if not files:
        return None
    with open(os.path.join(LOG_DIR, files[-1]), 'r', encoding='utf-8') as f:
        return json.load(f)


def fetch_quotes(codes):
    """
    批量获取实时行情（腾讯API）
    codes: ['000967', '603629', ...]
    返回: {code: {name, open, prev_close, price, high, low, volume, limit_up, gap_pct}}
    """
    quotes = {}
    # 分批，每批最多50只
    for i in range(0, len(codes), 50):
        batch = codes[i:i+50]
        pre_codes = []
        for c in batch:
            pre = 'sh' if c.startswith(('6','9')) else 'sz'
            pre_codes.append(f'{pre}{c}')

        url = f'https://qt.gtimg.cn/q={",".join(pre_codes)}'
        req = urllib.request.Request(url)
        req.add_header('User-Agent', UA)
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            raw = resp.read().decode('gbk')
            for line in raw.strip().split(';'):
                if '"' not in line:
                    continue
                v = line.split('"')[1].split('~')
                if len(v) < 48:
                    continue
                code = v[2]
                prev_close = float(v[4]) if v[4] else 0
                open_price = float(v[5]) if v[5] else 0
                gap = round((open_price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
                quotes[code] = {
                    'name': v[1],
                    'open': open_price,
                    'prev_close': prev_close,
                    'gap_pct': gap,
                    'price': float(v[3]) if v[3] else 0,
                    'high': float(v[33]) if v[33] else 0,
                    'low': float(v[34]) if v[34] else 0,
                    'volume': float(v[6]) if v[6] else 0,
                    'limit_up': float(v[47]) if v[47] else 0,
                }
        except Exception as e:
            print(f'[Auction] Quote fetch error: {e}')
        time.sleep(0.1 + random.uniform(0, 0.05))
    return quotes


def capture_auction():
    """T日9:25调用：采集竞价数据"""
    today = datetime.now().strftime('%Y-%m-%d')
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    print(f'[Auction Pool] 采集竞价数据 → {today} {ts}')

    # 1. 收标标的：涨停池所有标的 + 候选标的
    zt_state = load_zt_pool_state()
    candidates = load_latest_candidates()

    target_codes = set()
    target_info = {}  # code -> {name, score, limit_days, one_line, in_zt_pool, is_candidate}

    # 涨停池标的
    for s in zt_state.get('stocks', []):
        code = s['code']
        target_codes.add(code)
        target_info[code] = {
            'name': s['name'],
            'limit_days': s.get('limit_days', 1),
            'first_seal': s.get('first_seal', ''),
            'last_seal': s.get('last_seal', ''),
            'break_times': s.get('break_times', 0),
            'industry': s.get('industry', ''),
            'in_zt_pool': True,
            'is_candidate': False,
            'score': 0,
            'one_line': False,
        }

    # 候选标的（合并信息）
    if candidates:
        for c in candidates.get('candidates', []):
            code = c['code']
            target_codes.add(code)
            if code in target_info:
                target_info[code]['is_candidate'] = True
                target_info[code]['score'] = c.get('score', 0)
                target_info[code]['one_line'] = c.get('one_line', False)
            else:
                target_info[code] = {
                    'name': c['name'],
                    'limit_days': c.get('cons', 1),
                    'in_zt_pool': False,
                    'is_candidate': True,
                    'score': c.get('score', 0),
                    'one_line': c.get('one_line', False),
                }

    print(f'[Auction Pool] 目标标的: {len(target_codes)}只 (涨停池{len(zt_state.get("stocks",[]))} + 候选额外{len(target_codes)-len(zt_state.get("stocks",[]))})')

    # 2. 批量获取竞价行情
    all_codes = sorted(target_codes)
    quotes = fetch_quotes(all_codes)
    print(f'[Auction Pool] 获取行情: {len(quotes)}只')

    # 2.5 9:25前竞价未撮合(open=0) → 不覆盖快照
    if quotes:
        zero_opens = sum(1 for q in quotes.values() if q.get('open', 0) == 0)
        if zero_opens > len(quotes) * 0.5:
            print(f'[Auction Pool] ⚠ 竞价未结束({zero_opens}/{len(quotes)} open=0), 9:25后重跑')
            return None

    # 3. 构建快照
    snapshot = []
    buyable_count = 0
    gap_dist = defaultdict(int)  # gap分布

    for code in sorted(target_codes):
        info = target_info.get(code, {})
        q = quotes.get(code, {})

        gap = q.get('gap_pct', 0)
        is_one_line = info.get('one_line', False)
        is_true_one = info.get('true_one_line', False)
        buyable = 4.0 <= gap <= 8.0 and not is_one_line

        if 4.0 <= gap <= 8.0 and not is_one_line:
            buyable_count += 1

        # gap分布
        if gap >= 9: gap_dist['9%+'] += 1
        elif gap >= 5: gap_dist['5-9%'] += 1
        elif gap >= 2: gap_dist['2-5%'] += 1
        elif gap >= 0: gap_dist['0-2%'] += 1
        elif gap >= -3: gap_dist['-3-0%'] += 1
        else: gap_dist['<-3%'] += 1

        entry = {
            'code': code,
            'name': info.get('name', q.get('name', '')),
            'open': q.get('open', 0),
            'prev_close': q.get('prev_close', 0),
            'gap_pct': gap,
            'price': q.get('price', 0),
            'volume': q.get('volume', 0),
            'limit_up': q.get('limit_up', 0),
            # 关联信息
            'in_zt_pool': info.get('in_zt_pool', False),
            'is_candidate': info.get('is_candidate', False),
            'score': info.get('score', 0),
            'limit_days': info.get('limit_days', 1),
            'one_line': is_one_line,
            'buyable': buyable,
        }
        snapshot.append(entry)

    # 按gap降序排列
    snapshot.sort(key=lambda x: x['gap_pct'], reverse=True)

    # 4. 保存快照
    today_yyyymmdd = today.replace('-', '')
    fpath = os.path.join(AUCTION_DIR, f'{today}.json')
    # 也保存一份按代码索引的版本
    with open(fpath, 'w', encoding='utf-8') as f:
        json.dump({
            'date': today,
            'captured': ts,
            'total_stocks': len(snapshot),
            'quoted': len(quotes),
            'buyable_count': buyable_count,
            'gap_distribution': dict(gap_dist),
            'stocks': snapshot,
        }, f, ensure_ascii=False, indent=2)
    print(f'[Auction Pool] 快照保存: {fpath} ({len(snapshot)}只)')

    # 5. 更新状态文件
    state = load_auction_state()
    state['last_update'] = today
    state['total_sessions'] = state.get('total_sessions', 0) + 1

    # 当天摘要
    state['current'] = {
        'date': today,
        'captured': ts,
        'total': len(snapshot),
        'buyable': buyable_count,
        'gap_distribution': dict(gap_dist),
        'buyable_stocks': sorted([
            {'code': s['code'], 'name': s['name'], 'gap_pct': s['gap_pct'],
             'score': s['score'], 'limit_days': s['limit_days']}
            for s in snapshot if s['buyable']
        ], key=lambda x: x['score'], reverse=True)[:10],  # top 10 by score
    }

    # 历史记录（保留最近60天）
    history = state.get('history', [])
    history.append({
        'date': today,
        'total': len(snapshot),
        'buyable': buyable_count,
        'gap_distribution': dict(gap_dist),
    })
    if len(history) > 60:
        history = history[-60:]
    state['history'] = history

    save_auction_state(state)
    print(f'[Auction Pool] 可买标的: {buyable_count}只')
    if buyable_count > 0:
        buyable_stocks = [s for s in snapshot if s['buyable']]
        buyable_stocks.sort(key=lambda x: x['score'], reverse=True)
        for s in buyable_stocks:
            print(f'  {s["name"]}({s["code"]}) score={s["score"]:.0f} '
                  f'gap={s["gap_pct"]:+.1f}% {s["limit_days"]}板')


def load_auction_state():
    """加载竞价池状态"""
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        'created': datetime.now().strftime('%Y-%m-%d'),
        'total_sessions': 0,
        'current': {},
        'history': [],
    }


def save_auction_state(state):
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_auction(date_str=None):
    """加载指定日期竞价快照，默认最新"""
    if date_str is None:
        files = sorted([f for f in os.listdir(AUCTION_DIR) if f.endswith('.json') and not f.startswith('auction_state')])
        if not files:
            return None
        date_str = files[-1].replace('.json', '')
    fpath = os.path.join(AUCTION_DIR, f'{date_str}.json')
    if os.path.exists(fpath):
        with open(fpath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # 兼容旧格式
        if 'candidates' in data and 'stocks' not in data:
            data['stocks'] = data.pop('candidates')
            data['total_stocks'] = len(data['stocks'])
            data['buyable_count'] = sum(1 for s in data['stocks'] if s.get('buyable'))
            data['quoted'] = data['total_stocks']
        return data
    return None


def get_buyable(date_str=None):
    """获取可买标的列表（竞价在4%-8%区间）"""
    data = load_auction(date_str)
    if not data:
        return []
    return [s for s in data.get('stocks', []) if s.get('buyable', False)]


def print_summary(date_str=None):
    """打印竞价摘要"""
    data = load_auction(date_str)
    if not data:
        print('无竞价数据')
        return
    print(f"\n{'='*60}")
    print(f"  竞价池 | {data['date']} | 采集: {data.get('captured', '?')}")
    print(f"{'='*60}")
    print(f"  总标的: {data['total_stocks']} | 有行情: {data['quoted']} | 可买: {data['buyable_count']}")
    print(f"  Gap分布: {data.get('gap_distribution', {})}")
    print(f"\n  可买标的 (竞价4%-8%):")
    buyable = [s for s in data['stocks'] if s.get('buyable')]
    if buyable:
        for s in buyable:
            score = s.get('score', 0)
            ld = s.get('limit_days', '?')
            cand = '[候选]' if s.get('is_candidate') else ''
            print(f"    {s['name']}({s['code']}) gap={s['gap_pct']:+.1f}% "
                  f"score={score:.0f} {ld}板 {cand}")
    else:
        print(f"    (无可买标的)")


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--summary':
        date_arg = sys.argv[2] if len(sys.argv) > 2 else None
        print_summary(date_arg)
    elif len(sys.argv) > 1 and sys.argv[1] == '--history':
        state = load_auction_state()
        for h in state.get('history', []):
            print(f"  {h['date']} | {h['total']}只 | 可买{h['buyable']}只 | {h['gap_distribution']}")
    else:
        capture_auction()
