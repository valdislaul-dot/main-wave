"""
评分模块 — v2.2陡峭 + v3平滑，配置驱动
单点维护，screen_candidates/morning_check/backtest 统一引用
"""
import json, os
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) \
       if '__file__' in dir() else os.getcwd()
CONFIG_PATH = os.path.join(BASE, 'data', 'scoring_config.json')


# ============================================================
# 基础工具
# ============================================================

def get_lp(code):
    return 0.20 if (code.startswith('30') or code.startswith('688')) else 0.10


def is_limit_up(close, prev_close, lpct):
    if prev_close is None or prev_close <= 0:
        return False
    # 正常涨停: close >= 昨收*(1+涨跌幅)
    if close >= round(prev_close * (1 + lpct), 2) - 0.005:
        return True
    # 连续一字板: close ≈ prev_close (涨停价未变)
    if abs(close - prev_close) < 0.01:
        return True
    return False


def piecewise_linear(x, anchors):
    """anchors: [(x0,y0), (x1,y1), ...] 升序, 线性插值, 两端截断"""
    if not anchors:
        return 0
    if x <= anchors[0][0]:
        return anchors[0][1]
    if x >= anchors[-1][0]:
        return anchors[-1][1]
    for i in range(len(anchors) - 1):
        x0, y0 = anchors[i]
        x1, y1 = anchors[i + 1]
        if x0 <= x <= x1:
            t = (x - x0) / (x1 - x0)
            return round(y0 + t * (y1 - y0), 2)
    return anchors[-1][1]


def step_score_asc(x, tiers):
    """升序tiers: x < threshold → value (如量比: <0.3→37, <0.5→19...)"""
    for thresh, val in tiers:
        if x < thresh:
            return val
    return tiers[-1][1] if tiers else 0


def step_score_desc(x, tiers):
    """降序tiers: x >= threshold → value (如Gap: >=9→20, >=7→6...)"""
    for thresh, val in tiers:
        if x >= thresh:
            return val
    return tiers[-1][1] if tiers else 0


# ============================================================
# 配置加载
# ============================================================

def default_scoring_config():
    """默认配置: v2(当前陡峭) + v3(平滑)"""
    return {
        "version": "3.1",
        "active": "v3",
        "tables": {
            "v2": {
                "vr_tiers":  [[0.3, 37], [0.5, 19], [0.7, 7], [1.0, -1], [3.0, -3], [99, 0]],
                "gap_tiers": [[9, 20], [7, 6], [3, 1], [-1, -5], [-3, -3], [-99, 2]],
                "vr_mode":   "step",
                "gap_mode":  "step"
            },
            "v3": {
                "vr_tiers":  [[0.20, 40], [0.30, 34], [0.40, 27], [0.50, 20],
                              [0.60, 14], [0.70, 8], [0.85, 3], [1.20, -1],
                              [2.50, -2], [5.00, -1], [99, 0]],
                "gap_tiers": [[10, 22], [8, 16], [7, 11], [5, 7], [3, 3],
                              [1, -1], [-1, -5], [-3, -3], [-99, 2]],
                "vr_mode":   "step",
                "gap_mode":  "step"
            }
        },
        "one_line_score":      {"true_one": 20, "t_board": 10},
        "cons_score":          {"first": -2, "2": 6, "3": 14, "4": 22, "5": 26, "6plus": 30},
        "dow_score":           {"monday": 2, "friday": -1},
        "seal_time_tiers":     [[5, 14], [10, 6], [15, 4], [20, 7], [25, 2],
                                 [30, 1], [40, -5], [50, 2], [60, -3], [120, -10], [240, -9]],
        # 基于1,008样本实测: 0-5min=28.4% | 5-10=19.8% | 10-15=18.2% | 15-20=20.8%
        # 20-25=15.6% | 25-30=15.0% | 30-40=8.6% | 40-50=16.2% | 50-60=10.5% | 60+=4.7%
        # 加分=偏离基准14.0%, 分钟数为from 9:30
        "zhaban": {
            "early_reseal":   [1000, 2],
            "mid_reseal":     [1400, 6],
            "late_vol_low":   [1.5, 3],
            "late_vol_mid":   [3.0, 8],
            "late_vol_high":  [99, 15],
            "fallback":       5
        },
        "sector_tiers":        [[5, 12], [3, 6], [2, 2]],
        "mapping": {
            "prob":     [[75, 40], [55, 33], [35, 30], [20, 25], [10, 20], [-99, 14]],
            "position": [[40, 100], [20, 50], [-99, 33]]
        },
        "buy_window": [4.0, 8.0],
        "score_min":  10,
        "filters": {
            "true_one_line_skip":  True,
            "board4_one_line_skip": True
        }
    }


