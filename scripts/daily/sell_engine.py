"""
卖点引擎 v4.0 — 统一引擎 (2026-08-10)
=============================================
V3.2模型规则 + A交易体系，合二为一

来源:
  V3.2模型 (回测验证): 硬止损-10%, gap≥4%持有, 执行价公式, 14:45兜底
  A体系 (77笔实盘): 量能三态, 封板质量, 弱转强, 亏损分级
  待纳入: VWAP分时黄线 (需分钟数据补齐后激活)

配置: data/scoring_config.json → sell 段
"""

import json, os
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) \
       if '__file__' in dir() else os.getcwd()
CONFIG_PATH = os.path.join(BASE, 'data', 'scoring_config.json')


# ============================================================
# 量能分类 — A体系，77笔实盘数据驱动
# ============================================================

def classify_volume(vol, klines, date_idx, config=None):
    """
    量能三态 — A体系定义:
      - 爆量(heavy): 近20日涨停中量最大，且 ≥ 前涨停日均量×2.0
      - 缩量(shrink): < 前涨停日最大量×0.5
      - 正常(normal): 其余
      首板(无前序涨停): 退化为 vs MA20

    数据支撑: A的77笔中，<0.5x组已知盈亏均为正(+16.3%)，
              ≥2.0x组均值-2.8%，阈值清晰。
    """
    if config is None:
        config = _load_sell_config()
    heavy_th = config['volume']['heavy_threshold']   # 2.0
    shrink_th = config['volume']['shrink_threshold']  # 0.5

    # 近5日内涨停日的量（打板策略，太久无参考性）
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
        vr_max = vol / lu_max if lu_max > 0 else 1.0
        vr_avg = vol / lu_avg if lu_avg > 0 else 1.0

        # 爆量: 是近期涨停中最大量 AND 明显放量(vs均量≥2x)
        if vol >= lu_max and vr_avg >= heavy_th:
            return 'heavy'
        # 缩量: 相对近期涨停最大量缩到一半以下
        if vr_max < shrink_th:
            return 'shrink'
        return 'normal'

    # 首板(无前序涨停): 退化为 vs 5日MA
    start_ma = max(0, date_idx - 5)
    vols = [klines[j].get('volume', 0) for j in range(start_ma, date_idx + 1)]
    vols = [v for v in vols if v > 0]
    if not vols:
        return 'normal'
    ma20 = sum(vols) / len(vols)
    vr_ma20 = vol / ma20 if ma20 > 0 else 1.0
    if vr_ma20 >= heavy_th:
        return 'heavy'
    if vr_ma20 < shrink_th:
        return 'shrink'
    return 'normal'


def _load_sell_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        return cfg.get('sell', _default_sell_config())
    return _default_sell_config()


def _default_sell_config():
    return {
        "volume": {"heavy_threshold": 2.0, "shrink_threshold": 0.5},
        "weak_to_strong": {"surge_pct": 7.0, "vwap_stop": True},
        "gap": {"strong_high_open": 5.0, "weak_low_open": -3.0, "deep_low_open": -5.0},
        "break_even_line": 0.0,
        "seal_quality": {"strong_max_min": 30, "weak_min_min": 60},
        "loss_feedback": {"soft_stop_pct": -5.0, "hard_stop_pct": -10.0},
        "execution": {
            "limit_up_day": "涨停价",
            "non_limit_up_day": "70%(H+O)/2+30%收盘",
            "auction_half": "竞价价出50%",
            "deadline": "14:45市价兜底"
        }
    }


# ============================================================
# K线查询辅助
# ============================================================

def _load_klines(code, name=None):
    paths = [
        os.path.join(BASE, 'data', 'kline_data', f'{code}.json'),
        os.path.join(BASE, 'data', 'kline_data', f'{name}_{code}.json') if name else None,
    ]
    for p in paths:
        if p and os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict) and 'data' in data:
                return data['data']
            if isinstance(data, list):
                return data
    return None


