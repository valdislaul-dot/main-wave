"""
主升浪 V3.0 — GUI交易面板
用法: streamlit run scripts/daily/gui_dashboard.py
"""
import streamlit as st
import json, os, sys
from datetime import datetime
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scoring import load_config, step_score_asc, step_score_desc

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

st.set_page_config(page_title="主升浪 V3.0", page_icon="📈", layout="wide")

# ── 响应式CSS ──
st.markdown("""
<style>
    /* 全局缩小字体 */
    html { font-size: 14px; }
    .stMetric label { font-size: 0.75rem !important; }
    .stMetric [data-testid="stMetricValue"] { font-size: 1rem !important; }
    h1 { font-size: 1.5rem !important; }
    h2 { font-size: 1.2rem !important; }
    h3 { font-size: 1rem !important; }
    /* 表格紧凑 */
    .stDataFrame { font-size: 0.8rem !important; }
    /* 侧边栏缩小 */
    [data-testid="stSidebar"] { min-width: 200px !important; max-width: 220px !important; }
    /* 手机适配 */
    @media (max-width: 768px) {
        html { font-size: 12px; }
        .stMetric [data-testid="stMetricValue"] { font-size: 0.9rem !important; }
    }
</style>
""", unsafe_allow_html=True)

# ── 云端自动初始化: 用update_data增量下载涨停池标的K线 ──
import subprocess, glob
KLINE_DIR = os.path.join(BASE, 'data', 'backtest_kline')
KLINE_COUNT = len(glob.glob(os.path.join(KLINE_DIR, '*.json'))) if os.path.exists(KLINE_DIR) else 0

if KLINE_COUNT < 30:
    with st.spinner(f'🔧 首次运行, 下载K线中... ({KLINE_COUNT}只)'):
        try:
            from update_data import main as update_data
            update_data()
        except:
            # fallback: 拉涨停池数据至少能用
            pass
        KLINE_COUNT = len(glob.glob(os.path.join(KLINE_DIR, '*.json'))) if os.path.exists(KLINE_DIR) else 0
    if KLINE_COUNT >= 30:
        st.success(f'✅ K线就绪 ({KLINE_COUNT}只)')
        st.rerun()
    else:
        st.warning(f'⚠ K线较少({KLINE_COUNT}只), 涨停池标的可能缺数据')

@st.cache_data(ttl=3600)
def _load_kline(code, name):
    for d in [os.path.join(BASE, 'data', 'backtest_kline'), os.path.join(BASE, 'data', 'kline_data')]:
        if not os.path.exists(d): continue
        for fn in [f'{code}.json', f'{name}_{code}.json']:
            fp = os.path.join(d, fn)
            if os.path.exists(fp):
                with open(fp, 'r', encoding='utf-8') as f: return json.load(f)
        for fn in os.listdir(d):
            if fn.endswith(f'_{code}.json'):
                with open(os.path.join(d, fn), 'r', encoding='utf-8') as f: return json.load(f)
    return None

# ── 标题栏 ──
c1, c2 = st.columns([4, 1])
c1.title("📈 主升浪 V3.0")
cfg = load_config()
c2.caption(f"✅ V3 | 门槛≥{cfg['score_min']} | 止损-10%")

# ══════ 持仓 ══════
portfolio_path = os.path.join(BASE, 'logs', 'portfolio.json')
if os.path.exists(portfolio_path):
    with open(portfolio_path, 'r', encoding='utf-8') as f: pf = json.load(f)
    cash = pf.get('cash', 0); pos = pf.get('position')
    if pos:
        pos_value = pos['shares'] * pos.get('buy_price', 0)
        total = cash + pos_value
        metrics = [
            ("💰 总资产", f"{total:,.0f}"),
            ("📦 持仓", f"{pos['name']}({pos['code']})"),
            ("💵 现金", f"{cash:,.0f}"),
            ("📊 胜率", f"{pf.get('winning_trades',0)/pf.get('total_trades',1)*100:.0f}%"),
        ]
    else:
        metrics = [("💰 总资产", f"{cash:,.0f}"), ("📦 持仓", "空仓"), ("💵 现金", f"{cash:,.0f}"), ("📊 交易", f"{pf.get('total_trades',0)}笔")]
    cols = st.columns(4)
    for i, (label, val) in enumerate(metrics):
        cols[i].metric(label, val)
else:
    st.caption("📭 无持仓数据")

# ══════ 涨停池 ══════
st.divider()
st.subheader("🔴 涨停池")

