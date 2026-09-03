"""补齐同花顺历史池缺失/残缺日期 (2026-09-04用户指令: K线不自建, 用同花顺真实数据拉取填上)
- 缺失: ths目录无该日文件 → API拉取写入
- 残缺: API条数 > ths条数×1.5 → API重写(如2025-09疯牛段)
- API失败: 跳过该日(回测中该日池空=温度0极弱不买)
- 字段映射: reason_type←industry | first_limit_up_time←first_seal转时间戳 | turnover_rate←K线turnover_pct | open_num←0(API无炸板次数)
用法: python backfill_ths_pool.py 20250601 20251201
"""
import os, sys, json, time
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
THS_DIR = os.path.join(BASE, 'data', 'zt_pool_history_ths')
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')


def main():
    start, end = sys.argv[1], sys.argv[2]
    # 交易日历: 000001 K线日期列
    with open(os.path.join(KLINE_DIR, '000001.json'), encoding='utf-8') as f:
        base = json.load(f)
    base = base.get('data', base) if isinstance(base, dict) else base
    trade_dates = [x['date'].replace('-', '') for x in base
                   if isinstance(x, dict) and x.get('date') and start <= x['date'].replace('-', '') <= end]
    print(f'交易日: {trade_dates[0]} ~ {trade_dates[-1]} ({len(trade_dates)}天)')
    import hithink_api as ha
    written = skipped = failed = 0
    for ymd in trade_dates:
        path = os.path.join(THS_DIR, f'{ymd}.json')
        n_ths = None
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                n_ths = len(json.load(f))
        try:
            pool = ha.fetch_limit_up_pool(f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}')
        except Exception as e:
            print(f'  ✗ {ymd} API失败: {e}')
            failed += 1
            continue
        if n_ths is not None and len(pool) <= n_ths * 1.5:
            skipped += 1
            continue
        rows = []
        for s in pool:
            code = str(s.get('code', ''))
            fs = str(s.get('first_seal') or '15:00')[:5]
            try:
                hh, mm = fs.split(':')
                ts = int(datetime(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:]), int(hh), int(mm)).timestamp())
            except Exception:
                ts = None
            to = 0
            kpath = os.path.join(KLINE_DIR, f'{code}.json')
            if os.path.exists(kpath):
                try:
                    with open(kpath, encoding='utf-8') as f:
                        kls = json.load(f)
                    kls = kls.get('data', kls) if isinstance(kls, dict) else kls
                    k = next((x for x in kls if isinstance(x, dict) and x.get('date') == f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}'), None)
                    if k:
                        to = k.get('turnover_pct', 0) or 0
                except Exception:
                    pass
            rows.append({'code': code, 'name': s.get('name', ''),
                         'reason_type': s.get('industry', ''),
                         'turnover_rate': to,
                         'first_limit_up_time': ts,
                         'open_num': 0, 'is_again_limit': 1,
                         'latest': s.get('price', 0)})
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(rows, f, ensure_ascii=False)
        print(f'  ✓ {ymd}: API {len(pool)}条' + (f' (原{ n_ths}条残缺)' if n_ths is not None else ' (缺失)') + ' → 已写入')
        written += 1
        time.sleep(0.3)
    print(f'完成: 写入{written}天 | 跳过(已完整){skipped}天 | API失败{failed}天')


if __name__ == '__main__':
    main()
