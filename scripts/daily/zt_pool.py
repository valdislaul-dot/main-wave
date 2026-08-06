"""
涨停池管理器 — T日收盘更新, T+1竞价选股
数据流:
  T日15:00: update_zt_pool() → 扫描全市场涨停 → 收盘涨停的留在池中
  T+1 9:25: get_pool() → 读取池子 → morning_check选股
  T+1 15:00: 重复

文件: data/zt_pool_state.json (活跃池) + data/zt_pool_exit_log.json (离池记录)
"""
import json, os, sys
from datetime import datetime, timedelta
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scoring import is_limit_up, get_lp

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_PATH = os.path.join(BASE, 'data', 'zt_pool_state.json')
EXIT_LOG_PATH = os.path.join(BASE, 'data', 'zt_pool_exit_log.json')
POOL_DIR = os.path.join(BASE, 'data', 'zt_pool')
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')


# ============================================================
# 基础操作
# ============================================================

def load_state():
    """加载涨停池状态"""
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return _empty_state()


def _empty_state():
    return {
        "as_of_date": None,
        "last_updated": None,
        "stocks": []
    }


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    state['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_pool(state=None):
    """返回活跃涨停池股票列表"""
    if state is None:
        state = load_state()
    return state.get('stocks', [])


def get_by_code(code, state=None):
    if state is None:
        state = load_state()
    for s in state.get('stocks', []):
        if s['code'] == code:
            return s
    return None


def add_entry(state, stock_dict):
    """添加或更新一只股票到池中"""
    existing = get_by_code(stock_dict['code'], state)
    if existing:
        existing.update(stock_dict)
        if 'history' not in existing:
            existing['history'] = []
    else:
        stock_dict.setdefault('history', [])
        state.setdefault('stocks', []).append(stock_dict)


def remove_entry(state, code, reason=""):
    """从池中移除, 记录离池原因"""
    stocks = state.get('stocks', [])
    removed = None
    new_stocks = []
    for s in stocks:
        if s['code'] == code:
            removed = s
        else:
            new_stocks.append(s)
    state['stocks'] = new_stocks

    if removed:
        _log_exit(removed, reason)
    return removed


def _log_exit(stock, reason):
    entry = {
        'code': stock['code'],
        'name': stock.get('name', ''),
        'exit_date': datetime.now().strftime('%Y-%m-%d'),
        'exit_reason': reason,
        'days_in_pool': stock.get('days_in_pool', 0),
        'last_lu_date': stock.get('last_lu_date', ''),
        'limit_days': stock.get('limit_days', 1),
    }
    logs = []
    if os.path.exists(EXIT_LOG_PATH):
        try:
            with open(EXIT_LOG_PATH, 'r', encoding='utf-8') as f:
                logs = json.load(f)
        except:
            pass
    logs.append(entry)
    os.makedirs(os.path.dirname(EXIT_LOG_PATH), exist_ok=True)
    with open(EXIT_LOG_PATH, 'w', encoding='utf-8') as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)


def prune_stale(state, days=10):
    """清理超过N天未涨停的标的 (应该通过正常流程更新, 这是安全网)"""
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    stocks = state.get('stocks', [])
    new_stocks = []
    for s in stocks:
        if s.get('last_lu_date', '') >= cutoff:
            new_stocks.append(s)
        else:
            _log_exit(s, f"stale>{days}days")
    state['stocks'] = new_stocks


# ============================================================
# K线加载
# ============================================================

def _load_klines(code, name=None):
    """加载K线: 兼容新旧两种格式"""
    search_dirs = [
        os.path.join(BASE, 'data', 'kline_data'),
        os.path.join(BASE, 'data', 'backtest_kline'),
    ]

    for sdir in search_dirs:
        if not os.path.exists(sdir):
            continue
        # {code}.json (新搜狐格式 或 backtest_kline格式)
        fpath = os.path.join(sdir, f'{code}.json')
        if os.path.exists(fpath):
            for enc in ['utf-8', 'gbk']:
                try:
                    with open(fpath, 'r', encoding=enc) as f:
                        data = json.load(f)
                    # 新格式: dict with 'data' key
                    if isinstance(data, dict) and 'data' in data:
                        return data['data']
                    # 旧格式: list
                    return data
                except: pass
        # {name}_{code}.json (旧kline_data格式)
        if name:
            fpath = os.path.join(sdir, f'{name}_{code}.json')
            if os.path.exists(fpath):
                for enc in ['utf-8', 'gbk']:
                    try:
                        with open(fpath, 'r', encoding=enc) as f:
                            data = json.load(f)
                        return data
                    except: pass

    return None


