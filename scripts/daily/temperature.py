"""温度开关纯函数模块 (2026-09-04用户拍板新分档, 替代09-03四档)
档位决策与IO剥离, 供morning_check调用 + 离线单测/历史回放
分档(涨停数, 每10只一档, 仓位从40%起步):
  <40: 空仓(极弱, 升温日例外半仓) | 40-49: 40% | 50-59: 50% | ... | 90-99: 90% | ≥100: 100%(强势)
  极弱附加条件(09-03拍板保留): 最高板≤2 → 空仓
降档(任一条触发降一档=减10%仓位, 只降一次, 下限空仓):
  a. 骤降防线: 涨停数降≥30% 或 最高板降≥2级
  b. 竞价二次确认: 池均gap ≤ -0.5%
  c. 赚钱效应转负: <0 (原<-2.0, 2026-09-03收紧)
数据背景(2026-09-04检验, 用户已知晓仍拍板此方案): 298天重建序列上涨停数分档
对次日赚效区分度弱, 极弱档次日赚效最高(+1.89%)存在冰点反抽; 本分档为用户裁决口径。
"""

# 阈值常量 (2026-09-04用户拍板: 40以下空仓, 每10一档, 仓位从40%开始)
ZT_WEAK = 40          # 极弱线: 涨停<40 → 空仓
ZT_STRONG = 100       # 强势线: 涨停≥100 → 全仓
COLLAPSE_RATIO = 0.7  # 骤降防线: 涨停数 ≤ 前日×0.7 (降≥30%)
COLLAPSE_CONS = 2     # 骤降防线: 最高板较前日降≥2级
GAP_CONFIRM = -0.5    # 竞价二次确认: 池均gap ≤ -0.5% → 降档
WARMING_HALF = 0.5    # 极弱+升温日例外: 半仓
POS_STEP = 0.1        # 每档仓位步长10%


def base_position(zt_n):
    """基础仓位: zt_n//10×10% 封顶100%; <40空仓"""
    if zt_n < ZT_WEAK:
        return 0.0
    return round(min(1.0, (zt_n // 10) * POS_STEP), 2)


# 档位开关文案
def _switch_txt(pos):
    if pos <= 0:
        return '🛑 买入开关: 关闭(空仓)'
    if pos >= 1.0:
        return '🟢 买入开关: 全仓'
    label = {0.4: '四成', 0.5: '半仓', 0.6: '六成', 0.7: '七成', 0.8: '八成', 0.9: '九成'}
    return f'🟢 买入开关: {label.get(pos, f"{int(pos*100)}%")}仓'


# 合法仓位阶梯 (2026-09-04拍板: 40%起步每档+10%), 降档沿此下移一级, 40%降档→空仓
LADDER = (1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.0)


def _ladder_down(pos_pct):
    """沿 LADDER 降一档, 已是地板则原地不动"""
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

    # ① 基础档 (2026-09-04新分档)
    if zt_n < ZT_WEAK or max_cons <= 2:   # 极弱(09-03附加条件保留): 涨停<40 或 最高板≤2
        if warming:
            env, pos = '🌡️ 极弱', WARMING_HALF
            switch = '🟡 买入开关: 半仓(升温日例外)'
        else:
            env, pos = '🌡️ 极弱', 0.0
            switch = _switch_txt(0.0)
    else:
        pos = base_position(zt_n)
        env = '🌡️ 强势' if pos >= 1.0 else '🌡️ 弱市'
        switch = _switch_txt(pos)

    # ② 降档规则 (仓位>0才评估; 任一条触发降一档, 只降一次)
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
        if pos <= 0.0:
            switch = f'🛑 买入开关: 关闭(空仓, {reason}降档)'
        else:
            switch = f'{_switch_txt(pos)}({reason}降档)'

    return {'env': env, 'switch': switch, 'pos_pct': pos,
            'warming': warming, 'collapse': collapse,
            'downgraded': downgraded, 'downgrade_reason': reason}
