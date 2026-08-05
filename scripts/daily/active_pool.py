"""
历史涨停池 — 收集所有上过涨停榜的股票
数据流:
  每日盘后: update() → 扫描涨停池快照 → 更新出现次数/最近日期
  用途:     查询某股是否有涨停基因

文件: data/historical_zt_pool.json
"""
import json, os, glob
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POOL_DIR = os.path.join(BASE, 'data', 'zt_pool')
STATE_PATH = os.path.join(BASE, 'data', 'historical_zt_pool.json')
ZT_STATE_PATH = os.path.join(BASE, 'data', 'zt_pool_state.json')


def update():
    """扫描所有涨停池快照，汇总历史涨停股"""
    today = datetime.now().strftime('%Y-%m-%d')
    stocks = {}  # code -> {name, count, first_date, last_date, max_cons, industry}

    # 扫描每日快照
    for fp in sorted(glob.glob(os.path.join(POOL_DIR, '*.json'))):
        date_str = os.path.basename(fp).replace('.json', '')
        try:
            with open(fp, encoding='utf-8') as f:
                pool = json.load(f)
        except:
            try:
                with open(fp, encoding='gbk') as f:
                    pool = json.load(f)
            except:
                continue
        if not isinstance(pool, list):
            continue

        for s in pool:
            code = s['code']
            if code not in stocks:
                stocks[code] = {
                    'name': s.get('name', ''),
                    'count': 0,
                    'first_date': date_str,
                    'last_date': date_str,
                    'max_cons': 0,
                    'industry': s.get('industry', ''),
                }
            e = stocks[code]
            e['count'] += 1
            e['last_date'] = max(e['last_date'], date_str)
            e['first_date'] = min(e['first_date'], date_str)
            e['max_cons'] = max(e['max_cons'], s.get('limit_days', 1))

    # 合并当前涨停池
    if os.path.exists(ZT_STATE_PATH):
        with open(ZT_STATE_PATH, encoding='utf-8') as f:
            state = json.load(f)
        for s in state.get('stocks', []):
            code = s['code']
            if code not in stocks:
                stocks[code] = {
                    'name': s.get('name', ''),
                    'count': 1,
                    'first_date': today,
                    'last_date': today,
                    'max_cons': s.get('limit_days', 1),
                    'industry': s.get('industry', ''),
                }

    # 保存
    result = {
        'updated': today,
        'total_stocks': len(stocks),
        'stocks': dict(sorted(stocks.items())),
    }
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'[历史涨停池] {len(stocks)}只')
    return result


def load():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding='utf-8') as f:
            return json.load(f)
    return update()


def lookup(code):
    """查某只股票的历史涨停记录"""
    pool = load()
    return pool['stocks'].get(code)


def top(n=20, sort_by='count'):
    """出现次数最多的Top N"""
    pool = load()
    items = [{'code': k, **v} for k, v in pool['stocks'].items()]
    ranked = sorted(items, key=lambda x: x.get(sort_by, 0), reverse=True)
    return ranked[:n]


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--update':
        update()
    elif len(sys.argv) > 1 and sys.argv[1] == '--lookup':
        code = sys.argv[2] if len(sys.argv) > 2 else ''
        s = lookup(code)
        if s:
            print(f"{s['name']}({code}): 出现{s['count']}次 "
                  f"({s['first_date']}~{s['last_date']}) 最大{s['max_cons']}连板 {s['industry']}")
        else:
            print(f"{code} 未上过涨停榜")
    else:
        update()
        print('\nTop 20:')
        for i, s in enumerate(top(20)):
            print(f"  {i+1}. {s['name']}({s.get('code','')}): {s['count']}次 "
                  f"最大{s['max_cons']}连板 {s['industry']}")
