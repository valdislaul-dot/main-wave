"""温度开关纯函数模块 (2026-09-03用户拍板)
档位决策与IO剥离, 供morning_check调用 + 离线单测/历史回放
四档: 极弱(空仓, 升温例外半仓) | 弱市下沿40-64(1/3仓) | 弱市65-109(半仓) | 强市≥110(全仓)
降档(任一条触发降一档, 只降一次, 下限空仓):
  a. 骤降防线: 涨停数降≥30% 或 最高板降≥2级
  b. 竞价二次确认: 池均gap ≤ -0.5%
  c. 赚钱效应转负: <0 (原<-2.0, 2026-09-03收紧)
"""

# 阈值常量 (2026-09-03用户拍板)
ZT_WEAK = 40          # 极弱线: 涨停<40 或 最高≤2板 → 空仓
ZT_SUB = 65           # 弱市细分线: 40≤涨停<65 → 1/3仓, 65≤涨停<110 → 半仓
ZT_STRONG = 110       # 强市线: 涨停≥110 → 全仓
COLLAPSE_RATIO = 0.7  # 骤降防线: 涨停数 ≤ 前日×0.7 (降≥30%)
COLLAPSE_CONS = 2     # 骤降防线: 最高板较前日降≥2级
GAP_CONFIRM = -0.5    # 竞价二次确认: 池均gap ≤ -0.5% → 降档

# 仓位阶梯: 全仓→半仓→1/3→空仓, 降档沿此下移一级
LADDER = (1.0, 0.5, 0.33, 0.0)

# 档位开关文案(降档时按新仓位重建, 避免"1/3仓(降档)"误导)
_SWITCH_TXT = {
    1.0: '🟢 买入开关: 全仓',
    0.5: '🟢 买入开关: 半仓',
    0.33: '🟡 买入开关: 1/3仓',
    0.0: '🛑 买入开关: 关闭(空仓)',
}


def _ladder_down(pos_pct):
    """pos_pct 沿 LADDER 降一级, 已是地板则原地不动"""
    if pos_pct <= 0:
        return 0.0
    for i, p in enumerate(LADDER):
        if abs(p - pos_pct) < 1e-9:
            return LADDER[i + 1] if i + 1 < len(LADDER) else 0.0
    return 0.0


def decide_temp_switch(zt_n, max_cons, zt_prev=None, max_cons_prev=None,
                       avg_gap=None, money_effect=None):
    """计算温度档位+买入开关 (纯函数, 无IO)
    zt_n/max_cons: T-1涨停池只数/最高板 | zt_prev/max_cons_prev: T-2
    avg_gap: 竞价池均gap | money_effect: 盘后赚钱效应
    返回 {env, switch, pos_pct, warming, collapse, downgraded, downgrade_reason}"""
    warming = zt_prev is not None and zt_n > zt_prev

    # ① 基础档 (2026-09-03定稿)
    if zt_n < ZT_WEAK or max_cons <= 2:
        if warming:
            env, pos = '🌡️ 极弱', 0.5
            switch = '🟡 买入开关: 半仓(升温日例外)'
        else:
            env, pos = '🌡️ 极弱', 0.0
            switch = _SWITCH_TXT[0.0]
    elif zt_n >= ZT_STRONG:
        env, pos = '🌡️ 强势', 1.0
        switch = _SWITCH_TXT[1.0]
    elif zt_n < ZT_SUB:
        env, pos = '🌡️ 弱市(下沿)', 0.33
        switch = _SWITCH_TXT[0.33]
    else:
        env, pos = '🌡️ 弱市', 0.5
        switch = _SWITCH_TXT[0.5]

    # ② 降档规则 (仓位>0才评估; 任一条触发降一级, 只降一次)
    collapse_parts = []
    if zt_prev is not None and zt_n <= zt_prev * COLLAPSE_RATIO:
        collapse_parts.append(f'{zt_prev}→{zt_n}只')
    if max_cons_prev is not None and max_cons <= max_cons_prev - COLLAPSE_CONS:
        collapse_parts.append(f'{max_cons_prev}→{max_cons}板')
    collapse = bool(collapse_parts)

    reason = None
    if pos > 0:
        if collapse:
            reason = '骤降防线(' + '/'.join(collapse_parts) + ')'
        elif avg_gap is not None and avg_gap <= GAP_CONFIRM:
            reason = f'竞价二次确认(池均gap{avg_gap:+.1f}%)'
        elif money_effect is not None and money_effect < 0:
            reason = f'赚钱效应转负({money_effect:+.1f}%)'

    downgraded = False
    if reason:
        pos = _ladder_down(pos)
        downgraded = True
        env += '↓'
        if pos == 0.0:
            switch = f'🛑 买入开关: 关闭(空仓, {reason}降档)'
        else:
            switch = f'{_SWITCH_TXT[pos]}({reason}降档)'

    return {'env': env, 'switch': switch, 'pos_pct': pos,
            'warming': warming, 'collapse': collapse,
            'downgraded': downgraded, 'downgrade_reason': reason}
