"""
龙虎榜 + 大宗交易 增强因子 (实验性)
接入 run_pipeline.py 流水线，每日盘后自动抓取+积累

设计原则:
  - 只做信号记录，不修改V2评分 (避免过拟合)
  - 因子数据保存到 data/dt_block/ 目录
  - 积累一个月后再回测验证有效性
"""

import json, os, time, random, requests
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE, 'data', 'dt_block')
os.makedirs(DATA_DIR, exist_ok=True)

# ── 东财防封 ──
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
EM_MIN_INTERVAL = 1.2  # 批量任务间距调大
_em_last_call = [0.0]

def _em_get(url, params=None, headers=None, timeout=10, **kwargs):
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()

DC = "https://datacenter-web.eastmoney.com/api/data/v1/get"

def _dc(report, filter_str, ps=30, sc="", st="-1"):
    params = {"reportName": report, "columns": "ALL",
              "filter": filter_str, "pageNumber": "1", "pageSize": str(ps),
              "sortColumns": sc, "sortTypes": st, "source": "WEB", "client": "WEB"}
    r = _em_get(DC, params=params, timeout=15)
    d = r.json()
    return (d.get("result") or {}).get("data") or []

INST_KW = ['机构专用', '深股通专用', '沪股通专用', 'QFII']
LHASA_KW = ['拉萨', '团结路']