# ============================================================
# 基础判断
# ============================================================

def was_limit_up(klines, date_idx):
    if date_idx is None or date_idx < 0:
        return False
    k = klines[date_idx]
    if k.get('pct_change') is not None:
        return k['pct_change'] >= 9.9
    if date_idx > 0:
        prev_close = klines[date_idx - 1]['close']
        if prev_close > 0:
            return (k['close'] - prev_close) / prev_close >= 0.098
    return False


def get_vol_ratio20(klines, date_idx):
    """20日均量比"""
    if date_idx is None or date_idx < 5:
        return None
    k = klines[date_idx]
    vol = k.get('volume', 0)
    if vol <= 0:
        return None
    start = max(0, date_idx - 19)
    vols = [klines[j].get('volume', 0) for j in range(start, date_idx + 1)]
    ma20 = sum(vols) / len(vols) if vols else 1
    return vol / ma20 if ma20 > 0 else 1.0


def get_board_count(klines, date_idx):
    if date_idx is None or date_idx < 0:
        return 1
    cons = 1
    for j in range(date_idx - 1, max(date_idx - 10, -1), -1):
        if was_limit_up(klines, j):
            cons += 1
        else:
            break
    return cons


# ============================================================
# 封板质量 — 双源: zt_pool优先, 日K线兜底
# ============================================================

def seal_quality_from_daily_kline(k):
    """从日K线推断封板质量 (zt_pool不可用时的fallback)
    来源: A体系, 日K线上影线比例=炸板/烂板信号
    Returns: {'seal_minutes': None, 'zhaban': int, 'quality': 'strong'|'weak'}
    """
    o, c, h, l = k['open'], k['close'], k['high'], k['low']
    if h <= l or h <= 0:
        return {'seal_minutes': None, 'zhaban': 0, 'quality': 'strong'}

    upper_shadow_pct = (h - c) / (h - l) if (h - l) > 0 else 0

    # 强势: 收盘在最高价附近 (上影线<0.5%)
    if c >= h * 0.995:
        return {'seal_minutes': 10, 'zhaban': 0, 'quality': 'strong'}
    # 弱势: 有明显上影线 → 烂板/炸板
    else:
        zhaban = 1 if upper_shadow_pct > 0.2 else 0
        return {'seal_minutes': 90, 'zhaban': zhaban, 'quality': 'weak'}


def get_seal_quality(code, date_str):
    """获取封板质量: zt_pool快照优先, 日K线兜底"""
    # 优先从zt_pool获取
    pool_path = os.path.join(BASE, 'data', 'zt_pool', f'{date_str}.json')
    if not os.path.exists(pool_path):
        alt = os.path.join(BASE, 'data', 'zt_pool', f'{date_str.replace("-", "")}.json')
        if os.path.exists(alt):
            pool_path = alt
        else:
            return None  # zt_pool不存在, 需要调用方用日K线兜底

    try:
        with open(pool_path, 'r', encoding='utf-8') as f:
            pool = json.load(f)
    except (UnicodeDecodeError, json.JSONDecodeError):
        try:
            with open(pool_path, 'r', encoding='gbk') as f:
                pool = json.load(f)
        except Exception:
            return None

    if isinstance(pool, list):
        stocks = pool
    elif isinstance(pool, dict):
        stocks = pool.get('stocks', pool.get('data', []))
    else:
        return None

    for s in stocks:
        s_code = s.get('code', '').replace('sz', '').replace('sh', '')
        if s_code == code.replace('sz', '').replace('sh', ''):
            seal = s.get('first_seal', s.get('seal_time', '?'))
            zhaban = int(s.get('break_times', s.get('reblow', s.get('zhaban', 0))))
            try:
                st_clean = str(seal).replace(':', '')
                if st_clean and st_clean != '?' and len(st_clean) >= 4:
                    hh = int(st_clean[:2])
                    mm = int(st_clean[2:4])
                    mins = max(0, (hh - 9) * 60 + mm - 30)
                    return {'seal_minutes': mins, 'zhaban': zhaban, 'quality': 'strong' if (mins <= 30 and zhaban == 0) else 'weak'}
            except:
                pass
            return {'seal_minutes': None, 'zhaban': zhaban, 'quality': 'strong' if zhaban == 0 else 'weak'}
    return None


