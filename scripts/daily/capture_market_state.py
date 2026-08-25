"""市场状态采集 (2026-08-25) — 盘后计算赚钱效应, 次日竞价校准温度开关
赚钱效应 = 昨日涨停股今日平均收益 (斯皮尔曼+0.403, 全指标与买入期望关联最强)
存储: data/market_state.json → {date, zt_n, max_cons, money_effect, history:[...30天]}
用法: 盘后流水线Step 8体检后调用; morning_check读取昨日值做降档校准
"""
import json, os, sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATE_PATH = os.path.join(BASE, 'data', 'market_state.json')
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
ZT_DIR = os.path.join(BASE, 'data', 'zt_pool')


def is_limit_up_row(k, pk):
    if k.get('pct_change') is not None:
        return k['pct_change'] >= 9.8
    return pk and pk.get('close', 0) > 0 and (k['close'] - pk['close']) / pk['close'] >= 0.098


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    today = datetime.now().strftime('%Y-%m-%d')
    # 昨日涨停池快照
    files = sorted(f for f in os.listdir(ZT_DIR) if f.endswith('.json') and f[:-5] <= today.replace('-', ''))
    if not files:
        print('[MarketState] 无池快照, 跳过')
        return
    ymd = files[-1][:-5]
    date_fmt = f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}'
    try:
        with open(os.path.join(ZT_DIR, files[-1]), encoding='utf-8') as f:
            pool = json.load(f)
    except UnicodeDecodeError:
        with open(os.path.join(ZT_DIR, files[-1]), encoding='gbk') as f:
            pool = json.load(f)
    stocks = pool if isinstance(pool, list) else pool.get('stocks', pool.get('data', []))

    # 赚钱效应: 昨日涨停股今日均收益 (从K线取今日close vs 昨日close)
    rets = []
    zt_n = len(stocks)
    max_cons = 1
    for s in stocks:
        code = str(s.get('code', '')).replace('sh', '').replace('sz', '')
        if not code:
            continue
        try:
            max_cons = max(max_cons, int(s.get('limit_days', 1) or 1))
        except Exception:
            pass
        for enc in ('utf-8', 'gbk'):
            try:
                with open(os.path.join(KLINE_DIR, f'{code}.json'), encoding=enc) as f:
                    raw = json.load(f)
                kls = raw.get('data', raw) if isinstance(raw, dict) else raw
                idx_t = next((i for i, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == today), None)
                idx_y = next((i for i, x in enumerate(kls) if isinstance(x, dict) and x.get('date') == date_fmt), None)
                if idx_t is not None and idx_y is not None:
                    c_t, c_y = kls[idx_t].get('close', 0), kls[idx_y].get('close', 0)
                    if c_t > 0 and c_y > 0:
                        rets.append((c_t - c_y) / c_y * 100)
                break
            except Exception:
                continue
    money_effect = round(sum(rets) / len(rets), 2) if rets else None
    print(f'[MarketState] {date_fmt}: 涨停{zt_n}只 最高{max_cons}板 赚钱效应{money_effect}% ({len(rets)}只有效)')

    # 落库(保留30天)
    state = {}
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding='utf-8') as f:
                state = json.load(f)
        except Exception:
            state = {}
    state['date'] = date_fmt
    state['zt_n'] = zt_n
    state['max_cons'] = max_cons
    state['money_effect'] = money_effect
    hist = [h for h in state.get('history', []) if h.get('date') != date_fmt]
    hist.append({'date': date_fmt, 'zt_n': zt_n, 'max_cons': max_cons, 'money_effect': money_effect})
    state['history'] = hist[-30:]
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(f'[MarketState] 已写入 {STATE_PATH}')


if __name__ == '__main__':
    main()
