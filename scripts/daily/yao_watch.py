"""
妖股观察 — 强连板发现体系落地 (指纹层 + 晋级层)
================================================
源自: 资料/妖股研究_强连板发现体系.md (research_streaks.py 回测)
只提示不自动交易 (与「🐉分歧候选」同套路)。

指纹层(盘后): 涨停池筛 2~4 板股, 命中 4 条件:
  ① 量比缩量  (2板<0.8x 极度缩量 / 3-4板<1.2x 缩量不爆量)
  ② 启动价 <30 元   (连板起点前收盘价, 低价股接力成本低)
  ③ 前20日涨幅 +3~8% (温和蓄势, 非超跌反弹)
  ④ 板块 >= 2 只    (同行业涨停家数, 题材共振)

晋级层(次日竞价 --next): 指纹股验证 竞价gap 4-8%

用法:
  python yao_watch.py          # 盘后: 出指纹股清单 (存 logs/yao_watch.json)
  python yao_watch.py --next   # 次日竞价: 晋级验证
"""
import json, os, sys, glob
from datetime import datetime
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ZT_STATE = os.path.join(BASE, 'data', 'zt_pool_state.json')
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
AUCTION_DIR = os.path.join(BASE, 'data', 'auction')
WATCH_FILE = os.path.join(BASE, 'logs', 'yao_watch.json')

# 指纹阈值 (源自报告发现5/6/8)
BOARD_MIN, BOARD_MAX = 2, 4   # 观察 2~4 板
PRICE_MAX = 30.0              # 启动价 < 30元
PRE20_MIN, PRE20_MAX = 3.0, 8.0   # 前20日涨幅 +3~8%
SECTOR_MIN = 2                # 板块 >= 2只
GAP_MIN, GAP_MAX = 4.0, 8.0   # 晋级: 竞价 gap 4-8%


def _vol_ratio_max(board):
    """量比阈值按连板数: 2板极度缩量<0.8x, 3-4板缩量不爆量<1.2x"""
    return 0.8 if board == 2 else 1.2


def _is_lu(close, prev_close, cyb):
    limit = round(prev_close * (1.2 if cyb else 1.1), 2)
    return close >= limit - 0.005


def _load_klines(code):
    for fp in [os.path.join(KLINE_DIR, f'{code}.json')] + \
              glob.glob(os.path.join(KLINE_DIR, f'*_{code}.json')):
        if os.path.exists(fp):
            try:
                with open(fp, encoding='utf-8') as f:
                    raw = json.load(f)
                return raw.get('data', raw) if isinstance(raw, dict) else raw
            except Exception:
                continue
    return None


