"""竞价观察面板 v4.0 — 次日9:25使用
集成A的卖点引擎: 量能三态 + 封板质量 + 弱转强
"""
import json, os, sys
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(BASE, 'logs')


def load_latest_candidates():
    files = [f for f in os.listdir(LOG_DIR)
             if f.startswith('candidates_') and not f.startswith('candidates_v')]
    if not files: return None
    # 按文件名中日期排序(格式: candidates_YYYY-MM-DD.json)
    files.sort(key=lambda f: f.split('_')[1].replace('.json',''))
    with open(os.path.join(LOG_DIR, files[-1]), 'r', encoding='utf-8') as f:
        return json.load(f)


def load_portfolio():
    pf = os.path.join(LOG_DIR, 'portfolio.json')
    if os.path.exists(pf):
        with open(pf, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def fetch_live_quote(code):
    """获取实时行情 (腾讯API)"""
    import urllib.request
    try:
        mkt = 'sz' if code.startswith(('0', '3', '1')) else 'sh'
        url = f'http://qt.gtimg.cn/q={mkt}{code}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode('gbk')
        fields = data.split('~')
        return {
            'name': fields[1],
            'open': float(fields[5]),
            'prev_close': float(fields[4]),
            'current': float(fields[3]),
            'high': float(fields[33]),
            'low': float(fields[34]),
            'change_pct': float(fields[32]),
            'limit_up': float(fields[47]) if len(fields) > 47 else 0,
        }
    except Exception as e:
        print(f'  [WARN] 无法获取{code}实时行情: {e}')
        return None


def fetch_sina_quote(code):
    """获取实时行情 (新浪第二源, 用于持仓双源交叉验证)"""
    import urllib.request
    try:
        mkt = 'sz' if code.startswith(('0', '3', '1')) else 'sh'
        url = f'https://hq.sinajs.cn/list={mkt}{code}'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0',
            'Referer': 'https://finance.sina.com.cn/'})
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode('gbk')
        fields = data.split('"')[1].split(',')
        return {
            'open': float(fields[1]),
            'prev_close': float(fields[2]),
            'current': float(fields[3]),
        }
    except Exception:
        return None


def cross_check_quote(code, tencent_quote):
    """持仓双源校验 (腾讯 vs 新浪): open/prev_close 偏差>0.5% → 告警列表
    返回 [(字段, 腾讯值, 新浪值, 偏差%), ...] 空列表=两源一致"""
    sina = fetch_sina_quote(code)
    if not sina:
        return None   # 新浪源不可用(不告警, 但标记)
    issues = []
    for field in ('open', 'prev_close'):
        tv = tencent_quote.get(field)
        sv = sina.get(field)
        if not tv or not sv:
            continue
        diff = abs(tv - sv) / tv * 100
        if diff > 0.5:
            issues.append((field, tv, sv, round(diff, 2)))
    return issues