# ============================================================
# 核心: 涨停池更新 (T日15:00后运行)
# ============================================================

# === 东财API (独立实现, 不依赖screen_candidates) ===
import requests, time as _time, random as _random
ZT_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
ZT_SESSION = None
ZT_LAST = [0.0]
ZT_UT = "7eea3edcaed734bea9cbfc24409ed989"

def _zt_get(url, params=None, headers=None, timeout=15):
    global ZT_SESSION
    if ZT_SESSION is None:
        ZT_SESSION = requests.Session()
        ZT_SESSION.headers.update({"User-Agent": ZT_UA})
    wait = 1.0 - (_time.time() - ZT_LAST[0])
    if wait > 0: _time.sleep(wait + _random.uniform(0.1, 0.5))
    try:
        return ZT_SESSION.get(url, params=params, headers=headers, timeout=timeout)
    finally:
        ZT_LAST[0] = _time.time()


def fetch_zt_pool_raw(date_str):
    """
    拉取东财涨停池原始数据
    date_str: 'YYYY-MM-DD' 或 'YYYYMMDD'
    返回: [{code, name, price, pct, turnover, limit_days, first_seal,
            last_seal, seal_fund, break_times, industry, amount, float_cap}, ...]
    """
    date_yyyymmdd = date_str.replace('-', '')
    url = "https://push2ex.eastmoney.com/getTopicZTPool"
    params = {"ut": ZT_UT, "dpt": "wz.ztzt", "Pageindex": 0,
              "pagesize": 10000, "sort": "fbt:asc", "date": date_yyyymmdd}
    headers = {"User-Agent": ZT_UA, "Referer": "https://quote.eastmoney.com/"}

    try:
        r = _zt_get(url, params=params, headers=headers, timeout=15)
        data = r.json()
        pool_data = (data.get("data") or {}).get("pool") or []

        result = []
        for p in pool_data:
            code = p.get("c", "")
            if not code or code.startswith(('300', '301', '688')):
                continue
            ft = p.get("fbt", 0)
            lt = p.get("lbt", 0)
            result.append({
                'code': code,
                'name': p.get("n", ""),
                'price': p.get("p", 0) / 1000 if p.get("p", 0) > 100 else p.get("p", 0),
                'pct': round(p.get("zdp", 0), 2),
                'turnover': round(p.get("hs", 0), 2),
                'limit_days': p.get("days", 1),
                'first_seal': f"{str(ft).zfill(6)[:2]}:{str(ft).zfill(6)[2:4]}:{str(ft).zfill(6)[4:6]}",
                'last_seal': f"{str(lt).zfill(6)[:2]}:{str(lt).zfill(6)[2:4]}:{str(lt).zfill(6)[4:6]}",
                'seal_fund': p.get("fund", 0),
                'break_times': p.get("zbc", 0),
                'industry': p.get("hybk", ""),
                'amount': p.get("amount", 0),
                'float_cap': p.get("f20", 0),
            })
        return result
    except Exception as e:
        print(f'[ZT Pool] 东财API异常: {e}')

        # 备用: akshare
        try:
            import akshare as ak
            df = ak.stock_zt_pool_em(date=date_yyyymmdd)
            if df is not None and len(df) > 0:
                pool = []
                for _, row in df.iterrows():
                    code = str(row.get('代码', '')).zfill(6)
                    if code.startswith(('300', '301', '688')):
                        continue
                    pool.append({
                        'code': code, 'name': str(row.get('名称', '')),
                        'price': float(row.get('最新价', 0)),
                        'pct': float(row.get('涨跌幅', 0)),
                        'turnover': float(row.get('换手率', 0)),
                        'limit_days': int(row.get('连板数', 1)),
                        'first_seal': str(row.get('首次封板时间', '')),
                        'last_seal': str(row.get('最后封板时间', '')),
                        'break_times': int(row.get('炸板次数', 0)),
                        'industry': str(row.get('所属行业', '')),
                        'amount': float(row.get('成交额', 0)),
                        'float_cap': float(row.get('流通市值', 0)),
                    })
                return pool
        except:
            pass

        return []


