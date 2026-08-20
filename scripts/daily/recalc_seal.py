"""
封板质量重算 (2026-08-18)
==========================
东财涨停池的 zbc(炸板次数)/fbt(首次封板)/lbt(最后封板) 是派生字段,
对「反复炸板的烂板股」会失真(触板当炸板、尾盘回封当首次封板)。
本模块用腾讯 1分钟K线 重算这三个字段, 覆盖东财值, 保障评分数据准确。

用法(盘后, 收盘后分钟数据齐全):
  python recalc_seal.py [--date YYYY-MM-DD] [--dry-run]

核心算法(分钟级近似):
  - 封住: bar.close >= 涨停价 - 0.005
  - 首次封板: 第一根 close 封住的分钟
  - 最后封板: 最后一根 close 封住的分钟
  - 炸板次数: 「封住 → 打开」的状态转换次数
  (分钟级固有局限: 一根bar内打开又封回捕捉不到, 但远准于东财派生字段)
"""
import json, os, sys, time, urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ZT_STATE_PATH = os.path.join(BASE, 'data', 'zt_pool_state.json')
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _prefix(code):
    return 'sh' if code.startswith(('5', '6', '9')) else 'sz'


def fetch_minute(code, count=241):
    """腾讯 mkline → 当日1分钟K线 [{t,o,h,l,c,v}], t 为 HHMM"""
    pre = _prefix(code)
    url = (f'https://ifzq.gtimg.cn/appstock/app/kline/mkline'
           f'?param={pre}{code},m1,,{count}&_var=result')
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Referer': 'https://gu.qq.com/'})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        raw = resp.read().decode('gbk')
        if '=' not in raw:
            return []
        d = json.loads(raw.split('=', 1)[1].strip())
        bars = d.get('data', {}).get(f'{pre}{code}', {}).get('m1', [])
        out = []
        for b in bars:
            # b: [时间戳, open, close, high, low, volume, ...]
            t = str(b[0])
            out.append({
                't': t[-4:] if len(t) >= 4 else t,  # HHMM
                'o': round(float(b[1]), 2),
                'c': round(float(b[2]), 2),
                'h': round(float(b[3]), 2),
                'l': round(float(b[4]), 2),
                'v': int(float(b[5])),
            })
        return out
    except Exception:
        return []


def calc_seal_from_minutes(bars, limit_price):
    """
    分钟bar → {first_seal, last_seal, break_times}
    bars: [{t,o,h,l,c,v}], limit_price: 涨停价
    """
    if not bars or limit_price <= 0:
        return None

    first_seal = None
    last_seal = None
    break_times = 0
    sealed = False

    for b in bars:
        is_sealed = b['c'] >= limit_price - 0.005
        if is_sealed and not sealed:
            # 打开 → 封住: 记录封板
            if first_seal is None:
                first_seal = b['t']
            last_seal = b['t']
            sealed = True
        elif not is_sealed and sealed:
            # 封住 → 打开: 炸板一次
            break_times += 1
            sealed = False

    if first_seal is None:
        return None  # 从未封住(数据异常)

    return {
        'first_seal': first_seal,
        'last_seal': last_seal or first_seal,
        'break_times': break_times,
    }


def _fmt_hhmm(t):
    """HHMM → HH:MM:SS"""
    t = str(t).zfill(4)
    return f'{t[:2]}:{t[2:]}:00'


def _hhmm_to_min(t):
    """HHMM → 分钟数 (用于时间差对比, 避免跨小时直接相减出错)"""
    t = str(t).zfill(4)
    return int(t[:2]) * 60 + int(t[2:])


def recalc_pool(stocks, date_str, verbose=True):
    """
    对涨停池所有股票重算封板质量, 返回 {code: {first_seal, last_seal, break_times}}
    stocks: 涨停池 list (需含 code, close, prev_close, first_seal, break_times 等)
    """
    results = {}
    for s in stocks:
        code = s.get('code', '')
        close = s.get('close', 0)  # 涨停股收盘价 == 涨停价
        if not code or close <= 0:
            continue
        bars = fetch_minute(code)
        if not bars:
            if verbose:
                print(f'  [跳过] {s.get("name", "")}({code}) 无分钟数据')
            continue
        calc = calc_seal_from_minutes(bars, close)
        if not calc:
            continue
        results[code] = calc

        # 对比东财原值, 偏差大告警
        em_breaks = int(s.get('break_times', 0) or 0)
        em_first = str(s.get('first_seal', '')).replace(':', '')
        new_breaks = calc['break_times']
        new_first = calc['first_seal']
        warn = ''
        if abs(em_breaks - new_breaks) > 2:
            warn = f'  ⚠ 源炸{em_breaks}次 vs 分钟算炸{new_breaks}次'
        elif em_first and new_first and abs(_hhmm_to_min(em_first[:4]) - _hhmm_to_min(new_first)) > 30:
            warn = f'  ⚠ 源封{em_first} vs 分钟算封{new_first}'
        if verbose:
            print(f'  {s.get("name", "")}({code}) 封{_fmt_hhmm(new_first)} '
                  f'炸{new_breaks}次 末封{_fmt_hhmm(calc["last_seal"])}{warn}')
        time.sleep(0.12)
    return results


def apply_to_state(results, dry_run=False):
    """把重算结果写回 zt_pool_state.json, 覆盖 first_seal/last_seal/break_times"""
    if not os.path.exists(ZT_STATE_PATH):
        print('[recalc] state 文件不存在, 跳过写入')
        return 0
    with open(ZT_STATE_PATH, encoding='utf-8') as f:
        state = json.load(f)

    updated = 0
    for s in state.get('stocks', []):
        code = s.get('code', '')
        if code in results:
            calc = results[code]
            s['first_seal'] = _fmt_hhmm(calc['first_seal'])
            s['last_seal'] = _fmt_hhmm(calc['last_seal'])
            s['break_times'] = calc['break_times']
            s['seal_recalced'] = True
            updated += 1

    if not dry_run and updated:
        with open(ZT_STATE_PATH, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    print(f'[recalc] 重算覆盖 {updated} 只 ({"dry-run未写入" if dry_run else "已写入 state"})')
    return updated


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    args = sys.argv[1:]
    dry_run = '--dry-run' in args
    date_str = datetime.now().strftime('%Y-%m-%d')
    if '--date' in args:
        i = args.index('--date')
        date_str = args[i + 1] if len(args) > i + 1 else date_str

    if not os.path.exists(ZT_STATE_PATH):
        print('[recalc] 无涨停池 state, 退出')
        return

    with open(ZT_STATE_PATH, encoding='utf-8') as f:
        state = json.load(f)
    stocks = state.get('stocks', [])
    print(f'[recalc] 重算封板质量 → {date_str} | 涨停池 {len(stocks)} 只')

    results = recalc_pool(stocks, date_str, verbose=True)
    apply_to_state(results, dry_run=dry_run)


if __name__ == '__main__':
    main()
