"""卖点引擎回归测试 (2026-09-17 修复锁定)。

背景: sell_engine 此前**零测试覆盖** (tests/ 无任何文件引用它) —— 2026-09-16
实盘暴露的"一字跌停不走硬止损"正因如此长期潜伏。本文件锁定 2026-09-17 四项修复:

  ① 硬止损信号带 kind='hard_stop' —— morning_check 的「当日Top1仍是持仓则不卖」
     覆盖规则据此放行 (用户定稿: 硬止损 -10% 保留且优先)。原实现无条件覆写,
     只要持仓票当日 buyable 排第1, 连破位止损也被静默改成"继续持有"。
  ② A式信号带 kind='a_style', sell_execution_price 返回**挂单涨停价**。
     原实现让 A式信号落进 V3.2 公式, 9:25 时 H=0 且 close=竞价价 → 打印
     "执行价=开盘价", 与同一条 reason 的"挂涨停价X限价卖"自相矛盾, 照抄即
     退化为被回测否定的口径 (A式 +1.05%/59% vs 开盘价卖 -1.20%/45%)。
  ③ 涨停价优先取行情源真实值, 回退 prev_close*1.1。硬编码对 20%(创业板/
     科创板) 与 5%(ST) 涨跌幅标的全错。
  ④ scoring.gap_weight(None) 返回 0.0 (原抛 TypeError → 竞价面板整块崩)。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'scripts', 'daily'))

import sell_engine as se  # noqa: E402
from scoring import gap_weight  # noqa: E402


def _klines(prev_close=10.0, yest_pct=10.0):
    """两日K线: 末日=昨日(涨停), 前一日=再前一日。

    注: 末条日期刻意不等于今天 —— sell_engine 会把它当作 yesterday。
    """
    yest_close = round(prev_close * 1.1, 2)
    return [
        {'date': '2026-09-14', 'open': prev_close, 'high': prev_close,
         'low': prev_close, 'close': prev_close, 'volume': 1_000_000, 'pct_change': 0.0},
        {'date': '2026-09-15', 'open': prev_close, 'high': yest_close,
         'low': prev_close, 'close': yest_close, 'volume': 2_000_000, 'pct_change': yest_pct},
    ]


@pytest.fixture
def patch_klines(monkeypatch):
    """把 _load_klines 打桩为构造数据 (不触碰真实 data/kline_data)"""
    def _apply(klines):
        monkeypatch.setattr(se, '_load_klines', lambda code, name=None: klines)
        return klines
    return _apply


def _pos(buy_price, buy_date='2026-09-10'):
    """buy_date 取非"昨天", 避开「昨买入+昨炸板」缓冲例外"""
    return {'code': '000001', 'name': '测试股', 'buy_date': buy_date,
            'buy_price': buy_price, 'shares': 100}


def _cfg(a_style):
    """取当前 sell 配置并显式设置 sell_a_style.enabled。

    2026-09-17: 用户指令"严格按照A的卖出资料中写的来" → 主配置已把 A式
    (sell_a_style.enabled) 置 false, 决策树恢复。故 A式相关用例必须**显式传
    enabled=True**, 锁定的才是「A式代码路径」本身, 不受主开关影响。
    """
    cfg = dict(se._load_sell_config())
    cfg['sell_a_style'] = dict(cfg.get('sell_a_style') or {}, enabled=a_style)
    return cfg


# ── ① 硬止损 kind 标识 (Top1 覆盖放行的依据) ──

def test_hard_stop_carries_kind_marker(patch_klines):
    patch_klines(_klines(prev_close=10.0))          # 昨收 11.0
    # 成本 12.0 / 竞价 10.0 → 浮亏 -16.7% ≤ -10%
    sig = se.sell_signal(_pos(12.0), {'open': 10.0, 'prev_close': 11.0, 'gap_pct': -9.09,
                                      'current_price': 10.0, 'limit_up_price': 12.1})
    assert sig['action'] == 'sell'
    assert sig['urgency'] == 'urgent'
    assert sig['kind'] == 'hard_stop', '硬止损必须带 kind 标识, 否则会被 Top1 覆盖规则吞掉'
    assert '硬止损' in sig['reason']


def test_non_stop_signal_has_no_hard_stop_kind(patch_klines):
    """浮亏未达 -10% 时不得误标 hard_stop (否则 Top1 覆盖规则会被无谓放行)"""
    patch_klines(_klines(prev_close=10.0))
    sig = se.sell_signal(_pos(11.0), {'open': 11.22, 'prev_close': 11.0, 'gap_pct': 2.0,
                                      'current_price': 11.22, 'limit_up_price': 12.1})
    assert sig.get('kind') != 'hard_stop'


# ── ② A式: 信号标识 + 执行价 = 挂单涨停价 ──

def test_a_style_signal_uses_limit_up_as_execution_price(patch_klines):
    patch_klines(_klines(prev_close=10.0))          # 昨收 11.0
    ta = {'open': 11.22, 'prev_close': 11.0, 'gap_pct': 2.0,
          'current_price': 11.22, 'limit_up_price': 12.1}
    sig = se.sell_signal(_pos(10.0), ta, config=_cfg(True))
    assert sig['kind'] == 'a_style'

    exec_info = se.sell_execution_price(
        sig, {'open': 11.22, 'high': 0, 'close': 11.22,
              'prev_close': 11.0, 'limit_up_price': 12.1}, _pos(10.0))
    assert exec_info['price'] == 12.1, 'A式执行价必须是挂单涨停价'
    assert exec_info['price'] != 11.22, '不得退化成"执行价=开盘价"(被回测否定的口径)'
    assert '涨停价' in exec_info['note']


def test_execution_price_falls_back_when_no_limit_up(patch_klines):
    """行情源无涨停价时, A式执行价仍走 V3.2 公式(不崩, 不返回 0)"""
    patch_klines(_klines(prev_close=10.0))
    ta = {'open': 11.22, 'prev_close': 11.0, 'gap_pct': 2.0, 'current_price': 11.22}
    sig = se.sell_signal(_pos(10.0), ta)
    exec_info = se.sell_execution_price(
        sig, {'open': 11.22, 'high': 0, 'close': 11.22, 'prev_close': 11.0}, _pos(10.0))
    assert exec_info['price'] > 0


# ── ③ 涨停价优先用行情源值 (20%/5% 标的) ──

def test_limit_up_price_prefers_quote_over_hardcoded(patch_klines):
    """20% 标的: 昨收 11.0 的真实涨停价是 13.2, 硬编码 prev_close*1.1 会算成 12.1"""
    patch_klines(_klines(prev_close=10.0))
    ta = {'open': 11.5, 'prev_close': 11.0, 'gap_pct': 4.5,
          'current_price': 11.5, 'limit_up_price': 13.2}
    sig = se.sell_signal(_pos(10.0), ta, config=_cfg(True))
    assert '13.2' in sig['reason'], f'应使用行情源涨停价 13.2, 实际: {sig["reason"]}'
    assert '12.1' not in sig['reason'], '不得回退到硬编码的 11.0*1.1=12.1'


def test_a_style_disabled_uses_decision_tree(patch_klines):
    """A式关闭时走资料决策树, 不再一律挂涨停价 (2026-09-17 用户指令后的生产配置)。

    同一输入在 A式开启时返回 a_style 信号; 关闭后应落入决策树分支。
    """
    patch_klines(_klines(prev_close=10.0))
    ta = {'open': 11.22, 'prev_close': 11.0, 'gap_pct': 2.0,
          'current_price': 11.22, 'limit_up_price': 12.1}
    sig = se.sell_signal(_pos(10.0), ta, config=_cfg(False))
    assert sig.get('kind') != 'a_style', 'A式关闭后不得再返回 a_style 信号'
    assert sig['action'] in ('sell', 'sell_half', 'hold', 'watch')


# ── ④ gap_weight 空值防御 ──

@pytest.mark.parametrize('bad', [None, 'abc', True, False, float('nan'), [], {}])
def test_gap_weight_invalid_input_returns_zero(bad):
    assert gap_weight(bad) == 0.0, f'gap_weight({bad!r}) 不得抛异常'


def test_gap_weight_valid_input_unchanged():
    """正常输入行为不变 (现行硬边界 4-8%)"""
    assert gap_weight(4.0) == 1.0
    assert gap_weight(6.0) == 1.0
    assert gap_weight(8.0) == 1.0
    assert gap_weight(3.9) == 0.0
    assert gap_weight(8.1) == 0.0
