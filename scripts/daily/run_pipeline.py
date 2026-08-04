"""
每日选股流水线 - 主入口
用法：
  python run_pipeline.py              # 盘后运行：更新数据+筛选候选
  python run_pipeline.py --status     # 查看当前持仓
  python run_pipeline.py --buy CODE PRICE SHARES   # 记录买入
  python run_pipeline.py --sell CODE PRICE          # 记录卖出
  python run_pipeline.py --value PRICE              # 更新估值
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from update_data import main as update_data
from screen_candidates import main as screen_candidates
from trading_journal import print_status, record_buy, record_sell, record_hold_valuation


def main():
    fast_mode = '--fast' in sys.argv
    if len(sys.argv) > 1 and sys.argv[1] != '--fast':
        cmd = sys.argv[1]
        if cmd == '--status':
            print_status()
        elif cmd == '--buy' and len(sys.argv) >= 5:
            name = sys.argv[2]
            code = sys.argv[3]
            price = float(sys.argv[4])
            shares = int(sys.argv[5]) if len(sys.argv) > 5 else 0
            from trading_journal import load_portfolio
            pf = load_portfolio()
            if shares == 0:
                # Score-based position sizing
                import json, os
                candidates_file = None
                for f in sorted(os.listdir(os.path.join(BASE,'logs'))):
                    if f.startswith('candidates_'):
                        candidates_file = os.path.join(BASE,'logs',f)
                pos_pct = 0.5  # default half
                if candidates_file:
                    with open(candidates_file, 'r', encoding='utf-8') as cf:
                        data = json.load(cf)
                        for c in data.get('candidates',[]):
                            if c['code'] == code:
                                pos_pct = 1.0 if c['score'] >= 30 else 0.5
                                break
                deploy = pf['cash'] * pos_pct
                shares = int(deploy / price / 100) * 100
            cost = shares * price
            record_buy(name, code, price, shares, cost)
        elif cmd == '--sell' and len(sys.argv) >= 4:
            name = sys.argv[2]
            code = sys.argv[3]
            price = float(sys.argv[4])
            record_sell(name, code, price)
        elif cmd == '--value' and len(sys.argv) >= 3:
            price = float(sys.argv[2])
            record_hold_valuation(price)
        else:
            print('Usage: python run_pipeline.py [--status|--buy|--sell|--value]')
    else:
        print('=' * 60)
        print('  每日选股流水线')
        print('=' * 60)

        # Step 1: Update ZT pool (拉今日涨停池 + 只下载池中标的K线)
        print('\n[Step 1/4] 更新涨停池...')
        try:
            from zt_pool import update_zt_pool
            update_zt_pool()
        except Exception as e:
            print(f'[Warning] ZT pool update failed: {e}')

        # Step 2: Screen candidates (V3评分)
        print('\n[Step 2/4] V3评分选股...')
        try:
            screen_candidates()
        except Exception as e:
            print(f'[Error] Screening failed: {e}')

        # Step 3: Generate report
        print('\n[Step 3/4] 生成每日报告...')
        try:
            from generate_report import generate
            generate()
        except Exception as e:
            print(f'[Warning] Report generation failed: {e}')

        # Step 4: Full update (only with --full flag)
        if '--full' in sys.argv:
            print('\n[Step 4/4] 完整更新(K线+LHB+T字板)...')
            try: update_data()
            except: pass
            try:
                from dt_block_factor import run as run_dt_factor
                run_dt_factor()
            except: pass
            try:
                from capture_tboard_minute import main as capture_tboard
                capture_tboard()
            except: pass
        else:
            print('\n[Step 4/4] 完成 (K线批量更新用 --full)')

        print_status()
        print('流水线完成。报告已保存到 logs/daily_report.md')


if __name__ == '__main__':
    main()

# [Step 3/4] Update stock_data.json with today's K-line
print("\n[Step 3/4] 更新 stock_data.json...")
import json, urllib.request, time, random, glob, os
try:
    sd_path = os.path.join(BASE, 'data', 'stock_data.json')
    with open(sd_path) as f: sd = json.load(f)
    
    # Map names to codes from kline_data
    code_map = {}
    for kf in glob.glob(os.path.join(BASE, 'data', 'kline_data', '*.json')):
        nc = os.path.basename(kf).replace('.json','').rsplit('_',1)
        if len(nc) == 2: code_map[nc[0]] = nc[1]
    
    today = __import__('datetime').datetime.now().strftime('%Y-%m-%d')
    updated = 0
    for name in list(sd.keys()):
        if sd[name] and sd[name][-1].get('day','') >= today: continue
        code = code_map.get(name, '')
        if not code: continue
        pre = 'sh' if code.startswith('6') else 'sz'
        url = f'https://qt.gtimg.cn/q={pre}{code}'
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0')
        resp = urllib.request.urlopen(req, timeout=10)
        v = resp.read().decode('gbk').split('"')[1].split('~')
        if len(v) < 38: continue
        sd[name].append({'day': today, 'open': v[5], 'close': v[3], 'high': v[33], 'low': v[34], 'volume': v[6]})
        updated += 1
        time.sleep(0.1 + random.uniform(0, 0.05))
    
    with open(sd_path, 'w') as f: json.dump(sd, f, ensure_ascii=False, indent=2)
    print(f"[StockData] Updated {updated}/{len(sd)} stocks")
except Exception as e:
    print(f"[StockData] Warning: {e}")
