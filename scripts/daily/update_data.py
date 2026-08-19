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
    """腾讯qfq日K → 最近bar (主源), volume手→股
    pct_change 在 qfq 序列内部计算: 前复权不改变相邻两日的相对涨跌,
    故 qfq 内部 (close/prev_close-1) 即真实当日涨跌幅 (除权日也准确)"""
    try:
        import urllib.request
        mkt = 'sz' if code.startswith(('0', '3', '1')) else 'sh'
        url = f'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={mkt}{code},day,,,100,qfq'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        d = json.loads(urllib.request.urlopen(req, timeout=10).read().decode('utf-8'))
        rows = (d.get('data', {}).get(f'{mkt}{code}', {}) or {}).get('qfqday') or []
        out = []
        for i, r in enumerate(rows):
            if not (r[0] > last_date and r[0] <= end_date):
                continue
            # 腾讯格式: [date, open, close, high, low, volume(手)]
            row = {
                'date': r[0],
                'open': round(float(r[1]), 2),
                'high': round(float(r[3]), 2),
                'low': round(float(r[4]), 2),
                'close': round(float(r[2]), 2),
                'volume': round(float(r[5]) * 100, 2),
            }
            # qfq序列内计算pct_change: 前一行(序列内, 升序)收盘价
            prev_close = float(rows[i - 1][2]) if i > 0 else None
            if prev_close:
                row['pct_change'] = round((row['close'] - prev_close) / prev_close * 100, 2)
            out.append(row)
        return out or None
    except Exception:
        return None


def _tushare_latest(code, last_date, end_date):
    """Tushare daily → 最近bar (增量备源, 不复权与主库同口径), volume手→股"""
    from kline_source import fetch_tushare_daily
    rows = fetch_tushare_daily(code, last_date, end_date)
    if not rows:
        return None
    out = [r for r in rows if r['date'] > last_date and r['date'] <= end_date]
    return out or None


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


def append_latest(code, existing_path, end_date, pool_map=None):
    """追加最新一天到已有K线文件 (腾讯fqkline主源, 新浪兜底)
    pool_map: {code: {turnover, amount}} 当日涨停池映射, 用于补追加行的换手/成交额字段"""
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

    # 1. 腾讯fqkline前复权主源 (当日实时)
    candidate = _tencent_latest(code, last_date, end_date)
    if candidate and not _corporate_action_suspect(code, klines, candidate):
        new_rows, source = candidate, 'tencent'

    # 2. Tushare daily不复权备源 (权威, 当日更新及时, 与主库同口径)
    if not new_rows:
        candidate = _tushare_latest(code, last_date, end_date)
        if candidate:
            new_rows, source = candidate, 'tushare'

    # 3. 前两源失败 → 新浪不复权兜底 (与主库同口径)
    if not new_rows:
        full_rows, err = download_full(code, '', end_date)
        if full_rows:
            new_rows = [r for r in full_rows if r['date'] > last_date]
            if new_rows:
                source = 'sina'
        else:
            return -1

    # 字段补齐: 追加行缺 turnover_pct/amount → 从涨停池映射补 (池外股票维持None)
    if new_rows and pool_map and code in pool_map:
        pm = pool_map[code]
        for row in new_rows:
            if row['date'] == end_date:
                if pm.get('turnover') and row.get('turnover_pct') is None:
                    row['turnover_pct'] = round(float(pm['turnover']), 2)
                if pm.get('amount') and row.get('amount_10k_cny') is None:
                    # 东财 amount 单位元 → 万元 (与搜狐主库 amount_10k_cny 口径一致)
                    row['amount_10k_cny'] = round(float(pm['amount']) / 10000, 2)

    if new_rows:
        klines.extend(new_rows)
        if is_dict_fmt:
            raw['data'] = klines
            md = raw.get('metadata') or {}
            md['adjustment'] = 'mixed(qfq_append)'
            md['source'] = 'Sohu+EM/Tencent/Sina'
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

    # 5. 已有标的: 追加最新一天 (池映射用于补追加行的换手/成交额字段)
    pool_map = {s['code']: s for s in zt_pool}
    append_count = 0
    for s, fpath in existing:
        n = append_latest(s['code'], fpath, today, pool_map=pool_map)
        if n > 0:
            append_count += 1
        time.sleep(0.03)

    print(f'[K线更新] 新标的全量: {new_success}/{len(new_stocks)} | 追加最新: {append_count}/{len(existing)}')
    print(f'[K线更新] K线库总量: {len(glob.glob(os.path.join(KLINE_DIR, "*.json")))}只')

    # 6. Tushare权威校准 (可选, 抽查涨停池当日收盘价 vs 本地K线)
    try:
        from kline_source import fetch_tushare_daily, _load_tushare_token
        print('\n[K线更新] Tushare权威校准(抽查)...')
        if not _load_tushare_token():
            print('  [跳过] 未配置Tushare token (环境变量TUSHARE_TOKEN 或 data/tushare_token.txt)')
        else:
            checked = 0
            for s in zt_pool[:3]:
                rows = fetch_tushare_daily(s['code'], today, today)
                if not rows:
                    continue
                ts_close = rows[-1]['close']
                fpath = find_kline_path(s['code'])
                local_close = None
                if fpath:
                    with open(fpath, encoding='utf-8') as f:
                        raw = json.load(f)
                    kl = raw.get('data', raw) if isinstance(raw, dict) else raw
                    if kl:
                        local_close = kl[-1].get('close')
                if local_close and ts_close:
                    diff = abs(local_close - ts_close) / ts_close
                    flag = '✓' if diff <= 0.02 else '⚠'
                    print(f'  {flag} {s["name"]}({s["code"]}) 本地{local_close} vs Tushare{ts_close} (偏差{diff*100:.2f}%)')
                    checked += 1
            if checked == 0:
                print('  [跳过] Tushare当日数据未就绪(收盘后稍晚更新)')
    except Exception as e:
        print(f'  [警告] Tushare校准失败: {e}')

    print(f'[K线更新] 完成!')


if __name__ == '__main__':
    main()
