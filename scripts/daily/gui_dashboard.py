"""
主升浪 V3.0 — GUI交易面板
用法: streamlit run scripts/daily/gui_dashboard.py
"""
import streamlit as st
import json, os, sys, tarfile, glob, subprocess as sp
from datetime import datetime
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scoring import load_config, compute_score

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIR = os.path.join(BASE, 'data', 'backtest_kline')

st.set_page_config(page_title="主升浪 V3.0", page_icon="📈", layout="wide")

# ── CSS ──
st.markdown("""<style>
html{font-size:14px}
.stMetric label{font-size:.75rem!important}
.stMetric [data-testid="stMetricValue"]{font-size:1rem!important}
h1{font-size:1.5rem!important}
h2{font-size:1.2rem!important}
h3{font-size:1rem!important}
.stDataFrame{font-size:.8rem!important}
[data-testid="stSidebar"]{display:none!important}
@media(max-width:768px){html{font-size:12px}.stMetric [data-testid="stMetricValue"]{font-size:.9rem!important}}
</style>""", unsafe_allow_html=True)

# ── 云端初始化: 解压K线包 ──
KLINE_COUNT = len(glob.glob(os.path.join(KLINE_DIR, '*.json'))) if os.path.exists(KLINE_DIR) else 0
if KLINE_COUNT < 200:
    tgz = os.path.join(BASE, 'kline_data.tar.gz')
    if os.path.exists(tgz):
        with st.spinner('解压K线数据包...'):
            os.makedirs(KLINE_DIR, exist_ok=True)
            with tarfile.open(tgz, 'r:gz') as tar:
                for m in tar.getmembers():
                    if m.name.endswith('.json'):
                        m.name = os.path.basename(m.name)
                        tar.extract(m, KLINE_DIR)
            KLINE_COUNT = len(glob.glob(os.path.join(KLINE_DIR, '*.json')))
        if KLINE_COUNT >= 200:
            st.success(f'K线就绪({KLINE_COUNT}只)')
            st.rerun()

@st.cache_data(ttl=3600)
def _load_kline(code, name):
    for d in [KLINE_DIR, os.path.join(BASE, 'data', 'kline_data')]:
        if not os.path.exists(d): continue
        for fn in [f'{code}.json', f'{name}_{code}.json']:
            fp = os.path.join(d, fn)
            if os.path.exists(fp):
                with open(fp, encoding='utf-8') as f: return json.load(f)
        for fn in os.listdir(d):
            if fn.endswith(f'_{code}.json'):
                with open(os.path.join(d, fn), encoding='utf-8') as f: return json.load(f)
    return None

# ══════ 标题栏 ══════
now = datetime.now()
wd = ['周一','周二','周三','周四','周五','周六','周日'][now.weekday()]
c1, c2, c3 = st.columns([3, 1, 1])
c1.title("📈 主升浪 V3.0")
cfg = load_config()
c2.markdown(f"<div style='text-align:center;font-size:1.4rem;font-weight:bold;margin-top:15px'>"
            f"{now.strftime('%m月%d日')} {wd}</div>", unsafe_allow_html=True)
c2.caption(f"V3 | >= {cfg['score_min']} |  -10%")

