"""
每日资金流采集 (2026-08-18)
============================
⚠ 已弃用 (2026-09-04, 用户拍板): run_pipeline 不再调用本脚本。
裁决链: N≥50检验(51笔)初判达标 → 买入端T-1口径反向 → 历史补抓2562只大样本
四象限(状态×资金流): 区分度全部来自涨停/断板状态, 资金流方向零增量 → 无预测力。
历史数据仍保留: data/money_flow_history/ (2562只×500天, 供将来重验)。
"""
import json, os, sys, time, urllib.request

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ZT_STATE_PATH = os.path.join(BASE, 'data', 'zt_pool_state.json')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'


def fetch_money_flow(code, days=1):
    """新浪日频资金流, 返回最新一行 {date, netamount, ratioamount, r0_net, r0_ratio, r0x_ratio}"""
    pre = 'sh' if code.startswith(('5', '6', '9')) else 'sz'
    url = ('https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/'
           f'MoneyFlow.ssl_qsfx_zjlrqs?page=1&num={days}&sort=opendate&asc=0&daima={pre}{code}')
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': 'https://finance.sina.com.cn/'})
    try:
        raw = urllib.request.urlopen(req, timeout=10).read().decode('gbk')
        rows = json.loads(raw)
        if not rows:
            return None
        r = rows[0]
        return {
            'date': r['opendate'],
            'netamount': round(float(r.get('netamount', 0)), 2),       # 主力净流入(元)
            'ratioamount': round(float(r.get('ratioamount', 0)), 4),   # 净流入占比
            'r0_net': round(float(r.get('r0_net', 0)), 2),             # 超大单净流入(元)
            'r0_ratio': round(float(r.get('r0_ratio', 0)), 4),         # 超大单占比
            'r0x_ratio': round(float(r.get('r0x_ratio', 0)), 2),       # 主力(超大+大单)占比%
            'source': 'sina_moneyflow',
        }
    except Exception:
        return None


def main():
    if not os.path.exists(ZT_STATE_PATH):
        print('[MoneyFlow] 无涨停池 state, 退出')
        return
    with open(ZT_STATE_PATH, encoding='utf-8') as f:
        state = json.load(f)
    stocks = state.get('stocks', [])
    print(f'[MoneyFlow] 采集涨停池资金流 → {len(stocks)} 只')

    ok = 0
    for s in stocks:
        code = s.get('code', '')
        if not code:
            continue
        mf = fetch_money_flow(code)
        if mf:
            s['money_flow'] = mf
            ok += 1
        time.sleep(0.3)  # 限速防封

    # 2026-09-03修复: 原子写入(tmp+replace), 防与GUI刷新等并发写进程窗口内截断
    _tmp = ZT_STATE_PATH + '.tmp'
    with open(_tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(_tmp, ZT_STATE_PATH)
    print(f'[MoneyFlow] 写入 {ok}/{len(stocks)} 只 → {ZT_STATE_PATH}')


if __name__ == '__main__':
    main()
