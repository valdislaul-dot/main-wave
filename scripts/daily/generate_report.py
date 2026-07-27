"""
生成每日 Markdown 报告
被 run_pipeline.py 盘后自动调用
"""
import json, os
import os
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
    files = sorted([f for f in os.listdir(LOG_DIR) if f.startswith('candidates_')])
    if not files:
        return None
    with open(os.path.join(LOG_DIR, files[-1]), 'r', encoding='utf-8') as f:
        return json.load(f)


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

    # Portfolio
    pos = pf['position'] if pf else None
    cash = pf['cash'] if pf else 0
    pos_value = 0
    pos_info = {'name': '-', 'code': '-', 'buy_price': 0, 'shares': 0, 'buy_date': '-'}
    unrealized = 0

    if pos:
        # Try to get yesterday's close from daily data
        yesterday = today - timedelta(days=1)
        while yesterday.weekday() >= 5:
            yesterday = yesterday - timedelta(days=1)
        ystr = yesterday.strftime('%Y-%m-%d')

        close_price = None
        daily_file = os.path.join(BASE, '每日收盘数据', ystr, 'daily_data.json')
        if os.path.exists(daily_file):
            with open(daily_file, 'r', encoding='utf-8') as f:
                dd = json.load(f)
            if pos['code'] in dd:
                close_price = dd[pos['code']]['close']

        if close_price:
            pos_value = pos['shares'] * close_price
            unrealized = (close_price - pos['buy_price']) / pos['buy_price'] * 100
        else:
            pos_value = pos['shares'] * pos['buy_price']  # fallback

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
    r.append("| 项目 | 详情 |")
    r.append("|------|------|")
    r.append(f"| 标的 | {pos['name']} ({pos['code']}) |" if pos else "| 标的 | 空仓 |")
    r.append(f"| 成本 | {pos['buy_price']:.3f} |" if pos else "| 成本 | - |")
    r.append(f"| 股数 | {pos['shares']} |" if pos else "| 股数 | - |")
    r.append(f"| 买入日 | {pos['buy_date']} |" if pos else "| 买入日 | - |")
    r.append(f"| 市值 | {pos_value:,.0f} |")
    r.append(f"| 浮盈 | {unrealized:+.1f}% |" if pos else "| 浮盈 | - |")
    r.append(f"| 现金 | {cash:,.0f} |")
    r.append(f"| **总资产** | **{total:,.0f}** |")
    r.append("")
    r.append("---")
    r.append("")

    # Candidates
    r.append(f"## 明日候选 (T-1={cand_data['date']}涨停 → {next_day.strftime('%m/%d')}{dow_cn(next_day)})")
    r.append("")

    if cand_data and cand_data['candidates']:
        r.append("| # | 代码 | 名称 | 评分 | 量比 | 连板 | 封板 | 仓位 | 竞价观察(4-8%) |")
        r.append("|---|------|------|------|------|------|------|------|----------------|")
        for i, c in enumerate(cand_data['candidates'][:5]):
            ref_close = c['close']
            lo = ref_close * 1.04; hi = ref_close * 1.08
            seal = c.get('seal_time', '?')
            pos_type = '全仓' if c['score'] >= 30 else '半仓'
            r.append(f"| {i+1} | {c['code']} | {c['name']} | {c['score']:.0f} | {c['vr20']:.1f}x | {c['cons']}板 | {seal} | {pos_type} | {lo:.2f}-{hi:.2f} |")

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
    if pos:
        r.append(f"**卖出判断**: 昨涨停+今不低开(开≥昨收)→持有 | 昨涨停+今低开→卖出 | 昨断板+今gap<4%→卖出 | 昨断板+今gap≥4%→持有")
        r.append("")
    r.append("**买入**: 首选候选竞价≥6%且不低开 → 55%仓位买入；一字板封死 → 备选")
    r.append("")
    r.append("---")
    r.append("")

    # History
    r.append("## 交易历史")
    r.append("")
    r.append("| 日期 | 操作 | 标的 | 盈亏 | 总资产 |")
    r.append("|------|------|------|------|--------|")
    for entry in journal[-20:]:  # last 20 entries
        if entry['action'] in ('BUY', 'SELL'):
            dt = entry['date'][:10]
            act = entry['action']
            name = entry['name']
            pnl = f"{entry.get('pnl_pct', 0):+.1f}%" if act == 'SELL' else '—'
            val = f"{entry.get('cash_after', 0):,.0f}"
            r.append(f"| {dt} | {act} | {name} | {pnl} | {val} |")
    r.append("")
    r.append("---")
    r.append("")
    r.append("*报告由每日选股流水线自动生成*")

    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(r))

    print(f'[Report] Saved: {REPORT_FILE}')


if __name__ == '__main__':
    generate()