# ============================================================
# 主函数: sell_signal (统一版)
# ============================================================

def sell_signal(position, today_auction, config=None):
    """
    卖点判断 — V3.2 + A体系 统一版

    Args:
        position: {code, name, buy_date, buy_price, shares}
        today_auction: {open, prev_close, gap_pct, current_price (可选)}
        config: 可选

    Returns:
        {action, urgency, reason, reference_price, detail}
    """
    if config is None:
        config = _load_sell_config()

    code = position['code']
    name = position['name']
    buy_date = position['buy_date']
    buy_price = position['buy_price']
    gap = today_auction.get('gap_pct', 0)
    auction_price = today_auction.get('open', 0)
    prev_close = today_auction.get('prev_close', 0)

    # ── 加载K线 (提前: 硬止损需要判断昨日炸板状态) ──
    klines = _load_klines(code, name)
    if not klines:
        return _signal('hold', 'normal', '无K线数据', auction_price, '建议手动判断')

    today_str = datetime.now().strftime('%Y-%m-%d')
    last_date = klines[-1]['date']
    yesterday_idx = len(klines) - 2 if last_date == today_str else len(klines) - 1
    if yesterday_idx < 1:
        return _signal('hold', 'normal', 'K线数据不足', auction_price)

    yesterday = klines[yesterday_idx]
    yest_lu = was_limit_up(klines, yesterday_idx)
    board_num = get_board_count(klines, yesterday_idx)
    yest_vol = yesterday.get('volume', 0)

    # ── 硬止损 (2026-08-20调整: 炸板缓冲, 按当日收盘跌幅分级) ──
    # 数据(3年, 炸板股T日收盘分档×次日):
    #   跌停档(≤-9%): 次日-15.0% 正收益0%  |  -9~-7%: 次日-8.8%
    #   -7~-5%: 次日-5.6%  |  -5~-3%: -3.4%  |  -3~0%: -1.5%  |  收红: +2.8%
    # 规则:
    #   昨买入+昨炸板+收盘≥-3% → 缓冲(等修复, 次日平开76%上涨)
    #   昨买入+昨炸板+收盘<-7% → 不缓冲(深炸股次日继续暴跌, 哈森涨停是极端幸存者)
    #   其余情形(持有≥2日 / 昨封板 / 深炸) → 硬止损保留
    current_price = today_auction.get('current_price', auction_price)
    if current_price and current_price > 0:
        loss_pct = (current_price - buy_price) / buy_price * 100
        hard_stop = config['loss_feedback']['hard_stop_pct']
        if loss_pct <= hard_stop:
            bought_yest = bool(buy_date) and buy_date == yesterday['date']
            broke_on_buy_day = bought_yest and not yest_lu
            # 炸板缓冲只适用于温和炸板: 昨日收盘跌幅 > -7% (vs 前日收盘)
            mild_break = False
            if broke_on_buy_day and yesterday_idx >= 1:
                yest_pct = (yesterday['close'] - klines[yesterday_idx - 1]['close']) / klines[yesterday_idx - 1]['close'] * 100
                mild_break = yest_pct > -7.0
            if not mild_break:
                return _signal('sell', 'urgent',
                    f'硬止损: 浮亏{loss_pct:+.1f}% ≤ {hard_stop:+.0f}% — 无条件卖出',
                    current_price)

    # 前日量能 (T-2)
    prev_day_idx = yesterday_idx - 1
    prev_vol = klines[prev_day_idx].get('volume', 0) if prev_day_idx >= 0 else 0

    # 封板质量: zt_pool优先, 日K线兜底
    yest_date_str = yesterday['date']
    seal_info = get_seal_quality(code, yest_date_str)
    if seal_info is None:
        seal_info = seal_quality_from_daily_kline(yesterday)
    seal_quality = seal_info['quality']  # 'strong' | 'weak'

    cfg_gap = config['gap']
    cfg_w2s = config['weak_to_strong']
    soft_stop = config['loss_feedback']['soft_stop_pct']  # -5%

    # ── 低开判断 ──
    is_low_open = gap < 0
    is_deep_low = gap <= cfg_gap['deep_low_open']
    is_weak_low = gap <= cfg_gap['weak_low_open'] and gap > cfg_gap['deep_low_open']

    if yest_lu:
        # ==================== 昨涨停 ====================

        # 低开: 无条件竞价走 (两者一致)
        if is_low_open:
            return _signal('sell', 'urgent',
                f'昨涨停(第{board_num}板) + 今低开{gap:+.1f}% → 竞价卖出',
                auction_price, 'A体系+V3.2一致: 低开=第一卖点')

        yest_vol_class = classify_volume(yest_vol, klines, yesterday_idx, config) if yest_vol else 'normal'
        prev_vol_class = classify_volume(prev_vol, klines, prev_day_idx, config) if prev_vol else 'normal'

        if seal_quality == 'strong':
            # ① 前日爆量 + 昨缩量加速 → 次日加速预期 (A独有)
            if prev_vol_class == 'heavy' and yest_vol_class == 'shrink':
                if gap < cfg_gap['strong_high_open']:
                    return _signal('sell_half', 'urgent',
                        f'前日爆量+昨缩量加速, 竞价{gap:+.1f}%未达5%强高开预期 → 半仓减',
                        auction_price,
                        '剩余: 拉升量能<爆量日→格局; 量能放大逼近爆量或破5%→清')
                else:
                    return _signal('hold', 'normal',
                        f'前日爆量+昨缩量加速, 竞价{gap:+.1f}%达标 → 开盘关注量能',
                        yesterday['close'] * 1.10,
                        '量能<爆量日→格局; 量能放大逼近爆量→减仓')

            # ② 连续正常量 → 分歧日预期 (A独有)
            elif prev_vol_class == 'normal' and yest_vol_class == 'normal':
                if gap >= cfg_gap['strong_high_open']:
                    return _signal('sell', 'urgent',
                        f'连续正常量+今大高开{gap:+.1f}% → 分歧日, 大高开=第一卖点',
                        auction_price,
                        '分歧日常有大下杀, 杀后拉回>开盘+回封→格局; 否则→走')
                else:
                    return _signal('hold', 'normal',
                        f'连续正常量+小高开{gap:+.1f}%, 分歧日尚可观察',
                        yesterday['close'] * 1.10)

            # ③ 昨爆量(分歧日) → 看弱转强 (A独有)
            elif yest_vol_class == 'heavy':
                return _signal('watch', 'normal',
                    f'昨爆量分歧日(第{board_num}板), 今高开{gap:+.1f}% → 弱转强待确认',
                    auction_price,
                    '开盘拉升>7%→真弱转强格局; 下杀破0%→走')

            # ④ 正常持有
            else:
                return _signal('hold', 'normal',
                    f'昨强封(第{board_num}板), 今高开{gap:+.1f}% → 持有',
                    yesterday['close'] * 1.10)

        else:  # seal_quality == 'weak' (烂板/炸板)
            vwap_info = check_vwap_breach(yesterday)
            if gap >= cfg_gap['strong_high_open']:
                return _signal('watch', 'normal',
                    f'昨烂板(炸{seal_info["zhaban"]}次,昨VWAP{vwap_info["vwap"]:.1f}), '
                    f'今强高开{gap:+.1f}% → 弱转强信号',
                    auction_price,
                    f'开盘拉升>7%=弱转强→格局; '
                    f'量超烂板日→板砸; 下杀破0%或破今日VWAP→走')
            elif gap > 0:
                return _signal('watch', 'normal',
                    f'昨烂板+小高开{gap:+.1f}% → 弱转强待确认',
                    auction_price,
                    '开盘拉升>7%→格局; 下杀→0%底线走')
            else:
                return _signal('sell', 'urgent',
                    f'昨烂板+低开{gap:+.1f}% → 竞价走',
                    auction_price)

    else:
        # ==================== 昨断板 ====================

        # 计算亏损幅度
        buy_dt = yesterday['date']
        if buy_date and buy_date == buy_dt:
            loss_pct = (yesterday['close'] - buy_price) / buy_price * 100
        else:
            # 前日收盘作为参考
            prev_k = klines[yesterday_idx - 1] if yesterday_idx > 0 else yesterday
            loss_pct = (yesterday['close'] - prev_k['open']) / prev_k['open'] * 100 if prev_k['open'] > 0 else 0

        is_minor_loss = loss_pct > soft_stop  # 浮亏在软止损范围内=小亏

        # ── 大亏+平开/高开 → 等修复冲高 (2026-08-20新增, 仅温和炸板适用) ──
        # 数据: 炸板股T日收盘分档×次日 — 温和档(-3%内)次日-1.5%, 收红档+2.8%;
        #       深炸档(≤-7%)次日-8.8%~-15%, 正收益0%, 不适用缓冲(硬止损已在前面拦截)
        hard_stop = config['loss_feedback']['hard_stop_pct']
        if loss_pct <= hard_stop and gap > cfg_gap['deep_low_open'] + 1:
            return _signal('watch', 'urgent',
                f'昨浮亏{loss_pct:+.1f}%超硬止损+今{gap:+.1f}%平开/高开 → 等修复冲高减亏',
                yesterday.get('high', auction_price),
                '3年数据: 温和炸板次日平开76%上涨+2.18%, 比开盘止损平均少亏约1.6%; '
                '盘中破-4%或冲高乏力→走')

        # ── 弱转强高开 (gap≥5%) — A体系 ──
        if gap >= cfg_gap['strong_high_open']:
            vwap_info = check_vwap_breach(yesterday)
            vwap_note = f'昨VWAP={vwap_info["vwap"]:.2f}, 昨低={vwap_info["low"]:.2f}'
            if vwap_info['breached']:
                vwap_note += ', 昨已破VWAP⚠'
            return _signal('watch', 'normal',
                f'昨断板+今强高开{gap:+.1f}% → 弱转强(反包)信号',
                auction_price,
                f'开盘5min内拉升>7%=真反包→格局; '
                f'破分时黄线(VWAP)→走; 收盘未反包→走 | {vwap_note}')

        # ── gap≥4%持有 — V3.2保留 ──
        if gap >= 4.0 and gap > 0:
            return _signal('hold', 'normal',
                f'昨断板+gap{gap:+.1f}%≥4% → 持有观察 (V3.2规则)',
                yesterday.get('high', auction_price),
                'V3.2回测验证: 断板日gap≥4%持有收益为正')

        # ── 低开分支 — A体系 ──
        if is_deep_low and board_num <= 3:
            return _signal('watch', 'urgent',
                f'昨断板+深水低开{gap:+.1f}%({board_num}板) → 等自救冲高',
                yesterday.get('high', auction_price),
                '3板内资金自救预期, 冲高减亏; 高位板不适用')

        if is_deep_low and board_num > 3:
            return _signal('sell', 'urgent',
                f'昨断板+深水低开{gap:+.1f}%+高位({board_num}板) → 竞价走',
                auction_price, '高位板不适用自救逻辑')

        if is_weak_low:
            if is_minor_loss:
                return _signal('sell', 'urgent',
                    f'昨浮亏({loss_pct:+.1f}%)在软止损内+小低开{gap:+.1f}% → 竞价走',
                    auction_price, f'软止损{soft_stop:+.0f}%: 小亏快走, 防扩大亏损')
            else:
                return _signal('watch', 'urgent',
                    f'昨浮亏({loss_pct:+.1f}%)超软止损+小低开{gap:+.1f}% → 等冲高减亏',
                    yesterday.get('high', auction_price),
                    '冲高力度有限, 有赚就减')

        # ── 平开或微低开, gap<4% — A+V3.2一致: 卖 ──
        if gap < 4.0:
            return _signal('sell', 'normal',
                f'昨断板+gap{gap:+.1f}%<4% → 卖出',
                auction_price)

        return _signal('hold', 'normal',
            f'昨断板+gap{gap:+.1f}% → 持有',
            auction_price)

    return _signal('hold', 'normal', '默认持有', auction_price)


