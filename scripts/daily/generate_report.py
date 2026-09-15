"""
生成每日 Markdown 报告
被 run_pipeline.py 盘后自动调用
"""
import json, os
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timedelta

# BASE auto-detected below
LOG_DIR = os.path.join(BASE, 'logs')
REPORT_FILE = os.path.join(LOG_DIR, 'daily_report.md')


def load_portfolio():
    pf_file = os.path.join(LOG_DIR, 'portfolio.json')
    if os.path.exists(pf_file):
        with open(pf_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def load_latest_candidates():
    """按文件名日期取最新候选存档。禁止 sorted() 字典序: 'candidates_2026-08-07' 会排在
    'candidates_2026-09-08' 后面(files[-1]取到旧月文件); 且 candidates_v3_* 旧版必须排除。"""
    import re
    best, best_date = None, ''
    for f in os.listdir(LOG_DIR):
        m = re.match(r'candidates_(\d{4}-\d{2}-\d{2})\.json$', f)
        if not m:
            continue
        d = m.group(1)
        if d > best_date:
            try:
                with open(os.path.join(LOG_DIR, f), 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                if data.get('date', d) == d:  # 文件名与内部date一致才认
                    best, best_date = data, d
            except Exception:
                continue
    return best


def load_journal():
    jf = os.path.join(LOG_DIR, 'trading_journal.json')
    if os.path.exists(jf):
        with open(jf, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def get_next_trading_day():
    d = datetime.now() + timedelta(days=1)
    while d.weekday() >= 5:
        d = d + timedelta(days=1)
    return d


def dow_cn(d):
    return ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][d.weekday()]


def generate():
    pf = load_portfolio()
    cand_data = load_latest_candidates()
    journal = load_journal()
    today = datetime.now()
    next_day = get_next_trading_day()

    # Portfolio (多持仓: positions列表优先, 旧单持仓position字段兜底)
    cash = pf['cash'] if pf else 0
    positions = []
    if pf:
        ps = pf.get('positions') or ([pf['position']] if pf.get('position') else [])
        positions = [p for p in ps if p]

    # 现价: 今日daily_close(池内股) → K线最后bar(池外持仓股) → 成本价兜底
    # (禁止用昨日收盘算浮盈: 买入日=今日的持仓会算出方向相反的假浮亏)
    today_str = today.strftime('%Y-%m-%d')
    daily_file = os.path.join(BASE, 'data', 'daily_close', today_str, 'daily_data.json')
    dd = {}
    if os.path.exists(daily_file):
        with open(daily_file, 'r', encoding='utf-8') as f:
            dd = json.load(f)

    def get_close(code):
        if code in dd:
            return dd[code]['close']
        kf = os.path.join(BASE, 'data', 'kline_data', f'{code}.json')
        if os.path.exists(kf):
            try:
                with open(kf, 'r', encoding='utf-8') as f:
                    k = json.load(f)
                bars = k if isinstance(k, list) else (k.get('data') or k.get('klines') or [])
                if bars and isinstance(bars[-1], dict) and 'close' in bars[-1]:
                    return bars[-1]['close']
            except Exception:
                pass
        return None

    pos_rows, pos_value = [], 0
    for p in positions:
        close_price = get_close(p['code'])
        if close_price is None:
            close_price = p['buy_price']
        pos_rows.append({**p, 'close': close_price, 'value': p['shares'] * close_price})
        pos_value += pos_rows[-1]['value']

    total = cash + pos_value

    # Build report
    r = []
    r.append(f"# 每日选股报告 — {today.strftime('%Y-%m-%d')} ({dow_cn(today)})")
    r.append("")
    r.append(f"> 下一交易日: **{next_day.strftime('%Y-%m-%d')} ({dow_cn(next_day)})**")
    r.append(f"> 生成时间: {today.strftime('%Y-%m-%d %H:%M')}")
    r.append("")
    r.append("---")
    r.append("")
    r.append("## 当前持仓")
    r.append("")
    r.append("| 标的 | 成本 | 股数 | 买入日 | 现价 | 市值 | 浮盈 |")
    r.append("|------|------|------|--------|------|------|------|")
    if pos_rows:
        for p in pos_rows:
            up = (p['close'] - p['buy_price']) / p['buy_price'] * 100
            r.append(f"| {p['name']} ({p['code']}) | {p['buy_price']:.3f} | {p['shares']} | {p['buy_date']} | {p['close']:.2f} | {p['value']:,.0f} | {up:+.1f}% |")
    else:
        r.append("| 空仓 | — | — | — | — | — | — |")
    # 2026-09-15 用户定死: 账本只记持仓不记现金 → 不再输出"现金/总资产"行, 只合计持仓市值
    r.append(f"| **持仓市值** | — | — | — | — | **{pos_value:,.0f}** | — |")
    r.append("")
    r.append("---")
    r.append("")

    # Candidates
    cand_date = cand_data['date'] if cand_data else '?'
    r.append(f"## 明日候选 (T-1={cand_date}涨停 → {next_day.strftime('%m/%d')}{dow_cn(next_day)})")
    r.append("")

    if cand_data and cand_data['candidates']:
        cands = sorted(cand_data['candidates'], key=lambda c: -(c.get('score') or 0))[:5]
        r.append("| # | 代码 | 名称 | 评分 | 量比 | 连板 | 封板 | 仓位 | 竞价观察(4-8%) |")
        r.append("|---|------|------|------|------|------|------|------|----------------|")
        for i, c in enumerate(cands):
            ref_close = c['close']
            lo = ref_close * 1.04; hi = ref_close * 1.08
            seal = c.get('seal_time', '?')
            r.append(f"| {i+1} | {c['code']} | {c['name']} | {c['score']:.0f} | {c['vr20']:.1f}x | {c['cons']}板 | {seal} | 55% | {lo:.2f}-{hi:.2f} |")

        top = cand_data['top_pick']
        r.append("")
        r.append(f"> 首选: **{top['name']} ({top['code']})**")
    else:
        r.append("无候选（未找到符合条件的涨停股）")
    r.append("")
    r.append("---")
    r.append("")

    # Tomorrow's action
    r.append("## 明日操作")
    r.append("")
    if pos_rows:
        r.append("**卖出判断**(V4.1引擎): 昨涨停低开→竞价卖 | 烂板高开→弱转强观察 | 昨断板gap<4%→开盘价卖 | gap≥4%→持有 | 硬止损-10%兜底")
        r.append("")
    r.append("**买入**(A式): 开关恒开, 竞价面板Top1(综合分=评分×gap权重) gap4-8%平滑窗(边缘3-4/8-9衰减) → 恒定55%仓位；一字板封死 → 顺延备选")
    r.append("")
    r.append("---")
    r.append("")

    # History
    r.append("## 交易历史")
    r.append("")
    # 2026-09-15 用户定死: 只记持仓不记现金 → 去掉"总资产"列(原值来自 cash_after)
    r.append("| 日期 | 操作 | 标的 | 盈亏 |")
    r.append("|------|------|------|------|")
    for entry in journal[-20:]:  # last 20 entries
        if entry['action'] in ('BUY', 'SELL'):
            dt = entry['date'][:10]
            act = entry['action']
            name = entry['name']
            pnl = f"{entry.get('pnl_pct', 0):+.1f}%" if act == 'SELL' else '—'
            r.append(f"| {dt} | {act} | {name} | {pnl} |")
    r.append("")
    r.append("---")
    r.append("")
    r.append("*报告由每日选股流水线自动生成*")

    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(r))

    print(f'[Report] Saved: {REPORT_FILE}')


if __name__ == '__main__':
    generate()