def fetch_dragon_tiger(code, date):
    """拉单股龙虎榜"""
    rows = _dc("RPT_DAILYBILLBOARD_DETAILSNEW",
               f"(TRADE_DATE='{date}')(SECURITY_CODE=\"{code}\")",
               ps=3, sc="BILLBOARD_NET_AMT", st="-1")
    if not rows:
        return None

    r = rows[0]
    buy_seats = _dc("RPT_BILLBOARD_DAILYDETAILSBUY",
                    f"(TRADE_DATE='{date}')(SECURITY_CODE=\"{code}\")",
                    ps=5, sc="BUY", st="-1")
    sell_seats = _dc("RPT_BILLBOARD_DAILYDETAILSSELL",
                     f"(TRADE_DATE='{date}')(SECURITY_CODE=\"{code}\")",
                     ps=5, sc="SELL", st="-1")

    total_buy = sum(s.get("BUY", 0) or 0 for s in buy_seats)
    inst_buy = sum(s.get("BUY", 0) or 0 for s in buy_seats
                   if any(k in (s.get("OPERATEDEPT_NAME", "") or "") for k in INST_KW))
    lhasa = any(any(k in (s.get("OPERATEDEPT_NAME", "") or "") for k in LHASA_KW)
                for s in buy_seats)
    top1 = max((s.get("BUY", 0) or 0 for s in buy_seats), default=0)

    return {
        'net_buy_wan': round((r.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
        'buy_wan': round((r.get("BILLBOARD_BUY_AMT") or 0) / 10000, 1),
        'sell_wan': round((r.get("BILLBOARD_SELL_AMT") or 0) / 10000, 1),
        'inst_buy_pct': round(inst_buy / total_buy * 100, 1) if total_buy > 0 else 0,
        'inst_net_wan': round((inst_buy - sum(
            s.get("SELL", 0) or 0 for s in sell_seats
            if any(k in (s.get("OPERATEDEPT_NAME", "") or "") for k in INST_KW)
        )) / 10000, 1),
        'lhasa_flag': lhasa,
        'top1_pct': round(top1 / total_buy * 100, 1) if total_buy > 0 else 0,
        'buy_seats': [s.get("OPERATEDEPT_NAME", "") for s in buy_seats[:3]],
    }


def fetch_block_trades(code, date):
    """拉大宗交易"""
    rows = _dc("RPT_DATA_BLOCKTRADE",
               f"(SECURITY_CODE=\"{code}\")(TRADE_DATE='{date}')",
               ps=10, sc="DEAL_AMT", st="-1")
    trades = []
    for r in rows:
        dp = r.get("DEAL_PRICE") or 0
        cp = r.get("CLOSE_PRICE") or 0
        trades.append({
            'premium_pct': round((dp / cp - 1) * 100, 2) if cp else 0,
            'amount_wan': round((r.get("DEAL_AMT") or 0) / 10000, 1),
            'buyer': r.get("BUYER_NAME", ""),
            'seller': r.get("SELLER_NAME", ""),
        })
    return trades


def compute_factor(dt, blocks):
    """计算调整分"""
    score = 0

    if dt:
        # 机构买入
        ip = dt['inst_buy_pct']
        if ip >= 30: score += 8
        elif ip >= 15: score += 4
        elif ip <= -30: score -= 8
        elif ip <= -15: score -= 4

        # 拉萨散户席
        if dt['lhasa_flag']:
            score -= 5

        # 买一集中度
        if dt['top1_pct'] > 25: score -= 3
        elif dt['top1_pct'] > 15: score -= 1

        # 净买额
        if dt['net_buy_wan'] > 10000: score += 3
        elif dt['net_buy_wan'] < -5000: score -= 4

    if blocks:
        disc = sum(b['amount_wan'] for b in blocks if b['premium_pct'] < -5)
        prem = sum(b['amount_wan'] for b in blocks if b['premium_pct'] > 2)
        if disc > 1000: score -= 5
        elif disc > 500: score -= 3
        elif disc > 100: score -= 1
        if prem > 500: score += 4
        elif prem > 100: score += 2

    return score


def run(date_str=None):
    """
    主入口: 对涨停池标的拉取龙虎榜+大宗，计算因子，保存
    由 run_pipeline.py 在盘后调用
    """
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')

    zt_file = os.path.join(BASE, 'data', 'zt_pool',
                           f'{date_str.replace("-", "")}.json')
    if not os.path.exists(zt_file):
        print(f"[DT] 无涨停池快照: {zt_file}")
        return

    # 读涨停池
    pool = None
    for enc in ['utf-8', 'gbk']:
        try:
            with open(zt_file, encoding=enc) as f:
                pool = json.load(f)
            break
        except:
            continue
    if not pool:
        print("[DT] 涨停池读取失败")
        return

    # 过滤300/301/688
    pool = [s for s in pool if not s['code'].startswith(('300', '301', '688'))]

    results = {}
    dt_count = 0
    block_count = 0

    # 只检查候选池中评分最高的一批 (Top40, 兼顾覆盖面与速度)
    # 如果已有 candidates JSON, 按评分取前40; 否则取涨停池全部
    cand_file = os.path.join(BASE, 'logs', f'candidates_{date_str}.json')
    check_pool = pool
    if os.path.exists(cand_file):
        try:
            with open(cand_file, encoding='utf-8') as f:
                cand = json.load(f)
            scored = {c['code']: c['score'] for c in cand.get('candidates', [])}
            # 按V2评分排序取前40
            sorted_codes = sorted(scored, key=scored.get, reverse=True)[:40]
            pool_map = {s['code']: s for s in pool}
            check_pool = [pool_map[c] for c in sorted_codes if c in pool_map]
        except:
            pass

    for i, s in enumerate(check_pool):
        code = s['code']
        name = s['name']
        try:
            dt = fetch_dragon_tiger(code, date_str)
            blocks = fetch_block_trades(code, date_str)
        except Exception as e:
            print(f"  [DT] {code} {name} err: {e}")
            continue

        if dt or blocks:
            factor = compute_factor(dt, blocks)
            results[code] = {
                'name': name,
                'date': date_str,
                'factor': factor,
                'dragon_tiger': dt,
                'block_trades': blocks if blocks else None,
            }
            if dt: dt_count += 1
            if blocks: block_count += 1

    # 保存
    if results:
        out_file = os.path.join(DATA_DIR, f'{date_str}.json')
        with open(out_file, 'w', encoding='utf-8') as f:
            json.dump({
                'date': date_str,
                'total_checked': len(pool),
                'dt_hits': dt_count,
                'block_hits': block_count,
                'results': results,
            }, f, ensure_ascii=False, indent=2)

    print(f"[DT] {date_str}: 检查{len(check_pool)}只 "
          f"龙虎榜{dt_count}只 大宗{block_count}只 "
          f"因子范围{min(r['factor'] for r in results.values()):+d}~"
          f"{max(r['factor'] for r in results.values()):+d}")

    # 对今天评级最高的可买候选做特别标注
    cand_file = os.path.join(BASE, 'logs', f'candidates_{date_str}.json')
    if os.path.exists(cand_file):
        try:
            with open(cand_file, encoding='utf-8') as f:
                cand = json.load(f)
            top = cand.get('top_pick')
            if top and top['code'] in results:
                r = results[top['code']]
                print(f"[DT] ★首选 {top['name']}({top['code']}) 因子: {r['factor']:+d}")

                dt_info = r.get('dragon_tiger')
                if dt_info:
                    print(f"    龙虎榜: 机构买{dt_info['inst_buy_pct']:.0f}% "
                          f"净买{dt_info['net_buy_wan']:.0f}万 "
                          f"{'拉萨席位!' if dt_info['lhasa_flag'] else ''}")
        except:
            pass

    return results


if __name__ == '__main__':
    import sys
    d = sys.argv[1] if len(sys.argv) > 1 else None
    run(d)
