"""
妖股观察 — 强连板发现体系落地 (指纹层 + 晋级层)
================================================
源自: 资料/妖股研究_强连板发现体系.md (research_streaks.py 回测)
只提示不自动交易 (与「🐉分歧候选」同套路)。

指纹层(盘后): 涨停池筛 2~4 板股, 命中 3 条件:
  ① 量比缩量  (2板<0.8x 极度缩量 / 3-4板<1.2x 缩量不爆量)
  ② 启动价 <10 元   (连板起点前收盘价)
  ③ 板块 >= 2 只    (同题材共振家数)

2026-09-21 修订 (依据 09-19 独立全样本复现, 12636 个2板事件, 基线成妖率 2.03%):
  - 删除原条件③「前20日涨幅 +3~8%」—— 复现成妖率 2.12% / 1.04x, 零增量
  - 启动价阈值 30元 → 10元 —— 复现 <10元 2.76%(1.36x), 10-30元 降至 1.42%(0.70x)
  - 板块计数改用 scoring.sector_resonance_count —— 原 Counter 整串匹配在同花顺
    复合原因串下恒等于 1, 条件③自 2026-08-20 换源起永远为假 (模块哑了一个月)
  报告: logs/analysis/yaogu_theory_verification_2026-09-19.md §5

晋级层(次日竞价 --next): 指纹股验证 竞价gap 落在现行买入窗口内
  (窗口由 scoring_config.json buy_window 提供; 2026-09-22 下限 4→0)

用法:
  python yao_watch.py          # 盘后: 出指纹股清单 (存 logs/yao_watch.json)
  python yao_watch.py --next   # 次日竞价: 晋级验证
"""
import json, os, sys, glob
from datetime import datetime

from scoring import sector_resonance_count, get_buy_window

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ZT_STATE = os.path.join(BASE, 'data', 'zt_pool_state.json')
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
AUCTION_DIR = os.path.join(BASE, 'data', 'auction')
WATCH_FILE = os.path.join(BASE, 'logs', 'yao_watch.json')

# 指纹阈值 (源自报告发现5/6/8; 2026-09-21 按 09-19 复现结果修订)
BOARD_MIN, BOARD_MAX = 2, 4   # 观察 2~4 板
PRICE_MAX = 10.0              # 启动价 < 10元
SECTOR_MIN = 2                # 同题材共振 >= 2只
GAP_MIN, GAP_MAX = get_buy_window()   # 晋级判据跟随现行买入窗口(2026-09-22起不再硬编码)


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
    _all_industries = [s.get('industry', '') for s in stocks]

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
        fp['sector'] = sector_resonance_count(s.get('industry', ''), _all_industries)

        vol_max = _vol_ratio_max(board)
        conds = {
            f'量比<{vol_max}x': fp['vol_ratio'] < vol_max,
            f'启动<{PRICE_MAX:.0f}元': fp['start_price'] < PRICE_MAX,
            f'板块≥{SECTOR_MIN}只': fp['sector'] >= SECTOR_MIN,
        }
        fp['conds'] = conds
        n_ok = sum(conds.values())
        if n_ok == len(conds):
            hits.append(fp)
        elif n_ok >= 2:
            fp['miss'] = [k for k, v in conds.items() if not v]
            near.append(fp)

    print('=' * 60)
    print(f'  妖股指纹层 — 涨停池 {len(stocks)} 只, 观察 {BOARD_MIN}-{BOARD_MAX} 板')
    print('=' * 60)
    print(f'  阈值: 量比(2板<0.8x/3-4板<1.2x) | 启动<{PRICE_MAX:.0f}元 | 板块≥{SECTOR_MIN}只'
          f'  [前20日涨幅仅展示, 不参与筛选]')
    print('-' * 60)

    def _pre20(h):
        return f"{h['pre20']:+.1f}%" if h['pre20'] is not None else 'n/a'

    if hits:
        hits.sort(key=lambda x: x['vol_ratio'])
        print(f'  ⭐ 命中 {len(hits)} 只 (3条件全中):')
        for h in hits:
            print(f"    {h['name']}({h['code']}) {h['board']}板 {h['industry']} | "
                  f"量比{h['vol_ratio']:.2f}x 启动{h['start_price']:.2f}元 板块{h['sector']}只 前20日{_pre20(h)}")
    else:
        print('  ⭐ 命中 0 只 (3条件全中)')

    if near:
        near.sort(key=lambda x: -sum(x['conds'].values()))
        print(f'\n  ◐ 接近命中 {len(near)} 只 (缺1个条件):')
        for h in near:
            print(f"    {h['name']}({h['code']}) {h['board']}板 {h['industry']} | "
                  f"量比{h['vol_ratio']:.2f}x 启动{h['start_price']:.2f}元 板块{h['sector']}只 前20日{_pre20(h)} "
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
