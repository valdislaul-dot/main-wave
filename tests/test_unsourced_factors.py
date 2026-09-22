"""无来源因子处置单测 (2026-09-23 用户拍板「跟A保持一致」)

背景: 审核「生产系统还有哪些与A理论相悖」时发现 4 项在 A 的两份源资料
(干货_怎么选.doc / 干货合集-卖点.docx) 中均无依据, 全部可追溯到 commit ca5b37e「V3.0」:
  dow_score(周一+2/周五-1) / seal_time_tiers / sector_tiers / 活跃度过滤 recent_lu<2

处置:
  dow_score                            → 直接删除(配置键 + 计分代码 + full_breakdown 行)
  seal_time / sector / activity_filter → 暂停使用(config['disabled_factors'] 声明, 可恢复)

⚠ 关键不变量: sector_tiers 暂停后, sector_count 仍须供 divergence(烂板回封)使用 ——
   divergence 是 A 体系规则, 不得被本次改动连带停用。

注: dow 是"删除"不是"开关", 故 on/off 对照里 dow 恒不参与 —— 对照组只用
    ['sector','activity_filter'] / ['seal_time','activity_filter'] 单独隔离目标因子。
"""
import sys, os, copy, datetime as _dt
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'daily'))

from scoring import compute_score, full_breakdown, factor_enabled, load_config

DISABLED = ['seal_time', 'sector', 'activity_filter']
SEAL_ON = ['sector', 'activity_filter']       # 只隔离 seal_time
SECTOR_ON = ['seal_time', 'activity_filter']  # 只隔离 sector
ACTIVITY_ON = ['seal_time', 'sector']         # 活跃度过滤开启(用于验证其阈值语义)


def make_klines(n=30, prior_lu=0):
    """n 根日线, 最后一根涨停(10.00→11.00)。prior_lu>0 时在更早位置插入若干次
    非相邻涨停, 用于制造 recent_lu 计数(活跃度过滤要求 >=2 才放行)"""
    d0 = _dt.date(2026, 1, 1)
    lu_idx = {n - 3 - 2 * k for k in range(prior_lu) if n - 3 - 2 * k >= 0}
    rows = []
    for i in range(n):
        d = (d0 + _dt.timedelta(days=i)).isoformat()
        o = h = l = c = 10.0
        if i in lu_idx or i == n - 1:
            c, h = 11.0, 11.0
        rows.append({'date': d, 'open': o, 'close': c, 'high': h, 'low': l, 'volume': 100000})
    return rows


def cfg_with(disabled):
    c = copy.deepcopy(load_config())
    c['disabled_factors'] = disabled
    return c


# ---------- 1. 配置状态 ----------

def test_config_dow_score_removed():
    assert 'dow_score' not in load_config(), 'dow_score 应已从配置直接删除(无来源因子)'


def test_config_disabled_factors_present():
    assert load_config().get('disabled_factors') == DISABLED


def test_config_keeps_disabled_factor_tables():
    """暂停 != 删除: 参数表保留, 便于随时恢复与回归对照"""
    cfg = load_config()
    assert 'seal_time_tiers' in cfg and 'sector_tiers' in cfg


# ---------- 2. factor_enabled 语义 ----------

def test_factor_enabled_default_true():
    assert factor_enabled('vr', {}) is True


def test_factor_enabled_reads_list():
    cfg = {'disabled_factors': DISABLED}
    assert factor_enabled('seal_time', cfg) is False
    assert factor_enabled('sector', cfg) is False
    assert factor_enabled('activity_filter', cfg) is False
    assert factor_enabled('divergence', cfg) is True


def test_factor_enabled_tolerates_missing_key():
    assert factor_enabled('seal_time', {}) is True
    assert factor_enabled('seal_time', {'disabled_factors': None}) is True


# ---------- 3. dow 已删除 ----------

def test_dow_never_in_breakdown():
    sc, det = compute_score('600000', make_klines(prior_lu=2), {'seal_time': '093000'})
    assert sc is not None
    assert 'dow' not in det['v3_breakdown'], 'dow 分项应已随 dow_score 一并删除'