def fingerprint(code, klines, board):
    """对 board(2~4) 连板股算指纹, 返回 dict 或 None"""
    if not klines or len(klines) < board + 22:
        return None
    cyb = code.startswith(('30', '68'))
    n = len(klines)
    # 确认末尾 board 根是连续涨停
    for i in range(board):
        if not _is_lu(klines[n - 1 - i]['close'], klines[n - 2 - i]['close'], cyb):
            return None
    # 启动价 = 连板起点(第1板)前一日收盘价
    start_price = klines[n - board - 1].get('close', 0)
    # 量比 = 最新板量 / 前5日均量 (三口径对比实验最优: 区分度2.04x > 20日均量1.96x > 环比1.88x,
    # 且5日窗口受连板爆量污染小于20日; 阈值0.8x/1.2x按此口径统计的成妖率)
    v_latest = klines[n - 1].get('volume', 0) or 0
    vols = [klines[j].get('volume', 0) or 0 for j in range(max(0, n - 6), n - 1)]
    avg = sum(vols) / len(vols) if vols else 0
    vol_ratio = round(v_latest / avg, 2) if avg > 0 else 99.0
    # 前20日涨幅 = 启动价 / (起点前20日收盘) - 1
    idx = n - board - 1 - 20
    pre20 = None
    if idx >= 0:
        base = klines[idx].get('close', 0)
        if base > 0:
            pre20 = round((start_price / base - 1) * 100, 2)

    return {
        'code': code,
        'board': board,
        'start_price': start_price,
        'vol_ratio': vol_ratio,
        'pre20': pre20,
        'last_date': klines[-1].get('date', ''),
    }


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    next_mode = '--next' in sys.argv

    # ── 晋级层 ──
    if next_mode:
        if not os.path.exists(WATCH_FILE):
            print('[yao_watch] 无昨日指纹清单, 先跑 python yao_watch.py')
            return
        with open(WATCH_FILE, encoding='utf-8') as f:
            watch = json.load(f)
        today = datetime.now().strftime('%Y-%m-%d')
        af = os.path.join(AUCTION_DIR, f'{today}.json')
        auction = {}
        if os.path.exists(af):
            with open(af, encoding='utf-8') as f:
                ad = json.load(f)
            for s in (ad.get('stocks', []) if isinstance(ad, dict) else ad):
                auction[str(s.get('code'))] = s
        print('=' * 60)
        print(f'  妖股晋级验证 ({len(watch.get("stocks", []))} 只) — {today}')
        print('=' * 60)
        for w in watch.get('stocks', []):
            a = auction.get(w['code'])
            if not a:
                print(f'  {w["name"]}({w["code"]}) 不在今日竞价池 (未涨停/非候选)')
                continue
            gap = a.get('gap_pct', 0)
            mark = '✅ 晋级(打板观察)' if GAP_MIN <= gap <= GAP_MAX else '❌ 放弃'
            print(f'  {mark} {w["name"]}({w["code"]}) {w["board"]}板 竞价gap {gap:+.1f}%')
        return

    # ── 指纹层 ──
    if not os.path.exists(ZT_STATE):
        print('[yao_watch] 无涨停池 state, 先跑流水线')
        return
    with open(ZT_STATE, encoding='utf-8') as f:
        state = json.load(f)
    stocks = state.get('stocks', [])
    sector_cnt = Counter(str(s.get('industry', '')) for s in stocks)

    hits = []
    near = []  # 接近命中(缺1个条件)
    for s in stocks:
        board = int(s.get('limit_days', 1) or 1)
        if not (BOARD_MIN <= board <= BOARD_MAX):
            continue
        code = s.get('code', '')
        name = s.get('name', '')
        klines = _load_klines(code)
        fp = fingerprint(code, klines, board)
        if not fp:
            continue
        fp['name'] = name
        fp['industry'] = s.get('industry', '')
        fp['sector'] = sector_cnt.get(s.get('industry', ''), 1)

        vol_max = _vol_ratio_max(board)
        conds = {
            f'量比<{vol_max}x': fp['vol_ratio'] < vol_max,
            f'启动<{PRICE_MAX}元': fp['start_price'] < PRICE_MAX,
            '前20日+3~8%': fp['pre20'] is not None and PRE20_MIN <= fp['pre20'] <= PRE20_MAX,
            f'板块≥{SECTOR_MIN}只': fp['sector'] >= SECTOR_MIN,
        }
        fp['conds'] = conds
        n_ok = sum(conds.values())
        if n_ok == 4:
            hits.append(fp)
        elif n_ok >= 2:
            fp['miss'] = [k for k, v in conds.items() if not v]
            near.append(fp)

    print('=' * 60)
    print(f'  妖股指纹层 — 涨停池 {len(stocks)} 只, 观察 {BOARD_MIN}-{BOARD_MAX} 板')
    print('=' * 60)
    print(f'  阈值: 量比(2板<0.8x/3-4板<1.2x) | 启动<{PRICE_MAX}元 | 前20日+{PRE20_MIN}~{PRE20_MAX}% | 板块≥{SECTOR_MIN}只')
    print('-' * 60)

    if hits:
        hits.sort(key=lambda x: x['vol_ratio'])
        print(f'  ⭐ 命中 {len(hits)} 只 (4条件全中):')
        for h in hits:
            print(f"    {h['name']}({h['code']}) {h['board']}板 {h['industry']} | "
                  f"量比{h['vol_ratio']:.2f}x 启动{h['start_price']:.2f}元 前20日{h['pre20']:+.1f}% 板块{h['sector']}只")
    else:
        print('  ⭐ 命中 0 只 (4条件全中)')

    if near:
        near.sort(key=lambda x: -sum(x['conds'].values()))
        print(f'\n  ◐ 接近命中 {len(near)} 只 (缺1-2个条件):')
        for h in near:
            print(f"    {h['name']}({h['code']}) {h['board']}板 {h['industry']} | "
                  f"量比{h['vol_ratio']:.2f}x 启动{h['start_price']:.2f}元 前20日{h['pre20']:+.1f}% 板块{h['sector']}只 "
                  f"→ 缺: {'、'.join(h['miss'])}")
    else:
        print('\n  ◐ 接近命中 0 只')

    # 保存命中池(供次日晋级)
    out = {'generated': datetime.now().strftime('%Y-%m-%d %H:%M'),
           'stocks': [{'code': h['code'], 'name': h['name'], 'board': h['board']} for h in hits]}
    with open(WATCH_FILE, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'\n  命中池已存: {WATCH_FILE} → 次日 9:25 跑 `python yao_watch.py --next` 验证晋级')


if __name__ == '__main__':
    main()
