"""温度展示模块测试 (2026-09-07 A式拍板: 温度只展示不做仓位)
评级: 极弱(<40或最高≤2板) / 弱市(40-99) / 强势(≥100); 升温标记
警示(仅展示, 不降仓): 骤降防线(降≥30%或最高板降≥2级)/竞价二次确认(gap≤-0.5%)/赚效转负(<0)
仓位: pos_pct恒0.55(A式恒定55%), switch恒'🟢 买入开关: 恒定55%仓位'
纯函数无IO, 符合套件断网约束。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'scripts', 'daily'))
from temperature import decide_temp_switch, FIXED_POS  # noqa: E402


def _base(zt_n, max_cons, **kw):
    """构造默认参数: T-2数据缺失(骤降/升温惰性), 无gap/赚效信号, 便于单变量控制"""
    args = dict(zt_prev=None, max_cons_prev=None, avg_gap=1.0, money_effect=0.5)
    args.update(kw)
    return decide_temp_switch(zt_n, max_cons, **args)


# ── ① 评级边界 (仅展示) ──

def test_env_extreme_weak():
    d = _base(39, 3)
    assert d['env'] == '🌡️ 极弱'


def test_env_extreme_weak_by_max_cons():
    # 涨停≥40但最高板≤2 → 仍极弱
    d = _base(50, 2)
    assert d['env'] == '🌡️ 极弱'


def test_env_weak_middle():
    d = _base(50, 3)
    assert d['env'] == '🌡️ 弱市'


def test_env_weak_upper():
    d = _base(99, 3)
    assert d['env'] == '🌡️ 弱市'


def test_env_strong():
    d = _base(100, 3)
    assert d['env'] == '🌡️ 强势'


def test_env_strong_above():
    d = _base(130, 8)
    assert d['env'] == '🌡️ 强势'


def test_env_warming_flag():
    d = _base(39, 3, zt_prev=30, max_cons_prev=3)
    assert d['warming'] is True
    assert d['env'] == '🌡️ 极弱(升温)'


def test_env_not_warming():
    d = _base(39, 3, zt_prev=50, max_cons_prev=3)
    assert d['warming'] is False
    assert d['env'] == '🌡️ 极弱'


# ── ② 警示 (仅展示, 不降仓) ──

def test_warn_collapse_count():
    # 骤降: 涨停数降≥30%
    d = _base(50, 5, zt_prev=80, max_cons_prev=5)
    assert d['collapse'] is True
    assert d['downgraded'] is True
    assert '骤降防线' in d['downgrade_reason']
    assert '⚠' in d['env']


def test_warn_collapse_not_triggered():
    d = _base(60, 5, zt_prev=80, max_cons_prev=5)
    assert d['collapse'] is False
    assert d['downgraded'] is False


def test_warn_collapse_max_cons():
    # 骤降: 最高板降≥2级
    d = _base(50, 3, zt_prev=45, max_cons_prev=5)
    assert d['collapse'] is True
    assert '5→3板' in d['downgrade_reason']


def test_warn_gap_confirm():
    d = _base(50, 3, avg_gap=-0.8)
    assert d['downgraded'] is True
    assert '竞价二次确认' in d['downgrade_reason']
    assert '⚠' in d['env']


def test_warn_gap_ok():
    d = _base(50, 3, avg_gap=0.5)
    assert d['downgraded'] is False


def test_warn_money_effect_negative():
    d = _base(50, 3, money_effect=-0.3)
    assert d['downgraded'] is True
    assert '赚钱效应转负' in d['downgrade_reason']
    assert '⚠' in d['env']


def test_warn_priority_collapse_first():
    # 多条同时触发 → 骤降优先展示(只显示一条)
    d = _base(50, 3, zt_prev=80, max_cons_prev=5, avg_gap=-1.0, money_effect=-0.5)
    assert d['downgrade_reason'].startswith('骤降防线')


# ── ③ A式恒定仓位 (2026-09-07) ──

def test_pos_fixed_all_tiers():
    # 任意温度输入, 仓位恒为FIXED_POS
    for zt_n, mc in [(30, 1), (39, 3), (40, 3), (55, 4), (86, 6), (100, 5), (150, 9)]:
        d = _base(zt_n, mc)
        assert d['pos_pct'] == FIXED_POS, f'{zt_n}/{mc} → {d["pos_pct"]}'


def test_switch_fixed_text():
    d = _base(86, 6)
    assert d['switch'] == '🟢 买入开关: 恒定55%仓位'


def test_switch_fixed_even_on_warning():
    # 警示触发也不改变仓位/开关文案
    d = _base(50, 3, zt_prev=80, max_cons_prev=5)
    assert d['pos_pct'] == FIXED_POS
    assert d['switch'] == '🟢 买入开关: 恒定55%仓位'


def test_fixed_pos_constant():
    assert FIXED_POS == 0.55
