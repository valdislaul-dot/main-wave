"""
历史龙虎榜+大宗交易数据收集 (后台任务)
拉取近一年全市场龙虎榜上榜记录 + 大宗交易
输出到 data/dt_block/ 供回测使用

东财API: 每交易日 ~2-3次请求即可覆盖全市场
"""

import json, os, sys, time, random, requests
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE, 'data', 'dt_block')
os.makedirs(DATA_DIR, exist_ok=True)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
EM_MIN_INTERVAL = 1.5
_em_last = [0.0]

def em_get(url, params=None, timeout=15, **kw):
    wait = EM_MIN_INTERVAL - (time.time() - _em_last[0])
    if wait > 0: time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, timeout=timeout, **kw)
    finally:
        _em_last[0] = time.time()

DC = "https://datacenter-web.eastmoney.com/api/data/v1/get"

def dc(report, filter_str, ps=500, sc="", st="-1"):
    p = {"reportName": report, "columns": "ALL", "filter": filter_str,
         "pageNumber": "1", "pageSize": str(ps),
         "sortColumns": sc, "sortTypes": st, "source": "WEB", "client": "WEB"}
    r = em_get(DC, params=p, timeout=20)
    return (r.json().get("result") or {}).get("data") or []


def fetch_daily_dragon_tiger(date_str):
    """全市场龙虎榜 (只拉概要，不拉席位明细，批量快)"""
    rows = dc("RPT_DAILYBILLBOARD_DETAILSNEW",
              f"(TRADE_DATE>='{date_str}')(TRADE_DATE<='{date_str}')",
              ps=500, sc="BILLBOARD_NET_AMT", st="-1")
    results = []
    for r in rows:
        code = r.get("SECURITY_CODE", "")
        if code.startswith(('300', '301', '688')):
            continue
        results.append({
            'code': code,
            'name': r.get("SECURITY_NAME_ABBR", ""),
            'net_buy_wan': round((r.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
            'buy_wan': round((r.get("BILLBOARD_BUY_AMT") or 0) / 10000, 1),
            'sell_wan': round((r.get("BILLBOARD_SELL_AMT") or 0) / 10000, 1),
            'turnover': round(float(r.get("TURNOVERRATE") or 0), 2),
            'change_pct': round(float(r.get("CHANGE_RATE") or 0), 2),
            'reason': r.get("EXPLANATION", ""),
        })
    return results


def fetch_daily_block_trades(date_str):
    """当日全市场大宗交易"""
    rows = dc("RPT_DATA_BLOCKTRADE",
              f"(TRADE_DATE='{date_str}')",
              ps=500, sc="DEAL_AMT", st="-1")
    results = []
    for r in rows:
        code = r.get("SECURITY_CODE", "")
        if code.startswith(('300', '301', '688')):
            continue
        dp = r.get("DEAL_PRICE") or 0
        cp = r.get("CLOSE_PRICE") or 0
        results.append({
            'code': code,
            'name': r.get("SECURITY_NAME_ABBR", ""),
            'premium_pct': round((dp/cp - 1)*100, 2) if cp else 0,
            'amount_wan': round((r.get("DEAL_AMT") or 0)/10000, 1),
            'buyer': r.get("BUYER_NAME", ""),
        })
    return results


def get_trading_days(n_days=750):
    """生成近N个交易日"""
    days = []
    d = datetime.now() - timedelta(days=1)
    while len(days) < n_days:
        if d.weekday() < 5:
            days.append(d.strftime('%Y-%m-%d'))
        d -= timedelta(days=1)
    return sorted(days)


def main():
    days = get_trading_days(750)
    print(f"收集区间: {days[0]} → {days[-1]} (共{len(days)}个交易日)")

    dt_all = {}
    block_all = {}
    dt_days = 0
    block_days = 0

    for i, date in enumerate(days):
        # 跳过已收集的
        save_file = os.path.join(DATA_DIR, f'{date}.json')
        if os.path.exists(save_file):
            for enc in ['utf-8', 'gbk']:
                try:
                    with open(save_file, encoding=enc) as f:
                        prev = json.load(f)
                    break
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
            dt_all[date] = prev.get('dragon_tiger', [])
            block_all[date] = prev.get('block_trades', [])
            if dt_all[date]: dt_days += 1
            if block_all[date]: block_days += 1
            continue

        dt_list = []
        block_list = []
        try:
            dt_list = fetch_daily_dragon_tiger(date)
            block_list = fetch_daily_block_trades(date)
        except Exception as e:
            print(f"  {date}: 请求失败 {e}")
            time.sleep(2)
            continue

        dt_all[date] = dt_list
        block_all[date] = block_list
        if dt_list: dt_days += 1
        if block_list: block_days += 1

        # 每日保存
        with open(save_file, 'w', encoding='utf-8') as f:
            json.dump({
                'date': date,
                'dragon_tiger': dt_list,
                'block_trades': block_list,
            }, f, ensure_ascii=False)

        print(f"  [{i+1}/{len(days)}] {date}: 龙虎榜{len(dt_list)}只 大宗{len(block_list)}笔")

    # 汇总
    summary = {
        'collected_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'date_range': f'{days[0]} → {days[-1]}',
        'trading_days': len(days),
        'days_with_dt': dt_days,
        'days_with_block': block_days,
        'total_dt_records': sum(len(v) for v in dt_all.values()),
        'total_block_records': sum(len(v) for v in block_all.values()),
    }
    with open(os.path.join(DATA_DIR, '_summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n完成: {summary}")
    return dt_all, block_all


if __name__ == '__main__':
    main()
