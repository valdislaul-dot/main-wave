"""
模拟交易日志：记录每笔买卖、持仓、盈亏
"""
import json, os
import os
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


def save_portfolio(pf):
    with open(PORTFOLIO_FILE, 'w', encoding='utf-8') as f:
        json.dump(pf, f, ensure_ascii=False, indent=2)


def load_journal():
    if os.path.exists(JOURNAL_FILE):
        with open(JOURNAL_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_journal(journal):
    with open(JOURNAL_FILE, 'w', encoding='utf-8') as f:
        json.dump(journal, f, ensure_ascii=False, indent=2)


def record_buy(name, code, price, shares, cost, note=''):
    """Record a buy trade"""
    pf = load_portfolio()
    journal = load_journal()

    pf['cash'] -= cost
    pf['position'] = {
        'name': name, 'code': code,
        'buy_date': datetime.now().strftime('%Y-%m-%d'),
        'buy_price': price, 'shares': shares
    }

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
    """Record a sell trade"""
    pf = load_portfolio()
    journal = load_journal()

    pos = pf['position']
    if pos is None or pos['name'] != name:
        print(f'[Journal] WARNING: No position in {name}')
        return pf

    proceeds = price * pos['shares']
    pnl = (price - pos['buy_price']) / pos['buy_price'] * 100
    pnl_amt = proceeds - pos['buy_price'] * pos['shares']

    pf['cash'] += proceeds
    pf['position'] = None
    pf['total_trades'] += 1
    if pnl > 0:
        pf['winning_trades'] += 1
    pf['total_pnl'] += pnl_amt

    entry = {
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'action': 'SELL',
        'name': name, 'code': code,
        'price': price, 'shares': pos['shares'],
        'proceeds': proceeds, 'pnl_pct': round(pnl, 2),
        'pnl_amt': round(pnl_amt, 2),
        'buy_date': pos['buy_date'],
        'buy_price': pos['buy_price'],
        'hold_days': (datetime.now() - datetime.strptime(pos['buy_date'], '%Y-%m-%d')).days,
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
    pos_info = None

    # 新格式: positions数组
    positions = pf.get('positions', [])
    if positions:
        p = positions[0]
        pos_info = {'name': p['name'], 'code': p['code'],
            'buy_date': p.get('buy_date', '?'), 'buy_price': p['buy_price'],
            'shares': p['shares']}
    # 旧格式: position单对象
    elif pf.get('position'):
        p = pf['position']
        pos_info = {'name': p['name'], 'code': p['code'],
            'buy_date': p.get('buy_date', '?'), 'buy_price': p['buy_price'],
            'shares': p['shares']}

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
        'position': pos_info,
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
    print(f'  现金: {s["cash"]:,.0f}')
    if s['position']:
        p = s['position']
        print(f'  持仓: {p["name"]}({p["code"]})')
        print(f'  买入日: {p["buy_date"]} | 成本: {p["buy_price"]:.2f} | 股数: {p["shares"]}')
    else:
        print(f'  持仓: 空仓')
    print(f'  已完成交易: {s["total_trades"]}笔 | 胜率: {s["win_rate"]}%')
    print(f'  累计盈亏: {s["total_pnl"]:+,.0f}')
    print(f'{"="*50}\n')


if __name__ == '__main__':
    print_status()
