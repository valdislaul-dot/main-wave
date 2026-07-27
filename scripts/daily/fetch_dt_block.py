"""
龙虎榜 + 大宗交易 数据抓取 & 因子计算
用于 V2 评分的辅助增强因子

数据源: 东财 datacenter (em_get 限流)
"""

import json, os, time, random, requests
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE, 'data', 'dt_block')
os.makedirs(DATA_DIR, exist_ok=True)

# ── 东财防封 (复用项目现有模式) ──
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]

def _em_get(url, params=None, headers=None, timeout=15, **kwargs):
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()

DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"


def _eastmoney_datacenter(report_name, filter_str="", page_size=50,
                           sort_columns="", sort_types="-1"):
    """东财数据中心统一查询"""
    params = {
        "reportName": report_name, "columns": "ALL",
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    r = _em_get(DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


# ═══════════════════════════════════════════════════════════════
# 龙虎榜
# ═══════════════════════════════════════════════════════════════

# 知名游资/机构席位关键词 (东财席位名称中包含这些的判定为机构)
INST_KEYWORDS = ['机构专用', '深股通专用', '沪股通专用', 'QFII']

# 拉萨席位 = 散户大本营 (东方财富网上开户默认席位)
LHASA_KEYWORDS = ['拉萨', '团结路']


def fetch_dragon_tiger_stock(code, date_str):
    """
    获取单只股票在某日的龙虎榜数据
    date_str: 'YYYY-MM-DD'
    Returns: dict or None (未上榜)
    """
    # 查上榜记录
    data = _eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE='{date_str}')(SECURITY_CODE=\"{code}\")",
        page_size=5,
        sort_columns="BILLBOARD_NET_AMT", sort_types="-1",
    )
    if not data:
        return None

    row = data[0]
    net_buy = (row.get("BILLBOARD_NET_AMT") or 0) / 10000
    buy_amt = (row.get("BILLBOARD_BUY_AMT") or 0) / 10000
    sell_amt = (row.get("BILLBOARD_SELL_AMT") or 0) / 10000
    turnover = float(row.get("TURNOVERRATE") or 0)

    # 买席位 TOP5
    buy_seats = _eastmoney_datacenter(
        "RPT_BILLBOARD_DAILYDETAILSBUY",
        filter_str=f"(TRADE_DATE='{date_str}')(SECURITY_CODE=\"{code}\")",
        page_size=5, sort_columns="BUY", sort_types="-1",
    )

    # 卖席位 TOP5
    sell_seats = _eastmoney_datacenter(
        "RPT_BILLBOARD_DAILYDETAILSSELL",
        filter_str=f"(TRADE_DATE='{date_str}')(SECURITY_CODE=\"{code}\")",
        page_size=5, sort_columns="SELL", sort_types="-1",
    )

    # ── 分析席位 ──
    def _analyze_seats(seats):
        total_buy = sum(s.get("BUY", 0) or 0 for s in seats)
        total_sell = sum(s.get("SELL", 0) or 0 for s in seats)
        inst_buy = sum(s.get("BUY", 0) or 0 for s in seats
                       if _is_institution(s.get("OPERATEDEPT_NAME", "")))
        lhasa_buy = sum(s.get("BUY", 0) or 0 for s in seats
                        if _is_lhasa(s.get("OPERATEDEPT_NAME", "")))
        top1_buy = max((s.get("BUY", 0) or 0 for s in seats), default=0)
        top1_pct = (top1_buy / total_buy * 100) if total_buy > 0 else 0
        return {
            'total_buy': total_buy,
            'total_sell': total_sell,
            'inst_buy': inst_buy,
            'inst_buy_pct': (inst_buy / total_buy * 100) if total_buy > 0 else 0,
            'lhasa_buy': lhasa_buy,
            'lhasa_flag': lhasa_buy > 0,
            'top1_pct': top1_pct,
            'buyer_count': len([s for s in seats if (s.get("BUY") or 0) > 0]),
        }

    buy_info = _analyze_seats(buy_seats)
    # 综合买卖双方
    all_seats = buy_seats + sell_seats
    inst_total_buy = sum(s.get("BUY", 0) or 0 for s in all_seats
                         if _is_institution(s.get("OPERATEDEPT_NAME", "")))
    inst_total_sell = sum(s.get("SELL", 0) or 0 for s in all_seats
                          if _is_institution(s.get("OPERATEDEPT_NAME", "")))
    inst_net = inst_total_buy - inst_total_sell
    inst_net_pct = (inst_total_buy / (buy_amt * 10000) * 100) if buy_amt > 0 else 0

    return {
        'date': date_str,
        'code': code,
        'on_board': True,
        'reason': row.get("EXPLANATION", ""),
        'net_buy_wan': round(net_buy, 1),
        'buy_wan': round(buy_amt, 1),
        'sell_wan': round(sell_amt, 1),
        'turnover_pct': round(turnover, 2),
        'inst_net_wan': round(inst_net / 10000, 1),
        'inst_buy_pct': round(buy_info['inst_buy_pct'], 1),
        'top1_buyer_pct': round(buy_info['top1_pct'], 1),
        'lhasa_flag': buy_info['lhasa_flag'],
        'buyer_count': buy_info['buyer_count'],
        # 席位明细 (供调试)
        'buy_seats': [{'name': s.get("OPERATEDEPT_NAME", ""),
                       'buy': round((s.get("BUY") or 0) / 10000, 1)}
                      for s in buy_seats[:3]],
    }


def _is_institution(name):
    return any(kw in name for kw in INST_KEYWORDS)


def _is_lhasa(name):
    return any(kw in name for kw in LHASA_KEYWORDS)


# ═══════════════════════════════════════════════════════════════
# 大宗交易
# ═══════════════════════════════════════════════════════════════

def fetch_block_trades(code, date_str):
    """
    获取某只股票在指定日期的大宗交易
    date_str: 'YYYY-MM-DD'
    Returns: list of dicts (可能为空)
    """
    data = _eastmoney_datacenter(
        "RPT_DATA_BLOCKTRADE",
        filter_str=f"(SECURITY_CODE=\"{code}\")(TRADE_DATE='{date_str}')",
        page_size=20,
        sort_columns="DEAL_AMT", sort_types="-1",
    )
    if not data:
        return []

    trades = []
    for row in data:
        deal_price = row.get("DEAL_PRICE") or 0
        close = row.get("CLOSE_PRICE") or 0
        premium = ((deal_price / close - 1) * 100) if close else 0
        trades.append({
            'date': str(row.get("TRADE_DATE", ""))[:10],
            'price': deal_price,
            'close': close,
            'premium_pct': round(premium, 2),
            'vol_wan': round((row.get("DEAL_VOLUME") or 0) / 10000, 1),
            'amount_wan': round((row.get("DEAL_AMT") or 0) / 10000, 1),
            'buyer': row.get("BUYER_NAME", ""),
            'seller': row.get("SELLER_NAME", ""),
        })
    return trades


# ═══════════════════════════════════════════════════════════════
# 因子计算 (将龙虎榜+大宗数据转为评分调整)
# ═══════════════════════════════════════════════════════════════

def compute_dt_factor(code, date_str, verbose=False):
    """
    计算龙虎榜增强因子得分
    date_str: 涨停日期
    Returns: {
        'dt_score': 龙虎榜调整分,
        'block_score': 大宗交易调整分,
        'total_adj': 总分调整,
        'details': 明细
    }
    """
    details = {}

    # ── 龙虎榜因子 ──
    dt_score = 0
    dt = fetch_dragon_tiger_stock(code, date_str)

    if dt and dt['on_board']:
        details['dragon_tiger'] = dt

        # 1. 机构净买入
        inst_pct = dt['inst_buy_pct']
        if inst_pct >= 30:
            dt_score += 8    # 机构主导买入，强烈看多
        elif inst_pct >= 15:
            dt_score += 4    # 有机构参与
        elif inst_pct <= -30:
            dt_score -= 8    # 机构主导卖出，强烈看空
        elif inst_pct <= -15:
            dt_score -= 4

        # 2. 拉萨席位 = 散户
        if dt['lhasa_flag']:
            dt_score -= 5    # 散户席位上榜 → 主力已走

        # 3. 买一集中度
        top1 = dt['top1_buyer_pct']
        if top1 > 25:
            dt_score -= 3    # 一家独大，次日砸盘风险
        elif top1 > 15:
            dt_score -= 1

        # 4. 净买额信号 (不是所有上榜都净买)
        net = dt['net_buy_wan']
        if net > 10000:
            dt_score += 3    # 净买过亿
        elif net < -5000:
            dt_score -= 4    # 净卖为主

        if verbose:
            print(f"  [龙虎榜] {code} 机构%={inst_pct:.0f} "
                  f"拉萨={dt['lhasa_flag']} 集中度={top1:.0f}% 净买={net:.0f}万 "
                  f"→ 调整{dt_score:+d}")

    # ── 大宗交易因子 ──
    block_score = 0
    blocks = fetch_block_trades(code, date_str)

    if blocks:
        details['block_trades'] = blocks
        total_discount_amt = 0
        total_premium_amt = 0

        for b in blocks:
            if b['premium_pct'] < -5:
                total_discount_amt += b['amount_wan']  # 折价>5%，有人在逃
            elif b['premium_pct'] > 2:
                total_premium_amt += b['amount_wan']   # 溢价，抢筹信号

        if total_discount_amt > 1000:
            block_score -= 5   # 大宗折价出逃>1kw
        elif total_discount_amt > 500:
            block_score -= 3
        elif total_discount_amt > 100:
            block_score -= 1

        if total_premium_amt > 500:
            block_score += 4   # 溢价大宗>500w，强烈看多
        elif total_premium_amt > 100:
            block_score += 2

        if verbose:
            print(f"  [大宗] {code} {len(blocks)}笔 "
                  f"折价额={total_discount_amt:.0f}万 "
                  f"溢价额={total_premium_amt:.0f}万 "
                  f"→ 调整{block_score:+d}")

    total_adj = dt_score + block_score

    return {
        'dt_score': dt_score,
        'block_score': block_score,
        'total_adj': total_adj,
        'details': details,
    }


# ═══════════════════════════════════════════════════════════════
# 批量测试: 对涨停池所有标的拉龙虎榜+大宗
# ═══════════════════════════════════════════════════════════════

def batch_test(date_str, top_n=20):
    """对某日涨停池标的批量计算增强因子"""
    zt_file = os.path.join(BASE, 'data', 'zt_pool', f'{date_str.replace("-", "")}.json')
    if not os.path.exists(zt_file):
        print(f"[Error] 涨停池文件不存在: {zt_file}")
        return []

    # zt_pool 文件可能 utf-8 或 gbk
    pool = None
    for enc in ['utf-8', 'gbk', 'utf-8-sig']:
        try:
            with open(zt_file, encoding=enc) as f:
                pool = json.load(f)
            break
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    if pool is None:
        print(f"[Error] 无法读取涨停池文件: {zt_file}")
        return []
        pool = json.load(f)

    results = []
    for s in pool[:top_n]:
        code = s['code']
        name = s['name']
        try:
            factors = compute_dt_factor(code, date_str, verbose=True)
            factors['code'] = code
            factors['name'] = name
            results.append(factors)
        except Exception as e:
            print(f"  [Error] {code} {name}: {e}")
        time.sleep(0.5)  # 防封

    # 统计
    dt_hit = sum(1 for r in results if r['details'].get('dragon_tiger'))
    block_hit = sum(1 for r in results if r['details'].get('block_trades'))
    print(f"\n{'='*60}")
    print(f"统计: {len(results)}只 | 龙虎榜上榜 {dt_hit}只 | 大宗交易 {block_hit}只")
    print(f"评分调整范围: {min(r['total_adj'] for r in results):+d} ~ "
          f"{max(r['total_adj'] for r in results):+d}")

    return results


if __name__ == '__main__':
    import sys
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime('%Y-%m-%d')
    print(f"龙虎榜+大宗交易因子测试 — {date}")
    batch_test(date, top_n=30)