def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return default_scoring_config()


def save_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ============================================================
# 预处理K线 (各处复用的逻辑)
# ============================================================

def precompute_klines(code, klines):
    """返回 pdb: {date: {open,close,high,low,volume,is_limit_up,prev_close,gap_open_pct,
                         vol_ma5,vol_ma20,vol_ratio5,vol_ratio20,is_one_line,cons_lu_before}}
    兼容旧格式(baostock前复权)和新格式(搜狐财经不复权)"""
    # ── 新格式检测与转换 ──
    if isinstance(klines, dict) and 'data' in klines:
        klines = klines['data']
    # 搜狐新格式: volume_lots(手) → volume(股)
    if klines and 'volume_lots' in klines[0] and 'volume' not in klines[0]:
        for k in klines:
            k['volume'] = k.get('volume_lots', 0) * 100

    if len(klines) < 25:
        return None, None

    for k in klines:
        for field in ['open', 'close', 'high', 'low']:
            k[field] = round(k[field], 2)

    pdb = {}
    prev_close = None
    lpct = get_lp(code)

    for i, k in enumerate(klines):
        dt = k['date']
        o, c, h, l, v = k['open'], k['close'], k['high'], k['low'], k['volume']

        entry = {'open': o, 'close': c, 'high': h, 'low': l, 'volume': v,
                 'is_limit_up': False, 'prev_close': prev_close, 'gap_open_pct': 0}

        if prev_close and prev_close > 0:
            entry['is_limit_up'] = is_limit_up(c, prev_close, lpct)
            entry['gap_open_pct'] = round((o - prev_close) / prev_close * 100, 2)

        if i >= 5:
            entry['vol_ma5'] = sum(klines[j]['volume'] for j in range(i - 4, i + 1)) / 5
        else:
            entry['vol_ma5'] = v
        if i >= 20:
            entry['vol_ma20'] = sum(klines[j]['volume'] for j in range(i - 19, i + 1)) / 20
        else:
            entry['vol_ma20'] = v

        entry['vol_ratio5'] = round(v / entry['vol_ma5'], 2) if entry['vol_ma5'] > 0 else 1
        entry['vol_ratio20'] = round(v / entry['vol_ma20'], 2) if entry['vol_ma20'] > 0 else 1

        # 一字板判定
        if h > 0 and l > 0:
            if abs(h - l) < 0.001:
                entry['is_one_line'] = True
            elif h > l:
                us = (h - max(o, c)) / (h - l)
                body = abs(c - o) / (h - l)
                entry['is_one_line'] = (us < 0.1 and body < 0.1)
            else:
                entry['is_one_line'] = False
        else:
            entry['is_one_line'] = False

        # 连板数
        cons = 0
        for j in range(i - 1, max(i - 10, -1), -1):
            cd_ = klines[j]['date']
            if cd_ in pdb and pdb[cd_]['is_limit_up']:
                cons += 1
            else:
                break
        entry['cons_lu_before'] = cons
        pdb[dt] = entry
        prev_close = c

    today_dt = klines[-1]['date']
    if today_dt not in pdb or not pdb[today_dt]['is_limit_up']:
        return None, None

    return pdb, today_dt


# ============================================================
# 核心评分函数
# ============================================================