def update_zt_pool(date_str=None, verbose=True):
    """
    T日收盘后更新涨停池:
    1. 拉当天全市场涨停数据
    2. 过滤300/301/688
    3. 确认收盘价==涨停价(通过K线验证)
    4. 收盘涨停 → 加入/保留在池中
    5. 不涨停 → 移出池子
    """
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')

    if verbose:
        print(f'\n[ZT Pool] 更新涨停池 → {date_str}')

    # 1. 拉原始数据
    raw = fetch_zt_pool_raw(date_str)
    if not raw:
        if verbose:
            print('[ZT Pool] 警告: 未获取到涨停数据')
        return None

    if verbose:
        print(f'[ZT Pool] 当日涨停(已过滤300/301/688): {len(raw)} 只')

    # 2. 加载上一状态
    state = load_state()
    prev_codes = {s['code']: s for s in state.get('stocks', [])}

    # 3. 东财数据 + K线验证连板数 (东财limit_days不准)
    new_members = []
    added = 0
    updated = 0

    for s in raw:
        code = s['code']
        name = s.get('name', '')
        kls = _load_klines(code, name)

        # 用K线精确计算连板数
        cons = 0
        if kls and len(kls) >= 2:
            lpct = get_lp(code)
            # 从最后一天(K线可能含今天也可能不含)向前数连续涨停
            for i in range(len(kls) - 1, max(len(kls) - 13, -1), -1):
                if i <= 0: break
                if is_limit_up(float(kls[i].get('close', 0)),
                               float(kls[i-1].get('close', 0)), lpct):
                    cons += 1
                else:
                    break
        else:
            # 无K线时用东财数据 (可能有误)
            cons = s.get('limit_days', 1) - 1

        # 构建池条目
        close_price = s.get('price', 0)
        prev_close_price = kls[-1].get('close', close_price) if kls and len(kls) >= 1 else close_price

        entry = {
            'code': code,
            'name': name,
            'added_date': prev_codes.get(code, {}).get('added_date', date_str),
            'last_lu_date': date_str,
            'days_in_pool': prev_codes.get(code, {}).get('days_in_pool', 0) + 1,
            'limit_days': cons + 1,
            'close': close_price,
            'prev_close': prev_close_price,
            'first_seal': s.get('first_seal', ''),
            'last_seal': s.get('last_seal', ''),
            'seal_fund': s.get('seal_fund', 0),
            'break_times': s.get('break_times', 0),
            'industry': s.get('industry', ''),
            'turnover': s.get('turnover', 0),
            'amount': s.get('amount', 0),
            'float_cap': s.get('float_cap', 0),
        }

        # 历史记录
        prev_entry = prev_codes.get(code)
        if prev_entry:
            entry['history'] = prev_entry.get('history', [])
            updated += 1
        else:
            entry['history'] = []
            added += 1

        entry['history'].append({
            'date': date_str,
            'close': close_price,
            'cons': cons + 1,
        })

        new_members.append(entry)

    # 4. 移出: 之前池中但今天未收盘涨停的
    new_codes = {s['code'] for s in new_members}
    removed = 0
    for code, old_entry in prev_codes.items():
        if code not in new_codes:
            remove_entry(state, code, "断板(未收盘涨停)")
            removed += 1

    # 5. 更新池
    state['as_of_date'] = date_str
    state['stocks'] = new_members
    save_state(state)

    # 6. 行业统计
    industries = Counter(s['industry'] for s in new_members if s.get('industry'))
    top_sectors = industries.most_common(5)

    if verbose:
        print(f'[ZT Pool] 新增: {added} | 更新: {updated} | 移出: {removed}')
        print(f'[ZT Pool] 当前池大小: {len(new_members)} 只')
        print(f'[ZT Pool] 热门板块: {", ".join(f"{k}({v})" for k, v in top_sectors)}')

    return state


# ============================================================
# 状态摘要
# ============================================================

def pool_summary(state=None):
    if state is None:
        state = load_state()
    stocks = state.get('stocks', [])
    if not stocks:
        return "涨停池: 空"

    boards = Counter(s.get('limit_days', 1) for s in stocks)
    industries = Counter(s.get('industry', '') for s in stocks)
    top3 = industries.most_common(3)

    lines = [
        f"涨停池: {len(stocks)}只 (截至{state.get('as_of_date', '?')})",
        f"  连板分布: " + ", ".join(f"{k}板:{v}" for k, v in sorted(boards.items())),
        f"  热门板块: " + ", ".join(f"{k}({v})" for k, v in top3),
    ]
    return "\n".join(lines)


