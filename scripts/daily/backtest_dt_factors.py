"""
龙虎榜+大宗交易 回测验证
对比: V2原始 vs V2+龙虎榜增强 的选股表现

方法:
  历史涨停池 → 拉龙虎榜数据 → 计算增强因子 →
  统计次日收益率 → 评估因子有效性
"""

import json, os, sys, time, random
from datetime import datetime, timedelta
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, 'scripts', 'daily'))

from fetch_dt_block import (
    fetch_dragon_tiger_stock, fetch_block_trades,
    compute_dt_factor, _em_get, _eastmoney_datacenter,
    DATA_DIR, EM_MIN_INTERVAL
)


def get_trading_days(start_date, end_date):
    """生成交易日列表 (周一到周五, 排除已知假日的大致范围)"""
    days = []
    d = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    while d <= end:
        if d.weekday() < 5:
            days.append(d.strftime('%Y-%m-%d'))
        d += timedelta(days=1)
    return days


def collect_historical_factors(days, cache_file=None):
    """
    收集历史龙虎榜因子数据
    对每一天的涨停池股票，检查是否有龙虎榜上榜

    Returns: {
        date: {
            code: {dt_score, block_score, total_adj, details}
        }
    }
    """
    # 尝试读缓存
    if cache_file and os.path.exists(cache_file):
        with open(cache_file, encoding='utf-8') as f:
            cached = json.load(f)
        print(f"加载缓存: {len(cached)} 天")
        return cached

    all_data = {}

    for i, date in enumerate(days):
        zt_file = os.path.join(BASE, 'data', 'zt_pool',
                               f'{date.replace("-", "")}.json')
        if not os.path.exists(zt_file):
            continue

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
            continue

        day_data = {}
        for s in pool:
            code = s['code']
            # 排除300/301/688
            if code.startswith(('300', '301', '688')):
                continue

            try:
                factors = compute_dt_factor(code, date, verbose=False)
                if factors['details'].get('dragon_tiger') or factors['details'].get('block_trades'):
                    day_data[code] = {
                        'name': s['name'],
                        'dt_score': factors['dt_score'],
                        'block_score': factors['block_score'],
                        'total_adj': factors['total_adj'],
                        'limit_days': s.get('limit_days', 1),
                    }
                time.sleep(0.3)  # 东财限流
            except Exception as e:
                pass

        if day_data:
            all_data[date] = day_data

        print(f"  进度 {i+1}/{len(days)}: {date} "
              f"涨停{len(pool)}只 龙虎榜上榜{len(day_data)}只")

    # 保存缓存
    if cache_file:
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(all_data, f, ensure_ascii=False, indent=2)
        print(f"\n缓存已保存: {cache_file}")

    return all_data


def load_candidate_scores(days):
    """
    从 candidates JSON 加载 V2 原始评分
    Returns: {date: {code: {score, name, next_day_return}}}
    """
    scores = {}
    for date in days:
        cf = os.path.join(BASE, 'logs', f'candidates_{date}.json')
        if not os.path.exists(cf):
            # 试另一格式
            cf2 = os.path.join(BASE, 'logs', f'candidates_{date.replace("-", "")}.json')
            if not os.path.exists(cf2):
                continue

        try:
            for enc in ['utf-8', 'gbk']:
                try:
                    with open(cf, encoding=enc) as f:
                        data = json.load(f)
                    break
                except:
                    continue
        except:
            continue

        day_scores = {}
        for c in data.get('candidates', []):
            day_scores[c['code']] = {
                'name': c['name'],
                'score': c['score'],
                'vr20': c.get('vr20', 1),
                'cons': c.get('cons', 1),
            }

        if day_scores:
            scores[date] = day_scores

    return scores


def compute_next_day_return(code, date_str):
    """
    计算次日收益率 (T日涨停 → T+1开盘到收盘)
    使用 kline_data 中的日K线
    """
    # 找K线文件
    name = None
    kline_dir = os.path.join(BASE, 'data', 'kline_data')

    # 先找文件名
    for fname in os.listdir(kline_dir):
        if fname.endswith(f'_{code}.json'):
            name = fname.rsplit('_', 1)[0]
            fpath = os.path.join(kline_dir, fname)
            try:
                with open(fpath, encoding='utf-8') as f:
                    klines = json.load(f)
            except:
                continue

            # 找到涨停日和次日的K线
            t_idx = None
            for i, k in enumerate(klines):
                if k.get('date') == date_str:
                    t_idx = i
                    break

            if t_idx is not None and t_idx + 1 < len(klines):
                t1 = klines[t_idx + 1]
                t_open = t1.get('open', 0)
                t_close = t1.get('close', 0)
                if t_open > 0:
                    intraday_ret = (t_close - t_open) / t_open * 100
                    gap = (t_open - k['close']) / k['close'] * 100
                    return {
                        'next_date': t1.get('date', ''),
                        'gap_pct': round(gap, 2),
                        'intraday_ret': round(intraday_ret, 2),
                        'is_limit_up': intraday_ret > 9,
                    }
            break

    return None


