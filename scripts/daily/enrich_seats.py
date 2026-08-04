"""
龙虎榜席位明细补全脚本 (后台)
对近一年 dt_block 数据中的每条上榜记录，补全买卖席位TOP5

API: 东财 datacenter RPT_BILLBOARD_DAILYDETAILSBUY/SELL
速度: ~3s/条, 近一年约5000条 → ~4小时
"""

import json, os, sys, time, random, requests
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DT_DIR = os.path.join(BASE, 'data', 'dt_block')

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
EM_MIN_INTERVAL = 1.5
_em_last = [0.0]

def em_get(url, params=None, timeout=15):
    global _em_last
    wait = EM_MIN_INTERVAL - (time.time() - _em_last[0])
    if wait > 0: time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, timeout=timeout)
    finally:
        _em_last[0] = time.time()

DC = "https://datacenter-web.eastmoney.com/api/data/v1/get"

def fetch_seats(code, date_str):
    """拉取单股单日买卖席位"""
    buy_seats = []
    sell_seats = []

    # 买席位
    try:
        data = _dc("RPT_BILLBOARD_DAILYDETAILSBUY",
                   f"(TRADE_DATE='{date_str}')(SECURITY_CODE=\"{code}\")",
                   ps=5, sc="BUY", st="-1")
        for r in data:
            buy_seats.append({
                'name': r.get("OPERATEDEPT_NAME", ""),
                'buy': round((r.get("BUY") or 0) / 10000, 1),
                'sell': round((r.get("SELL") or 0) / 10000, 1),
                'net': round((r.get("NET") or 0) / 10000, 1),
                'code': r.get("OPERATEDEPT_CODE", ""),
            })
    except: pass

    # 卖席位
    try:
        data = _dc("RPT_BILLBOARD_DAILYDETAILSSELL",
                   f"(TRADE_DATE='{date_str}')(SECURITY_CODE=\"{code}\")",
                   ps=5, sc="SELL", st="-1")
        for r in data:
            sell_seats.append({
                'name': r.get("OPERATEDEPT_NAME", ""),
                'buy': round((r.get("BUY") or 0) / 10000, 1),
                'sell': round((r.get("SELL") or 0) / 10000, 1),
                'net': round((r.get("NET") or 0) / 10000, 1),
                'code': r.get("OPERATEDEPT_CODE", ""),
            })
    except: pass

    return buy_seats, sell_seats


def _dc(report, filter_str, ps=5, sc="", st="-1"):
    params = {"reportName": report, "columns": "ALL", "filter": filter_str,
              "pageNumber": "1", "pageSize": str(ps),
              "sortColumns": sc, "sortTypes": st, "source": "WEB", "client": "WEB"}
    r = em_get(DC, params=params, timeout=15)
    return (r.json().get("result") or {}).get("data") or []


def analyze_seats(buy_seats, sell_seats):
    """从席位数据计算关键指标"""
    total_buy = sum(s['buy'] for s in buy_seats)
    total_sell = sum(s['sell'] for s in sell_seats)

    # 机构参与度
    inst_buy = sum(s['buy'] for s in buy_seats
                   if any(k in s['name'] for k in ['机构专用', '深股通专用', '沪股通专用', 'QFII']))
    inst_sell = sum(s['sell'] for s in sell_seats
                    if any(k in s['name'] for k in ['机构专用', '深股通专用', '沪股通专用', 'QFII']))

    # 拉萨席位
    lhasa_buy = any('拉萨' in s['name'] or '团结路' in s['name'] for s in buy_seats)
    lhasa_sell = any('拉萨' in s['name'] or '团结路' in s['name'] for s in sell_seats)

    # 买一占比
    top1_buy = max((s['buy'] for s in buy_seats), default=0)
    top1_pct = round(top1_buy / total_buy * 100, 1) if total_buy > 0 else 0

    # 知名游资 (简单版: 非机构非拉萨的大额席位)
    known_buyers = [s['name'] for s in buy_seats
                    if s['name'] and s['name'] not in ('-', '')
                    and not any(k in s['name'] for k in ['机构专用', '深股通', '沪股通', '拉萨', '团结路', 'QFII'])]

    return {
        'inst_buy_pct': round(inst_buy / total_buy * 100, 1) if total_buy > 0 else 0,
        'inst_sell_pct': round(inst_sell / total_sell * 100, 1) if total_sell > 0 else 0,
        'inst_net_wan': round(inst_buy - inst_sell, 1),
        'lhasa_flag': lhasa_buy or lhasa_sell,
        'lhasa_buy': lhasa_buy,
        'top1_pct': top1_pct,
        'buyer_count': len([s for s in buy_seats if s['buy'] > 0]),
        'known_buyers': known_buyers[:3],
        'total_buy_wan': round(total_buy, 1),
        'total_sell_wan': round(total_sell, 1),
    }