def test_breakdown_no_dow_row():
    _t, items = full_breakdown('600000', make_klines(prior_lu=2), {}, config=cfg_with(DISABLED))
    assert not [it for it in items if it[0] == '周几'], 'full_breakdown 的周几行应已删除'


# ---------- 4. seal_time / sector 停用后贡献 0 ----------

def test_seal_time_disabled_contributes_zero():
    k = make_klines(prior_lu=2)
    s_on, d_on = compute_score('600000', k, {'seal_time': '093000'}, config=cfg_with(SEAL_ON))
    s_off, d_off = compute_score('600000', k, {'seal_time': '093000'}, config=cfg_with(DISABLED))
    assert d_on['v3_breakdown'].get('seal_time') == 14   # 09:30封板=0min → seal_time_tiers 最高档
    assert 'seal_time' not in d_off['v3_breakdown']
    assert abs((s_on - s_off) - 14) < 1e-9


def test_sector_disabled_contributes_zero():
    k = make_klines(prior_lu=2)
    s_on, d_on = compute_score('600000', k, {'sector_count': 5}, config=cfg_with(SECTOR_ON))
    s_off, d_off = compute_score('600000', k, {'sector_count': 5}, config=cfg_with(DISABLED))
    assert d_on['v3_breakdown'].get('sector') == 12      # sector_tiers [[5,12],...]
    assert 'sector' not in d_off['v3_breakdown']
    assert abs((s_on - s_off) - 12) < 1e-9


# ---------- 5. 活跃度过滤开关 ----------

def test_activity_filter_disabled_admits_inactive_stock():
    """近1年无其他涨停的票: 过滤开启时被排除(None), 暂停后可评分"""
    k = make_klines(prior_lu=0)
    assert compute_score('600000', k, {}, config=cfg_with(ACTIVITY_ON)) == (None, None)
    assert compute_score('600000', k, {}, config=cfg_with(DISABLED))[0] is not None


def test_activity_filter_threshold_is_two():
    """阈值语义锁定: recent_lu=1 仍被拒, =2 才放行"""
    assert compute_score('600000', make_klines(prior_lu=1), {}, config=cfg_with(ACTIVITY_ON)) == (None, None)
    assert compute_score('600000', make_klines(prior_lu=2), {}, config=cfg_with(ACTIVITY_ON))[0] is not None


# ---------- 6. 关键不变量: sector_count 仍供 divergence 使用 ----------

def test_sector_count_still_available_when_sector_disabled():
    """板块加分停了, 但板块计数必须仍传递给 divergence(烂板回封=A体系规则)"""
    _t, items = full_breakdown('600000', make_klines(prior_lu=2), {'sector_count': 7},
                               config=cfg_with(DISABLED))
    row = [it for it in items if it[0] == '板块共振']
    assert row, 'full_breakdown 应仍输出板块共振行(仅分数归零)'
    assert row[0][1] == '7只', '板块计数不得因暂停加分而丢失'
    assert row[0][2] == 0
    assert any(it[0] == '分歧质量' for it in items), 'divergence 行不得被连带删除'


# ---------- 7. full_breakdown 与 compute_score 口径一致 ----------

def test_breakdown_matches_score_when_disabled():
    k = make_klines(prior_lu=2)
    det_raw = {'seal_time': '093000', 'sector_count': 5, 'zhaban': 0}
    sc, _ = compute_score('600000', k, det_raw, config=cfg_with(DISABLED))
    total, _items = full_breakdown('600000', k, det_raw, config=cfg_with(DISABLED))
    assert abs(sc - total) < 1e-9, f'compute_score={sc} 与 full_breakdown={total} 应一致'


def test_readd_factor_restores_old_score():
    """把三项全部移出 disabled_factors, 分数应高于暂停态(证明开关可逆)"""
    k = make_klines(prior_lu=2)
    raw = {'seal_time': '093000', 'sector_count': 5}
    s_off, _ = compute_score('600000', k, raw, config=cfg_with(DISABLED))
    s_all, d_all = compute_score('600000', k, raw, config=cfg_with([]))
    assert abs((s_all - s_off) - (14 + 12)) < 1e-9
    assert d_all['v3_breakdown']['seal_time'] == 14
    assert d_all['v3_breakdown']['sector'] == 12
