"""
主升浪 V4.1 — GUI 交易面板 (本地完整版)
用法: streamlit run scripts/daily/gui_dashboard.py

本地版能力:
  - 实时评分(读 data/kline_data)
  - 一键刷新(跑 run_pipeline --fast)
  - 多持仓 + 竞价决策 + 涨停池 + 交易记录
"""
import streamlit as st
import json, os, sys, glob, subprocess
from datetime import datetime
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import morning_check as mc
from scoring import load_config, compute_score

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')
DATA_DIR = os.path.join(BASE, 'data')
LOG_DIR = os.path.join(BASE, 'logs')

st.set_page_config(page_title="主升浪 V4.1", page_icon="📈", layout="wide")

# ── CSS (移动端适配) ──
st.markdown("""<style>
html{font-size:14px}
.stMetric label{font-size:.75rem!important}
.stMetric [data-testid="stMetricValue"]{font-size:1rem!important}
h1{font-size:1.4rem!important}
h2{font-size:1.15rem!important}
h3{font-size:1rem!important}
.stDataFrame{font-size:.8rem!important}
@media(max-width:768px){html{font-size:12px}}
</style>""", unsafe_allow_html=True)


# ══════ 数据加载 ══════
@st.cache_data(ttl=300)
def _load_json(p):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _load_klines(code, name):
    """K线: 优先 {code}.json, 回退 {name}_{code}.json"""
    for fn in [f'{code}.json', f'{name}_{code}.json']:
        fp = os.path.join(KLINE_DIR, fn)
        if os.path.exists(fp):
            raw = _load_json(fp)
            if raw is not None:
                return raw.get('data', raw) if isinstance(raw, dict) else raw
    # 回退: 扫 {name}_{code}.json
    for fn in glob.glob(os.path.join(KLINE_DIR, f'*_{code}.json')):
        raw = _load_json(fn)
        if raw is not None:
            return raw.get('data', raw) if isinstance(raw, dict) else raw
    return None


def _auction_snapshot():
    """最新竞价快照 → dict 或 None"""
    today = datetime.now().strftime('%Y-%m-%d')
    fp = os.path.join(DATA_DIR, 'auction', f'{today}.json')
    if os.path.exists(fp):
        return _load_json(fp)
    files = sorted(glob.glob(os.path.join(DATA_DIR, 'auction', '*.json')))
    return _load_json(files[-1]) if files else None


# ══════ 标题栏 ══════
now = datetime.now()
wd = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][now.weekday()]
cfg = load_config()

c1, c2, c3 = st.columns([3, 1.2, 1])
c1.title("📈 主升浪 V4.1")
c2.markdown(f"<div style='text-align:center;font-size:1.3rem;font-weight:bold;margin-top:14px'>"
            f"{now.strftime('%m月%d日')} {wd}</div>", unsafe_allow_html=True)
c2.caption(f"V3评分 | ≥{cfg['score_min']}分 | 竞价4-8%")

if c3.button("🔄 刷新数据", width='stretch'):
    with st.spinner("拉涨停池+评分(轻量)..."):
        r = subprocess.run(
            [sys.executable, 'scripts/daily/run_pipeline.py', '--fast'],
            cwd=BASE, capture_output=True, text=True, timeout=180)
        st.success("完成!" if r.returncode == 0 else f"部分失败(见日志)")
    st.rerun()

# ══════ 持仓 (多持仓) ══════
pf = _load_json(os.path.join(LOG_DIR, 'portfolio.json'))
if pf:
    positions = pf.get('positions', [])
    if not positions and pf.get('position'):
        positions = [pf['position']]
    cash = pf.get('cash', 0)
    pos_val = sum(p['shares'] * p['buy_price'] for p in positions)
    total = cash + pos_val
    win_rate = (pf.get('winning_trades', 0) / pf.get('total_trades', 1) * 100
                if pf.get('total_trades') else 0)

    m = st.columns(4)
    m[0].metric("💰总资产", f"{total:,.0f}")
    m[1].metric("💵现金", f"{cash:,.0f}")
    m[2].metric("📊胜率", f"{win_rate:.0f}%")
    m[3].metric("累计盈亏", f"{pf.get('total_pnl', 0):+,.0f}")

    if positions:
        st.markdown("**📦 持仓**")
        rows = [{'代码': p['code'], '名称': p['name'], '成本': f"{p['buy_price']:.3f}",
                 '股数': p['shares'], '买入日': p.get('buy_date', '?')}
                for p in positions]
        st.dataframe(rows, width='stretch', hide_index=True)
