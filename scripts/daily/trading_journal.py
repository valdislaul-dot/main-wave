"""
模拟交易日志：记录每笔买卖、持仓、盈亏
Phase 4 (D-04..D-06): save_portfolio/save_journal 原子写 —— 同目录 .tmp + os.replace
"""
import json, os
import os
import time
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime

# BASE auto-detected below
LOG_DIR = os.path.join(BASE, 'logs')
JOURNAL_FILE = os.path.join(LOG_DIR, 'trading_journal.json')
PORTFOLIO_FILE = os.path.join(LOG_DIR, 'portfolio.json')

os.makedirs(LOG_DIR, exist_ok=True)

INITIAL_CAPITAL = 200000
POSITION_PCT = 0.55  # base position under normal market

def adaptive_position_pct(today_lu_count, avg_lu_count=5):
    """Market-adaptive position sizing.
    More LU stocks -> stronger market -> higher position.
    Fewer LU stocks -> weaker market -> lower position or skip.
    """
    if today_lu_count >= 10:   return 0.70  # very strong
    elif today_lu_count >= 7:  return 0.65
    elif today_lu_count >= 4:  return 0.55  # normal
    elif today_lu_count >= 2:  return 0.35  # weak
    else:                      return 0.0   # skip (only 0-1 LU stocks)


def load_portfolio():
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        'cash': INITIAL_CAPITAL,
        'position': None,  # {name, code, buy_date, buy_price, shares}
        'total_trades': 0,
        'winning_trades': 0,
        'total_pnl': 0,
        'created': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


def _replace_retry(tmp, dst):
    """os.replace 短重试 (WR-03, 04 修复; api/jobs.py write_job L73-85 模板):
    读者 (GET /v1/private/*) 的 open 句柄撞上 replace 的 µs 窗口在 Windows 抛
    PermissionError (WinError-5 类) —— 账本两文件写序 (portfolio 先 journal 后)
    不容许 journal 一次碰撞丢条目 (两文件对 API 永久不一致)。4 次尝试、10ms 退避
    (读句柄窗口 µs 级, 远够); 非 PermissionError (真盘满/权限) 立即上抛, 目标
    保持上次已提交内容 (D-04 失败语义不变, Test 3/4 钉 OSError 首调即抛)。"""
    for attempt in range(4):  # 3 次重试, 每次让出 10ms
        try:
            os.replace(tmp, dst)
            return
        except PermissionError:
            if attempt < 3:
                time.sleep(0.01)
                continue
            raise


def save_portfolio(pf):
    # 原子写 (D-04..D-06, zt_pool save_state 模板): 同目录 .tmp 保证同卷, os.replace 原子替换
    # (Windows 上 os.rename 对已存在目标会失败, 禁用); 读者永不 observe 半写 JSON。
    # WR-03 (04 修复): replace 碰撞 PermissionError 短重试 (见 _replace_retry)。
    # 不注入 last_updated 等字段 —— 账本 schema 是用户的 (与旧写者字节一致)。
    tmp = PORTFOLIO_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(pf, f, ensure_ascii=False, indent=2)
    _replace_retry(tmp, PORTFOLIO_FILE)


def load_journal():
    if os.path.exists(JOURNAL_FILE):
        with open(JOURNAL_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_journal(journal):
    # 原子写 (D-04..D-06, zt_pool save_state 模板): 同上 —— 同目录 .tmp + os.replace
    # WR-03 (04 修复): replace 碰撞 PermissionError 短重试 (见 _replace_retry)。
    tmp = JOURNAL_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(journal, f, ensure_ascii=False, indent=2)
    _replace_retry(tmp, JOURNAL_FILE)


def record_buy(name, code, price, shares, cost, note=''):
    """Record a buy trade"""
    pf = load_portfolio()
    journal = load_journal()

    pf['cash'] -= cost
    pos = {
        'name': name, 'code': code,
        'buy_date': datetime.now().strftime('%Y-%m-%d'),
        'buy_price': price, 'shares': shares
    }
    positions = pf.get('positions')
    if positions:
        positions.append(pos)
    elif pf.get('position'):
        positions = [pf['position'], pos]
    else:
        # 2026-09-03修复: 原pf['positions']=[pos]但局部变量未更新,
        # 下一行positions[0]崩溃且买入未落盘
        positions = [pos]
    pf['positions'] = positions
    pf['position'] = positions[0]  # 主持仓=第一只(兼容旧读取方)

    entry = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'action': 'BUY',
        'name': name, 'code': code,
        'price': price, 'shares': shares, 'cost': cost,
        'cash_after': pf['cash'],
        'note': note
    }
    journal.append(entry)

    save_portfolio(pf)
    save_journal(journal)
    print(f'[Journal] BUY {name}({code}) @{price:.2f} x{shares} cost={cost:,.0f} cash={pf["cash"]:,.0f}')
    return pf


