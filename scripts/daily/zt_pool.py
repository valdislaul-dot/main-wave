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
RAW_DIR = os.path.join(BASE, 'data', 'raw')


def _save_raw(date_str, name, content):
    """原始报文存档 → data/raw/YYYY-MM-DD/name (失真时回溯「源错了」还是「解析错了」)"""
    d = os.path.join(RAW_DIR, date_str)
    os.makedirs(d, exist_ok=True)
    try:
        with open(os.path.join(d, name), 'w', encoding='utf-8') as f:
            f.write(content)
    except Exception as e:
        print(f'[ZT Pool] raw存档失败 {name}: {e}')


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


def get_prev_pool_file(ref_date=None):
    """最近一个严格早于 ref_date(默认今天) 的涨停池快照文件名 (YYYYMMDD.json)
    2026-09-01统一: 此前4处手写过滤, capture_market_state写<=today致date_fmt=当天
    → K线同日bar相减恒0, 赚钱效应连续7天输出0.0无人发现; 收敛为一处实现防复制出错
    """
    if ref_date is None:
        ref_date = datetime.now().strftime('%Y%m%d')
    ref_date = str(ref_date).replace('-', '')
    try:
        names = [f for f in os.listdir(POOL_DIR)
                 if f.endswith('.json') and f[:-5].isdigit() and f[:-5] < ref_date]
    except FileNotFoundError:
        return None
    return max(names, default=None)  # YYYYMMDD字符串比较=日期比较, max即最近一天


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    state['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    tmp = STATE_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


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


def _fetch_tencent_batch(codes):
    """腾讯批量 → {code: {close, prev_close}}, 用于三方确认收盘涨停 + 除权检测"""
    import time
    quotes = {}
    for i in range(0, len(codes), 50):
        batch = codes[i:i+50]
        pre = [('sh' if c.startswith(('6', '9')) else 'sz') + c for c in batch]
        url = f'http://qt.gtimg.cn/q={",".join(pre)}'
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            raw = urllib.request.urlopen(req, timeout=10).read().decode('gbk')
            for line in raw.strip().split(';'):
                if '"' not in line:
                    continue
                v = line.split('"')[1].split('~')
                if len(v) < 5:
                    continue
                code = v[2]
                quotes[code] = {
                    'close': float(v[3]) if v[3] else 0,
                    'prev_close': float(v[4]) if v[4] else 0,
                }
        except Exception:
            pass
        time.sleep(0.1)
    return quotes


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
    拉取涨停池原始数据 (2026-08-20起: 同花顺涨停揭秘, 弃用东财push2ex)
    弃用原因: 东财接口改版, lbc连板数恒1失效 / zbc炸板次数大面积失真(金健米业报9次实4次)
              / 收盘后数据仍会修正(城投控股zbc 7→5), 已不可作为单一可靠源
    date_str: 'YYYY-MM-DD' 或 'YYYYMMDD'
    返回: [{code, name, price, pct, turnover, limit_days, first_seal,
            last_seal, seal_fund, break_times, industry, amount, float_cap}, ...]
    """
    date_yyyymmdd = date_str.replace('-', '')
    url = 'https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool'
    THS_FIELDS = ('199112,10,9001,330323,330324,330325,9002,330329,'
                  '133971,133970,1968584,3475914,9003,9004')

    def _fmt_ts(ts):
        """Unix秒 → HH:MM:SS"""
        try:
            return datetime.fromtimestamp(int(ts)).strftime('%H:%M:%S')
        except Exception:
            return ''

    def _parse_high_days(hd):
        """'6天5板'/'首板' → 板数 ('3天2板'→2, 窗口板数; 连板数由K线回算覆盖)"""
        import re
        m = re.search(r'(\d+)板', str(hd))
        if m:
            return int(m.group(1))
        return 1

    try:
        import requests
        all_info = []
        page = 1
        while True:
            params = {'page': page, 'limit': 200, 'field': THS_FIELDS,
                      'filter': 'HS,GEM2STAR', 'order_field': '330324',
                      'order_type': '0', 'date': date_yyyymmdd}
            r = requests.get(url, params=params, headers={'User-Agent': ZT_UA}, timeout=15)
            _save_raw(date_str, 'zt_pool_10jqka.json', r.text)
            info = (r.json().get('data') or {}).get('info', [])
            if not info:
                break
            all_info.extend(info)
            if len(info) < 200:
                break
            page += 1
            import time as _t
            _t.sleep(0.5)

        result = []
        for p in all_info:
            code = str(p.get('code', ''))
            if not code or code.startswith(('300', '301', '688', '8', '9')):
                continue
            result.append({
                'code': code,
                'name': p.get('name', ''),
                'price': float(p.get('latest', 0) or 0),
                'pct': round(float(p.get('change_rate', 0) or 0), 2),
                'turnover': round(float(p.get('turnover_rate', 0) or 0), 2),
                'limit_days': _parse_high_days(p.get('high_days')),
                'first_seal': _fmt_ts(p.get('first_limit_up_time')),
                'last_seal': _fmt_ts(p.get('last_limit_up_time')),
                'seal_fund': float(p.get('order_amount', 0) or 0),
                'break_times': int(p.get('open_num', 0) or 0),
                # industry 用同花顺涨停原因题材 (比东财行业分类更适合板块共振判定)
                'industry': p.get('reason_type', '') or '',
                'amount': 0,   # 同花顺无成交额字段 (K线成交额由pool_map补, 池外维持None)
                'float_cap': float(p.get('currency_value', 0) or 0),
                # 附加字段 (下游可选消费, 不破坏旧结构)
                'board_type': p.get('limit_up_type', ''),
                'seal_rate': float(p.get('limit_up_suc_rate', 0) or 0),
                'is_again': int(p.get('is_again_limit', 0) or 0),
            })
        return result
    except Exception as e:
        print(f'[ZT Pool] 同花顺涨停池拉取失败: {e}')
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
        # 2026-08-31: 同花顺爬虫失败 → 官方API兜底 (炸板次数/换手率缺失, 炸板因子按0)
        if verbose:
            print('[ZT Pool] 同花顺爬取失败 → 官方API兜底')
        try:
            from hithink_api import fetch_limit_up_pool as _official_pool
            _off = _official_pool(date_str)
            raw = [{
                'code': x['code'], 'name': x['name'], 'price': x['price'], 'pct': x['pct'],
                'turnover': 0, 'limit_days': x['limit_days'], 'first_seal': x['first_seal'],
                'last_seal': '', 'seal_fund': x['seal_fund'], 'break_times': 0,
                'industry': x['industry'], 'amount': 0, 'float_cap': 0,
                'board_type': '', 'seal_rate': 0, 'is_again': 0,
            } for x in _off]
            if verbose and raw:
                print(f'[ZT Pool] 官方兜底 {len(raw)} 只 (注意: 炸板次数/换手率缺失)')
        except Exception as e:
            if verbose:
                print(f'[ZT Pool] 官方API兜底也失败: {e}')
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

    # 3.1 腾讯批量行情 (三方确认收盘涨停 + 除权检测)
    tencent_q = _fetch_tencent_batch([s['code'] for s in raw])

    # 3.2 官方API连板数 (2026-08-31: K线滞后时兜底, 防跨断板误连)
    _prev_td = datetime.strptime(date_str, '%Y-%m-%d') - timedelta(days=1)
    while _prev_td.weekday() >= 5:
        _prev_td -= timedelta(days=1)
    _prev_td_str = _prev_td.strftime('%Y-%m-%d')
    _off_ld = {}
    try:
        from hithink_api import fetch_limit_up_pool as _official_pool
        _off_ld = {x['code']: x['limit_days'] for x in _official_pool(date_str)}
    except Exception:
        pass

    for s in raw:
        code = s['code']
        name = s.get('name', '')
        kls = _load_klines(code, name)

        # 用K线精确计算连板数 (cons=前序连续涨停数不含今日; limit_days=cons+1)
        # 本地K线缺今日时用腾讯收盘价补判今日是否涨停(流水线中池更新先于K线更新)
        cons = 0
        kline_fresh = False
        today_lu = False
        if kls and len(kls) >= 2:
            lpct = get_lp(code)
            # 检查K线是否包含今天(或昨天)
            last_date = kls[-1].get('date', '')
            kline_fresh = (last_date == date_str)
            if kline_fresh:
                # K线含今日: 今日是涨停(在当日池内), 前序从倒数第二根向前数
                start_i = len(kls) - 2
            else:
                # 今日K线缺失 → 用批量腾讯收盘价判今日是否涨停(复用tencent_q, 不重复请求)
                tq_ = tencent_q.get(code) or {}
                t_close = tq_.get('close', 0)
                today_lu = bool(t_close and t_close > 0 and
                                is_limit_up(t_close, float(kls[-1].get('close', 0)), lpct))
                # 2026-08-20修复: 昨日(K线末行)若断板 → 今日=首板(cons=0), 不再往前数
                if not today_lu:
                    start_i = None
                elif last_date < _prev_td_str:
                    # 2026-08-31修复B: K线滞后于昨日(可能缺断板日) → 官方连板数兜底,
                    # 防跨断板误连(如康盛股份断板日K线缺失被误算4板)
                    start_i = None
                    if _off_ld.get(code):
                        cons = int(_off_ld[code]) - 1
                elif len(kls) >= 2 and is_limit_up(float(kls[-1].get('close', 0)),
                                                  float(kls[-2].get('close', 0)), lpct):
                    # 2026-08-31修复A: 从昨日(末行)起数, 原len-2跳过昨日致连板数系统性少1
                    start_i = len(kls) - 1
                else:
                    start_i = None           # 昨日断板 → 今日首板
            # 从start_i向前数连续涨停(不含今日)
            if start_i is not None:
                for i in range(start_i, max(start_i - 13, -1), -1):
                    if i <= 0:
                        break
                    if is_limit_up(float(kls[i].get('close', 0)),
                                   float(kls[i-1].get('close', 0)), lpct):
                        cons += 1
                    else:
                        break
        # K线+腾讯都拿不到今日涨停判定时, 用东财连板数兜底
        if not kline_fresh and not today_lu:
            em_cons = s.get('limit_days', 1) - 1
            cons = max(cons, em_cons)
        if cons == 0 and not kls:
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

        # ── 三方确认 + 除权检测 ──
        tq = tencent_q.get(code)
        # 东财收盘 vs 腾讯收盘: 偏差>2% → 疑似尾盘炸板/池滞后
        if tq and tq.get('close') and close_price:
            if abs(tq['close'] - close_price) / close_price > 0.02:
                print(f'[ZT Pool] ⚠ {name}({code}) 东财收{close_price} vs 腾讯{tq["close"]} (疑似尾盘炸板/池滞后)')
        # 腾讯昨收 vs K线昨收: 偏差>1% → 疑似除权
        if tq and tq.get('prev_close') and kls and len(kls) >= 1:
            k_idx = len(kls) - 2 if kline_fresh else len(kls) - 1
            if k_idx >= 0:
                k_prev = float(kls[k_idx].get('close', 0) or 0)
                if k_prev > 0 and abs(tq['prev_close'] - k_prev) / k_prev > 0.01:
                    print(f'[ZT Pool] ⚠ {name}({code}) 昨收 腾讯{tq["prev_close"]} vs K线{k_prev} (疑似除权)')

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