else:
    st.info("无持仓数据")

st.divider()

# ══════ 市场环境评级 ══════
ztp = os.path.join(DATA_DIR, 'zt_pool_state.json')
zt_state = _load_json(ztp)
zt_stocks = zt_state.get('stocks', []) if zt_state else []

if zt_stocks:
    zt_n = len(zt_stocks)
    max_cons = max((int(s.get('limit_days', 1) or 1) for s in zt_stocks), default=1)
    if zt_n < 40 or max_cons <= 2:
        env, advice = '🌡️ 弱市', '观望/1-3仓'
    elif zt_n >= 70 and max_cons >= 5:
        env, advice = '🌡️ 强势', '按评分仓位映射'
    else:
        env, advice = '🌡️ 正常', '常规仓位'
    st.markdown(f"**{env}**：昨日涨停 {zt_n} 只，最高 {max_cons} 板 → {advice}")
else:
    st.caption("暂无涨停池数据，点🔄刷新")

# ══════ 竞价决策区 ══════
auc = _auction_snapshot()
if auc:
    st.subheader("🎯 竞价决策")
    astocks = auc.get('stocks', [])
    captured = auc.get('captured', '?')

    # 可买前三 (评分≥10, 竞价4-8%, 已过滤一字/4板+一字/300·688)
    buyable = []
    for s in astocks:
        code = s.get('code', '')
        gap = s.get('gap_pct', 0)
        if code.startswith(('300', '301', '688', '8', '9')):
            continue
        if s.get('one_line') or s.get('high_risk'):
            continue
        if not (4.0 <= gap <= 8.0):
            continue
        # 现场评分(复用morning_check, 消除盲区), 失败退回快照分
        score = s.get('score', 0)
        try:
            meta = mc.stock_scoring_meta(code)
            if meta.get('score') is not None:
                score = meta['score']
        except Exception:
            pass
        if score < cfg['score_min']:
            continue
        buyable.append({'code': code, 'name': s.get('name', ''), 'gap': gap,
                        'score': score, 'limit_days': s.get('limit_days', '?')})
    buyable.sort(key=lambda x: x['score'], reverse=True)

    c1, c2 = st.columns([2, 1])
    with c1:
        if buyable:
            top3 = buyable[:3]
            st.markdown(f"**可买前三**（采集 {captured}，评分≥{cfg['score_min']}）")
            rows = [{'#': i + 1, '名称': b['name'], '代码': b['code'],
                     '评分': f"{b['score']:.0f}", '竞价gap': f"{b['gap']:+.1f}%",
                     '连板': b['limit_days']}
                    for i, b in enumerate(top3)]
            st.dataframe(rows, width='stretch', hide_index=True)
        else:
            st.caption("无可买标的（评分≥10 且竞价4-8%）")
    with c2:
        st.markdown("**盘中买点参考**")
        st.caption("半路: 拉升破7%才追\n\n低吸①: 开盘价-7%急跌\n\n低吸②: 较开盘-10%\n\n⚠9:25后挂单受价格笼子(卖一×102%)")
else:
    st.caption("暂无竞价快照")

st.divider()

