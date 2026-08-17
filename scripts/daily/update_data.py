"""
每日K线数据更新 — V3.2
盘后运行：只更新当日涨停池标的的K线
- 已有K线文件 → 追加最新一天
- 无K线文件 → 下载近3年全量
数据源: 腾讯fqkline前复权(主源) + 新浪不复权(兜底)
"""
import json, os, glob, sys, time
from datetime import datetime, timedelta
from collections import Counter

# BASE auto-detected
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
ZT_STATE_PATH = os.path.join(BASE, 'data', 'zt_pool_state.json')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zt_pool import fetch_zt_pool_raw

os.makedirs(KLINE_DIR, exist_ok=True)


def get_today():
    today = datetime.now()
    if today.hour < 15:
        today = today - timedelta(days=1)
    while today.weekday() >= 5:
        today = today - timedelta(days=1)
    return today.strftime('%Y-%m-%d')


def find_kline_path(code):
    """在K线目录中查找已有文件"""
    # 精确匹配: name_code.json
    for fp in glob.glob(os.path.join(KLINE_DIR, f'*_{code}.json')):
        return fp
    # 精确匹配: code.json
    fp = os.path.join(KLINE_DIR, f'{code}.json')
    if os.path.exists(fp):
        return fp
    # 模糊匹配: _code.json (旧格式)
    fp = os.path.join(KLINE_DIR, f'_{code}.json')
    if os.path.exists(fp):
        return fp
    return None


def _tencent_latest(code, last_date, end_date):
    """腾讯qfq日K → 最近bar (主源), volume手→股"""
    try:
        import urllib.request
        mkt = 'sz' if code.startswith(('0', '3', '1')) else 'sh'
        url = f'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={mkt}{code},day,,,100,qfq'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        d = json.loads(urllib.request.urlopen(req, timeout=10).read().decode('utf-8'))
        rows = (d.get('data', {}).get(f'{mkt}{code}', {}) or {}).get('qfqday') or []
        out = []
        for r in rows:
            if r[0] > last_date and r[0] <= end_date:
                # 腾讯格式: [date, open, close, high, low, volume(手)]
                out.append({
                    'date': r[0],
                    'open': round(float(r[1]), 2),
                    'high': round(float(r[3]), 2),
                    'low': round(float(r[4]), 2),
                    'close': round(float(r[2]), 2),
                    'volume': round(float(r[5]) * 100, 2),
                })
        return out or None
    except Exception:
        return None


def download_full(code, name, end_date):
    """下载完整K线（新浪API，快）"""
    import urllib.request
    sym = f'sz{code}' if code.startswith(('0', '3')) else f'sh{code}'
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"CN_MarketData.getKLineData?symbol={sym}&scale=240&ma=no&datalen=5000")
    req = urllib.request.Request(url)
    req.add_header('User-Agent', 'Mozilla/5.0')
    req.add_header('Referer', 'https://finance.sina.com.cn/')
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        raw = resp.read().decode('gbk')
        data = json.loads(raw)
    except Exception as e:
        return None, str(e)

    if not data:
        return None, 'no data'
    rows = []
    for d in data:
        rows.append({
            'date': d['day'],
            'open': round(float(d['open']), 2),
            'high': round(float(d['high']), 2),
            'low': round(float(d['low']), 2),
            'close': round(float(d['close']), 2),
            'volume': float(d['volume']),
        })
    return rows, None


def _corporate_action_suspect(code, klines, new_rows):
    """除权边界守卫: 腾讯qfq首条新行open与存量末行close偏离超涨跌幅上限 → 疑似窗口内除权, 弃用qfq行"""
    prev_close = klines[-1].get('close')
    first_open = new_rows[0].get('open')
    if not prev_close or not first_open:
        return True
    limit = 0.205 if code.startswith(('3', '68')) else 0.105
    return abs(first_open - prev_close) / prev_close > limit + 0.01


