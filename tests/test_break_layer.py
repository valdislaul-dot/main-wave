"""📉 断板去留分层 测试 (2026-09-19)
触发=持仓最后交易日为断板日(前日涨停)且断板前连板数>=3;
分层=按板级(3-4/5+)与今日竞价gap三档映射历史数字, 深水拉回收阳仅5板+有效。
依据: logs/analysis/yaogu_theory_verification_2026-09-19.md §8/§9
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'scripts', 'daily'))
import break_layer as bl  # noqa: E402


def _klines(streak=6, break_gap=0.0, break_recover=True, code='000001', tail=10, rate=None):
    """连板 streak 天后接一根断板K线; 前面 tail 根平盘"""
    if rate is None:
        rate = 1.2 if code.startswith(('30', '68')) else 1.1
    out = []
    c = 10.0
    for i in range(tail):
        out.append({'date': f'2026-07-{i + 1:02d}', 'open': c, 'close': c,
                    'high': c + 0.05, 'low': c - 0.05, 'volume': 100})
    prev_c = c
    for i in range(streak):
        nc = round(prev_c * rate, 2)
        out.append({'date': f'2026-08-{i + 1:02d}', 'open': prev_c, 'close': nc,
                    'high': nc, 'low': prev_c, 'volume': 120})
        prev_c = nc
    b_open = round(prev_c * (1 + break_gap / 100), 2)
    b_close = round(b_open * 1.03, 2) if break_recover else round(b_open * 0.97, 2)
    out.append({'date': '2026-08-20', 'open': b_open, 'close': b_close,
                'high': max(b_open, b_close) + 0.05, 'low': min(b_open, b_close) - 0.05,
                'volume': 200})
    return out


def test_detect_streak_and_tier():
    st = bl.detect_break_state('000001', _klines(streak=6))
    assert st and st['streak'] == 6
    st3 = bl.detect_break_state('000001', _klines(streak=3))
    assert st3 and st3['streak'] == 3


def test_not_triggered_cases():
    # 昨日仍涨停(连板中) → 不触发
    kl = _klines(streak=6)
    kl[-1] = {'date': '2026-08-20', 'open': kl[-2]['close'], 'close': round(kl[-2]['close'] * 1.1, 2),
              'high': round(kl[-2]['close'] * 1.1, 2), 'low': kl[-2]['close'], 'volume': 150}
    assert bl.detect_break_state('000001', kl) is None
    # 2连板后断板 → 低于 min_streak, context 不触发
    assert bl.break_layer_context('000001', 'x', 1.0, klines=_klines(streak=2)) is None
    # 断板日不是昨天(前天断板, 昨日继续非涨停) → d1窗口已过
    kl2 = _klines(streak=6)
    kl2.append({'date': '2026-08-21', 'open': kl2[-1]['close'], 'close': kl2[-1]['close'] * 0.99,
                'high': kl2[-1]['close'], 'low': kl2[-1]['close'] * 0.98, 'volume': 90})
    assert bl.detect_break_state('000001', kl2) is None


def test_gap_bands():
    kl = _klines(streak=6, break_gap=0.0, break_recover=False)
    assert bl.break_layer_context('000001', 'x', 1.0, klines=kl)['band'] == 'high'
    assert bl.break_layer_context('000001', 'x', 0.0, klines=kl)['band'] == 'high'
    assert bl.break_layer_context('000001', 'x', -1.5, klines=kl)['band'] == 'mid'
    assert bl.break_layer_context('000001', 'x', -3.0, klines=kl)['band'] == 'mid'
    assert bl.break_layer_context('000001', 'x', -4.0, klines=kl)['band'] == 'low'


def test_stats_match_tier():
    r5 = bl.break_layer_context('000001', 'x', 1.0, klines=_klines(streak=6))
    assert r5['tier'] == '5p' and r5['stat']['d1'] == 3.05
    r3 = bl.break_layer_context('000001', 'x', 1.0, klines=_klines(streak=4))
    assert r3['tier'] == '34' and r3['stat']['d1'] == 3.29


def test_deep_recover_special():
    # 深水(-6%)拉回收阳: 5板+ → 强承接有效
    r5 = bl.break_layer_context('000001', 'x', 0.5, klines=_klines(streak=5, break_gap=-6, break_recover=True))
    assert r5['special'] and r5['special']['valid'] is True and r5['special']['d1'] == 3.16
    # 同组合 3-4板 → 不适用标注
    r3 = bl.break_layer_context('000001', 'x', 0.5, klines=_klines(streak=3, break_gap=-6, break_recover=True))
    assert r3['special'] and r3['special']['valid'] is False
    # 深水收阴 → 无 special
    rn = bl.break_layer_context('000001', 'x', 0.5, klines=_klines(streak=5, break_gap=-6, break_recover=False))
    assert rn['special'] is None


def test_cyb_20pct_limit():
    # 创业板 10% 涨幅不算涨停 → 不构成连板
    assert bl.detect_break_state('300001', _klines(streak=6, code='300001', rate=1.1)) is None
    # 创业板 20% 涨停正确识别
    kl = _klines(streak=6, code='300001')
    st = bl.detect_break_state('300001', kl)
    assert st and st['streak'] == 6


def test_disabled_and_guards():
    cfg = bl.load_config()
    cfg['enabled'] = False
    assert bl.break_layer_context('000001', 'x', 1.0, klines=_klines(streak=6), config=cfg) is None
    # gap_pct 缺失 → None
    assert bl.break_layer_context('000001', 'x', None, klines=_klines(streak=6)) is None
    # 无K线 → None
    assert bl.break_layer_context('000001', 'x', 1.0, klines=[]) is None


def test_config_numbers_lock():
    """生产配置数字锁定 = 研究报告 §8/§9 检验段 (防误改)"""
    cfg = bl.load_config()
    assert cfg['min_streak'] == 3 and cfg['recover_min_streak'] == 5
    s = cfg['stats']
    assert s['34']['high'] == {'d1': 3.29, 'up': 66, 'fb': 29, 'n': 359}
    assert s['34']['low']['d1'] == -8.02
    assert s['5p']['high'] == {'d1': 3.05, 'up': 63, 'fb': 26, 'n': 105}
    assert s['5p']['deep_recover']['d1'] == 3.16 and s['5p']['deep_recover']['n'] == 25
    assert s['34']['deep_recover']['d1'] == -5.69  # 3-4板无效对照
