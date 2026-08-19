"""
数据体检 (2026-08-15) — 每日流水线后自动交叉校验, 当场报警
校验项:
  1. 涨停池文件 vs state 连板数一致性
  2. 候选评分覆盖率 (评分失败>3只 → 警告)
  3. 候选 vr20↔换手率交叉验证 (隐含日均换手在合理区间; vr20=0=量比清零回归)
  4. 池内抽样: 腾讯实时收盘价 vs 池文件价格
  5. 池内股票K线最新日期抽查
用法: python data_health_check.py [--date YYYY-MM-DD]   (默认今天, 返回警告数)
"""
import json, os, sys, urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
POOL_DIR = os.path.join(BASE, 'data', 'zt_pool')
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
LOG_DIR = os.path.join(BASE, 'logs')


def load_json(p, encodings=('utf-8', 'gbk')):
    for enc in encodings:
        try:
            with open(p, encoding=enc) as f:
                return json.load(f)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return None


def fetch_quote(code):
    mkt = 'sz' if code.startswith(('0', '3', '1')) else 'sh'
    url = f'http://qt.gtimg.cn/q={mkt}{code}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        f = urllib.request.urlopen(req, timeout=10).read().decode('gbk').split('~')
        return {'name': f[1], 'close': float(f[3]), 'prev_close': float(f[4])}
    except Exception:
        return None


def fetch_quotes_batch(codes):
    """腾讯批量行情 → {code: {close, prev_close}} (一次请求全池, 2026-08-19全量化)"""
    result = {}
    prefixed = []
    for c in codes:
        mkt = 'sz' if c.startswith(('0', '3', '1')) else 'sh'
        prefixed.append(f'{mkt}{c}')
    # 腾讯批量单次建议 ≤50只, 分批
    for i in range(0, len(prefixed), 50):
        batch = prefixed[i:i + 50]
        url = f'http://qt.gtimg.cn/q={",".join(batch)}'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            txt = urllib.request.urlopen(req, timeout=10).read().decode('gbk')
            for line in txt.strip().split(';'):
                if '=' not in line or '"' not in line:
                    continue
                key = line.split('=')[0].split('_')[-1]
                fields = line.split('"')[1].split('~')
                if len(fields) < 5:
                    continue
                code = key[2:]
                try:
                    result[code] = {'close': float(fields[3]), 'prev_close': float(fields[4])}
                except ValueError:
                    continue
        except Exception:
            continue
    return result