def _signal(action, urgency, reason, reference_price, detail=''):
    return {
        'action': action,
        'urgency': urgency,
        'reason': reason,
        'reference_price': reference_price,
        'detail': detail
    }


# ============================================================
# 卖出执行价 — V3.2公式保留
# ============================================================

def sell_execution_price(signal, today_quote, position):
    """
    V3.2执行价公式:
      涨停日 → 涨停价限价单
      不涨停日 → 70%(H+O)/2 + 30%收盘价
      14:45 → 市价兜底
    """
    action = signal['action']
    o = today_quote.get('open', 0)
    h = today_quote.get('high', 0)
    c = today_quote.get('close', 0)
    lu = today_quote.get('limit_up_price', 0)
    buy_price = position.get('buy_price', 0)

    if action == 'sell_half':
        return {
            'price': o, 'shares_pct': 50,
            'order_type': '竞价半仓',
            'note': f'竞价{o:.2f}出50%'
        }

    if action == 'sell':
        if c >= lu * 0.995 and lu > 0:
            return {
                'price': lu, 'shares_pct': 100,
                'order_type': '限价单(涨停价)',
                'note': f'涨停日挂涨停价{lu:.2f}'
            }
        ho2 = (h + o) / 2 if h > 0 and o > 0 else o
        price = round(0.7 * ho2 + 0.3 * c, 2) if c > 0 else o
        return {
            'price': price, 'shares_pct': 100,
            'order_type': '限价单(半程价)',
            'note': '70%(H{:.2f}+O{:.2f})/2+30%收{:.2f}={:.2f}'.format(h, o, c, price)
        }

    return {
        'price': signal['reference_price'], 'shares_pct': 0,
        'order_type': '持有/观察',
        'note': signal['reason']
    }


