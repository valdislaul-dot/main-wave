"""📉 断板去留分层 — 连板持仓辅助 (2026-09-19)
==============================================
场景: 持仓股昨日断板(连板段结束), 今日竞价决定去留 —— 历史同类走成什么样?

依据: logs/analysis/yaogu_theory_verification_2026-09-19.md §8/§9
  全样本 3-4板 n=3369 / 5板+ n=987; 训练段(2016-2022)与检验段(2023-2026)同向,
  幅度打6-7折 → 只用方向性倾斜, 数字取检验段并视为上限, 展示时须标样本量。

分板级分支表(检验段 2023-2026, d1 = 断板日收盘 → 次日收盘):
  通用最强因子 = 次日竞价 gap 三档 (跨板级一致, 跨期完全稳定)
  5板+专属    = 断板日深水低开(<=-5%)拉回收阳 (3-4板不成立, 反而是坏消息)

纪律: 只读本地 data/kline_data/; 本层是背景概率层, 不替代 sell_engine 决策树
(三层分工: V3管选股 / sell_engine管常规卖出 / 本层管连板断板期的去留背景)。
"""
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
CONFIG_PATH = os.path.join(BASE, 'data', 'scoring_config.json')

# 缺省=2026-09-19研究报告 §8/§9 检验段数字; 生产配置在 scoring_config.json break_layer 段
DEFAULTS = {
    'enabled': True,
    'min_streak': 3,        # 触发门槛: 断板前连板数 >= 3
    'deep_gap': -5.0,       # 断板日深水判定 (开盘 gap <= -5%)
    'gap_high': 0.0,        # 今日竞价 gap 三档边界
    'gap_low': -3.0,
    'recover_min_streak': 5,  # 深水拉回收阳"强承接"仅 >=5板成立
    'baseline': {
        '34': {'d1': -3.83, 'up': 36, 'n': 3369},
        '5p': {'d1': -4.31, 'up': 35, 'n': 987},
    },
    'stats': {
        '34': {
            'high': {'d1': 3.29, 'up': 66, 'fb': 29, 'n': 359},
            'mid': {'d1': -2.39, 'up': 40, 'fb': 16, 'n': 378},
            'low': {'d1': -8.02, 'up': 19, 'fb': 8, 'n': 859},
            'deep_recover': {'d1': -5.69, 'up': 32, 'fb': 15, 'n': 65},
            'deep_fail': {'d1': -6.96, 'up': 20, 'fb': 5, 'n': 146},
        },
        '5p': {
            'high': {'d1': 3.05, 'up': 63, 'fb': 26, 'n': 105},
            'mid': {'d1': 0.14, 'up': 51, 'fb': 23, 'n': 79},
            'low': {'d1': -9.96, 'up': 18, 'fb': 9, 'n': 308},
            'deep_recover': {'d1': 3.16, 'up': 64, 'fb': 16, 'n': 25},
            'deep_fail': {'d1': -9.84, 'up': 19, 'fb': 6, 'n': 95},
        },
    },
}

NOTES = {
    'high': '偏强档: 历史同类多数收涨; 待盘中弱转强确认(拉升/封板), 破分时均线再走',
    'mid': '中性档: 无方向优势; 等盘中确认, 破前低/分时均线走',
    'low': '偏弱档: 历史同类约八成下跌; 竞价离场或反抽即走',
}


def load_config():
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            seg = json.load(f).get('break_layer')
        if isinstance(seg, dict):
            cfg.update({k: v for k, v in seg.items() if not k.startswith('_')})
    except Exception:
        pass
    return cfg


def _is_lu(close, prev_close, cyb):
    if not prev_close or close is None:
        return False
    limit = round(prev_close * (1.2 if cyb else 1.1), 2)
    return close >= limit - 0.005


def load_klines(name, code):
    """双路径读取本地K线 (与 morning_check 同口径); 无则 None"""
    for fn in (f'{name}_{code}.json', f'{code}.json'):
        p = os.path.join(KLINE_DIR, fn)
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                kl = raw.get('data', raw) if isinstance(raw, dict) else raw
                if isinstance(kl, list) and len(kl) >= 10:
                    return kl
            except Exception:
                continue
    return None


def detect_break_state(code, klines):
    """最后交易日为断板日(其前一日涨停)时返回断板日特征, 否则 None"""
    n = len(klines) if klines else 0
    if n < 10:
        return None
    cyb = code.startswith(('30', '68'))
    last, prev, prev2 = klines[-1], klines[-2], klines[-3]
    lc, pc = last.get('close'), prev.get('close')
    if _is_lu(lc, pc, cyb):
        return None                      # 昨日仍涨停 → 连板中, 非断板
    if not _is_lu(pc, prev2.get('close'), cyb):
        return None                      # 前日也非涨停 → 断板日不是昨天, d1窗口已过
    streak = 1                           # klines[-2] 这一板
    j = n - 3
    while j >= 1 and _is_lu(klines[j].get('close'), klines[j - 1].get('close'), cyb):
        streak += 1
        j -= 1
    b_open = last.get('open')
    if not pc or b_open is None:
        return None
    return {
        'date': last.get('date', '?'),
        'streak': streak,
        'gap': round((b_open - pc) / pc * 100, 2),
        'brk_pct': round((lc - pc) / pc * 100, 2) if lc is not None else None,
        'recover': (lc or 0) > (b_open or 0),
    }


def break_layer_context(code, name=None, gap_pct=None, klines=None, config=None):
    """主入口: 持仓昨断板 且 连板数达门槛 → 返回分层背景 dict; 否则 None

    gap_pct: 今日竞价 gap (morning_check 已算好)
    """
    cfg = config or load_config()
    if not cfg.get('enabled', True) or gap_pct is None:
        return None
    if klines is None:
        klines = load_klines(name or '', code)
    st = detect_break_state(code, klines)
    if not st or st['streak'] < cfg['min_streak']:
        return None
    tier = '34' if st['streak'] <= 4 else '5p'
    band = ('high' if gap_pct >= cfg['gap_high']
            else 'mid' if gap_pct >= cfg['gap_low'] else 'low')
    stat = cfg['stats'][tier][band]
    special = None
    if st['gap'] <= cfg['deep_gap'] and st['recover']:
        dr = cfg['stats'][tier]['deep_recover']
        special = {
            'valid': st['streak'] >= cfg['recover_min_streak'],
            'd1': dr['d1'], 'up': dr['up'], 'n': dr['n'],
            'fail': {k: cfg['stats'][tier]['deep_fail'][k] for k in ('d1', 'up', 'n')},
        }
    return {
        'code': code, 'name': name or code,
        'streak': st['streak'], 'tier': tier, 'break_date': st['date'],
        'break_gap': st['gap'], 'break_pct': st['brk_pct'], 'recover': st['recover'],
        'deep': st['gap'] <= cfg['deep_gap'],
        'gap_pct': gap_pct, 'band': band,
        'stat': dict(stat), 'baseline': dict(cfg['baseline'][tier]),
        'note': NOTES[band], 'special': special,
    }
