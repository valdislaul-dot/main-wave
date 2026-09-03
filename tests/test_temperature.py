"""温度开关纯函数测试 (2026-09-03定稿)
四档基础档 + 三条降档规则(骤降防线/竞价确认/赚效转负), 任一条触发降一档只降一次。
纯函数无IO, 符合套件断网约束。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'scripts', 'daily'))
from temperature import decide_temp_switch  # noqa: E402


def _base(zt_n, max_cons, **kw):
    """构造默认参数: T-2数据缺失(骤降/升温惰性), 无gap/赚效信号, 便于单变量控制"""
    args = dict(zt_prev=None, max_cons_prev=None, avg_gap=1.0, money_effect=0.5)
    args.update(kw)
    return decide_temp_switch(zt_n, max_cons, **args)


# ── ① 基础档边界 ──

def test_tier_extreme_weak():
    d = _base(39, 3)
    assert d['pos_pct'] == 0.0
    assert d['switch'].startswith('🛑')


def test_tier_extreme_weak_by_max_cons():
    # 涨停≥40但最高板≤2 → 仍极弱
    d = _base(50, 2)
    assert d['pos_pct'] == 0.0
    assert d['env'] == '🌡️ 极弱'


def test_tier_weak_low_boundary():
    d = _base(40, 3)
    assert d['pos_pct'] == 0.33
    assert '1/3仓' in d['switch']


def test_tier_weak_low_upper():
    d = _base(64, 3)
    assert d['pos_pct'] == 0.33


def test_tier_weak_boundary():
    d = _base(65, 3)
    assert d['pos_pct'] == 0.5
    assert '半仓' in d['switch'] and '1/3' not in d['switch']


def test_tier_weak_upper():
    d = _base(109, 3)
    assert d['pos_pct'] == 0.5


def test_tier_strong():
    d = _base(110, 3)
    assert d['pos_pct'] == 1.0
    assert '全仓' in d['switch']


def test_tier_strong_boundary_below():
    d = _base(109, 3)
    assert d['pos_pct'] == 0.5


# ── ② 升温日例外 ──

def test_warming_exception():
    d = _base(35, 3, zt_prev=30)
    assert d['warming'] is True
    assert d['pos_pct'] == 0.5
    assert '升温日例外' in d['switch']


def test_no_warming_stays_closed():
    d = _base(35, 3, zt_prev=40)
    assert d['pos_pct'] == 0.0


# ── ③ 骤降防线: 两条腿 ──

def test_collapse_count_leg():
    # 76→49 = -36% ≥ 30%
    d = decide_temp_switch(49, 4, zt_prev=76, max_cons_prev=7, avg_gap=1.3, money_effect=0.5)
    assert d['collapse'] is True
    assert d['downgraded'] is True
    assert d['downgrade_reason'].startswith('骤降防线')
    assert d['pos_pct'] == 0.0  # 下沿1/3 → 空仓
    assert '关闭(空仓' in d['switch']


def test_collapse_cons_leg():
    # 涨停数不降但最高板7→4(降3级≥2)
    d = decide_temp_switch(75, 4, zt_prev=76, max_cons_prev=7, avg_gap=1.3, money_effect=0.5)
    assert d['collapse'] is True
    assert d['downgraded'] is True
    assert d['pos_pct'] == 0.33  # 半仓 → 1/3仓
    assert '1/3仓' in d['switch']


def test_collapse_not_triggered_small_drop():
    # -5%不触发
    d = _base(95, 4, zt_prev=100, max_cons_prev=5)
    assert d['collapse'] is False
    assert d['downgraded'] is False
    assert d['pos_pct'] == 0.5


def test_collapse_boundary_30pct():
    # 恰好-30%: 70 ≤ 100×0.7 → 触发
    d = _base(70, 5, zt_prev=100, max_cons_prev=5)
    assert d['collapse'] is True


def test_collapse_missing_prev():
    d = decide_temp_switch(49, 4, zt_prev=None, max_cons_prev=None, avg_gap=1.0, money_effect=0.5)
    assert d['collapse'] is False
    assert d['downgraded'] is False


# ── ④ 竞价二次确认 / 赚钱效应转负 ──

def test_gap_confirm_triggers():
    d = _base(80, 5, avg_gap=-0.6)
    assert d['downgraded'] is True
    assert d['downgrade_reason'].startswith('竞价二次确认')
    assert d['pos_pct'] == 0.33


def test_gap_confirm_not_triggered():
    d = _base(80, 5, avg_gap=-0.4)
    assert d['downgraded'] is False


def test_me_negative_triggers():
    d = _base(80, 5, money_effect=-0.1)
    assert d['downgraded'] is True
    assert d['downgrade_reason'].startswith('赚钱效应转负')
    assert d['pos_pct'] == 0.33


def test_me_zero_not_triggered():
    # 严格<0: 0.0不触发
    d = _base(80, 5, money_effect=0.0)
    assert d['downgraded'] is False


# ── ⑤ 叠加: 只降一档 ──

def test_multi_trigger_only_one_downgrade():
    # 半仓 + 骤降 + 赚效双触发 → 只降一级到1/3仓
    d = decide_temp_switch(70, 5, zt_prev=100, max_cons_prev=5, avg_gap=-0.6, money_effect=-0.5)
    assert d['downgraded'] is True
    assert d['pos_pct'] == 0.33
    assert d['downgrade_reason'].startswith('骤降防线')  # 优先骤降


def test_floor_empty_stays_empty():
    d = _base(30, 3, zt_prev=50, max_cons_prev=5, avg_gap=-0.6, money_effect=-1.0)
    assert d['pos_pct'] == 0.0
    assert d['downgraded'] is False  # 已空仓不再降


def test_strong_downgrades_to_half():
    d = _base(120, 6, avg_gap=-0.6)
    assert d['pos_pct'] == 0.5


# ── ⑥ 真实回放 ──

def test_replay_20260903():
    # 09-03早晨: 49只/4板 vs 前日76/7板, 池gap+1.3%, 赚效-0.67%
    d = decide_temp_switch(49, 4, zt_prev=76, max_cons_prev=7, avg_gap=1.3, money_effect=-0.67)
    assert d['pos_pct'] == 0.0
    assert '骤降防线' in d['switch'] or d['downgrade_reason'].startswith('骤降防线')


def test_replay_20260902():
    # 09-02早晨: 76只/7板 vs 前日78/6板, 池gap+1.4%, 赚效+1.2% → 半仓不降
    d = decide_temp_switch(76, 7, zt_prev=78, max_cons_prev=6, avg_gap=1.4, money_effect=1.2)
    assert d['pos_pct'] == 0.5
    assert d['downgraded'] is False
