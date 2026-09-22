"""
研究: 2板时点因子的成妖预测力 (独立复现 + 新因子探索) 2026-09-19
=================================================================
问题: 妖股研究文档的分档数字(量比4.5%/1.7%...、启动价2.8%/0.0%...)口径
      是否可复现? "前20日蓄势"有无预测力(文档只给了均值对比, 没给分层成妖率)?
口径(全样本预测口径, 2板时点可观测, 无未来函数):
  - 事件 = 每个连板段的第2板日 (段起点+1), 仅统计已结束段
  - 启动价 = 段起点(第1板)前一日收盘
  - 2板量比 = 第2板日量 / 前5日均量 (yao_watch.py 同口径)
  - 前20日涨幅 = 启动价 / (起点前20日收盘) - 1 (yao_watch.py 同口径)
  - 标签: 段最终高度 >=5 (走强) / >=7 (成妖)
"""
import json, os, sys, glob

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
IPO_GUARD = 40


def is_lu(close, prev_close, cyb):
    limit = round(prev_close * (1.2 if cyb else 1.1), 2)
    return close >= limit - 0.005


def main():
    files = glob.glob(os.path.join(KLINE_DIR, '*.json'))
    print(f'K线库: {len(files)} 只')
    evs = []
    for fp in files:
        code = os.path.basename(fp).replace('.json', '')
        if not code.isdigit():
            continue
        try:
            raw = json.load(open(fp, encoding='utf-8'))
            kl = raw['data'] if isinstance(raw, dict) else raw
        except Exception:
            continue
        n = len(kl)
        if n < 30:
            continue
        cyb = code.startswith(('30', '68'))
        lu = [False] * n
        for i in range(1, n):
            if kl[i].get('close') and kl[i - 1].get('close'):
                lu[i] = is_lu(kl[i]['close'], kl[i - 1]['close'], cyb)
        i = 1
        while i < n:
            if not lu[i]:
                i += 1
                continue
            start = i
            while i < n and lu[i]:
                i += 1
            streak = i - start
            if start < IPO_GUARD or i >= n or streak < 2:
                continue
            b2 = start + 1  # 第2板日
            # 启动价 = 第1板前一日收盘
            sp = kl[start - 1].get('close', 0)
            # 2板量比: 第2板日量/前5日均量
            vols = [kl[j].get('volume', 0) or 0 for j in range(max(0, b2 - 5), b2)]
            avg = sum(vols) / len(vols) if vols else 0
            vr = round((kl[b2].get('volume', 0) or 0) / avg, 2) if avg > 0 else None
            # 前20日涨幅
            idx = start - 1 - 20
            pre20 = None
            if idx >= 0 and kl[idx].get('close', 0):
                pre20 = round((sp / kl[idx]['close'] - 1) * 100, 2)
            evs.append({'code': code, 'date': kl[b2]['date'], 'sp': sp, 'vr': vr,
                        'pre20': pre20, 'streak': streak, 'is7': streak >= 7, 'is5': streak >= 5})
    base7 = sum(e['is7'] for e in evs) / len(evs) * 100
    base5 = sum(e['is5'] for e in evs) / len(evs) * 100
    print(f'\n2板事件 (已结束段): {len(evs)} 个 | 基线成妖率(>=7板) {base7:.2f}% | 走强率(>=5板) {base5:.2f}%')

    def show(field, bins, fmt='{:.2f}', label=''):
        print(f'\n-- {label or field} 分档 --')
        print(f'{"档位":<18} {"样本":>6} {"成妖率>=7":>9} {"走强率>=5":>9} {"倍数(vs基线)":>12}')
        valid = [e for e in evs if e[field] is not None]
        for lo, hi, name in bins:
            sub = [e for e in valid if (lo <= e[field] < hi)]
            if not sub:
                continue
            r7 = sum(x['is7'] for x in sub) / len(sub) * 100
            r5 = sum(x['is5'] for x in sub) / len(sub) * 100
            print(f'{name:<18} {len(sub):>6} {r7:>8.2f}% {r5:>8.2f}% {r7/base7:>11.2f}x')

    show('vr', [(0, 0.8, '<0.8x'), (0.8, 1.5, '0.8-1.5x'), (1.5, 2.5, '1.5-2.5x'),
                (2.5, 5, '2.5-5x'), (5, 999, '>5x')], label='2板量比 (独立复现研究表)')
    show('sp', [(0, 10, '<10元'), (10, 30, '10-30元'), (30, 50, '30-50元'), (50, 1e9, '>50元')],
         label='启动价 (独立复现研究表)')
    show('pre20', [(-999, 0, '<0%'), (0, 3, '0~3%'), (3, 8, '3~8%★'), (8, 20, '8~20%'), (20, 9999, '>20%')],
         label='前20日涨幅 (文档只给均值, 此处做分层)')
    # 组合: 量比<0.8 且 前20日3~8
    combo = [e for e in evs if e['vr'] is not None and e['vr'] < 0.8 and e['pre20'] is not None and 3 <= e['pre20'] <= 8]
    if combo:
        r7 = sum(x['is7'] for x in combo) / len(combo) * 100
        r5 = sum(x['is5'] for x in combo) / len(combo) * 100
        print(f'\n-- 组合: 量比<0.8x 且 前20日3~8% --')
        print(f'  样本{len(combo)} 成妖率{r7:.2f}% ({r7/base7:.1f}x基线) 走强率{r5:.2f}%')
    # 组合: 量比<0.8 且 启动<10
    combo2 = [e for e in evs if e['vr'] is not None and e['vr'] < 0.8 and e['sp'] < 10]
    if combo2:
        r7 = sum(x['is7'] for x in combo2) / len(combo2) * 100
        r5 = sum(x['is5'] for x in combo2) / len(combo2) * 100
        print(f'\n-- 组合: 量比<0.8x 且 启动价<10元 --')
        print(f'  样本{len(combo2)} 成妖率{r7:.2f}% ({r7/base7:.1f}x基线) 走强率{r5:.2f}%')

    out = os.path.join(BASE, 'logs', 'research_yaogu_factors.json')
    json.dump({'total': len(evs), 'base7': base7, 'events': evs},
              open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'\n结果已存: {out}')


if __name__ == '__main__':
    main()
