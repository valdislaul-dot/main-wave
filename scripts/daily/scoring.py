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
        "divergence": {
            "enabled": True,
            "prev_day_vol_min": 1.5,
            "bonus": 15,
            "no_sector_bonus": 4,
            "_note": "分歧质量(烂板出妖): 爆量+烂板回封+收盘涨停=大分歧日加分; 板块>=2只给满额"
        },
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

def classify_volume(vol, klines, date_idx, heavy=2.0, shrink=0.5):
    """量能分类 — A体系，77笔实盘数据驱动
    比较基准: 近5日涨停日的量（打板策略，太久无参考性）
    heavy(爆量): 是近期涨停中最大量 AND vs涨停日均量>=2x
    shrink(缩量): vs近期涨停最大量<0.5x
    normal(正常): 其余
    首板(无前序涨停): 退化为 vs 5日MA"""
    # 近5日内涨停日的量
    start = max(0, date_idx - 5)
    lu_vols = []
    for j in range(start, date_idx):
        if j > 0:
            prev_c = klines[j - 1].get('close', 0)
            curr_c = klines[j].get('close', 0)
            if prev_c > 0 and (curr_c - prev_c) / prev_c >= 0.098:
                v = klines[j].get('volume', 0)
                if v > 0:
                    lu_vols.append(v)

    if lu_vols:
        lu_max = max(lu_vols)
        lu_avg = sum(lu_vols) / len(lu_vols)
        vr_avg = vol / lu_avg if lu_avg > 0 else 1.0
        vr_max = vol / lu_max if lu_max > 0 else 1.0
        if vol >= lu_max and vr_avg >= heavy:
            return 'heavy'
        if vr_max < shrink:
            return 'shrink'
        return 'normal'

    # 首板: 退化为 vs 5日MA
    start_ma = max(0, date_idx - 5)
    vols = [klines[j].get('volume', 0) for j in range(start_ma, date_idx + 1)]
    vols = [v for v in vols if v > 0]
    if not vols:
        return 'normal'
    ma20 = sum(vols) / len(vols)
    vr_ma20 = vol / ma20 if ma20 > 0 else 1.0
    if vr_ma20 >= heavy:
        return 'heavy'
    if vr_ma20 < shrink:
        return 'shrink'
    return 'normal'


def classify_seal_quality(seal_minutes, zhaban_count, strong_max=30, weak_min=60):
    """封板质量
    strong: 封板<=30min 且 0炸板
    weak: 封板>60min 或 炸板>0"""
    if seal_minutes is not None and seal_minutes <= strong_max and zhaban_count == 0:
        return 'strong'
    return 'weak'