# ============================================================
# 历史活跃度统计
# ============================================================

def activity_report(top_n=30):
    """
    统计历史活跃度 = 涨停出现天数 + 离池次数
    数据来源: ZT池快照 + 当前池 + 离池日志
    """
    activity = {}  # code -> {name, total_days, pool_entries, last_date, max_cons, industry}

    # 1. 每日涨停池快照
    if os.path.exists(POOL_DIR):
        for fn in sorted(os.listdir(POOL_DIR)):
            if not fn.endswith('.json'):
                continue
            date_str = fn.replace('.json', '')
            fpath = os.path.join(POOL_DIR, fn)
            try:
                with open(fpath, encoding='utf-8') as f:
                    pool = json.load(f)
            except:
                with open(fpath, encoding='gbk') as f:
                    pool = json.load(f)
            if not isinstance(pool, list):
                continue

            for s in pool:
                code = s['code']
                if code not in activity:
                    activity[code] = {
                        'name': s.get('name', ''), 'total_days': 0,
                        'pool_entries': 0, 'last_date': '', 'max_cons': 0,
                        'industry': s.get('industry', ''),
                    }
                activity[code]['total_days'] += 1
                activity[code]['last_date'] = max(activity[code]['last_date'], date_str)
                ld = s.get('limit_days', 1)
                activity[code]['max_cons'] = max(activity[code]['max_cons'], ld)

    # 2. 当前涨停池（可能含快照没有的日期）
    state = load_state()
    pool_date = state.get('as_of_date', '')
    for s in state.get('stocks', []):
        code = s['code']
        if code not in activity:
            activity[code] = {
                'name': s.get('name', ''), 'total_days': 0,
                'pool_entries': 0, 'last_date': '', 'max_cons': 0,
                'industry': s.get('industry', ''),
            }
        if pool_date and pool_date > activity[code]['last_date']:
            activity[code]['total_days'] += 1
            activity[code]['last_date'] = pool_date
        activity[code]['max_cons'] = max(activity[code]['max_cons'],
                                          s.get('limit_days', 1))

    # 3. 离池记录（补入池次数）
    if os.path.exists(EXIT_LOG_PATH):
        with open(EXIT_LOG_PATH, encoding='utf-8') as f:
            exits = json.load(f)
        for e in exits:
            code = e['code']
            if code in activity:
                activity[code]['pool_entries'] += 1
                activity[code]['max_cons'] = max(activity[code]['max_cons'],
                                                  e.get('limit_days', 1))

    # 4. 当前池中的每只也算一次进入
    for s in state.get('stocks', []):
        code = s['code']
        if code in activity:
            activity[code]['pool_entries'] = max(1, activity[code]['pool_entries'])

    # 排序：按出现天数降序
    ranked = sorted(activity.items(),
                    key=lambda x: (x[1]['total_days'], x[1]['pool_entries']),
                    reverse=True)

    return ranked, len(activity)


def print_activity(top_n=30):
    ranked, total = activity_report(top_n)
    print(f"\n{'='*70}")
    print(f"  历史活跃度排名 (共{total}只上过涨停池)")
    print(f"{'='*70}")
    print(f"{'#':<4} {'代码':<8} {'名称':<8} {'出现':>5} {'入池':>4} {'最大连板':>6} {'最近':>10} {'行业':<10}")
    print(f"{'-'*70}")

    for i, (code, a) in enumerate(ranked[:top_n]):
        print(f"{i+1:<4} {code:<8} {a['name']:<8} {a['total_days']:>4}天 "
              f"{a['pool_entries']:>3}次 {a['max_cons']:>4}连板 "
              f"{a['last_date']:>10} {a['industry']:<10}")

    # 行业活跃度
    industry_freq = Counter()
    for code, a in ranked:
        if a['industry']:
            industry_freq[a['industry']] += a['total_days']
    print(f"\n热门行业（按出现天数）: "
          + ", ".join(f"{k}({v}天)" for k, v in industry_freq.most_common(8)))


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--activity':
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        print_activity(n)
    elif len(sys.argv) > 1 and sys.argv[1] == '--summary':
        state = load_state()
        print(pool_summary(state))
    elif len(sys.argv) > 1 and sys.argv[1] == '--update':
        update_zt_pool(verbose=True)
    else:
        state = load_state()
        print(pool_summary(state))
        print("\n活跃度: python zt_pool.py --activity")
