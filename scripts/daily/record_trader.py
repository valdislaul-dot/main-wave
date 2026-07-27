"""
记录交易员实际操作 (用于与模型对比)
用法:
  python record_trader.py --buy NAME CODE PRICE SHARES DATE
  python record_trader.py --sell NAME CODE PRICE DATE
  python record_trader.py --compare   # 对比模型 vs 交易员
"""
import json, os, sys
import os
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime

# BASE auto-detected below
LOG_DIR = os.path.join(BASE, 'logs')
TRADER_FILE = os.path.join(LOG_DIR, 'trader_journal.json')
MODEL_PORTFOLIO = os.path.join(LOG_DIR, 'portfolio.json')


def load_trader():
    if os.path.exists(TRADER_FILE):
        with open(TRADER_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'trades': [], 'current_position': None, 'cash': 200000}


def save_trader(data):
    with open(TRADER_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_model_portfolio():
    if os.path.exists(MODEL_PORTFOLIO):
        with open(MODEL_PORTFOLIO, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def trader_buy(name, code, price, shares, date=None):
    t = load_trader()
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')

    cost = price * shares
    t['cash'] -= cost
    t['current_position'] = {
        'name': name, 'code': code, 'buy_date': date,
        'buy_price': price, 'shares': shares
    }
    t['trades'].append({
        'date': date, 'action': 'BUY',
        'name': name, 'code': code, 'price': price, 'shares': shares,
        'cost': cost, 'cash_after': t['cash']
    })
    save_trader(t)
    print(f'[Trader] BUY {name}({code}) @{price:.2f} x{shares}')


def trader_sell(name, code, price, date=None):
    t = load_trader()
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d')

    pos = t['current_position']
    if pos is None:
        print('[Trader] No position to sell')
        return

    proceeds = price * pos['shares']
    pnl_pct = (price - pos['buy_price']) / pos['buy_price'] * 100
    pnl_amt = proceeds - pos['buy_price'] * pos['shares']

    t['cash'] += proceeds
    t['current_position'] = None
    t['trades'].append({
        'date': date, 'action': 'SELL',
        'name': name, 'code': code, 'price': price,
        'shares': pos['shares'], 'proceeds': proceeds,
        'pnl_pct': round(pnl_pct, 2), 'pnl_amt': round(pnl_amt, 2),
        'buy_date': pos['buy_date'], 'buy_price': pos['buy_price'],
        'cash_after': t['cash']
    })
    save_trader(t)
    print(f'[Trader] SELL {name}({code}) @{price:.2f} PnL={pnl_pct:+.1f}%')
    return pnl_pct, pnl_amt


def compare():
    """Compare model vs trader performance"""
    t = load_trader()
    m = load_model_portfolio()

    if m is None:
        print('Model portfolio not found')
        return

    # Trader stats
    trader_trades = [tr for tr in t['trades'] if tr['action'] == 'SELL']
    trader_wins = sum(1 for tr in trader_trades if tr.get('pnl_pct', 0) > 0)
    trader_total = len(trader_trades)
    trader_pnl = sum(tr.get('pnl_amt', 0) for tr in trader_trades)
    trader_value = t['cash']
    if t['current_position']:
        # Can't value without current price
        trader_value = t['cash']  # conservative: ignore unrealized

    # Model stats
    model_cash = m['cash']
    model_pos = m['position']
    model_trades = m['total_trades']
    model_wins = m['winning_trades']
    model_pnl = m['total_pnl']
    model_value = model_cash  # simplified

    INIT = 200000

    print(f'\n{"="*55}')
    print(f'  模型 vs 交易员 对比')
    print(f'{"="*55}')
    print(f'  {"指标":<20} {"模型":>15} {"交易员":>15}')
    print(f'  {"-"*50}')
    print(f'  {"已完成交易":<20} {model_trades:>15} {trader_total:>15}')
    print(f'  {"盈利笔数":<20} {model_wins:>15} {trader_wins:>15}')
    wr_m = model_wins/model_trades*100 if model_trades>0 else 0
    wr_t = trader_wins/trader_total*100 if trader_total>0 else 0
    print(f'  {"胜率":<20} {wr_m:>14.0f}% {wr_t:>14.0f}%')
    print(f'  {"累计盈亏":<20} {model_pnl:>+14,.0f} {trader_pnl:>+14,.0f}')
    ret_m = (model_value-INIT)/INIT*100
    ret_t = (trader_value-INIT)/INIT*100
    print(f'  {"当前资产":<20} {model_value:>15,.0f} {trader_value:>15,.0f}')
    print(f'  {"收益率":<20} {ret_m:>+14.1f}% {ret_t:>+14.1f}%')
    print(f'{"="*55}\n')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage:')
        print('  python record_trader.py --buy NAME CODE PRICE SHARES [DATE]')
        print('  python record_trader.py --sell NAME CODE PRICE [DATE]')
        print('  python record_trader.py --compare')
    elif sys.argv[1] == '--buy' and len(sys.argv) >= 6:
        trader_buy(sys.argv[2], sys.argv[3], float(sys.argv[4]), int(sys.argv[5]),
                   sys.argv[6] if len(sys.argv) > 6 else None)
    elif sys.argv[1] == '--sell' and len(sys.argv) >= 5:
        trader_sell(sys.argv[2], sys.argv[3], float(sys.argv[4]),
                    sys.argv[5] if len(sys.argv) > 5 else None)
    elif sys.argv[1] == '--compare':
        compare()