def main():
    # 近一年范围
    cutoff = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')

    # 列出需要补全的文件(近一年)
    files = sorted([f for f in os.listdir(DT_DIR)
                    if f.endswith('.json') and not f.startswith('_')
                    and f.replace('.json', '') >= cutoff])

    print(f"席位补全: {len(files)} 天 ({files[0]} → {files[-1]})")

    total_enriched = 0
    total_skipped = 0

    for fi, fn in enumerate(files):
        fpath = os.path.join(DT_DIR, fn)
        date_str = fn.replace('.json', '')

        # 读文件
        for enc in ['utf-8', 'gbk']:
            try:
                with open(fpath, encoding=enc) as f:
                    day_data = json.load(f)
                break
            except: continue

        dt_list = day_data.get('dragon_tiger', [])
        modified = False

        for si, stock in enumerate(dt_list):
            # 跳过已有席位数据的
            if stock.get('buy_seats') or stock.get('analysis'):
                total_skipped += 1
                continue

            code = stock.get('code', '')
            if not code: continue

            try:
                buy_seats, sell_seats = fetch_seats(code, date_str)
                if buy_seats or sell_seats:
                    stock['buy_seats'] = buy_seats
                    stock['sell_seats'] = sell_seats
                    stock['analysis'] = analyze_seats(buy_seats, sell_seats)
                    modified = True
                    total_enriched += 1
            except Exception as e:
                print(f"  [{fn}] {code} err: {e}")
                continue

        if modified:
            with open(fpath, 'w', encoding='utf-8') as f:
                json.dump(day_data, f, ensure_ascii=False, indent=2)

        if (fi + 1) % 20 == 0:
            print(f"  [{fi+1}/{len(files)}] {date_str}: "
                  f"补{total_enriched}跳{total_skipped}")

    print(f"\n完成: 补全{total_enriched}条 跳过{total_skipped}条")


if __name__ == '__main__':
    # 先测第一条看速度
    if '--dry' in sys.argv:
        today_files = sorted([f for f in os.listdir(DT_DIR)
                             if f.endswith('.json') and not f.startswith('_')])[-5:]
        for fn in today_files:
            fpath = os.path.join(DT_DIR, fn)
            date_str = fn.replace('.json', '')
            for enc in ['utf-8', 'gbk']:
                try:
                    with open(fpath, encoding=enc) as f:
                        day = json.load(f)
                    break
                except: continue
            dt = day.get('dragon_tiger', [])
            if dt:
                s = dt[0]
                t0 = time.time()
                buy, sell = fetch_seats(s['code'], date_str)
                print(f"  {s['code']} {s['name']}: "
                      f"买{len(buy)}席 卖{len(sell)}席 "
                      f"({time.time()-t0:.1f}s)")
                if buy:
                    print(f"    买1: {buy[0]['name']} {buy[0]['buy']}万")
                if sell:
                    print(f"    卖1: {sell[0]['name']} {sell[0]['sell']}万")
                analysis = analyze_seats(buy, sell)
                print(f"    分析: {analysis}")
                break
    else:
        main()