# ============================================================
# VWAP — 日K线直接计算（已激活）
# ============================================================

def calc_daily_vwap(k):
    """
    从日K线计算日VWAP
    优先: amount_10k_cny / (volume_lots * 100)  — 真VWAP
    兜底: (H + L + C) / 3                        — 近似VWAP
    """
    amt = k.get('amount_10k_cny', 0)
    vol_lots = k.get('volume_lots', k.get('volume', 0))
    # 真VWAP: 成交额 / 成交量
    if amt and vol_lots and amt > 0 and vol_lots > 0:
        return (amt * 10000) / (vol_lots * 100)

    # 近似VWAP: (H+L+C)/3 — 无成交额时的最佳替代
    h = k.get('high', 0)
    l = k.get('low', 0)
    c = k.get('close', 0)
    if h > 0 and l > 0 and c > 0:
        return round((h + l + c) / 3, 2)

    return None


def check_vwap_breach(k):
    """
    检查当日是否跌破VWAP
    Returns: {breached: bool, vwap: float, low: float}
    """
    vwap = calc_daily_vwap(k)
    low = k.get('low', 0)
    if vwap is None or low <= 0:
        return {'breached': False, 'vwap': vwap, 'low': low}
    return {
        'breached': low < vwap,
        'vwap': round(vwap, 2),
        'low': low
    }


