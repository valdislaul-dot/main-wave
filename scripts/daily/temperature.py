"""温度展示模块 (2026-09-07 A式拍板: 温度只展示不做仓位)
仓位恒定55%(A同款, 一年回测+3877%/均笔+5.44%), 风控交个股层(gap窗口+质量过滤+卖出引擎)。
温度评级+三条警示保留为展示信息, 不再改变仓位:
  评级: 极弱(<40或最高≤2板) / 弱市(40-99) / 强势(≥100)
  警示(仅展示): 骤降防线(降≥30%或最高板降≥2级) | 竞价二次确认(池均gap≤-0.5%) | 赚效转负(<0)
历史(2026-09-07前): 温度四档仓位(2026-09-04拍板)已废弃 — 数据裁决:
  logs/analysis/temperature_switch_review_2026-09-07.md — 温度四档均仓63%择时为负贡献
  (同仓位水平恒定65% +7172% > 温度四档 +5072%); A实盘极弱档最赚/90+档全亏; 竞价gap无市场区分度。
"""

# 阈值常量 (展示评级/警示用, 2026-09-04原拍板保留为评级线)
ZT_WEAK = 40          # 极弱线: 涨停<40 → 极弱评级
ZT_STRONG = 100       # 强势线: 涨停≥100 → 强势评级
COLLAPSE_RATIO = 0.7  # 骤降警示: 涨停数 ≤ 前日×0.7 (降≥30%)
COLLAPSE_CONS = 2     # 骤降警示: 最高板较前日降≥2级
GAP_CONFIRM = -0.5    # 竞价二次确认警示: 池均gap ≤ -0.5%

# A式恒定仓位 (2026-09-07用户拍板, A同款55%滚动)
FIXED_POS = 0.55


def decide_temp_switch(zt_n, max_cons, zt_prev=None, max_cons_prev=None,
                       avg_gap=None, money_effect=None):
    """温度评级+警示 (纯函数, 无IO; 2026-09-07起只展示不控仓)
    zt_n/max_cons: T-1涨停池只数/最高板 | zt_prev/max_cons_prev: T-2
    avg_gap: 竞价池均gap | money_effect: 盘后赚钱效应
    返回 {env, switch, pos_pct, warming, collapse, downgraded, downgrade_reason}
    pos_pct恒为FIXED_POS(0.55); downgraded=True表示警示触发(仅展示, 不降仓)"""
    warming = zt_prev is not None and zt_n > zt_prev

    # ① 评级 (展示)
    if zt_n < ZT_WEAK or max_cons <= 2:   # 极弱: 涨停<40 或 最高板≤2
        env = '🌡️ 极弱(升温)' if warming else '🌡️ 极弱'
    else:
        env = '🌡️ 强势' if zt_n >= ZT_STRONG else '🌡️ 弱市'

    # ② 警示 (仅展示, 不降仓; 2026-09-07 A式)
    collapse_parts = []
    if zt_prev is not None and zt_n <= zt_prev * COLLAPSE_RATIO:
        collapse_parts.append(f'{zt_prev}→{zt_n}只')
    if max_cons_prev is not None and max_cons <= max_cons_prev - COLLAPSE_CONS:
        collapse_parts.append(f'{max_cons_prev}→{max_cons}板')
    collapse = bool(collapse_parts)

    reason = None
    if collapse:
        reason = '骤降防线(' + '/'.join(collapse_parts) + ')'
    elif avg_gap is not None and avg_gap <= GAP_CONFIRM:
        reason = f'竞价二次确认(池均gap{avg_gap:+.1f}%)'
    elif money_effect is not None and money_effect < 0:
        reason = f'赚钱效应转负({money_effect:+.1f}%)'

    if reason:
        env += '⚠'

    switch = '🟢 买入开关: 恒定55%仓位'

    return {'env': env, 'switch': switch, 'pos_pct': FIXED_POS,
            'warming': warming, 'collapse': collapse,
            'downgraded': bool(reason), 'downgrade_reason': reason}