if c3.button("🔄 刷新数据", use_container_width=True):
    with st.spinner("拉涨停池+更新K线(仅最新日)..."):
        today = datetime.now().strftime('%Y-%m-%d')
        # 1. 拉涨停池
        sp.run([sys.executable, '-c',
            'import sys; sys.path.insert(0,"scripts/daily"); from zt_pool import update_zt_pool; update_zt_pool()'],
            cwd=BASE, capture_output=True, text=True, timeout=60)
        # 2. 对新标的下载完整K线, 已有标的只追加最新日
        ztp = os.path.join(BASE, 'data', 'zt_pool_state.json')
        codes = []
        if os.path.exists(ztp):
            with open(ztp, encoding='utf-8') as f:
                codes = [s['code'] for s in json.load(f).get('stocks', [])]
        if codes:
            # 区分新标的(无文件) vs 已有标的(只追加最后一天)
            new_codes = [c for c in codes if not os.path.exists(os.path.join(KLINE_DIR, f'{c}.json'))]
            old_codes = [c for c in codes if c not in new_codes]
            msg = f'新{len(new_codes)}只+更新{len(old_codes)}只...'
            st.info(msg)
            sp.run([sys.executable, '-c', f'''
import baostock as bs, json, os
bs.login()
new_codes = {repr(new_codes)}
old_codes = {repr(old_codes)}
today = "{today}"
out_dir = r"{KLINE_DIR}"
os.makedirs(out_dir, exist_ok=True)

# 新标的: 下载完整3年K线
for c in new_codes:
    bc = "sh."+c if c.startswith("6") else "sz."+c
    rs = bs.query_history_k_data_plus(bc, "date,open,high,low,close,volume",
        start_date="2023-08-04", end_date=today, frequency="d", adjustflag="2")
    rows = []
    while rs.next():
        r2 = rs.get_row_data()
        if r2[0]: rows.append({{"date":r2[0],"open":round(float(r2[1]),2),"high":round(float(r2[2]),2),"low":round(float(r2[3]),2),"close":round(float(r2[4]),2),"volume":float(r2[5]) if r2[5] else 0}})
    if rows: json.dump(rows, open(os.path.join(out_dir, f"{{c}}.json"), "w"), ensure_ascii=False)

# 已有标的: 只更新最近7天(快速追加)
for c in old_codes:
    old_path = os.path.join(out_dir, f"{{c}}.json")
    old_data = json.load(open(old_path)) if os.path.exists(old_path) else []
    last_date = old_data[-1]["date"] if old_data else "2023-08-04"
    bc = "sh."+c if c.startswith("6") else "sz."+c
    rs = bs.query_history_k_data_plus(bc, "date,open,high,low,close,volume",
        start_date=last_date, end_date=today, frequency="d", adjustflag="2")
    new_rows = []
    while rs.next():
        r2 = rs.get_row_data()
        if r2[0] and r2[0] > last_date:
            new_rows.append({{"date":r2[0],"open":round(float(r2[1]),2),"high":round(float(r2[2]),2),"low":round(float(r2[3]),2),"close":round(float(r2[4]),2),"volume":float(r2[5]) if r2[5] else 0}})
    if new_rows:
        json.dump(old_data + new_rows, open(old_path, "w"), ensure_ascii=False)
bs.logout()
'''], cwd=BASE, capture_output=True, text=True, timeout=120)
        st.success("完成!")
        st.rerun()

# ══════ 持仓 ══════
pfp = os.path.join(BASE, 'logs', 'portfolio.json')
if os.path.exists(pfp):
    with open(pfp, encoding='utf-8') as f: pf = json.load(f)
    cash = pf.get('cash', 0); pos = pf.get('position')
    if pos:
        tv = cash + pos['shares'] * pos.get('buy_price', 0)
        ms = [("💰总资产", f"{tv:,.0f}"), ("📦持仓", f"{pos['name']}({pos['code']})"),
              ("💵现金", f"{cash:,.0f}"),
              ("📊胜率", f"{pf.get('winning_trades',0)/pf.get('total_trades',1)*100:.0f}%")]
    else:
        ms = [("💰总资产", f"{cash:,.0f}"), ("📦持仓", "空仓")]
    for i, (l, v) in enumerate(ms):
        st.columns(len(ms))[i].metric(l, v)

# ══════ 涨停池 ══════
st.divider()
st.subheader("🔴 涨停池")

ztp = os.path.join(BASE, 'data', 'zt_pool_state.json')
if not os.path.exists(ztp):
    st.warning("无涨停池数据，请点刷新")
    st.stop()

with open(ztp, encoding='utf-8') as f: state = json.load(f)
stocks = state.get('stocks', [])
n1 = sum(1 for s in stocks if s.get('limit_days',1)==1)
n2 = sum(1 for s in stocks if s.get('limit_days',1)==2)
n3 = sum(1 for s in stocks if s.get('limit_days',1)>=3)
st.caption(f"截至{state.get('as_of_date','?')} | {len(stocks)}只 | 1板:{n1} 2板:{n2} 3+:{n3}")