def compute_score(code, klines, details_raw=None, version='v3', config=None):
    """
    统一评分入口
    version: 'v2' (当前陡峭) 或 'v3' (平滑)
    details_raw: {seal_time, zhaban, final_seal_time, sector_count}
    返回: (score_float, details_dict) or (None, None)
    """
    if config is None:
        config = load_config()

    result = precompute_klines(code, klines)
    if result is None or result[0] is None:
        return None, None
    pdb, today_dt = result

    t1 = pdb[today_dt]
    cons = t1['cons_lu_before']

    # -------- v3.1: 近1年活跃度过滤 --------
    from datetime import timedelta
    cutoff = (datetime.strptime(today_dt, '%Y-%m-%d') - timedelta(days=365)).strftime('%Y-%m-%d')
    recent_lu = sum(1 for dt, entry in pdb.items()
                    if dt >= cutoff and dt != today_dt and entry['is_limit_up'])
    if recent_lu < 2:
        return None, None  # 近1年涨停<2次, 不纳入候选

    score = 0.0
    tables = config['tables'][version]

    # -------- 量比 --------
    # 连板>=2用5日均量, 否则20日
    if cons >= 2:
        vr = t1['vol_ratio5']
    else:
        vr = t1['vol_ratio20']

    if tables.get('vr_mode') == 'linear':
        score += piecewise_linear(vr, tables['vr_anchors'])
    else:
        score += step_score_asc(vr, tables['vr_tiers'])

    # -------- Gap --------
    g = t1['gap_open_pct']
    if tables.get('gap_mode') == 'linear':
        score += piecewise_linear(g, tables['gap_anchors'])
    else:
        score += step_score_desc(g, tables['gap_tiers'])

    # -------- 一字板 --------
    if t1.get('is_one_line', False):
        if abs(t1['high'] - t1['low']) < 0.001:
            score += config['one_line_score']['true_one']
        else:
            score += config['one_line_score']['t_board']

    # -------- 连板 --------
    # 按具体连板数给分
    if cons == 0:
        score += config['cons_score']['first']
    elif cons == 1:
        score += config['cons_score']['2']
    elif cons == 2:
        score += config['cons_score']['3']
    elif cons == 3:
        score += config['cons_score']['4']
    elif cons == 4:
        score += config['cons_score']['5']
    else:
        score += config['cons_score']['6plus']

    # -------- 周几 --------
    tomorrow = datetime.strptime(today_dt, '%Y-%m-%d') + timedelta(days=1)
    while tomorrow.weekday() >= 5:
        tomorrow = tomorrow + timedelta(days=1)
    dow = tomorrow.weekday()
    if dow == 0:
        score += config['dow_score']['monday']
    elif dow == 4:
        score += config['dow_score']['friday']

    # -------- 封板时间 --------
    if details_raw is None:
        details_raw = {}
    seal_time = details_raw.get('seal_time', '1459')
    if seal_time and seal_time != '?':
        try:
            # seal_time格式: "092500" 或 "09:25:00" → 转换为距9:30的分钟数
            st_clean = seal_time.replace(':', '')
            hh = int(st_clean[:2])
            mm = int(st_clean[2:4])
            mins = max(0, (hh - 9) * 60 + mm - 30)  # 距9:30分钟数
            score += step_score_asc(mins, config['seal_time_tiers'])
        except:
            pass

    # -------- 炸板 --------
    zhaban = details_raw.get('zhaban', 0)
    final_seal = details_raw.get('final_seal_time', seal_time)
    if zhaban > 0:
        try:
            fst = int(final_seal[:4]) if final_seal and final_seal != '?' else 1500
            vr20_val = t1.get('vol_ratio20', 2)
            zb_cfg = config['zhaban']
            if fst <= zb_cfg['early_reseal'][0]:
                score -= zhaban * zb_cfg['early_reseal'][1]
            elif fst <= zb_cfg['mid_reseal'][0]:
                score -= zhaban * zb_cfg['mid_reseal'][1]
            else:
                if vr20_val < zb_cfg['late_vol_low'][0]:
                    score -= zhaban * zb_cfg['late_vol_low'][1]
                elif vr20_val < zb_cfg['late_vol_mid'][0]:
                    score -= zhaban * zb_cfg['late_vol_mid'][1]
                else:
                    score -= zhaban * zb_cfg['late_vol_high'][1]
        except:
            score -= zhaban * config['zhaban']['fallback']

    # -------- 板块共振 --------
    sector_count = details_raw.get('sector_count', 1)
    for thresh, val in config['sector_tiers']:
        if sector_count >= thresh:
            score += val
            break

    score = round(score, 2)

    details = {
        'vr20': vr,
        'gap': t1['gap_open_pct'],
        'cons': cons + 1,
        'one_line': t1.get('is_one_line', False),
        'true_one_line': abs(t1['high'] - t1['low']) < 0.001,
        'open': t1['open'],
        'close': t1['close'],
        't2_lu': False,
        'tomorrow_dow': dow
    }

    return score, details