# ============================================================
# 自测
# ============================================================

if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    print("=" * 60)
    print("  卖点引擎 v4.0 — 统一引擎 (V3.2 + A体系)")
    print("=" * 60)

    config = _load_sell_config()
    print(f"量能: 爆量>={config['volume']['heavy_threshold']}x, "
          f"缩量<{config['volume']['shrink_threshold']}x")
    print(f"弱转强: 拉升>{config['weak_to_strong']['surge_pct']}%")
    print(f"Gap: 强高开>{config['gap']['strong_high_open']}%, "
          f"深水<{config['gap']['deep_low_open']}%")
    print(f"硬止损: ≤{config['loss_feedback']['hard_stop_pct']:+.0f}%")
    print(f"软止损: >{config['loss_feedback']['soft_stop_pct']:+.0f}%")
    print(f"VWAP: {'已激活(日K线计算)' if config['weak_to_strong'].get('vwap_stop') else '关闭'}")

    print("\n--- 量能分类 (新: vs近5日涨停量) ---")
    # Mock klines with limit-up days
    mock_klines = [
        {'date': f'2026-08-{d:02d}', 'open': 10, 'close': 10.5, 'high': 10.5, 'low': 10, 'volume': 10000}
        for d in range(1, 15)
    ]
    # Add some limit-up days
    mock_klines[5]['close'] = mock_klines[4]['close'] * 1.10  # 涨停
    mock_klines[5]['volume'] = 50000
    mock_klines[8]['close'] = mock_klines[7]['close'] * 1.10  # 涨停
    mock_klines[8]['volume'] = 80000
    mock_klines[10]['close'] = mock_klines[9]['close'] * 1.10  # 涨停
    mock_klines[10]['volume'] = 100000  # lu_max

    # Test: shrink (vol small vs lu_max)
    r = classify_volume(30000, mock_klines, 12, config)
    print(f"  vol=30k vs lu_max=100k (vr=0.3) → {r} (expected shrink) {'✓' if r == 'shrink' else '✗'}")
    # Test: heavy (vol is largest AND >=2x avg of lu)
    r = classify_volume(250000, mock_klines, 12, config)
    print(f"  vol=250k, largest, 2x+ avg → {r} (expected heavy) {'✓' if r == 'heavy' else '✗'}")
    # Test: normal
    r = classify_volume(80000, mock_klines, 12, config)
    print(f"  vol=80k vs lu_max=100k (vr=0.8) → {r} (expected normal) {'✓' if r == 'normal' else '✗'}")

    print("\n--- 封板质量(日K线推断) ---")
    test_k = [
        ({'open': 100, 'close': 110, 'high': 110, 'low': 99}, 'strong'),
        ({'open': 100, 'close': 108, 'high': 110, 'low': 99}, 'weak'),
    ]
    for k, exp in test_k:
        r = seal_quality_from_daily_kline(k)['quality']
        print(f"  close/high={k['close']/k['high']:.3f} → {r} (expected {exp}) {'✓' if r == exp else '✗'}")

    print("\n--- VWAP 日K线计算 ---")
    # Test with real data fields
    test_real = {'amount_10k_cny': 50000, 'volume_lots': 100000}
    v_real = calc_daily_vwap(test_real)
    print(f"  真VWAP: amt=50000万 vol=100000手 → {v_real:.2f} (expected 50.00)")

    test_approx = {'high': 110, 'low': 99, 'close': 108}
    v_approx = calc_daily_vwap(test_approx)
    print(f"  近似VWAP: H=110 L=99 C=108 → {v_approx:.2f} (expected 105.67)")

    test_breach = check_vwap_breach({'high': 110, 'low': 95, 'close': 108})
    print(f"  VWAP破位: VWAP={test_breach['vwap']} low={test_breach['low']} → "
          f"{'破位⚠' if test_breach['breached'] else '撑住✓'}")

    print("\n✅ 自测通过")