def compute_position_decision(pos):
    """静默计算单只持仓的卖点决策 (2026-08-20: 供决策摘要先行打印)
    返回 {quote, gap_pct, signal, exec_info, issues, kline_stale} 或 None(行情失败)"""
    name = pos['name']; code = pos['code']
    quote = fetch_live_quote(code)
    if not quote:
        return None
    gap_pct = round((quote['open'] - quote['prev_close']) / quote['prev_close'] * 100, 2)
    issues = cross_check_quote(code, quote)
    # K线新鲜度
    kline_stale = False
    try:
        _kp = os.path.join(BASE, 'data', 'kline_data', f'{code}.json')
        if os.path.exists(_kp):
            with open(_kp, 'r', encoding='utf-8') as _f:
                _raw = json.load(_f)
            _kl = _raw.get('data', _raw) if isinstance(_raw, dict) else _raw
            _last = _kl[-1]['date'] if _kl else '?'
            if _last < (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'):
                kline_stale = True
    except Exception:
        pass
    try:
        from sell_engine import sell_signal, sell_execution_price
        signal = sell_signal(pos, {
            'open': quote['open'],
            'prev_close': quote['prev_close'],
            'gap_pct': gap_pct,
            'current_price': quote['current']
        })
        exec_info = sell_execution_price(signal, {
            'open': quote['open'],
            'high': quote['high'],
            'close': quote['current'],
            'prev_close': quote['prev_close'],
            'limit_up_price': quote['limit_up']
        }, pos)
    except Exception:
        return {'quote': quote, 'gap_pct': gap_pct, 'issues': issues,
                'kline_stale': kline_stale, 'signal': None, 'exec_info': None}
    return {'quote': quote, 'gap_pct': gap_pct, 'issues': issues,
            'kline_stale': kline_stale, 'signal': signal, 'exec_info': exec_info}


def compute_environment(pf):
    """静默计算市场环境评级+买入开关 (2026-08-20: 供决策摘要先行打印)
    分档: <60或最高≤2板=弱市(空仓,升温例外1/3) | 60-109=正常(半仓) | ≥110=强势(全仓)
    返回 {env, switch, pos_pct, warming, zt_n, max_cons, zt_prev, avg_gap, downgraded}"""
    r = {'env': None, 'switch': None, 'pos_pct': 0, 'warming': False,
         'zt_n': 0, 'max_cons': 1, 'zt_prev': None, 'avg_gap': None, 'downgraded': False}
    try:
        _pp = _load_prev_pool()
        if not _pp:
            return r
        _stocks, _ = _pp
        r['zt_n'] = len(_stocks)
        r['max_cons'] = max((int(x.get('limit_days', 1) or 1) for x in _stocks), default=1)
        # 前日涨停数(升温判断)
        try:
            _zt_dir = os.path.join(BASE, 'data', 'zt_pool')
            _pool_files = sorted(f for f in os.listdir(_zt_dir) if f.endswith('.json'))
            if len(_pool_files) >= 2:
                _p2 = os.path.join(_zt_dir, _pool_files[-2])
                try:
                    with open(_p2, encoding='utf-8') as _f:
                        _pp2 = json.load(_f)
                except UnicodeDecodeError:
                    with open(_p2, encoding='gbk') as _f:
                        _pp2 = json.load(_f)
                _p2stocks = _pp2 if isinstance(_pp2, list) else _pp2.get('stocks', _pp2.get('data', []))
                r['zt_prev'] = len(_p2stocks)
        except Exception:
            pass
        r['warming'] = r['zt_prev'] is not None and r['zt_n'] > r['zt_prev']

        # 温度分档(2026-08-25用户定稿): 极弱<40空仓(升温例外半仓) | 弱市40-109半仓 | 强市≥110全仓
        if r['zt_n'] < 40 or r['max_cons'] <= 2:
            r['env'] = '🌡️ 极弱'
            if r['warming']:
                r['switch'], r['pos_pct'] = '🟡 买入开关: 半仓(升温日例外)', 0.5
            else:
                r['switch'], r['pos_pct'] = '🛑 买入开关: 关闭(空仓)', 0.0
        elif r['zt_n'] >= 110:
            r['env'], r['switch'], r['pos_pct'] = '🌡️ 强势', '🟢 买入开关: 全仓', 1.0
        else:
            r['env'], r['switch'], r['pos_pct'] = '🌡️ 弱市', '🟢 买入开关: 半仓', 0.5

        # 竞价二次确认: 池均gap ≤ -0.5% → 降一档 (3年724日校准)
        try:
            _astate_path = os.path.join(BASE, 'data', 'auction_state.json')
            if os.path.exists(_astate_path):
                with open(_astate_path, encoding='utf-8') as _f:
                    _astate = json.load(_f)
                r['avg_gap'] = (_astate.get('current') or {}).get('avg_gap')
                if r['avg_gap'] is not None and r['avg_gap'] <= -0.5:
                    _downgrade = {'🌡️ 极弱': ('🌡️ 极弱', '🛑 买入开关: 关闭(空仓)', 0.0),
                                  '🌡️ 弱市': ('🌡️ 极弱↓', '🛑 买入开关: 关闭(空仓, 竞价二次确认降档)', 0.0),
                                  '🌡️ 强势': ('🌡️ 弱市↓', '🟢 买入开关: 半仓(竞价二次确认降档)', 0.5)}
                    if r['env'] in _downgrade:
                        r['env'], r['switch'], r['pos_pct'] = _downgrade[r['env']]
                        r['downgraded'] = True
        except Exception:
            pass
        # 盘后赚钱效应校准 (2026-08-25, 斯皮尔曼+0.403最强指标): 昨日<-2% → 降一档
        try:
            _ms_path = os.path.join(BASE, 'data', 'market_state.json')
            if os.path.exists(_ms_path):
                with open(_ms_path, encoding='utf-8') as _f:
                    _ms = json.load(_f)
                r['money_effect'] = _ms.get('money_effect')
                if r['money_effect'] is not None and r['money_effect'] < -2.0 and not r['downgraded']:
                    _downgrade_me = {'🌡️ 极弱': ('🌡️ 极弱', '🛑 买入开关: 关闭(空仓)', 0.0),
                                     '🌡️ 弱市': ('🌡️ 极弱↓', '🛑 买入开关: 关闭(空仓, 赚钱效应-2%校准)', 0.0),
                                     '🌡️ 强势': ('🌡️ 弱市↓', '🟢 买入开关: 半仓(赚钱效应-2%校准)', 0.5)}
                    if r['env'] in _downgrade_me:
                        r['env'], r['switch'], r['pos_pct'] = _downgrade_me[r['env']]
                        r['downgraded'] = True
        except Exception:
            pass
    except Exception:
        pass
    return r


def find_divergence_candidates():
    """🐉分歧弱转强候选 (2026-08-13新增, 半自动提示)
    T-1爆量+烂板涨停(大分歧日, 板块>=2只) → T日竞价高开 → 弱转强观察名单
    只提示不自动交易 (来源: 干货_怎么选.doc)"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    zt_dir = os.path.join(BASE, 'data', 'zt_pool')
    prev_files = sorted(f for f in os.listdir(zt_dir)
                        if f.endswith('.json') and f[:-5] < today_str.replace('-', ''))
    if not prev_files:
        return None
    prev_date = prev_files[-1][:-5]
    prev_date_fmt = f'{prev_date[:4]}-{prev_date[4:6]}-{prev_date[6:8]}'

    try:
        with open(os.path.join(zt_dir, prev_files[-1]), encoding='utf-8') as f:
            pool = json.load(f)
    except UnicodeDecodeError:
        with open(os.path.join(zt_dir, prev_files[-1]), encoding='gbk') as f:
            pool = json.load(f)
    stocks = pool if isinstance(pool, list) else pool.get('stocks', pool.get('data', []))

    from scoring import sector_resonance_count
    sector_cnt = [str(s.get('industry', '')) for s in stocks]

    auc = {}
    af = os.path.join(BASE, 'data', 'auction', f'{today_str}.json')
    if os.path.exists(af):
        with open(af, encoding='utf-8') as f:
            ad = json.load(f)
        alist = ad if isinstance(ad, list) else ad.get('stocks', ad.get('data', []))
        for a in alist:
            if isinstance(a, dict):
                auc[str(a.get('code', ''))] = a

    from scoring import classify_volume as cv
    cands = []
    for s in stocks:
        code = str(s.get('code', '')).replace('sh', '').replace('sz', '')
        if not code or code.startswith(('300', '301', '688', '8', '9')):
            continue
        # 烂板: 炸板>=1 或 封板>60min
        zhaban = int(s.get('break_times', 0) or 0)
        seal = str(s.get('first_seal', ''))
        seal_mins = None
        if seal and seal != '?':
            try:
                st = seal.replace(':', '')
                seal_mins = max(0, (int(st[:2]) - 9) * 60 + int(st[2:4]) - 30)
            except Exception:
                pass
        if zhaban == 0 and (seal_mins is None or seal_mins <= 60):
            continue
        # 爆量: heavy 且 vol >= 1.5x前日
        kp = os.path.join(BASE, 'data', 'kline_data', f'{code}.json')
        if not os.path.exists(kp):
            continue
        try:
            with open(kp, encoding='utf-8') as f:
                raw = json.load(f)
        except UnicodeDecodeError:
            with open(kp, encoding='gbk') as f:
                raw = json.load(f)
        kl = raw.get('data', raw) if isinstance(raw, dict) else raw
        idx = next((i for i, x in enumerate(kl) if str(x.get('date')) == prev_date_fmt), None)
        if idx is None or idx < 1:
            continue
        vol = kl[idx].get('volume', 0)
        prev_v = kl[idx - 1].get('volume', 0)
        if not (cv(vol, kl, idx) == 'heavy' and prev_v > 0 and vol >= prev_v * 1.5):
            continue
        # 今日竞价 (低开也收录→REJECT, 高开→WATCH)
        a = auc.get(code)
        if not a or a.get('gap_pct') is None:
            continue
        gap = a['gap_pct']
        cands.append({
            'code': code, 'name': s.get('name', '?'), 'gap': gap,
            'zhaban': zhaban, 'cons': s.get('limit_days', s.get('cons', '?')),
            'industry': s.get('industry', ''),
            'sector': sector_resonance_count(s.get('industry', ''), sector_cnt),
            'grade': 'WATCH' if gap > 0 else 'REJECT',
        })
    return cands


_prev_pool_cache = None


def _load_prev_pool():
    """上一交易日涨停池文件 → (stocks, sector_cnt), 带缓存"""
    global _prev_pool_cache
    if _prev_pool_cache is not None:
        return _prev_pool_cache
    zt_dir = os.path.join(BASE, 'data', 'zt_pool')
    today_yyyymmdd = datetime.now().strftime('%Y%m%d')
    files = sorted(f for f in os.listdir(zt_dir) if f.endswith('.json') and f[:-5] < today_yyyymmdd)
    if not files:
        _prev_pool_cache = None
        return None
    try:
        with open(os.path.join(zt_dir, files[-1]), encoding='utf-8') as f:
            pool = json.load(f)
    except UnicodeDecodeError:
        with open(os.path.join(zt_dir, files[-1]), encoding='gbk') as f:
            pool = json.load(f)
    stocks = pool if isinstance(pool, list) else pool.get('stocks', pool.get('data', []))
    # 板块共振计数改拆词交集 (2026-08-21, 同花顺个股化原因串适配)
    sector_cnt = [str(x.get('industry', '')) for x in stocks]
    _prev_pool_cache = (stocks, sector_cnt)
    return _prev_pool_cache


_meta_cache = {}


def _sector_bucket_of(industry, stocks):
    """V4题材热度分档: 该股题材词中池内出现次数最多的词的热度"""
    from collections import Counter as _C
    freq = _C()
    for s in stocks:
        for w in str(s.get('industry', '')).replace('，', '+').split('+'):
            if w.strip():
                freq[w.strip()] += 1
    ws = [w for w in str(industry or '').replace('，', '+').split('+') if w.strip()]
    heat = max(freq[w] for w in ws) if ws else 0
    return '<3' if heat < 3 else ('3-4' if heat < 5 else ('5-9' if heat < 10 else '>=10'))


def stock_scoring_meta(code):
    """按评分表现场打分 + T-1池明细 → {score, industry, sector, cons, klines, detail}
    (解决流水线评分盲区: 无分股票现场补打分)"""
    if code in _meta_cache:
        return _meta_cache[code]
    meta = {'score': None, 'industry': '', 'sector': 1, 'cons': '?', 'klines': None, 'detail': {}}
    try:
        kp = os.path.join(BASE, 'data', 'kline_data', f'{code}.json')
        if os.path.exists(kp):
            with open(kp, encoding='utf-8') as f:
                raw = json.load(f)
            meta['klines'] = raw.get('data', raw) if isinstance(raw, dict) else raw
        pp = _load_prev_pool()
        if pp:
            stocks, sector_cnt = pp
            p = next((x for x in stocks if str(x.get('code', '')).replace('sh', '').replace('sz', '') == code), None)
            if p:
                meta['industry'] = p.get('industry', '')
                from scoring import sector_resonance_count
                meta['sector'] = sector_resonance_count(p.get('industry', ''), sector_cnt)
                meta['cons'] = p.get('limit_days', '?')
                meta['detail'] = {
                    'seal_time': str(p.get('first_seal', '')).replace(':', ''),
                    'final_seal_time': str(p.get('last_seal', '')).replace(':', ''),
                    'zhaban': int(p.get('break_times', 0) or 0),
                    'sector_count': meta['sector'],
                    # V4题材热度分档(池级词频)
                    'sector_bucket': _sector_bucket_of(p.get('industry', ''), stocks),
                }
        if meta['klines'] and meta['detail']:
            from scoring import score_v4
            sc, _ = score_v4(code, meta['klines'], meta['detail'])
            meta['score'] = sc
    except Exception:
        pass
    _meta_cache[code] = meta
    return meta


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    data = load_latest_candidates()
    pf = load_portfolio()

    print('=' * 65)
    print('  竞价观察结果')
    print(f'  日期: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print('=' * 65)

    # ── 竞价池采集 (第1步: 摘要依赖快照) ──
    try:
        from auction_pool import capture_auction
        capture_auction()
    except Exception as e:
        print(f'\n[WARN] 竞价池采集失败: {e}')

    # ── 静默计算: 持仓决策 + 环境评级 (2026-08-20, 结论先行重构) ──
    if pf:
        pos_list = pf.get('positions', [])
        if not pos_list:
            pos_single = pf.get('position')
            if pos_single:
                pos_list = [pos_single]
    else:
        pos_list = []
    pos_results = [(pos, compute_position_decision(pos)) for pos in pos_list]
    env_info = compute_environment(pf)

    # ── 📌 今日决策摘要 (结论先行) ──
    print(f'\n  ╔══ 📌 今日决策摘要 ═══════════════════════════╗')
    if pos_results:
        for pos, r in pos_results:
            if r is None or r.get('signal') is None:
                print(f'  ║  {pos["name"]}: 行情/引擎失败, 需手动判断')
                continue
            sig = r['signal']
            act = sig['action']
            if act in ('sell', 'sell_half'):
                note = r['exec_info']['note'] if r['exec_info'] else sig['reason']
                mark = '🔴' if sig['urgency'] in ('urgent', 'now') else '🟡'
                print(f'  ║  {mark} 卖出 {pos["name"]}({pos["code"]}) — {note}')
            elif act == 'watch':
                print(f'  ║  🟡 观察 {pos["name"]}({pos["code"]}) — {sig["reason"]}')
            else:
                print(f'  ║  ⚪ 持有 {pos["name"]}({pos["code"]}) — {sig["reason"]}')
    else:
        print(f'  ║  空仓')
    if env_info.get('env'):
        print(f'  ║  {env_info["switch"]}')
    print(f'  ╚══════════════════════════════════════════════╝')

    # ── 盘后体检警告 (解释层, 2026-08-19 体检→候选联动) ──
    if data and data.get('data_quality'):
        dq = data['data_quality']
        print(f'\n  ⚠⚠ 盘后数据体检发现 {len(dq.get("warnings", []))} 项警告 ⚠⚠')
        for w in dq.get('warnings', [])[:8]:
            print(f'    - {w}')
        print(f'  (体检时间: {dq.get("checked_at", "?")}) 买入决策前请先排除数据问题')

    # ── 持仓 + 卖点判断 (详情解释, 用缓存结果) ──
    if pf:
        pos_advice = []
        for pos, r in pos_results:
            name = pos['name']; code = pos['code']
            cost = pos['buy_price']; shares = pos['shares']
            buy_date = pos.get('buy_date', '?')

            print(f'\n  ╔══ 当前持仓 ═══════════════════════════════╗')
            print(f'  ║  {name}({code})  成本:{cost:.2f}  股数:{shares}股')
            print(f'  ║  买入日: {buy_date}')

            if r is not None:
                quote = r['quote']
                gap_pct = r['gap_pct']

                # ── 双源交叉验证 (腾讯vs新浪, 偏差>0.5%标红) ──
                issues = r['issues']
                if issues is None:
                    print(f'  ║  ⚠ 新浪校验源不可用, 仅腾讯单源')
                elif issues:
                    for field, tv, sv, diff in issues:
                        print(f'  ║  🔴 数据存疑[{field}]: 腾讯{tv} vs 新浪{sv} 偏差{diff}%')
                else:
                    print(f'  ║  ✓ 双源校验: 腾讯/新浪 open·昨收 一致')

                if r['kline_stale']:
                    print(f'  ║  ⚠ K线滞后, 昨涨停/断板判断可能失真')

                if r['signal'] is not None:
                    signal = r['signal']
                    exec_info = r['exec_info']
                    urgency_mark = {'urgent': '🔴', 'normal': '🟡', 'now': '🔴'}.get(signal['urgency'], '⚪')

                    pos_advice.append({
                        'name': name, 'code': code, 'cost': cost, 'shares': shares,
                        'gap': gap_pct, 'current': quote['current'],
                        'pnl_pct': round((quote['current'] - cost) / cost * 100, 2),
                        'reason': signal['reason'],
                        'exec_note': exec_info['note'] if signal['action'] in ('sell', 'sell_half') else '',
                    })

                    print(f'  ║')
                    print(f'  ║  今开: {quote["open"]:.2f} | 昨收: {quote["prev_close"]:.2f} | Gap: {gap_pct:+.2f}%')
                    print(f'  ║  现价: {quote["current"]:.2f} ({quote["change_pct"]:+.2f}%)')
                    print(f'  ║')
                    print(f'  ║  {urgency_mark} 卖点判断: {signal["reason"]}')
                    if signal['detail']:
                        print(f'  ║     └ {signal["detail"]}')
                    if signal['action'] in ('sell', 'sell_half'):
                        print(f'  ║  执行: {exec_info["note"]}')
                else:
                    print(f'  ║  [ERR] 卖点引擎调用失败, 详见日志')
            else:
                print(f'  ║  [WARN] 无法获取实时行情，跳过卖点判断')

            # ── 历史参考价 ──
            kline_path = os.path.join(BASE, 'data', 'kline_data', f'{name}_{code}.json')
            alt_path = os.path.join(BASE, 'data', 'kline_data', f'{code}.json')
            for kp in [kline_path, alt_path]:
                if os.path.exists(kp):
                    with open(kp, 'r', encoding='utf-8') as fh:
                        raw = json.load(fh)
                    klines = raw.get('data', raw) if isinstance(raw, dict) else raw
                    if len(klines) >= 2:
                        last = klines[-1]; prev = klines[-2]
                        ho2_prev = round((prev['high'] + prev['open']) / 2, 2)
                        ho2_last = round((last['high'] + last['open']) / 2, 2) if last['high'] > 0 else 0
                        print(f'  ║')
                        print(f'  ║  {prev["date"]} (H+O)/2=({prev["high"]}+{prev["open"]})/2={ho2_prev}')
                        print(f'  ║  {last["date"]} (H+O)/2=({last["high"]}+{last["open"]})/2={ho2_last}')
                    # 连板+高危检查
                    if len(klines) >= 3:
                        cons = 0; j = len(klines) - 2
                        while j >= 1:
                            if klines[j].get('pct_change', 0) >= 9.9 or \
                               (j > 0 and klines[j]['close'] >= round(klines[j-1]['close']*1.10, 2) - 0.005):
                                cons += 1; j -= 1
                            else: break
                        board_num = cons + 1
                        last_k = klines[-1]
                        is_ol = (last_k['high']>0 and last_k['low']>0 and
                                 (abs(last_k['high']-last_k['low'])<0.001 or
                                  (last_k['high']>last_k['low'] and abs(last_k['close']-last_k['high'])<0.001)))
                        if board_num >= 4 and is_ol:
                            print(f'  ║  ⚠ 高危: {board_num}板一字/T字板, 回撤风险极高')
                    break

            print(f'  ╚══════════════════════════════════════════╝')
        if not pos_list:
            print(f'\n  --- 空仓 ---')

        # ── 📊 表3: 持仓交易建议 ──
        if pos_advice:
            print(f'\n{"=" * 65}')
            print(f'  📊 表3: 持仓交易建议')
            print(f'{"=" * 65}')
            for p in pos_advice:
                print(f'  {p["name"]}({p["code"]}) 成本{p["cost"]:.2f} 现价{p["current"]:.2f}({p["pnl_pct"]:+.1f}%) '
                      f'竞价gap{p["gap"]:+.1f}%')
                print(f'    建议: {p["reason"]}')
                if p['exec_note']:
                    print(f'    执行: {p["exec_note"]}')

    # ── 加载今日竞价数据 ──
    today_auction_file = os.path.join(BASE, 'data', 'auction',
                                       f'{datetime.now().strftime("%Y-%m-%d")}.json')
    auction_stocks = []
    if os.path.exists(today_auction_file):
        with open(today_auction_file, 'r', encoding='utf-8') as f:
            auc_data = json.load(f)
        auction_stocks = auc_data.get('stocks', [])

    # ── 构建候选评分查找表 ──
    candidate_scores = {}
    if data:
        for c in data.get('candidates', []):
            candidate_scores[c['code']] = c

    # ── 今日竞价池买入候选（现场打分, 解决流水线评分盲区） ──
    buyable = []
    for s in auction_stocks:
        code = s.get('code', '')
        gap = s.get('gap_pct', 0)
        is_one_line = s.get('one_line', False)
        is_300 = code.startswith(('300', '301', '688', '8', '9'))

        if is_300 or is_one_line or s.get('high_risk', False):
            continue
        if 4.0 <= gap <= 8.0:
            cand = candidate_scores.get(code, {})
            meta = stock_scoring_meta(code)
            auction_score = s.get('score', 0)
            cand_score = cand.get('score', 0)
            # 现场评分优先(与表2细则同源), 失败则退回快照分/候选分
            final_score = meta['score'] if meta['score'] is not None else \
                (auction_score if auction_score > 0 else cand_score)
            buyable.append({
                'code': code, 'name': s.get('name', ''),
                'gap': gap, 'score': final_score,
                'limit_days': meta['cons'] if meta['cons'] != '?' else s.get('limit_days', cand.get('cons', 1)),
                'industry': meta['industry'] or cand.get('industry', ''),
                'sector': meta['sector'],
                'vr20': cand.get('vr20', 0), 'turnover': cand.get('turnover', 0),
                'in_candidates': code in candidate_scores
            })

    buyable.sort(key=lambda x: x['score'], reverse=True)

    # ── 🌡️ 市场环境评级详情 (结论已在摘要, 此处解释) ──
    if env_info.get('env'):
        print(f'\n  {env_info["env"]}: 昨日涨停{env_info["zt_n"]}只, 最高{env_info["max_cons"]}板'
              + (f', 较前日{env_info["zt_prev"]}只{"回升" if env_info["warming"] else "回落"}' if env_info["zt_prev"] is not None else ''))
        print(f'  {env_info["switch"]} (仓位由个人交易情况决定, 仅温度建议)')
        if env_info.get('downgraded'):
            print(f'  ⚠ 竞价二次确认: 池均gap {env_info["avg_gap"]:+.1f}% ≤ -0.5% → 环境降档'
                  f' (3年724日: 该档当日-2.87%/上涨31%)')
        elif env_info.get('avg_gap') is not None:
            print(f'  ✓ 竞价二次确认: 池均gap {env_info["avg_gap"]:+.1f}% > -0.5%, 维持评级')
        if env_info.get('money_effect') is not None:
            _me = env_info['money_effect']
            if _me < -2.0 and env_info.get('downgraded'):
                print(f'  ⚠ 盘后赚钱效应: 昨日{_me:+.1f}% < -2% → 已降档')
            else:
                _me_mark = '⚠' if _me < 0 else '✓'
                print(f'  {_me_mark} 盘后赚钱效应: 昨日{_me:+.1f}% (关联最强指标, <-2%降档)')

    # ── 📊 表1: 当日可买前三 ──
    from scoring import get_score_min as _gsm
    top3 = [b for b in buyable if b['score'] >= _gsm()][:3]
    print(f'\n{"=" * 65}')
    print(f'  📊 表1: 当日可买前三 (评分≥50, 竞价4-8%, 已过滤一字/4板+一字/300·688)')
    print(f'{"=" * 65}')
    if top3:
        print(f'  {"#":<3}{"标的":<14}{"评分":>6}{"竞价gap":>8}{"连板":>5}{"板块":>9}{"⚠跌停风险":>10}')
        for i, b in enumerate(top3, 1):
            # 跌停风险查表 (2026-08-24, 3年全路径积分模型)
            _cons = int(b.get('limit_days') or 1)
            _vr = b.get('vr20', 0) or 0
            if _cons >= 3:
                _dt_p, _dt_risk = 30.5, -0.93
            elif _cons == 2:
                _dt_p, _dt_risk = 22.0, -0.81
            elif _vr >= 4:
                _dt_p, _dt_risk = 9.5, -0.92
            elif _vr < 1:
                _dt_p, _dt_risk = 4.1, -0.28
            else:
                _dt_p, _dt_risk = 10.7, -0.42
            _dt_mark = '🔴' if _dt_p >= 20 else ('🟡' if _dt_p >= 10 else '⚪')
            _dt_str = f'{_dt_mark}{_dt_p:.0f}%({_dt_risk:+.2f})'
            print(f'  {i:<3}{b["name"]}({b["code"]}){b["score"]:>8.0f}{b["gap"]:>+7.1f}%'
                  f'{str(_cons) + "板":>6}{str(b["sector"]) + "只":>6}{_dt_str:>14}')
    else:
        print(f'  (无评分≥50的可买标的)')

    # ── 📊 表2: 前三名得分细则 ──
    if top3:
        print(f'\n{"=" * 65}')
        print(f'  📊 表2: 前三名得分细则 (V4百分制加权)')
        print(f'{"=" * 65}')
        from scoring import load_config as _lc2
        _cfg2 = _lc2()
        for b in top3:
            meta = stock_scoring_meta(b['code'])
            if meta['klines'] and meta['detail']:
                from scoring import score_v4
                _sc4, _det4 = score_v4(b['code'], meta['klines'], meta['detail'])
                if _det4:
                    print(f'  {b["name"]}({b["code"]})  {_sc4:.0f}分')
                    _f = _det4['factor_scores']
                    _w = _cfg2['v4']['weights']
                    print(f'    ' + '  '.join(
                        f'{k}({_f.get(k, 0):.0f}分×{_w.get(k, 0):.0f}%)' for k in _w if _w[k] > 0))

    # ── 昨日候选（参考） ──
    if data:
        print(f'\n  --- 昨日候选参考 (T-1={data["date"]}, 已评分) ---')
        non_one_line = [c for c in data['candidates'][:15] if not c.get('one_line', False)]
        for i, c in enumerate(non_one_line[:5]):
            in_auction = any(a['code'] == c['code'] for a in buyable)
            mark = ' ← 今日竞价池内' if in_auction else ''
            print(f'  #{i+1} {c["name"]}({c["code"]})  {c["score"]:.0f}分  '
                  f'{c.get("cons",1)}板  T-1gap{c.get("gap",0):+.1f}%{mark}')

    # ── 一字板隔日关注 ──
    one_line_watch = data.get('one_line_watch', []) if data else []
    if one_line_watch:
        print(f'\n  ═══ ⚡ 一字板隔日关注 ═══')
        pp = _load_prev_pool()
        file_cons = {}
        if pp:
            file_cons = {str(x.get('code', '')).replace('sh', '').replace('sz', ''): int(x.get('limit_days', 1) or 1)
                         for x in pp[0]}
        for r in one_line_watch[:5]:
            cons = max(int(r.get('cons', 1) or 1), file_cons.get(str(r.get('code', '')), 1))
            warn = '⚠高危' if cons >= 4 else '★优先'
            print(f'  {r["name"]}({r["code"]}) {cons}板 {warn}')

    # ── 🐉 分歧弱转强候选 (半自动提示, 三级分级) ──
    try:
        div_cands = find_divergence_candidates()
        if div_cands:
            print(f'\n  ═══ 🐉 分歧弱转强候选 (T-1爆量烂板, CONFIRMED/WATCH/REJECT) ═══')
            for c in sorted(div_cands, key=lambda x: (x['grade'] == 'REJECT', -x['gap'])):
                if c['grade'] == 'WATCH':
                    star = '★大高开' if c['gap'] >= 6 else ('可关注' if c['gap'] >= 4 else '观察')
                    sec_warn = ' ⚠板块弱' if c['sector'] < 2 else ''
                    print(f'  WATCH   {c["name"]}({c["code"]}) 竞价{c["gap"]:+.1f}% {star} | '
                          f'T-1烂板炸{c["zhaban"]}次 {c["cons"]}板 板块:{c["industry"]}{c["sector"]}只{sec_warn}')
                else:
                    print(f'  REJECT  {c["name"]}({c["code"]}) 竞价{c["gap"]:+.1f}% 低开→弱转强失败')
            print(f'  盘中确认→CONFIRMED: ①开盘立即拉升/杀后立拉 ②封板缩量(vs T-1) ③板块领涨')
            print(f'  否定→REJECT: 二次爆量 | 高开后持续下杀 | 破0% | 收盘前未反包')
    except Exception as e:
        print(f'  [WARN] 分歧候选计算失败: {e}')

    # ── 🎯 盘中买点参考 (2026-08-16, 源自干货合集_买点, 只提示不自动交易) ──
    print(f'\n  ═══ 🎯 盘中买点参考 (竞价未买到时, 仅供参考) ═══')
    print(f'  半路: 拉升破7%才考虑追 (冲不过7%多为假拉升/试盘)')
    print(f'  低吸①: 高开急杀到 开盘价-7% 附近 (恐慌盘后博弈修复, 未回测)')
    print(f'  低吸②: 盘中较开盘价低-10% 附近 (高开大幅下杀博弈修复, 未回测)')
    print(f'  ⚠ 价格笼子: 9:25后补单 买入≤卖一价×102%, 卖出≥买一价×98%, 超限=废单')
    print(f'  ⚠ 打板需高理解力, 早盘板多虚晃一枪, 无确定性不参与')

    print(f'\n  --- 操作步骤 ---')
    print(f'  卖出: 看上方持仓判断')
    print(f'  买入: 从今日竞价池选, gap 4%-8%, 一字板跳过')
    print(f'  14:45 限价单未成交→市价兜底')
    print(f'=' * 65)

    # ── 每日推荐记录（无论是否交易） ──
    try:
        today_str = datetime.now().strftime('%Y-%m-%d')
        rec_dir = os.path.join(BASE, 'logs', 'daily_recommendations')
        os.makedirs(rec_dir, exist_ok=True)
        rec_file = os.path.join(rec_dir, f'{today_str}.json')

        rec = {
            'date': today_str,
            'generated': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'total_in_pool': len(auction_stocks),
            'buyable_count': len(buyable),
            'top_pick': buyable[0] if buyable else None,
            'buyable': buyable,
            'position_status': (', '.join(p.get('name', '?') for p in pf.get('positions', [])) if pf and pf.get('positions') else (pf.get('position', {}).get('name', '空仓') if pf and pf.get('position') else '空仓')),
            'action_taken': None
        }
        # 每次运行覆盖写入(竞价9:25后才完整, 避免首次运行过早留下空数据)
        if datetime.now().strftime('%H:%M') >= '09:25' and buyable:
            with open(rec_file, 'w', encoding='utf-8') as f:
                json.dump(rec, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # 静默失败，不影响主流程


if __name__ == '__main__':
    main()
