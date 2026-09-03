"""
历史资金流补抓 (2026-09-04)
============================
同花顺历史池(2025-07起, 271天)全部涨停股的资金流一次性补齐。
新浪日频资金流接口 num=500 可翻到 2024-08, 覆盖历史池全窗口。
输出: data/money_flow_history/{code}.json = {opendate: {net, r0x}}
断点续跑: 已存在且最新日期>=昨日的跳过; 限速0.3s防封; 失败重试2次。
用途: 资金流因子大样本检验(卖出端T日/买入端T-1两口径), 替代51笔初判。
"""
import json, os, sys, time, urllib.request

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
THS_DIR = os.path.join(BASE, 'data', 'zt_pool_history_ths')
OUT_DIR = os.path.join(BASE, 'data', 'money_flow_history')
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
NUM = 500  # 覆盖2024-08至今


def fetch_hist(code):
    pre = 'sh' if code.startswith(('5', '6', '9')) else 'sz'
    url = ('https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/'
           f'MoneyFlow.ssl_qsfx_zjlrqs?page=1&num={NUM}&sort=opendate&asc=0&daima={pre}{code}')
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': 'https://finance.sina.com.cn/'})
    raw = urllib.request.urlopen(req, timeout=15).read().decode('gbk')
    return json.loads(raw)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # 收集历史池去重股票
    codes = set()
    for fn in sorted(os.listdir(THS_DIR)):
        if not fn.endswith('.json'):
            continue
        info = json.load(open(os.path.join(THS_DIR, fn), encoding='utf-8'))
        for s in info:
            c = str(s.get('code', ''))
            if c and not c.startswith(('300', '301', '688', '8', '9')):
                codes.add(c)
    codes = sorted(codes)
    print(f'[Backfill] 待补抓: {len(codes)}只 → {OUT_DIR}')

    done = skip = fail = 0
    for i, code in enumerate(codes):
        out_path = os.path.join(OUT_DIR, f'{code}.json')
        # 断点续跑: 已存在且覆盖到昨日 → 跳过
        if os.path.exists(out_path):
            try:
                old = json.load(open(out_path, encoding='utf-8'))
                if old and max(old.keys()) >= '2026-09-02':
                    skip += 1
                    continue
            except Exception:
                pass
        for attempt in range(3):
            try:
                rows = fetch_hist(code)
                hist = {r['opendate']: {'net': float(r.get('netamount', 0) or 0),
                                        'r0x': float(r.get('r0x_ratio', 0) or 0)} for r in rows}
                with open(out_path, 'w', encoding='utf-8') as f:
                    json.dump(hist, f, ensure_ascii=False)
                done += 1
                break
            except Exception:
                if attempt == 2:
                    fail += 1
                    print(f'  FAIL {code} (3次重试后放弃)')
                time.sleep(2)
        time.sleep(0.3)  # 限速防封
        if (i + 1) % 50 == 0:
            print(f'  进度 {i + 1}/{len(codes)} | 完成{done} 跳过{skip} 失败{fail}')

    print(f'[Backfill] 完成: {done}只新增, {skip}只跳过, {fail}只失败')


if __name__ == '__main__':
    main()