# ============================================================
# 便捷函数
# ============================================================

def score_v2(code, klines, details_raw=None, config=None):
    return compute_score(code, klines, details_raw, 'v2', config)


def score_v3(code, klines, details_raw=None, config=None):
    return compute_score(code, klines, details_raw, 'v3', config)


def score_to_prob(score, config=None):
    if config is None:
        config = load_config()
    return step_score_desc(score, config['mapping']['prob'])


def score_to_position(score, config=None):
    if config is None:
        config = load_config()
    return step_score_desc(score, config['mapping']['position'])


def get_buy_window(config=None):
    if config is None:
        config = load_config()
    return config['buy_window']


def get_score_min(config=None):
    if config is None:
        config = load_config()
    return config['score_min']


def should_filter(one_line, true_one_line, cons, config=None):
    """返回 (filtered: bool, reason: str)"""
    if config is None:
        config = load_config()
    filters = config['filters']
    if filters.get('true_one_line_skip') and true_one_line:
        return True, "真一字板(买不到)"
    if filters.get('board4_one_line_skip') and one_line and cons >= 4:
        return True, "4板+一字/T字(高危)"
    return False, ""


# ============================================================
# 评分摘要 (调试用)
# ============================================================

def score_breakdown(code, klines, details_raw=None, version='v3', config=None):
    """返回各因子贡献明细"""
    if config is None:
        config = load_config()

    result = precompute_klines(code, klines)
    if result is None:
        return None
    pdb, today_dt = result
    t1 = pdb[today_dt]
    cons = t1['cons_lu_before']
    tables = config['tables'][version]

    if cons >= 2:
        vr = t1['vol_ratio5']
    else:
        vr = t1['vol_ratio20']
    g = t1['gap_open_pct']

    if tables.get('vr_mode') == 'linear':
        vr_score = piecewise_linear(vr, tables['vr_anchors'])
    else:
        vr_score = step_score_asc(vr, tables['vr_tiers'])

    if tables.get('gap_mode') == 'linear':
        gap_score = piecewise_linear(g, tables['gap_anchors'])
    else:
        gap_score = step_score_desc(g, tables['gap_tiers'])

    return {
        'code': code,
        'vr': vr,
        'vr_score': vr_score,
        'gap': g,
        'gap_score': gap_score,
        'one_line': t1.get('is_one_line', False),
        'true_one_line': abs(t1['high'] - t1['low']) < 0.001,
        'cons': cons + 1,
        'vr_type': '5d' if cons >= 2 else '20d'
    }


if __name__ == '__main__':
    # Self-test
    cfg = load_config()
    print(f"Active: {cfg['active']}")
    print(f"V2 VR tiers:  {cfg['tables']['v2']['vr_tiers']}")
    print(f"V3 VR anchors: {cfg['tables']['v3']['vr_anchors'][:5]}...")
    print(f"V3 Gap anchors: {cfg['tables']['v3']['gap_anchors'][:5]}...")
    print(f"Buy window: {cfg['buy_window']}, Score min: {cfg['score_min']}")

    # Test interpolation
    for x in [0.2, 0.4, 0.6, 1.0, 2.0, 5.0]:
        v2s = step_score_asc(x, cfg['tables']['v2']['vr_tiers'])
        v3s = piecewise_linear(x, cfg['tables']['v3']['vr_anchors'])
        print(f"  vr={x:.1f}  v2={v2s}  v3={v3s}")
    for x in [-5, -1, 0, 3, 7, 10]:
        v2s = step_score_desc(x, cfg['tables']['v2']['gap_tiers'])
        v3s = piecewise_linear(x, cfg['tables']['v3']['gap_anchors'])
        print(f"  gap={x}  v2={v2s}  v3={v3s}")
