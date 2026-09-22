"""低开深水拉涨停 形态的次日表现 (2026-09-21 用户问华金资本 000532)

背景: 华金资本 09-21 低开-3.16%(最低-3.32%)拉到涨停 + 14:38 尾盘封板 + 换手16.38%/量比4.24x
问: 这种"低开拉板"是主升浪启动信号吗?
做法: 全样本3047只K线, 取所有涨停日(pct_change>=9.8)按形态分组, 看 T+1 (次日开盘买入→次日收盘)
     训练段 2016~2023 / 检验段 2024~2026-09 分开报, 防跨期反向
"""
import json, os, sys

sys.stdout.reconfigure(encoding='utf-8')
D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'kline_data')
SPLIT = '2024-01-01'

GROUPS = {
    'A 全部涨停(基准)': dict(),
    'B 涨停+低开': dict(gap_max=0.0),
    'C 涨停+低开<=-2%': dict(gap_max=-2.0),
    'D C+量比>=3x': dict(gap_max=-2.0, vr_min=3.0),
    'E D+收盘=最高(尾盘封)': dict(gap_max=-2.0, vr_min=3.0, close_is_high=True),
}


def match(kw, gap, vr, hi):
    if kw.get('gap_max') is not None and gap > kw['gap_max']:
        return False
    if kw.get('vr_min') is not None and vr < kw['vr_min']:
        return False
    if kw.get('close_is_high') and not hi:
        return False
    return True


def main():
    files = [f for f in os.listdir(D) if f.endswith('.json') and f != 'stock_index.json']
    rec = {name: {'train': [], 'test': []} for name in GROUPS}
    for fn in files:
        try:
            raw = json.load(open(os.path.join(D, fn), encoding='utf-8'))
        except Exception:
            continue
        kl = raw['data'] if isinstance(raw, dict) else raw
        if not isinstance(kl, list) or len(kl) < 40:
            continue
        for i in range(20, len(kl) - 1):
            k = kl[i]
            if (k.get('pct_change') or 0) < 9.8:
                continue
            pc = kl[i - 1].get('close') or 0
            if pc <= 0:
                continue
            vs = [kl[j].get('volume') or 0 for j in range(i - 20, i)]
            vs = [v for v in vs if v > 0]
            if len(vs) < 15:
                continue
            ma = sum(vs) / len(vs)
            v = k.get('volume') or 0
            if ma <= 0 or v <= 0:
                continue
            vr = v / ma
            gap = (k['open'] - pc) / pc * 100
            hi = k['close'] >= (k.get('high') or 0) - 1e-6
            nxt = kl[i + 1]
            if not nxt.get('open'):
                continue
            ret = (nxt['close'] - nxt['open']) / nxt['open'] * 100
            seg = 'train' if k['date'] < SPLIT else 'test'
            for name, kw in GROUPS.items():
                if match(kw, gap, vr, hi):
                    rec[name][seg].append(ret)

    hdr = f"{'组合':<22}{'训练段 2016~2023':>26}{'检验段 2024~2026-09':>26}"
    sub = f"{'':<22}{'n':>7}{'T+1均%':>9}{'胜率':>10}{'n':>7}{'T+1均%':>9}{'胜率':>10}"
    print(hdr)
    print(sub)
    print('-' * 74)
    for name in GROUPS:
        row = f'{name:<22}'
        for seg in ('train', 'test'):
            a = rec[name][seg]
            if a:
                row += f"{len(a):>7}{sum(a) / len(a):>9.2f}{sum(1 for x in a if x > 0) / len(a) * 100:>9.0f}%"
            else:
                row += f"{'-':>7}{'-':>9}{'-':>10}"
        print(row)


if __name__ == '__main__':
    main()
