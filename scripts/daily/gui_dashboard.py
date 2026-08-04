"""
主升浪 V3.0 — GUI交易面板
用法: streamlit run scripts/daily/gui_dashboard.py
"""
import streamlit as st
import json, os, sys
from datetime import datetime, timedelta
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scoring import load_config, score_v3, score_to_prob, score_to_position, get_buy_window, step_score_asc, step_score_desc, is_limit_up, get_lp

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

st.set_page_config(page_title="主升浪 V3.0", page_icon="📈", layout="wide")

# ── 云端自动初始化 ──
import subprocess, glob
KLINE_DIR = os.path.join(BASE, 'data', 'backtest_kline')
KLINE_COUNT = len(glob.glob(os.path.join(KLINE_DIR, '*.json'))) if os.path.exists(KLINE_DIR) else 0

if KLINE_COUNT < 100:
    with st.spinner(f'🔧 首次运行 — 正在下载全市场K线数据... (当前{KLINE_COUNT}只, 需要≥100只)'):
        import subprocess
        r = subprocess.run(
            [sys.executable, os.path.join(BASE, 'scripts', 'daily', 'fetch_backtest_klines.py')],
            cwd=BASE, capture_output=True, text=True, timeout=900)
        KLINE_COUNT = len(glob.glob(os.path.join(KLINE_DIR, '*.json'))) if os.path.exists(KLINE_DIR) else 0
    if KLINE_COUNT >= 100:
        st.success(f'✅ K线数据就绪 ({KLINE_COUNT}只)')
        st.rerun()
    else:
        st.error(f'❌ K线下载失败 ({KLINE_COUNT}只), 请检查baostock连接')

@st.cache_data(ttl=3600)
def _load_kline(code, name):
    for d in [os.path.join(BASE, 'data', 'backtest_kline'), os.path.join(BASE, 'data', 'kline_data')]:
        if not os.path.exists(d): continue
        for fn in [f'{code}.json', f'{name}_{code}.json']:
            fp = os.path.join(d, fn)
            if os.path.exists(fp):
                with open(fp, 'r', encoding='utf-8') as f:
                    return json.load(f)
        for fn in os.listdir(d):
            if fn.endswith(f'_{code}.json'):
                with open(os.path.join(d, fn), 'r', encoding='utf-8') as f:
                    return json.load(f)
    return None

st.title("📈 主升浪 V3.0 — 涨停板量化交易系统")

# ============================================================
# Sidebar: 系统状态
# ============================================================
with st.sidebar:
    st.header("⚙️ 系统")
    cfg = load_config()
    st.metric("评分版本", f"V3 (active={cfg['active']})")
    st.metric("买入门槛", f"≥{cfg['score_min']}分")
    st.metric("止损", "-10%")

    st.divider()

    if st.button("🔄 运行盘后流水线", use_container_width=True):
        with st.spinner("运行中..."):
            import subprocess
            r = subprocess.run([sys.executable, os.path.join(BASE, 'scripts', 'daily', 'run_pipeline.py')],
                             cwd=BASE, capture_output=True, text=True, timeout=300)
            st.success("完成!")
            st.code(r.stdout[-500:])

    if st.button("🌅 竞价选股 (模拟)", use_container_width=True):
        st.info("实盘请在9:25运行: python morning_check.py")

    st.divider()
    st.caption(f"更新时间: {datetime.now().strftime('%H:%M:%S')}")

# ============================================================
# Row 1: 持仓 + 交易统计
# ============================================================
col1, col2, col3, col4 = st.columns(4)

# 持仓
portfolio_path = os.path.join(BASE, 'logs', 'portfolio.json')
if os.path.exists(portfolio_path):
    with open(portfolio_path, 'r', encoding='utf-8') as f:
        pf = json.load(f)
    cash = pf.get('cash', 0)
    pos = pf.get('position')
    if pos:
        pos_value = pos['shares'] * pos.get('buy_price', 0)
        total = cash + pos_value
        col1.metric("💰 总资产", f"{total:,.0f}")
        col2.metric("📦 持仓", f"{pos['name']}({pos['code']})", f"{pos['shares']}股")
        col3.metric("💵 现金", f"{cash:,.0f}")
        col4.metric("📊 交易", f"{pf.get('total_trades',0)}笔", f"胜率{pf.get('winning_trades',0)/pf.get('total_trades',1)*100:.0f}%")
    else:
        col1.metric("💰 总资产", f"{cash:,.0f}")
        col2.metric("📦 持仓", "空仓")
        col3.metric("💵 现金", f"{cash:,.0f}")
        col4.metric("📊 交易", f"{pf.get('total_trades',0)}笔")
else:
    col1.metric("💰 总资产", "--")
    col2.metric("📦 持仓", "无数据")

# ============================================================
# Row 2: 涨停池
# ============================================================
st.header("🔴 涨停池")