def append_latest(code, existing_path, end_date):
    """追加最新一天到已有K线文件 (腾讯fqkline主源, 新浪兜底)"""
    with open(existing_path, encoding='utf-8') as f:
        raw = json.load(f)
    # 兼容两种格式: dict {metadata, data} 或 list
    klines = raw.get('data', raw) if isinstance(raw, dict) else raw
    is_dict_fmt = isinstance(raw, dict) and 'data' in raw

    last_date = klines[-1]['date'] if klines else '2023-01-01'
    if last_date >= end_date:
        return 0  # 已是最新

    new_rows = None
    source = None

    # 1. 腾讯fqkline前复权主源 (收盘后即有当日数据)
    candidate = _tencent_latest(code, last_date, end_date)
    if candidate and not _corporate_action_suspect(code, klines, candidate):
        new_rows, source = candidate, 'tencent'

    # 2. 腾讯失败/疑似窗口内除权 → 新浪不复权兜底 (与主库同口径)
    if not new_rows:
        full_rows, err = download_full(code, '', end_date)
        if full_rows:
            new_rows = [r for r in full_rows if r['date'] > last_date]
            if new_rows:
                source = 'sina'
        else:
            return -1

    if new_rows:
        klines.extend(new_rows)
        if is_dict_fmt:
            raw['data'] = klines
            md = raw.get('metadata') or {}
            md['adjustment'] = 'mixed(qfq_append)'
            md['source'] = 'Sohu+Tencent'
            md['last_append_source'] = source
            raw['metadata'] = md
            with open(existing_path, 'w', encoding='utf-8') as f:
                json.dump(raw, f, ensure_ascii=False)
        else:
            with open(existing_path, 'w', encoding='utf-8') as f:
                json.dump(klines, f, ensure_ascii=False)
        if klines[-1]['date'] < end_date:
            print(f'  [警告] {code} 追加后尾行 {klines[-1]["date"]} 仍落后 {end_date} (停牌或数据缺口)')
    return len(new_rows)


def main():
    today = get_today()
    print(f'[K线更新] 目标日期: {today}')

    # 1. 拉取当日涨停池
    print('[K线更新] 拉取当日涨停池...')
    zt_pool = fetch_zt_pool_raw(today)
    if not zt_pool:
        print('[K线更新] 未获取到涨停数据，尝试从状态文件读取')
        if os.path.exists(ZT_STATE_PATH):
            with open(ZT_STATE_PATH, encoding='utf-8') as f:
                state = json.load(f)
            zt_pool = state.get('stocks', [])
        if not zt_pool:
            print('[K线更新] 无数据，退出')
            return

    # 去重
    seen = set()
    unique = []
    for s in zt_pool:
        code = s['code']
        if code not in seen:
            seen.add(code)
            unique.append(s)
    zt_pool = unique
    print(f'[K线更新] 涨停池: {len(zt_pool)}只')

    # 1.5 持仓标的也纳入更新 (卖点引擎依赖K线判断昨涨停/断板)
    pf_path = os.path.join(BASE, 'logs', 'portfolio.json')
    if os.path.exists(pf_path):
        with open(pf_path, encoding='utf-8') as f:
            pf = json.load(f)
        pool_codes = {s['code'] for s in zt_pool}
        for p in pf.get('positions') or []:
            if p.get('code') and p['code'] not in pool_codes:
                zt_pool.append({'code': p['code'], 'name': p.get('name', '')})
                print(f'[K线更新] 加入持仓标的: {p.get("name")}({p["code"]})')

    # 2. 统计: 哪些已有K线, 哪些是新标的
    existing = []
    new_stocks = []
    for s in zt_pool:
        fpath = find_kline_path(s['code'])
        if fpath:
            existing.append((s, fpath))
        else:
            new_stocks.append(s)

    print(f'[K线更新] 已有K线: {len(existing)}只 | 新标的: {len(new_stocks)}只')

    # 3. 新标的: 下载完整历史
    new_success = 0
    for s in new_stocks:
        rows, err = download_full(s['code'], s['name'], today)
        if err:
            print(f'  [ERROR] {s["name"]}({s["code"]}): {err}')
            continue
        if rows:
            fpath = os.path.join(KLINE_DIR, f'{s["name"]}_{s["code"]}.json')
            with open(fpath, 'w', encoding='utf-8') as f:
                json.dump(rows, f, ensure_ascii=False)
            new_success += 1
        time.sleep(0.05)

    # 5. 已有标的: 追加最新一天
    append_count = 0
    for s, fpath in existing:
        n = append_latest(s['code'], fpath, today)
        if n > 0:
            append_count += 1
        time.sleep(0.03)

    print(f'[K线更新] 新标的全量: {new_success}/{len(new_stocks)} | 追加最新: {append_count}/{len(existing)}')
    print(f'[K线更新] K线库总量: {len(glob.glob(os.path.join(KLINE_DIR, "*.json")))}只')
    print(f'[K线更新] 完成!')


if __name__ == '__main__':
    main()