def _log_result(today, warnings):
    """体检结果落库 → logs/data_quality_log.json (追加, 保留最近90天, 失真可追溯)"""
    log_path = os.path.join(LOG_DIR, 'data_quality_log.json')
    records = []
    if os.path.exists(log_path):
        try:
            with open(log_path, encoding='utf-8') as f:
                records = json.load(f)
        except Exception:
            records = []
    records.append({
        'date': today,
        'checked_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'warnings': len(warnings),
        'details': warnings,
    })
    records = records[-90:]
    try:
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f'体检日志写入失败: {e}')


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    args = sys.argv[1:]
    if '--date' in args:
        i = args.index('--date')
        today = args[i + 1] if len(args) > i + 1 else datetime.now().strftime('%Y-%m-%d')
    else:
        today = datetime.now().strftime('%Y-%m-%d')
    today_c = today.replace('-', '')
    warnings = []

    print(f'🔍 数据体检 {today}')
    print('-' * 60)

    # ── 1. 池文件 vs state 连板数 ──
    pool_path = os.path.join(POOL_DIR, f'{today_c}.json')
    state_path = os.path.join(BASE, 'data', 'zt_pool_state.json')
    if os.path.exists(pool_path) and os.path.exists(state_path):
        pool = load_json(pool_path)
        state = load_json(state_path)
        pstocks = pool if isinstance(pool, list) else pool.get('stocks', pool.get('data', []))
        sstocks = state.get('stocks', []) if isinstance(state, dict) else []
        smap = {str(s.get('code', '')).replace('sh', '').replace('sz', ''): s for s in sstocks}
        mismatch = []
        for p in pstocks:
            code = str(p.get('code', '')).replace('sh', '').replace('sz', '')
            if code in smap:
                a = int(smap[code].get('limit_days', 1) or 1)
                b = int(p.get('limit_days', 1) or 1)
                if a != b:
                    mismatch.append(f'{p.get("name")}({code}) state{a}vs池{b}')
        if mismatch:
            warnings.append(f'连板数不一致{len(mismatch)}只: {"; ".join(mismatch[:5])}')
            print(f'  ⚠ {warnings[-1]}')
        else:
            print(f'  ✓ 连板数: state与池文件一致 ({len(pstocks)}只)')
    else:
        print(f'  - 池文件或state缺失, 跳过连板数校验')

    # ── 2. 评分覆盖率 ──
    cand_path = os.path.join(LOG_DIR, f'candidates_{today}.json')
    if os.path.exists(pool_path) and os.path.exists(cand_path):
        pool = load_json(pool_path)
        cand = load_json(cand_path)
        pstocks = pool if isinstance(pool, list) else pool.get('stocks', pool.get('data', []))
        n_pool = len(pstocks)
        n_cand = len(cand.get('candidates', [])) if isinstance(cand, dict) else 0
        n_fail = n_pool - n_cand
        if n_fail > 3:
            warnings.append(f'评分失败{n_fail}/{n_pool}只 (覆盖率{100 - n_fail / n_pool * 100:.0f}%)')
            print(f'  ⚠ {warnings[-1]}')
        else:
            print(f'  ✓ 评分覆盖率: {n_cand}/{n_pool} ({n_fail}只失败)')
    else:
        print(f'  - 候选文件缺失, 跳过覆盖率校验')

    # ── 3. vr20↔换手率交叉验证 ──
    if os.path.exists(cand_path):
        cand = load_json(cand_path)
        cands = cand.get('candidates', []) if isinstance(cand, dict) else []
        bad = []
        for c in cands:
            vr = c.get('vr20', 0) or 0
            to = c.get('turnover', 0) or 0
            if vr == 0:
                bad.append(f'{c.get("name")}(vr20=0)')
                continue
            implied = to / vr  # 隐含20日均换手%
            if implied < 0.03 or implied > 60:
                bad.append(f'{c.get("name")}(vr={vr}换手{to}%→隐含日均{implied:.1f}%)')
        if bad:
            warnings.append(f'vr↔换手矛盾{len(bad)}只: {"; ".join(bad[:5])}')
            print(f'  ⚠ {warnings[-1]}')
        else:
            print(f'  ✓ vr↔换手率: {len(cands)}只候选全部合理')
    else:
        print(f'  - 候选文件缺失, 跳过vr校验')

    # ── 4. 腾讯收盘价 vs 池文件价格 (全池批量, 2026-08-19从5只抽样改全量化) ──
    if os.path.exists(pool_path):
        pool = load_json(pool_path)
        pstocks = pool if isinstance(pool, list) else pool.get('stocks', pool.get('data', []))
        codes = [str(p.get('code', '')).replace('sh', '').replace('sz', '') for p in pstocks]
        quotes = fetch_quotes_batch(codes)
        bad_price = []
        checked = 0
        for p in pstocks:
            code = str(p.get('code', '')).replace('sh', '').replace('sz', '')
            q = quotes.get(code)
            if q is None:
                continue
            checked += 1
            pool_price = float(p.get('price', 0) or 0)
            if pool_price > 0 and q['close'] > 0 and abs(q['close'] - pool_price) / pool_price > 0.02:
                bad_price.append(f'{p.get("name")}(池{pool_price}vs腾讯{q["close"]})')
        if bad_price:
            warnings.append(f'收盘价偏差: {"; ".join(bad_price)}')
            print(f'  ⚠ {warnings[-1]}')
        else:
            print(f'  ✓ 收盘价全池校验: {checked}/{len(pstocks)}只 池文件与腾讯一致')
    else:
        print(f'  - 池文件缺失, 跳过价格校验')

    # ── 5. K线最新日期检查 (全池, 2026-08-19从5只抽样改全量化) ──
    if os.path.exists(pool_path):
        pool = load_json(pool_path)
        pstocks = pool if isinstance(pool, list) else pool.get('stocks', pool.get('data', []))
        stale = []
        for p in pstocks:
            code = str(p.get('code', '')).replace('sh', '').replace('sz', '')
            kp = os.path.join(KLINE_DIR, f'{code}.json')
            if not os.path.exists(kp):
                stale.append(f'{p.get("name")}(无K线文件)')
                continue
            k = load_json(kp)
            if not k:
                stale.append(f'{p.get("name")}(K线为空)')
                continue
            rows = k.get('data', k) if isinstance(k, dict) else k
            if rows and rows[-1].get('date', '') < today:
                stale.append(f'{p.get("name")}(K线停在{rows[-1].get("date")})')
        if stale:
            warnings.append(f'K线滞后: {"; ".join(stale[:8])}')
            print(f'  ⚠ {warnings[-1]}')
        else:
            print(f'  ✓ K线日期全池检查: {len(pstocks)}只均为最新')
    else:
        print(f'  - 池文件缺失, 跳过K线校验')

    # ── 6. 竞价快照质量 ──
    auction_path = os.path.join(BASE, 'data', 'auction', f'{today}.json')
    if os.path.exists(auction_path):
        au = load_json(auction_path)
        astocks = au.get('stocks', []) if isinstance(au, dict) else au
        if astocks:
            zero_open = sum(1 for s in astocks if (s.get('open', 0) or 0) == 0)
            ratio = zero_open / len(astocks)
            if ratio > 0.3:
                warnings.append(f'竞价快照open=0占比{ratio*100:.0f}% (疑似采集过早)')
                print(f'  ⚠ {warnings[-1]}')
            else:
                print(f'  ✓ 竞价快照: {len(astocks)}只, open=0占{ratio*100:.0f}%')
    else:
        print(f'  - 竞价快照缺失, 跳过竞价质量校验')

    # ── 7. 炸板次数异常校验 (东财zbc派生字段对烂板股失真, >5次告警) ──
    if os.path.exists(state_path):
        state = load_json(state_path)
        sstocks = state.get('stocks', []) if isinstance(state, dict) else []
        odd = []
        for s in sstocks:
            bt = int(s.get('break_times', 0) or 0)
            if bt > 5:
                odd.append(f'{s.get("name")}(炸{bt}次)')
        if odd:
            warnings.append(f'炸板次数异常{len(odd)}只(>5次, 疑似东财失真): {"; ".join(odd[:5])}')
            print(f'  ⚠ {warnings[-1]}')
        else:
            print(f'  ✓ 炸板次数: {len(sstocks)}只均在合理范围')
    else:
        print(f'  - 池文件缺失, 跳过炸板校验')

    # ── 落库 ──
    _log_result(today, warnings)

    # ── 体检→候选联动 (2026-08-19): 警告写入候选文件, 竞价面板显示 ──
    try:
        cand_path2 = os.path.join(LOG_DIR, f'candidates_{today}.json')
        if os.path.exists(cand_path2) and warnings:
            cand = load_json(cand_path2)
            if isinstance(cand, dict):
                cand['data_quality'] = {
                    'warnings': warnings,
                    'checked_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                }
                with open(cand_path2, 'w', encoding='utf-8') as f:
                    json.dump(cand, f, ensure_ascii=False, indent=1)
                print(f'  → 已将 {len(warnings)} 项警告写入候选文件 data_quality 字段')
    except Exception as e:
        print(f'  [警告] 体检→候选联动失败: {e}')

    print('-' * 60)
    if warnings:
        print(f'❌ 体检发现 {len(warnings)} 项警告')
    else:
        print(f'✅ 数据体检全绿')
    return len(warnings)


if __name__ == '__main__':
    sys.exit(1 if main() else 0)