zt_path = os.path.join(BASE, 'data', 'zt_pool_state.json')
if os.path.exists(zt_path):
    with open(zt_path, 'r', encoding='utf-8') as f:
        state = json.load(f)

    stocks = state.get('stocks', [])
    st.caption(f"截至 {state.get('as_of_date', '?')} | {len(stocks)}只 | "
               f"1板:{sum(1 for s in stocks if s.get('limit_days',1)==1)} "
               f"2板:{sum(1 for s in stocks if s.get('limit_days',1)==2)} "
               f"3板+:{sum(1 for s in stocks if s.get('limit_days',1)>=3)}")

    # 计算评分
    industries = Counter(s.get('industry','') for s in stocks)

    scored = []
    for s in stocks:
        code, name = s['code'], s['name']
        ft = s.get('first_seal','')
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
            'code': code, 'name': name, 'score': total, 'vr': vr_sc, 'gap': gap_sc,
            'ol': ol_sc, 'cons': cons_sc, 'seal': seal_sc, 'zha': zha_sc, 'sec': sec_sc,
            'ft': ft, 'industry': s.get('industry',''), 'limit_days': cons,
            'breaks': breaks, 'true_one': true_one, 'one_line': one_line,
            'vr_val': vr, 'gap_val': gap,
        })

    scored.sort(key=lambda x: x['score'], reverse=True)

    # 过滤风控
    filtered = []
    for r in scored:
        if r['true_one']: continue  # 真一字买不到
        if r['one_line'] and r['limit_days'] >= 4: continue  # 高危
        if r['score'] < cfg['score_min']: continue
        filtered.append(r)

    # 显示
    tab1, tab2 = st.tabs(["✅ 可买候选", "📋 全部评分"])

    with tab1:
        if filtered:
            top = filtered[:10]
            st.caption(f"风控过滤后: {len(filtered)}只 (真一字跳过+4板高危+评分<{cfg['score_min']})")
            for i, r in enumerate(top):
                cols = st.columns([1, 2, 1, 1, 1, 1, 1, 2])
                marker = "⭐" if i == 0 else ("🥈" if i == 1 else ("🥉" if i == 2 else f"#{i+1}"))
                cols[0].metric(marker, r['name'])
                cols[1].metric("评分", f"{r['score']:.0f}")
                cols[2].metric("量比", f"{r['vr_val']:.1f}x")
                cols[3].metric("Gap", f"{r['gap_val']:.1f}%")
                cols[4].metric("连板", f"{r['limit_days']}板")
                cols[5].metric("封板", r['ft'][:5])
                cols[6].metric("行业", r['industry'][:6])

                # 各因子贡献
                if i < 3:
                    with st.expander(f"📊 {r['name']} 评分拆解"):
                        c1,c2,c3,c4,c5,c6,c7 = st.columns(7)
                        c1.metric("量比", f"{r['vr']:+d}")
                        c2.metric("Gap", f"{r['gap']:+d}")
                        c3.metric("一字板", f"{r['ol']:+d}")
                        c4.metric("连板", f"{r['cons']:+d}")
                        c5.metric("封板时间", f"{r['seal']:+d}")
                        c6.metric("炸板", f"{r['zha']:+d}")
                        c7.metric("板块", f"{r['sec']:+d}")
        else:
            st.warning("无符合条件的候选")

    with tab2:
        st.dataframe(
            [{'代码': r['code'], '名称': r['name'], '评分': f"{r['score']:.0f}",
              '量比': f"{r['vr_val']:.1f}x", 'Gap': f"{r['gap_val']:.1f}%",
              '连板': f"{r['limit_days']}板", '封板': r['ft'][:5],
              '行业': r['industry'][:8],
              '风控': '⛔真一字' if r['true_one'] else ('⚠4板+' if r['one_line'] and r['limit_days']>=4 else ''),
              '量比分': r['vr'], 'Gap分': r['gap'], '一字分': r['ol'],
              '连板分': r['cons'], '封板分': r['seal'], '炸板分': r['zha'], '板块分': r['sec']}
             for r in scored],
            use_container_width=True, height=400,
            column_config={'风控': st.column_config.TextColumn(width='small')}
        )

else:
    st.warning("涨停池数据不存在，请先运行盘后流水线")

# ============================================================
# Row 3: 交易记录
# ============================================================
st.header("📝 交易记录")

journal_path = os.path.join(BASE, 'logs', 'trading_journal.json')
if os.path.exists(journal_path):
    with open(journal_path, 'r', encoding='utf-8') as f:
        journal = json.load(f)

    if journal:
        # 只显示买卖配对
        trades = []
        buy_map = {}
        for entry in journal:
            if entry.get('action') == 'BUY':
                buy_map[entry['code']] = entry
            elif entry.get('action') == 'SELL':
                buy = buy_map.get(entry['code'], {})
                trades.append({
                    '买入日': buy.get('date', ''),
                    '卖出日': entry.get('date', ''),
                    '代码': entry.get('code', ''),
                    '名称': entry.get('name', ''),
                    '买入价': buy.get('price', 0),
                    '卖出价': entry.get('price', 0),
                    '盈亏': f"{entry.get('pnl_pct', 0):+.1f}%",
                    '金额': f"{entry.get('pnl_amt', 0):+,.0f}",
                })

        if trades:
            st.dataframe(trades, use_container_width=True)

            total_pnl = sum(
                j.get('pnl_amt', 0) for j in journal if j.get('action') == 'SELL')
            st.metric("累计盈亏", f"{total_pnl:+,.0f}")
        else:
            st.caption("暂无交易记录")
else:
    st.caption("暂无交易记录")

# ============================================================
# Footer
# ============================================================
st.divider()
st.caption("主升浪 V3.0 | 10档量比+9档Gap+11档封板时间 | 买入门槛≥10 | 止损-10% | 三年回测+2,734%")

