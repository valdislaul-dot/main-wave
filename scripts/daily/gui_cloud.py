"""
主升浪 V4.1 — 云端只读面板 (Streamlit Cloud / 多端用)
=====================================================
只读 GitHub 上已同步的快照, 不依赖 data/kline_data(未上云) 和实时行情(海外IP受限)。

数据源(均由本地 sync_cloud.py 定时 push, 2026-08-31隐私约定: 仅行情数据):
  - data/zt_pool_state.json          涨停池(连板/封板/炸板/换手)
  - data/auction_state.json          竞价状态(含可买标的+评分)
  - data/market_state.json           市场温度(涨停家数/最高板/赚钱效应)
  - data/auction/*.json              每日竞价快照
  (持仓/交易/候选/推荐 按约定不上云, 仅本地GUI可见)

用法: streamlit run scripts/daily/gui_cloud.py
"""
import streamlit as st
import json, os, glob
from datetime import datetime
from collections import Counter

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(BASE, 'data')

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


# ══════ 标题 ══════
now = datetime.now()
wd = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][now.weekday()]
zt_state = _load(os.path.join(DATA_DIR, 'zt_pool_state.json'))
updated = (zt_state or {}).get('last_updated', '?') if zt_state else '?'
st.title("☁️ 主升浪 · 云端")
st.caption(f"{now.strftime('%Y-%m-%d')} {wd} | 快照更新: {updated} | 只读(数据由本地定时同步)")
st.info("🔒 持仓/交易/候选按隐私约定不上云 — 查看持仓请开本地GUI(gui_dashboard)。本页仅盘面行情。")

# ══════ 市场温度 ══════
ms = _load(os.path.join(DATA_DIR, 'market_state.json'))
if ms:
    st.subheader(f"🌡️ 市场温度 (截至 {ms.get('date', '?')})")
    m = st.columns(4)
    m[0].metric("涨停家数", f"{ms.get('zt_n', '?')}")
    m[1].metric("最高板", f"{ms.get('max_cons', '?')}板")
    m[2].metric("赚钱效应", f"{ms.get('money_effect', 0):+.1f}%")
    tier = ms.get('zt_n', 0)
    tier_txt = '强市(≥110)' if tier >= 110 else ('弱市(40-109)' if tier >= 40 else '极弱(<40)')
    m[3].metric("温度档", tier_txt)
    hist = ms.get('history', [])
    if hist:
        st.caption("近" + str(len(hist)) + "日涨停家数: " +
                   " ".join(f"{h['date'][5:]}:{h['zt_n']}" for h in hist[-10:]))
else:
    st.info("无温度快照")

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