def precompute_klines(code, klines):
    """返回 pdb: {date: {open,close,high,low,volume,is_limit_up,prev_close,gap_open_pct,
                         vol_ma5,vol_ma20,vol_ratio5,vol_ratio20,is_one_line,cons_lu_before,
                         vol_class}}
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
        entry['vol_class'] = classify_volume(v, klines, i)
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
            fst = int(final_seal.replace(':', '')[:4]) if final_seal and final_seal != '?' else 1500
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

    # -------- 分歧质量 (2026-08-13新增: 烂板出妖/预期差) --------
    # 爆量+烂板(炸板回封或封板>60min)+收盘涨停 = 大分歧日 → 加分, 修正"烂板一味扣分"
    div_cfg = config.get('divergence', {})
    div_bonus = 0
    if div_cfg.get('enabled', True):
        seal_mins = None
        if seal_time and seal_time != '?':
            try:
                st_clean = seal_time.replace(':', '')
                seal_mins = max(0, (int(st_clean[:2]) - 9) * 60 + int(st_clean[2:4]) - 30)
            except Exception:
                pass
        seal_weak = zhaban > 0 or (seal_mins is not None and seal_mins > 60)
        pdb_keys = list(pdb.keys())
        prev_entry = pdb[pdb_keys[-2]] if len(pdb_keys) >= 2 else None
        prev_vol_ratio = (t1['volume'] / prev_entry['volume']) if (prev_entry and prev_entry.get('volume', 0) > 0) else 1.0
        if seal_weak and t1.get('vol_class') == 'heavy' and prev_vol_ratio >= div_cfg.get('prev_day_vol_min', 1.5):
            # 板块效应=必要条件: 有板块给满额, 无板块只给象征分
            div_bonus = div_cfg.get('bonus', 15) if sector_count >= 2 else div_cfg.get('no_sector_bonus', 4)
            score += div_bonus

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
        'tomorrow_dow': dow,
        'divergence': div_bonus,
        'vol_class': t1.get('vol_class', 'normal')
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
# 逐因子得分明细 (竞价面板表2用)
# ============================================================

def full_breakdown(code, klines, details_raw=None, version='v3', config=None):
    """返回 (total, [(因子, 数值说明, 得分), ...]), 与compute_score同口径"""
    if config is None:
        config = load_config()
    result = precompute_klines(code, klines)
    if result is None or result[0] is None:
        return None
    pdb, today_dt = result
    t1 = pdb[today_dt]
    cons = t1['cons_lu_before']
    tables = config['tables'][version]
    if details_raw is None:
        details_raw = {}
    vr = t1['vol_ratio5'] if cons >= 2 else t1['vol_ratio20']
    g = t1['gap_open_pct']
    items = []
    if tables.get('vr_mode') == 'linear':
        items.append(('量比', f'vr={vr:.2f}', piecewise_linear(vr, tables.get('vr_anchors', []))))
    else:
        items.append(('量比', f'vr={vr:.2f}', step_score_asc(vr, tables['vr_tiers'])))
    if tables.get('gap_mode') == 'linear':
        items.append(('T-1日gap', f'{g:+.1f}%', piecewise_linear(g, tables.get('gap_anchors', []))))
    else:
        items.append(('T-1日gap', f'{g:+.1f}%', step_score_desc(g, tables['gap_tiers'])))
    if t1.get('is_one_line', False):
        true_one = abs(t1['high'] - t1['low']) < 0.001
        items.append(('一字/T字', '真一字' if true_one else 'T字',
                      config['one_line_score']['true_one'] if true_one else config['one_line_score']['t_board']))
    else:
        items.append(('一字/T字', '否', 0))
    items.append(('连板', f'{cons + 1}板', config['cons_score'][{0: 'first', 1: '2', 2: '3', 3: '4', 4: '5'}.get(cons, '6plus')]))
    tmrw = datetime.strptime(today_dt, '%Y-%m-%d') + timedelta(days=1)
    while tmrw.weekday() >= 5:
        tmrw += timedelta(days=1)
    dow = tmrw.weekday()
    dow_v = config['dow_score']['monday'] if dow == 0 else (config['dow_score']['friday'] if dow == 4 else 0)
    items.append(('周几', '周一' if dow == 0 else ('周五' if dow == 4 else '其他'), dow_v))
    seal_time = details_raw.get('seal_time', '1459')
    seal_v, seal_disp = 0, '?'
    if seal_time and seal_time != '?':
        try:
            st_clean = str(seal_time).replace(':', '')
            mins = max(0, (int(st_clean[:2]) - 9) * 60 + int(st_clean[2:4]) - 30)
            seal_disp = f'{mins}min'
            seal_v = step_score_asc(mins, config['seal_time_tiers'])
        except Exception:
            pass
    items.append(('封板时间', seal_disp, seal_v))
    zhaban = int(details_raw.get('zhaban', 0) or 0)
    final_seal = str(details_raw.get('final_seal_time', seal_time))
    zb_pen = 0
    if zhaban > 0:
        try:
            fst = int(final_seal.replace(':', '')[:4]) if final_seal and final_seal != '?' else 1500
            vr20_val = t1.get('vol_ratio20', 2)
            zb_cfg = config['zhaban']
            if fst <= zb_cfg['early_reseal'][0]:
                zb_pen = zhaban * zb_cfg['early_reseal'][1]
            elif fst <= zb_cfg['mid_reseal'][0]:
                zb_pen = zhaban * zb_cfg['mid_reseal'][1]
            else:
                if vr20_val < zb_cfg['late_vol_low'][0]:
                    zb_pen = zhaban * zb_cfg['late_vol_low'][1]
                elif vr20_val < zb_cfg['late_vol_mid'][0]:
                    zb_pen = zhaban * zb_cfg['late_vol_mid'][1]
                else:
                    zb_pen = zhaban * zb_cfg['late_vol_high'][1]
        except Exception:
            zb_pen = zhaban * config['zhaban']['fallback']
    items.append(('炸板扣分', f'炸{zhaban}次', -zb_pen))
    sector_count = int(details_raw.get('sector_count', 1) or 1)
    items.append(('板块共振', f'{sector_count}只', next((v for th, v in config['sector_tiers'] if sector_count >= th), 0)))
    div_cfg = config.get('divergence', {})
    div_v = 0
    if div_cfg.get('enabled', True):
        seal_mins2 = None
        if seal_time and seal_time != '?':
            try:
                st_clean = str(seal_time).replace(':', '')
                seal_mins2 = max(0, (int(st_clean[:2]) - 9) * 60 + int(st_clean[2:4]) - 30)
            except Exception:
                pass
        seal_weak = zhaban > 0 or (seal_mins2 is not None and seal_mins2 > 60)
        pdb_keys = list(pdb.keys())
        prev_entry = pdb[pdb_keys[-2]] if len(pdb_keys) >= 2 else None
        prev_vol_ratio = (t1['volume'] / prev_entry['volume']) if (prev_entry and prev_entry.get('volume', 0) > 0) else 1.0
        if seal_weak and t1.get('vol_class') == 'heavy' and prev_vol_ratio >= div_cfg.get('prev_day_vol_min', 1.5):
            div_v = div_cfg.get('bonus', 15) if sector_count >= 2 else div_cfg.get('no_sector_bonus', 4)
    items.append(('分歧质量', '是' if div_v else '否', div_v))
    total = round(sum(v for _, _, v in items), 2)
    return total, items


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