zt_path = os.path.join(BASE, 'data', 'zt_pool_state.json')
if not os.path.exists(zt_path):
    st.warning("涨停池数据不存在，请先运行盘后流水线")
    st.stop()

with open(zt_path, 'r', encoding='utf-8') as f: state = json.load(f)
stocks = state.get('stocks', [])
st.caption(f"截至 {state.get('as_of_date', '?')} | {len(stocks)}只 | "
           f"1板:{sum(1 for s in stocks if s.get('limit_days',1)==1)} "
           f"2板:{sum(1 for s in stocks if s.get('limit_days',1)==2)} "
           f"3+:{sum(1 for s in stocks if s.get('limit_days',1)>=3)}")

# 评分计算
industries = Counter(s.get('industry','') for s in stocks)
scored = []
for s in stocks:
    code, name, ft = s['code'], s['name'], s.get('first_seal','')
    kls = _load_kline(code, name)
    if not kls or len(kls) < 25: continue

    o = float(kls[-1].get('open',0)); c = float(kls[-1].get('close',0))
    h = float(kls[-1].get('high',0)); l = float(kls[-1].get('low',0))
    v = float(kls[-1].get('volume',0))
    pc = float(kls[-2].get('close',0)) if len(kls) >= 2 else 0
    gap = (o-pc)/pc*100 if pc>0 else 0

    ma5 = sum(float(kls[j].get('volume',0)) for j in range(max(0,len(kls)-5),len(kls)))/min(len(kls),5)
    ma20 = sum(float(kls[j].get('volume',0)) for j in range(max(0,len(kls)-20),len(kls)))/min(len(kls),20)
    cons = s.get('limit_days',1)
    vr = v/ma5 if (cons>=2 and ma5>0) else (v/ma20 if ma20>0 else 1)

    one_line = False; true_one = False
    if h>0 and l>0:
        if abs(h-l)<0.001: true_one = one_line = True
        elif h>l:
            us = (h-max(o,c))/(h-l); body = abs(c-o)/(h-l)
            one_line = (us<0.1 and body<0.1)

    vr_sc = step_score_asc(vr, cfg['tables']['v3']['vr_tiers'])
    gap_sc = step_score_desc(gap, cfg['tables']['v3']['gap_tiers'])
    ol_sc = 20 if true_one else (10 if one_line else 0)
    cons_sc = -4 if cons<=1 else (10 if cons<=3 else 15)

    try:
        ftc = ft.replace(':',''); hh=int(ftc[:2]); mm=int(ftc[2:4])
        seal_sc = step_score_asc(max(0,(hh-9)*60+mm-30), cfg['seal_time_tiers'])
    except: seal_sc = 0

    breaks = s.get('break_times',0)
    try:
        lt = s.get('last_seal',ft).replace(':','')
        fst = int(lt[:2])*60+int(lt[2:4])
        if fst<=630: zha_sc = -breaks*2
        elif fst<=870: zha_sc = -breaks*6
        else: zha_sc = -breaks*(3 if vr<1.5 else (8 if vr<3.0 else 15))
    except: zha_sc = -breaks*5 if breaks>0 else 0

    sec_count = industries.get(s.get('industry',''),1)
    sec_sc = 12 if sec_count>=5 else (6 if sec_count>=3 else (2 if sec_count>=2 else 0))

    total = vr_sc + gap_sc + ol_sc + cons_sc + seal_sc + zha_sc + sec_sc
    scored.append({
        'code': code, 'name': name, 'score': total,
        'vr': vr_sc, 'gap': gap_sc, 'ol': ol_sc, 'cons': cons_sc,
        'seal': seal_sc, 'zha': zha_sc, 'sec': sec_sc,
        'ft': ft, 'industry': s.get('industry',''), 'limit_days': cons,
        'breaks': breaks, 'true_one': true_one, 'one_line': one_line,
        'vr_val': vr, 'gap_val': gap,
    })

scored.sort(key=lambda x: x['score'], reverse=True)

# 风控过滤
filtered = [r for r in scored
    if not r['true_one']
    and not (r['one_line'] and r['limit_days'] >= 4)
    and r['score'] >= cfg['score_min']]

# ── 紧凑表格显示 ──
tab1, tab2 = st.tabs([f"✅ 可买 ({len(filtered)}只)", f"📋 全部 ({len(scored)}只)"])