# ══════ 涨停池 (实时评分) ══════
st.subheader("🔴 涨停池")
if zt_stocks:
    industries = Counter(s.get('industry', '') for s in zt_stocks)
    scored = []
    no_kline = 0
    for s in zt_stocks:
        code, name = s['code'], s['name']
        kls = _load_klines(code, name)
        if not kls or len(kls) < 25:
            no_kline += 1
            continue
        pool_date = zt_state.get('as_of_date', '')
        if kls[-1].get('date', '') < pool_date and len(kls) >= 2:
            prev_c = kls[-1].get('close', 0)
            lp = 0.2 if code.startswith(('30', '688')) else 0.1
            lu_price = round(prev_c * (1 + lp), 2)
            kls.append({'date': pool_date, 'open': lu_price, 'high': lu_price,
                        'low': round(prev_c * 0.99, 2), 'close': lu_price,
                        'volume': kls[-1].get('volume', 1e8)})
        ft = s.get('first_seal', '')
        details = {
            'seal_time': ft.replace(':', '') if ft else '1459',
            'final_seal_time': (s.get('last_seal', ft) or ft).replace(':', ''),
            'zhaban': s.get('break_times', 0),
            'sector_count': industries.get(s.get('industry', ''), 1),
        }
        try:
            score, det = compute_score(code, kls, details, 'v3', cfg)
        except Exception:
            continue
        if score is None:
            continue
        scored.append({'code': code, 'name': name, 'score': score, 'ft': ft,
                       'industry': s.get('industry', ''), 'limit_days': det.get('cons', 1),
                       'breaks': s.get('break_times', 0),
                       'true_one': det.get('true_one_line', False),
                       'one_line': det.get('one_line', False),
                       'vr': det.get('vr20', 1), 'gap': det.get('gap', 0),
                       'turnover': s.get('turnover', 0)})

    scored.sort(key=lambda x: x['score'], reverse=True)
    filtered = [r for r in scored if not r['true_one']
                and not (r['one_line'] and r['limit_days'] >= 4)
                and r['score'] >= cfg['score_min']]

    st.caption(f"池 {len(zt_stocks)} 只 | 有K线 {len(scored)} 只 | 缺K线 {no_kline} 只")
    tab1, tab2 = st.tabs([f"✅ 可买({len(filtered)})", f"📋 全部({len(scored)})"])
    with tab1:
        if filtered:
            rows = [{'名称': r['name'], '代码': r['code'], '评分': f"{r['score']:.0f}",
                     '量比': f"{r['vr']:.1f}x", 'Gap': f"{r['gap']:.1f}%",
                     '连板': r['limit_days'], '封板': r['ft'][:5],
                     '换手': f"{r['turnover']:.1f}%", '行业': r['industry'][:6]}
                    for r in filtered[:40]]
            st.dataframe(rows, width='stretch', hide_index=True)
        else:
            st.warning("无符合条件候选")
    with tab2:
        rows = [{'名称': r['name'], '代码': r['code'], '评分': f"{r['score']:.0f}",
                 '量比': f"{r['vr']:.1f}x", 'Gap': f"{r['gap']:.1f}%",
                 '连板': r['limit_days'], '封板': r['ft'][:5], '行业': r['industry'][:6],
                 '风控': '⛔一字' if r['true_one'] else ('⚠4板+' if r['one_line'] and r['limit_days'] >= 4 else '')}
                for r in scored]
        st.dataframe(rows, width='stretch', hide_index=True)
else:
    st.info("无涨停池数据，点🔄刷新")

st.divider()

# ══════ 交易记录 ══════
st.subheader("📝 交易记录")
jn = _load_json(os.path.join(LOG_DIR, 'trading_journal.json'))
if jn:
    trades, bm = [], {}
    for e in jn:
        if e.get('action') == 'BUY':
            bm[e['code']] = e
        elif e.get('action') == 'SELL':
            b = bm.get(e['code'], {})
            trades.append({'买入': b.get('date', ''), '卖出': e.get('date', ''),
                           '代码': e.get('code', ''), '名称': e.get('name', ''),
                           '买价': b.get('price', 0), '卖价': e.get('price', 0),
                           '盈亏': f"{e.get('pnl_pct', 0):+.1f}%"})
    if trades:
        st.dataframe(trades, width='stretch', hide_index=True)
        tp = sum(j.get('pnl_amt', 0) for j in jn if j.get('action') == 'SELL')
        st.caption(f"累计盈亏: **{tp:+,.0f}**")
