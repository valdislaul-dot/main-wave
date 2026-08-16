"""
主升浪 V4.1 — 云端只读面板 (Streamlit Cloud / 多端用)
=====================================================
只读 GitHub 上已同步的快照, 不依赖 data/kline_data(未上云) 和实时行情(海外IP受限)。

数据源(均由本地 sync_cloud.py 定时 push):
  - logs/portfolio.json              持仓(多持仓)
  - data/zt_pool_state.json          涨停池(连板/封板/炸板/换手)
  - data/auction_state.json          竞价状态(含可买标的+评分)
  - logs/candidates_*.json           盘后候选评分
  - logs/trading_journal.json        交易记录
  - logs/recommendation_review.json  推荐回看

用法: streamlit run scripts/daily/gui_cloud.py
"""
import streamlit as st
import json, os, glob
from datetime import datetime
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE, 'data')
LOG_DIR = os.path.join(BASE, 'logs')

st.set_page_config(page_title="主升浪 · 云端", page_icon="☁️", layout="wide")
st.markdown("""<style>
html{font-size:14px}
h1{font-size:1.4rem!important}
h2{font-size:1.15rem!important}
.stDataFrame{font-size:.8rem!important}
.stMetric [data-testid="stMetricValue"]{font-size:1.1rem!important}
@media(max-width:768px){html{font-size:12px}}
</style>""", unsafe_allow_html=True)


@st.cache_data(ttl=120)
def _load(p):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _latest(path_pattern):
    files = sorted(glob.glob(path_pattern))
    return files[-1] if files else None


# ══════ 标题 ══════
now = datetime.now()
wd = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][now.weekday()]
zt_state = _load(os.path.join(DATA_DIR, 'zt_pool_state.json'))
updated = (zt_state or {}).get('last_updated', '?') if zt_state else '?'
st.title("☁️ 主升浪 · 云端")
st.caption(f"{now.strftime('%Y-%m-%d')} {wd} | 快照更新: {updated} | 只读(数据由本地定时同步)")

# ══════ 持仓 ══════
pf = _load(os.path.join(LOG_DIR, 'portfolio.json'))
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
    m[0].metric("总资产", f"{total:,.0f}")
    m[1].metric("现金", f"{cash:,.0f}")
    m[2].metric("胜率", f"{win_rate:.0f}%")
    m[3].metric("累计盈亏", f"{pf.get('total_pnl', 0):+,.0f}")
    if positions:
        st.dataframe([{'代码': p['code'], '名称': p['name'], '成本': f"{p['buy_price']:.3f}",
                       '股数': p['shares'], '买入日': p.get('buy_date', '?')} for p in positions],
                     width='stretch', hide_index=True)
else:
    st.info("无持仓快照")

st.divider()

# ══════ 竞价可买 ══════
auction_state = _load(os.path.join(DATA_DIR, 'auction_state.json'))
if auction_state:
    cur = auction_state.get('current', {})
    st.subheader(f"🎯 竞价可买 (采集 {cur.get('captured', '?')})")
    buyable = cur.get('buyable_stocks', [])
    if buyable:
        st.dataframe([{'名称': b['name'], '代码': b['code'], '评分': f"{b['score']:.0f}",
                       '竞价gap': f"{b['gap_pct']:+.1f}%", '连板': b.get('limit_days', '?')}
                      for b in buyable],
                     width='stretch', hide_index=True)
    else:
        st.caption("当日无可买标的")
    gapd = cur.get('gap_distribution', {})
    if gapd:
        st.caption("竞价gap分布: " + " ".join(f"{k}:{v}" for k, v in gapd.items()))
else:
    st.info("无竞价快照")

st.divider()

# ══════ 盘后候选 ══════
cand_file = _latest(os.path.join(LOG_DIR, 'candidates_*.json'))
if cand_file:
    cand = _load(cand_file)
    st.subheader(f"📊 盘后候选 (T-1={cand.get('date', '?')})")
    cands = [c for c in cand.get('candidates', []) if not c.get('true_one_line')]
    if cands:
        st.dataframe([{'名称': c['name'], '代码': c['code'], '评分': f"{c['score']:.0f}",
                       '量比': f"{c.get('vr20', 0):.1f}x", 'Gap': f"{c.get('gap', 0):.1f}%",
                       '连板': c.get('cons', '?'), '封板': str(c.get('seal_time', ''))[:5],
                       '行业': c.get('industry', '')[:6]} for c in cands[:30]],
                     width='stretch', hide_index=True)
else:
    st.info("无盘后候选快照")

st.divider()

# ══════ 涨停池 ══════
if zt_state:
    stocks = zt_state.get('stocks', [])
    st.subheader(f"🔴 涨停池 (截至 {zt_state.get('as_of_date', '?')})")
    industries = Counter(s.get('industry', '') for s in stocks)
    st.caption(f"{len(stocks)} 只 | 热门: " + ", ".join(f"{k}({v})" for k, v in industries.most_common(5)))
    st.dataframe([{'名称': s['name'], '代码': s['code'], '连板': s.get('limit_days', 1),
                   '收盘': s.get('close', 0), '封板': str(s.get('first_seal', ''))[:5],
                   '炸板': s.get('break_times', 0), '换手': f"{s.get('turnover', 0):.1f}%",
                   '行业': s.get('industry', '')[:6]} for s in stocks],
                 width='stretch', hide_index=True, height=420)
else:
    st.info("无涨停池快照")

st.divider()

# ══════ 交易记录 + 推荐回看 ══════
jn = _load(os.path.join(LOG_DIR, 'trading_journal.json'))
if jn:
    st.subheader("📝 交易记录")
    trades, bm = [], {}
    for e in jn:
        if e.get('action') == 'BUY':
            bm[e['code']] = e
        elif e.get('action') == 'SELL':
            b = bm.get(e['code'], {})
            trades.append({'买入': b.get('date', ''), '卖出': e.get('date', ''),
                           '名称': e.get('name', ''), '买价': b.get('price', 0),
                           '卖价': e.get('price', 0), '盈亏': f"{e.get('pnl_pct', 0):+.1f}%"})
    if trades:
        st.dataframe(trades, width='stretch', hide_index=True)

rr = _load(os.path.join(LOG_DIR, 'recommendation_review.json'))
if rr and rr.get('stats'):
    s = rr['stats']
    st.subheader("🎯 推荐回看")
    st.caption(f"累计 {s.get('total', 0)} 只 | 胜率 {s.get('win_rate', 0)}% | 平均 {s.get('avg_pnl', 0):+.2f}%")