def record_sell(name, code, price, note=''):
    """Record a sell trade (2026-09-03修复: 同码多笔加仓整仓卖时合并全部批次,
    原只删第一笔致残仓滞留+现金少记; 2026-09-04 WR-02修复: code 优先精确匹配,
    name/code 错配拒绝, 原 name-OR-code 并集会把两只持仓一并卖出记双卖;
    WR-07: 拒绝路径 (错配/无持仓) 打印 WARNING 并返回 None —— 成功返回 pf,
    调用方须以 None 判定卖出被拒 (run_pipeline --sell 映射为 sys.exit(1)))"""
    pf = load_portfolio()
    journal = load_journal()

    positions = pf.get('positions')
    if positions:
        # WR-02 (04 修复): code 是身份键, name 是展示名 —— 原 name-OR-code 并集在
        # name/code 错配时 (手滑码/过期名) 会把两只不同持仓一并卖出、账本记双卖。
        # 语义: 任一持仓带该 code -> 只按 code 匹配 (2026-09-03 同码多批整仓卖保持,
        # 同码改名历史批也并卖); 无 code 命中 -> 退回 name 全等单匹配。name/code
        # 双给且 name 不属于该 code 任何批的名字 -> fail-loud 拒绝, 绝不猜。
        by_code = [p for p in positions if p['code'] == code]
        if by_code:
            if name and name != code and name not in {p['name'] for p in by_code}:
                print(f'[Journal] WARNING: {name}/{code} 错配: code 属于 '
                      f'{[p["name"] for p in by_code]}, 拒绝卖出(防错配双卖)')
                return None  # WR-07: 拒绝信号 (None = 未卖出, 调用方非零退出)
            matched = by_code
        else:
            matched = [p for p in positions if p['name'] == name]
        if not matched:
            print(f'[Journal] WARNING: No position in {name}')
            return None  # WR-07: 拒绝信号 (None = 未卖出, 调用方非零退出)
        for p in matched:
            positions.remove(p)
    else:
        pos = pf['position']
        if pos is None or (pos['name'] != name and pos['code'] != code):
            print(f'[Journal] WARNING: No position in {name}')
            return None  # WR-07: 拒绝信号 (None = 未卖出, 调用方非零退出)
        matched = [pos]

    total_sh = sum(p['shares'] for p in matched)
    avg_cost = sum(p['buy_price'] * p['shares'] for p in matched) / total_sh
    proceeds = price * total_sh
    pnl = (price - avg_cost) / avg_cost * 100
    pnl_amt = proceeds - avg_cost * total_sh
    buy_date = min(p['buy_date'] for p in matched)

    pf['cash'] += proceeds
    pf['positions'] = positions
    # 2026-09-03修复: 原无条件置None, 剩余持仓被盘后报告/估值漏掉
    pf['position'] = positions[0] if positions else None
    pf['total_trades'] += 1
    if pnl > 0:
        pf['winning_trades'] += 1
    pf['total_pnl'] += pnl_amt

    # WR-02 (04 修复): SELL 身份写实际被卖持仓 —— name 回退匹配时 argv code 可能
    # 是手滑值, 照记会把不存在的代码写进账本 (账本现经 /v1/private/* 对外服务)。
    # name 给了且确属被卖批次真名时保留 argv 形态 (同码更名批整仓卖不记旧名)。
    sell_code = matched[0]['code']
    sell_name = (name if (name and name != code
                          and name in {p['name'] for p in matched})
                 else matched[0]['name'])
    entry = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'action': 'SELL',
        'name': sell_name, 'code': sell_code,
        'price': price, 'shares': total_sh,
        'proceeds': proceeds, 'pnl_pct': round(pnl, 2),
        'pnl_amt': round(pnl_amt, 2),
        'buy_date': buy_date,
        'buy_price': round(avg_cost, 3),
        'hold_days': (datetime.now() - datetime.strptime(buy_date, '%Y-%m-%d')).days,
        'cash_after': pf['cash'],
        'note': note
    }
    journal.append(entry)

    win_rate = pf['winning_trades'] / pf['total_trades'] * 100 if pf['total_trades'] > 0 else 0
    total_value = pf['cash']  # No position, all cash
    total_return = (total_value - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    save_portfolio(pf)
    save_journal(journal)

    print(f'[Journal] SELL {name}({code}) @{price:.2f} PnL={pnl:+.1f}%({pnl_amt:+,.0f}) '
          f'cash={pf["cash"]:,.0f} | WinRate={win_rate:.0f}% | Return={total_return:+.1f}%')
    return pf


def record_hold_valuation(current_price):
    """Update portfolio valuation without trading (for daily tracking)"""
    pf = load_portfolio()
    journal = load_journal()

    pos = pf['position']
    if pos is None:
        return pf

    pnl = (current_price - pos['buy_price']) / pos['buy_price'] * 100
    position_value = current_price * pos['shares']
    total_value = pf['cash'] + position_value
    total_return = (total_value - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    entry = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'action': 'VALUATION',
        'name': pos['name'], 'code': pos['code'],
        'price': current_price,
        'position_value': position_value,
        'cash': pf['cash'],
        'total_value': total_value,
        'unrealized_pnl_pct': round(pnl, 2),
        'total_return_pct': round(total_return, 2),
    }
    # Don't add to main journal, save separately
    val_file = os.path.join(LOG_DIR, 'daily_valuations.json')
    vals = []
    if os.path.exists(val_file):
        with open(val_file, 'r', encoding='utf-8') as f:
            vals = json.load(f)
    vals.append(entry)
    with open(val_file, 'w', encoding='utf-8') as f:
        json.dump(vals, f, ensure_ascii=False, indent=2)

    return pf


def get_status():
    """Get current portfolio status for display (兼容新旧格式)"""
    pf = load_portfolio()
    pos_list = []

    # 新格式: positions数组
    positions = pf.get('positions', [])
    if positions:
        for p in positions:
            pos_list.append({'name': p['name'], 'code': p['code'],
                'buy_date': p.get('buy_date', '?'), 'buy_price': p['buy_price'],
                'shares': p['shares']})
    # 旧格式: position单对象
    elif pf.get('position'):
        p = pf['position']
        pos_list.append({'name': p['name'], 'code': p['code'],
            'buy_date': p.get('buy_date', '?'), 'buy_price': p['buy_price'],
            'shares': p['shares']})

    # 统计: 优先用closed列表(新), 否则用旧字段
    closed = pf.get('closed', [])
    if closed:
        total_trades = len(closed)
        winning_trades = sum(1 for t in closed if t.get('pnl', 0) > 0)
        total_pnl = sum(t.get('pnl', 0) for t in closed)
    else:
        total_trades = pf.get('total_trades', 0)
        winning_trades = pf.get('winning_trades', 0)
        total_pnl = pf.get('total_pnl', 0)
    win_rate = winning_trades / total_trades * 100 if total_trades > 0 else 0

    return {
        'cash': pf.get('cash', 0),
        'positions': pos_list,
        'position': pos_list[0] if pos_list else None,
        'total_trades': total_trades,
        'winning_trades': winning_trades,
        'win_rate': round(win_rate, 1),
        'total_pnl': round(total_pnl, 2),
    }


def print_status():
    s = get_status()
    print(f'\n{"="*50}')
    print(f'  当前持仓状态')
    print(f'{"="*50}')
    # 2026-09-15 用户定死: 账本只记持仓不记现金 → 不再打印现金行
    if s['positions']:
        for p in s['positions']:
            print(f'  持仓: {p["name"]}({p["code"]})')
            print(f'  买入日: {p["buy_date"]} | 成本: {p["buy_price"]:.2f} | 股数: {p["shares"]}')
    else:
        print(f'  持仓: 空仓')
    print(f'  已完成交易: {s["total_trades"]}笔 | 胜率: {s["win_rate"]}%')
    print(f'  累计盈亏: {s["total_pnl"]:+,.0f}')
    print(f'{"="*50}\n')


if __name__ == '__main__':
    print_status()