def run_backtest_comparison(start, end):
    """
    核心回测: 对比有无龙虎榜增强因子的表现

    输出:
    - 龙虎榜上榜股票的次日表现分布
    - 不同因子得分的次日表现
    - V2增强前后选股差异
    """
    days = get_trading_days(start, end)
    cache_file = os.path.join(DATA_DIR, 'historical_factors.json')

    # 收集因子数据
    print("=" * 60)
    print("Step 1: 收集历史龙虎榜因子...")
    print("=" * 60)
    factors = collect_historical_factors(days, cache_file)

    # 统计
    print("\n" + "=" * 60)
    print("Step 2: 统计分析")
    print("=" * 60)

    all_stocks = []  # 所有有龙虎榜数据的股票
    adj_groups = defaultdict(list)  # 按调整分组
    no_dt_stocks = 0

    for date, day_data in factors.items():
        for code, info in day_data.items():
            # 获取次日收益
            next_day = compute_next_day_return(code, date)
            if next_day:
                entry = {
                    'date': date,
                    'code': code,
                    'name': info['name'],
                    'dt_score': info['dt_score'],
                    'block_score': info['block_score'],
                    'total_adj': info['total_adj'],
                    'limit_days': info['limit_days'],
                    **next_day,
                }
                all_stocks.append(entry)
                adj_groups[info['total_adj']].append(entry)

    if not all_stocks:
        print("[WARN] 无足够数据: 涨停池快照缺失或K线数据不足")
        # 用已有数据进行简化分析
        return simple_factor_analysis(factors)

    # ── 分组统计 ──
    print(f"\n总样本: {len(all_stocks)} 只 (有龙虎榜数据的涨停股)")

    # 按因子得分分组
    positive = [s for s in all_stocks if s['total_adj'] > 0]    # 正面信号
    neutral = [s for s in all_stocks if s['total_adj'] == 0]    # 无信号(未上榜)
    negative = [s for s in all_stocks if s['total_adj'] < 0]    # 负面信号

    def stats(group, label):
        if not group:
            print(f"\n{label}: 无样本")
            return
        n = len(group)
        avg_gap = sum(s['gap_pct'] for s in group) / n
        avg_ret = sum(s['intraday_ret'] for s in group) / n
        lu_rate = sum(1 for s in group if s['is_limit_up']) / n * 100
        print(f"\n{label} ({n}只):")
        print(f"  次日平均竞价gap: {avg_gap:+.2f}%")
        print(f"  次日平均日内收益: {avg_ret:+.2f}%")
        print(f"  次日连板率: {lu_rate:.1f}%")
        return n, avg_gap, avg_ret, lu_rate

    stats(positive, "正面信号 (total_adj > 0)")
    stats(neutral, "中性信号 (total_adj = 0)")
    stats(negative, "负面信号 (total_adj < 0)")

    # ── 更细粒度: 强正面 vs 弱正面 ──
    strong_pos = [s for s in all_stocks if s['total_adj'] >= 5]
    weak_pos = [s for s in all_stocks if 0 < s['total_adj'] < 5]
    strong_neg = [s for s in all_stocks if s['total_adj'] <= -3]

    stats(strong_pos, "强正面 (adj >= +5)")
    stats(weak_pos, "弱正面 (0 < adj < +5)")
    stats(strong_neg, "强负面 (adj <= -3)")

    # ── 机构买入占比分析 ──
    print(f"\n{'='*60}")
    print("机构买入占比 vs 次日连板率")
    print(f"{'='*60}")
    inst_groups = {
        '高机构(>50%)': [],
        '中机构(20-50%)': [],
        '低机构(<20%)': [],
        '无机构(0%)': [],
    }
    for s in all_stocks:
        dt = s.get('details', {}).get('dragon_tiger', {})
        if not dt:
            inst_groups['无机构(0%)'].append(s)
        else:
            pct = dt.get('inst_buy_pct', 0)
            if pct > 50:
                inst_groups['高机构(>50%)'].append(s)
            elif pct > 20:
                inst_groups['中机构(20-50%)'].append(s)
            elif pct > 0:
                inst_groups['低机构(<20%)'].append(s)
            else:
                inst_groups['无机构(0%)'].append(s)

    for label, group in inst_groups.items():
        if group:
            n = len(group)
            avg_ret = sum(s['intraday_ret'] for s in group) / n
            lu_rate = sum(1 for s in group if s['is_limit_up']) / n * 100
            print(f"  {label}: {n}只 | 均收益{avg_ret:+.2f}% | 连板率{lu_rate:.1f}%")

    return all_stocks


def simple_factor_analysis(factors):
    """简化分析: 当K线数据不足时的统计"""
    print(f"\n简化分析: {len(factors)} 天有龙虎榜数据")

    total_stocks = 0
    score_dist = defaultdict(int)

    for date, day_data in factors.items():
        total_stocks += len(day_data)
        for code, info in day_data.items():
            score_dist[info['total_adj']] += 1

    print(f"总上榜次数: {total_stocks}")
    print(f"\n因子得分分布:")
    for score in sorted(score_dist.keys()):
        bar = '█' * score_dist[score]
        print(f"  {score:+3d}: {score_dist[score]:3d} {bar}")

    return factors


if __name__ == '__main__':
    if len(sys.argv) >= 3:
        start, end = sys.argv[1], sys.argv[2]
    else:
        # 默认: 从涨停池快照中找最早和最晚的日期
        zt_dir = os.path.join(BASE, 'data', 'zt_pool')
        dates = sorted([f.replace('.json', '') for f in os.listdir(zt_dir)
                       if f.endswith('.json')])
        if dates:
            start = f"{dates[0][:4]}-{dates[0][4:6]}-{dates[0][6:8]}"
            end = f"{dates[-1][:4]}-{dates[-1][4:6]}-{dates[-1][6:8]}"
        else:
            start, end = '2026-07-24', '2026-07-27'

    print(f"回测区间: {start} → {end}")
    run_backtest_comparison(start, end)