industries = Counter(s.get('industry','') for s in stocks)
scored = []
for s in stocks:
    code, name = s['code'], s['name']
    kls = _load_kline(code, name)
    if not kls or len(kls) < 25: continue

    ft = s.get('first_seal','')
    lt = s.get('last_seal', ft)
    details_raw = {
        'seal_time': ft.replace(':','') if ft else '1459',
        'final_seal_time': lt.replace(':','') if lt else '1459',
        'zhaban': s.get('break_times', 0),
        'sector_count': industries.get(s.get('industry',''), 1),
    }
    try:
        score, det = compute_score(code, kls, details_raw, 'v3', cfg)
    except Exception:
        continue
    if score is None: continue

    scored.append({
        'code': code, 'name': name, 'score': score,
        'ft': ft, 'industry': s.get('industry',''),
        'limit_days': det.get('cons',1),
        'breaks': s.get('break_times',0),
        'true_one': det.get('true_one_line',False),
        'one_line': det.get('one_line',False),
        'vr_val': det.get('vr20',1),
        'gap_val': det.get('gap',0),
    })

scored.sort(key=lambda x: x['score'], reverse=True)
filtered = [r for r in scored if not r['true_one']
    and not (r['one_line'] and r['limit_days']>=4)
    and r['score'] >= cfg['score_min']]

tab1, tab2 = st.tabs([f"✅ 可买({len(filtered)})", f"📋 全部({len(scored)})"])

with tab1:
    if filtered:
        rows = []
        for i, r in enumerate(filtered[:30]):
            m = "⭐" if i==0 else ("🥈" if i==1 else ("🥉" if i==2 else str(i+1)))
            fg = ""
            if r['limit_days']>=4: fg += "⚠4板"
            if r['breaks']>=5: fg += f"💥{r['breaks']}炸"
            rows.append({'':m, '代码':r['code'], '名称':r['name'], '评分':f"{r['score']:.0f}",
                '量比':f"{r['vr_val']:.1f}x", 'Gap':f"{r['gap_val']:.1f}%",
                '连板':r['limit_days'], '封板':r['ft'][:5], '行业':r['industry'][:6], '⚠':fg})
        st.dataframe(rows, use_container_width=True, height=min(len(rows)*38+38, 500))
    else:
        st.warning("无符合条件候选")

with tab2:
    rows = []
    for r in scored:
        fl = '⛔一字' if r['true_one'] else ('⚠4板+' if r['one_line'] and r['limit_days']>=4 else '')
        rows.append({'代码':r['code'], '名称':r['name'], '评分':f"{r['score']:.0f}",
            '量比':f"{r['vr_val']:.1f}x", 'Gap':f"{r['gap_val']:.1f}%",
            '连板':r['limit_days'], '封板':r['ft'][:5], '行业':r['industry'][:6], '风控':fl})
    st.dataframe(rows, use_container_width=True, height=400)

# ══════ 交易记录 ══════
st.divider()
st.subheader("📝 交易记录")
jfp = os.path.join(BASE, 'logs', 'trading_journal.json')
if os.path.exists(jfp):
    with open(jfp, encoding='utf-8') as f: jn = json.load(f)
    if jn:
        trades, bm = [], {}
        for e in jn:
            if e.get('action')=='BUY': bm[e['code']]=e
            elif e.get('action')=='SELL':
                b = bm.get(e['code'],{})
                trades.append({'买入':b.get('date',''),'卖出':e.get('date',''),
                    '代码':e.get('code',''),'名称':e.get('name',''),
                    '买价':b.get('price',0),'卖价':e.get('price',0),
                    '盈亏':f"{e.get('pnl_pct',0):+.1f}%"})
        if trades:
            st.dataframe(trades, use_container_width=True)
            tp = sum(j.get('pnl_amt',0) for j in jn if j.get('action')=='SELL')
            st.caption(f"累计盈亏: **{tp:+,.0f}**")
