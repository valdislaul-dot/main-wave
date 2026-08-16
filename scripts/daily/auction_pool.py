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
from datetime import datetime, timedelta, time as clock_time
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AUCTION_DIR = os.path.join(BASE, 'data', 'auction')
STATE_PATH = os.path.join(BASE, 'data', 'auction_state.json')
ZT_STATE_PATH = os.path.join(BASE, 'data', 'zt_pool_state.json')
LOG_DIR = os.path.join(BASE, 'logs')

os.makedirs(AUCTION_DIR, exist_ok=True)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
RAW_DIR = os.path.join(BASE, 'data', 'raw')


def _save_raw(date_str, name, content):
    """原始报文存档 → data/raw/YYYY-MM-DD/name (失真时回溯「源错了」还是「解析错了」)"""
    d = os.path.join(RAW_DIR, date_str)
    os.makedirs(d, exist_ok=True)
    try:
        with open(os.path.join(d, name), 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception as e:
        print(f'[Auction] raw存档失败 {name}: {e}')


def load_zt_pool_state():
    """加载当前涨停池标的列表"""
    if os.path.exists(ZT_STATE_PATH):
        with open(ZT_STATE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'stocks': [], 'as_of_date': ''}


def load_latest_candidates():
    """加载最新候选清单 (排除candidates_v*旧格式, 否则字母序会选中过期文件)"""
    files = sorted([f for f in os.listdir(LOG_DIR)
                    if f.startswith('candidates_') and not f.startswith('candidates_v')])
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
    raw_parts = []
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
            raw_parts.append(raw)
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
    if raw_parts:
        _save_raw(datetime.now().strftime('%Y-%m-%d'), 'auction_tencent.txt',
                  '\n\n'.join(raw_parts))
    return quotes


def fetch_sina_quotes(codes):
    """
    新浪行情 → {code: {open, prev_close, gap_pct}}
    用于与腾讯交叉验证竞价 gap / 昨收 (除权检测)
    """
    quotes = {}
    raw_parts = []
    for i in range(0, len(codes), 60):
        batch = codes[i:i+60]
        pre = [('sh' if c.startswith(('6', '9')) else 'sz') + c for c in batch]
        url = f'https://hq.sinajs.cn/list={",".join(pre)}'
        req = urllib.request.Request(url)
        req.add_header('User-Agent', UA)
        req.add_header('Referer', 'https://finance.sina.com.cn/')
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            raw = resp.read().decode('gbk')
            raw_parts.append(raw)
            for line in raw.strip().split(';'):
                if '="' not in line:
                    continue
                code_full = line.split('=')[0].replace('var hq_str_', '').strip()
                fields = line.split('"')[1].split(',')
                if len(fields) < 3 or not fields[1]:
                    continue
                code = code_full[2:] if code_full.startswith(('sh', 'sz')) else code_full
                open_p = float(fields[1]) if fields[1] else 0
                prev_close = float(fields[2]) if fields[2] else 0
                gap = round((open_p - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
                quotes[code] = {'open': open_p, 'prev_close': prev_close, 'gap_pct': gap}
        except Exception as e:
            print(f'[Auction] Sina quote fetch error: {e}')
        time.sleep(0.1)
    if raw_parts:
        _save_raw(datetime.now().strftime('%Y-%m-%d'), 'auction_sina.txt',
                  '\n\n'.join(raw_parts))
    return quotes


def capture_auction(force=False):
    """T日9:25调用：采集竞价数据 (force=True 跳过交易日/时钟守卫, 用于手动补采)"""
    now = datetime.now()
    today = now.strftime('%Y-%m-%d')
    ts = now.strftime('%Y-%m-%d %H:%M:%S')

    # ── 采集守卫: 交易日 + 9:25~9:30窗口 ──
    if not force:
        from trading_calendar import is_trading_day
        if not is_trading_day(now.date()):
            print(f'[Auction Pool] ⚠ 今日({today})非交易日, 跳过竞价采集 (--force可强制)')
            return None
        t = now.time()
        if t < clock_time(9, 25):
            print(f'[Auction Pool] ⚠ 未到9:25({t.strftime("%H:%M:%S")}), 竞价未撮合, 拒绝采集')
            return None
        if t > clock_time(9, 30):
            print(f'[Auction Pool] ⚠ 已过9:30({t.strftime("%H:%M:%S")}), 竞价价已失效, 拒绝采集 (--force可强制)')
            return None

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

    # 2.4 双源交叉: 新浪 vs 腾讯 (gap 偏差>0.3% 或 昨收不一致=疑似除权 → 告警)
    sina_quotes = fetch_sina_quotes(all_codes)
    if sina_quotes:
        cross_warn = []
        for code, q in quotes.items():
            sq = sina_quotes.get(code)
            if not sq or not q.get('prev_close') or not sq.get('prev_close'):
                continue
            if abs(q['prev_close'] - sq['prev_close']) / q['prev_close'] > 0.001:
                cross_warn.append(f'{q.get("name")}({code})昨收 腾讯{q["prev_close"]}vs新浪{sq["prev_close"]}(疑似除权)')
            elif abs(q['gap_pct'] - sq['gap_pct']) > 0.3:
                cross_warn.append(f'{q.get("name")}({code})gap 腾讯{q["gap_pct"]}vs新浪{sq["gap_pct"]}')
        if cross_warn:
            print(f'[Auction Pool] ⚠ 双源交叉异常({len(cross_warn)}只): {"; ".join(cross_warn[:8])}')
        else:
            print(f'[Auction Pool] ✓ 双源交叉: 腾讯vs新浪 gap一致')

    # 2.5 9:25前竞价未撮合(open=0) → 不覆盖快照
    if quotes:
        zero_opens = sum(1 for q in quotes.values() if q.get('open', 0) == 0)
        if zero_opens > len(quotes) * 0.5:
            print(f'[Auction Pool] ⚠ 竞价未结束({zero_opens}/{len(quotes)} open=0), 9:25后重跑')
            return None

    # 2.7 昨日涨停池文件连板数(最准) → 修正state连板数少算问题
    file_cons = {}
    zt_files = sorted(f for f in os.listdir(os.path.join(BASE, 'data', 'zt_pool'))
                      if f.endswith('.json') and f[:-5] < datetime.now().strftime('%Y%m%d'))
    if zt_files:
        try:
            with open(os.path.join(BASE, 'data', 'zt_pool', zt_files[-1]), encoding='utf-8') as f:
                _pp = json.load(f)
        except UnicodeDecodeError:
            with open(os.path.join(BASE, 'data', 'zt_pool', zt_files[-1]), encoding='gbk') as f:
                _pp = json.load(f)
        _pstocks = _pp if isinstance(_pp, list) else _pp.get('stocks', _pp.get('data', []))
        file_cons = {str(x.get('code', '')).replace('sh', '').replace('sz', ''): int(x.get('limit_days', 1) or 1)
                     for x in _pstocks if isinstance(x, dict)}
        # 连板数一致性校验: state vs 池文件, 不一致立即警告(池文件为准)
        _mismatch = []
        for _s in zt_state.get('stocks', []):
            _c = str(_s.get('code', '')).replace('sh', '').replace('sz', '')
            _st = int(_s.get('limit_days', 1) or 1)
            if _c in file_cons and _st != file_cons[_c]:
                _mismatch.append(f'{_s.get("name")}({_c}) state{_st}板vs池文件{file_cons[_c]}板')
        if _mismatch:
            print(f'[Auction Pool] ⚠ 连板数不一致({len(_mismatch)}只), 已取池文件值: {"; ".join(_mismatch[:6])}')

    # 3. 构建快照
    snapshot = []
    buyable_count = 0
    gap_dist = defaultdict(int)  # gap分布

    for code in sorted(target_codes):
        info = target_info.get(code, {})
        q = quotes.get(code, {})

        gap = q.get('gap_pct', 0)
        # 连板数取多源最大(state可能少算, 昨日池文件最准)
        limit_days = max(int(info.get('limit_days', 1) or 1), file_cons.get(code, 1))
        # 一字判定: 今日竞价gap≈10%=今日一字买不到; 昨日一字(候选one_line)用于4板+一字高危过滤
        one_line_prev = info.get('one_line', False)
        is_one_line = gap >= 9.5
        high_risk = limit_days >= 4 and one_line_prev
        buyable = 4.0 <= gap <= 8.0 and not is_one_line and not high_risk

        if buyable:
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
            'limit_days': limit_days,
            'one_line': is_one_line,
            'high_risk': high_risk,
            'buyable': buyable,
        }
        snapshot.append(entry)

    # 按gap降序排列
    snapshot.sort(key=lambda x: x['gap_pct'], reverse=True)

    # 4. 保存快照 (原子写入: 先tmp再rename; 已有快照且非force不覆盖)
    fpath = os.path.join(AUCTION_DIR, f'{today}.json')
    if os.path.exists(fpath) and not force:
        print(f'[Auction Pool] 快照已存在({fpath}), 跳过覆盖 (--force可覆盖)')
    else:
        payload = {
            'date': today,
            'captured': ts,
            'total_stocks': len(snapshot),
            'quoted': len(quotes),
            'buyable_count': buyable_count,
            'gap_distribution': dict(gap_dist),
            'stocks': snapshot,
        }
        tmp_path = fpath + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, fpath)
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
        capture_auction(force='--force' in sys.argv)