with tab1:
    if filtered:
        rows = []
        for i, r in enumerate(filtered[:30]):
            marker = "⭐" if i == 0 else ("🥈" if i == 1 else ("🥉" if i == 2 else str(i+1)))
            flags = ""
            if r['limit_days'] >= 4: flags += "⚠4板"
            if r['breaks'] >= 5: flags += f"💥{r['breaks']}炸"
            rows.append({
                '': marker, '代码': r['code'], '名称': r['name'],
                '评分': r['score'], '量比': f"{r['vr_val']:.1f}x",
                'Gap': f"{r['gap_val']:.1f}%", '连板': r['limit_days'],
                '封板': r['ft'][:5], '行业': r['industry'][:6], '⚠': flags,
            })
        st.dataframe(rows, use_container_width=True, height=min(len(rows)*38+38, 500),
                     column_config={'': st.column_config.TextColumn(width='small'),
                                    '⚠': st.column_config.TextColumn(width='small')})
    else:
        st.warning("无符合条件的候选")

with tab2:
    rows = []
    for r in scored:
        filt = '⛔一字' if r['true_one'] else ('⚠4板+' if r['one_line'] and r['limit_days']>=4 else '')
        rows.append({
            '代码': r['code'], '名称': r['name'], '评分': r['score'],
            '量比': f"{r['vr_val']:.1f}x", 'Gap': f"{r['gap_val']:.1f}%",
            '连板': r['limit_days'], '封板': r['ft'][:5], '行业': r['industry'][:6],
            '风控': filt,
            'V': r['vr'], 'G': r['gap'], '一': r['ol'],
            '连': r['cons'], '封': r['seal'], '炸': r['zha'], '板': r['sec'],
        })
    st.dataframe(rows, use_container_width=True, height=400,
                 column_config={'V': st.column_config.NumberColumn(width='small'),
                                'G': st.column_config.NumberColumn(width='small'),
                                '一': st.column_config.NumberColumn(width='small'),
                                '连': st.column_config.NumberColumn(width='small'),
                                '封': st.column_config.NumberColumn(width='small'),
                                '炸': st.column_config.NumberColumn(width='small'),
                                '板': st.column_config.NumberColumn(width='small')})

# ── 评分拆解 (仅Top3) ──
if filtered:
    with st.expander("📊 Top3 评分拆解"):
        for r in filtered[:3]:
            st.caption(f"**{r['name']}({r['code']})** — 总分 **{r['score']:.0f}**")
            cols = st.columns(7)
            cols[0].metric("量比", f"{r['vr']:+d}", help=f"vr={r['vr_val']:.2f}")
            cols[1].metric("Gap", f"{r['gap']:+d}")
            cols[2].metric("一字板", f"{r['ol']:+d}")
            cols[3].metric("连板", f"{r['cons']:+d}")
            cols[4].metric("封板时间", f"{r['seal']:+d}", help=r['ft'])
            cols[5].metric("炸板", f"{r['zha']:+d}")
            cols[6].metric("板块共振", f"{r['sec']:+d}")

# ══════ 交易记录 ══════
st.divider()
st.subheader("📝 交易记录")

journal_path = os.path.join(BASE, 'logs', 'trading_journal.json')
if os.path.exists(journal_path):
    with open(journal_path, 'r', encoding='utf-8') as f: journal = json.load(f)
    if journal:
        trades, buy_map = [], {}
        for e in journal:
            if e.get('action') == 'BUY': buy_map[e['code']] = e
            elif e.get('action') == 'SELL':
                b = buy_map.get(e['code'], {})
                trades.append({
                    '买入': b.get('date',''), '卖出': e.get('date',''),
                    '代码': e.get('code',''), '名称': e.get('name',''),
                    '买价': b.get('price',0), '卖价': e.get('price',0),
                    '盈亏': f"{e.get('pnl_pct', 0):+.1f}%",
                })
        if trades:
            st.dataframe(trades, use_container_width=True, height=min(len(trades)*38+38, 300))
            total_pnl = sum(j.get('pnl_amt', 0) for j in journal if j.get('action') == 'SELL')
            st.caption(f"累计盈亏: **{total_pnl:+,.0f}**")
        else:
            st.caption("暂无交易记录")

# ── 侧边栏 ──
with st.sidebar:
    if st.button("🔄 刷新涨停池", use_container_width=True):
        with st.spinner("拉取涨停数据+评分..."):
            # 只做轻量操作: 拉涨停池 + 更新状态 (跳过K线下载/T字板分钟数据)
            r = subprocess.run([
                sys.executable, '-c', '''
import sys; sys.path.insert(0, "scripts/daily")
from zt_pool import update_zt_pool
update_zt_pool()
'''], cwd=BASE, capture_output=True, text=True, timeout=60)
            st.success("完成! 刷新页面查看")
            st.rerun()
    st.divider()
    st.caption("主升浪 V3.0 | 3年回测+2,734%")
