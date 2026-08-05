"""
活跃股筛选器 — 基于K线数据统计历史涨停活跃度
无需额外数据积累，直接扫描 data/kline_data/ 即可

用法:
  python active_stocks.py              # 全部排名
  python active_stocks.py --top 50     # Top 50
  python active_stocks.py --recent 30  # 近30天活跃
  python active_stocks.py --industry   # 按行业
"""
import json, os, glob, sys
from datetime import datetime, timedelta
from collections import defaultdict, Counter

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
ZT_POOL_DIR = os.path.join(BASE, 'data', 'zt_pool')
ZT_STATE_PATH = os.path.join(BASE, 'data', 'zt_pool_state.json')


def is_limit_up(close, prev_close, lp=0.10):
    return prev_close > 0 and close >= round(prev_close * (1 + lp), 2) - 0.005


def load_industry_map():
    """从涨停池数据构建行业映射"""
    imap = {}
    for src in [ZT_STATE_PATH] + sorted(glob.glob(os.path.join(ZT_POOL_DIR, '*.json'))):
        if not os.path.exists(src):
            continue
        try:
            with open(src, encoding='utf-8') as f:
                data = json.load(f)
        except:
            try:
                with open(src, encoding='gbk') as f:
                    data = json.load(f)
            except:
                continue
        stocks = data.get('stocks', data) if isinstance(data, dict) else data
        if isinstance(stocks, list):
            for s in stocks:
                if isinstance(s, dict) and 'code' in s:
                    imap[s['code']] = s.get('industry', '')
    return imap


def scan_active(cutoff_date=None, min_lu_days=0):
    """
    扫描所有K线，统计涨停活跃度
    cutoff_date: 只统计此日期之后的涨停（None=全部）
    """
    industry_map = load_industry_map()
    results = []

    # 先收集所有文件，去重（同名不同文件取名字完整的）
    code_files = {}  # code -> (name, filepath)
    for fp in glob.glob(os.path.join(KLINE_DIR, '*.json')):
        fname = os.path.basename(fp).replace('.json', '')
        parts = fname.rsplit('_', 1)
        if len(parts) == 2 and parts[0] and parts[0] != parts[1]:
            name, code = parts[0], parts[1]
        else:
            code = fname.lstrip('_')
            name = ''
        # 优先保留有名字的
        if code not in code_files or (name and not code_files[code][0]):
            code_files[code] = (name, fp)

    for code, (name, fp) in code_files.items():
        try:
            with open(fp, encoding='utf-8') as f:
                klines = json.load(f)
        except:
            continue
        if len(klines) < 25:
            continue

        lu_days = 0
        max_cons = 0
        cur_cons = 0
        last_lu_date = ''
        recent_lu_days = 0  # 近30天

        for i in range(1, len(klines)):
            prev_c = klines[i-1]['close']
            cur_c = klines[i]['close']
            dt = klines[i]['date']
            lp = 0.20 if code.startswith(('30','688')) else 0.10

            if is_limit_up(cur_c, prev_c, lp):
                # 时间过滤
                if cutoff_date and dt < cutoff_date:
                    continue
                lu_days += 1
                cur_cons += 1
                max_cons = max(max_cons, cur_cons)
                last_lu_date = dt
                if cutoff_date:
                    recent_lu_days += 1
            else:
                cur_cons = 0

        if lu_days >= min_lu_days:
            results.append({
                'name': name, 'code': code,
                'lu_days': lu_days,
                'max_cons': max_cons,
                'last_lu': last_lu_date,
                'industry': industry_map.get(code, ''),
            })

    return results


def print_table(results, top_n=30, title=None):
    if title:
        print(f"\n{'='*70}")
        print(f"  {title} (共{len(results)}只)")
        print(f"{'='*70}")
    print(f"{'#':<4} {'代码':<8} {'名称':<8} {'涨停天':>5} {'最大连板':>6} {'最近':>10} {'行业'}")
    print(f"{'-'*70}")
    for i, a in enumerate(results[:top_n]):
        print(f"{i+1:<4} {a['code']:<8} {a['name']:<8} {a['lu_days']:>4}天 "
              f"{a['max_cons']:>4}连板 {a['last_lu']:>10} {a['industry']}")


if __name__ == '__main__':
    args = sys.argv[1:]

    if '--recent' in args:
        idx = args.index('--recent')
        days = int(args[idx+1]) if idx+1 < len(args) else 30
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        results = scan_active(cutoff_date=cutoff)
        results.sort(key=lambda x: x['lu_days'], reverse=True)
        print_table(results, top_n=50, title=f"近{days}天活跃股")
    elif '--industry' in args:
        results = scan_active()
        # 按行业汇总
        ind = defaultdict(lambda: {'count': 0, 'lu_days': 0, 'top_stock': ''})
        for a in results:
            ind_name = a['industry'] or '未知'
            ind[ind_name]['count'] += 1
            ind[ind_name]['lu_days'] += a['lu_days']
            if a['lu_days'] > ind[ind_name].get('_max_lu', 0):
                ind[ind_name]['_max_lu'] = a['lu_days']
                ind[ind_name]['top_stock'] = f"{a['name']}({a['code']})"
        ranked = sorted(ind.items(), key=lambda x: x[1]['lu_days'], reverse=True)
        print(f"\n{'='*50}")
        print(f"  行业活跃度排名 (按涨停总天数)")
        print(f"{'='*50}")
        for i, (name, d) in enumerate(ranked[:15]):
            print(f"  {i+1}. {name}: {d['count']}只 {d['lu_days']}天 "
                  f"| 代表: {d['top_stock']}")
    else:
        top_n = 30
        if '--top' in args:
            idx = args.index('--top')
            top_n = int(args[idx+1]) if idx+1 < len(args) else 30
        results = scan_active()
        results.sort(key=lambda x: (x['lu_days'], x['max_cons']), reverse=True)
        print_table(results, top_n=top_n, title="历史活跃股排名（全量K线）")
