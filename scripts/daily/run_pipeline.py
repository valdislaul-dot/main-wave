"""
每日选股流水线 - 主入口
用法：
  python run_pipeline.py              # 盘后运行
  python run_pipeline.py --fast       # 轻量模式(仅涨停池+评分)
  python run_pipeline.py --status     # 查看持仓
  python run_pipeline.py --buy CODE PRICE SHARES
  python run_pipeline.py --sell CODE PRICE
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
            name = sys.argv[2]; code = sys.argv[3]
            price = float(sys.argv[4]); shares = int(sys.argv[5]) if len(sys.argv) > 5 else 0
            from trading_journal import load_portfolio
            pf = load_portfolio()
            if shares == 0:
                import json
                candidates_file = None
                for f in sorted(os.listdir(os.path.join(BASE,'logs'))):
                    if f.startswith('candidates_'): candidates_file = os.path.join(BASE,'logs',f)
                pos_pct = 0.5
                if candidates_file:
                    with open(candidates_file, 'r', encoding='utf-8') as cf:
                        data = json.load(cf)
                        for c in data.get('candidates',[]):
                            if c['code'] == code: pos_pct = 0.5; break
                deploy = pf['cash'] * pos_pct
                shares = int(deploy / price / 100) * 100
            cost = shares * price
            record_buy(name, code, price, shares, cost)
        elif cmd == '--sell' and len(sys.argv) >= 4:
            record_sell(sys.argv[2], sys.argv[3], float(sys.argv[4]))
        elif cmd == '--value' and len(sys.argv) >= 3:
            record_hold_valuation(float(sys.argv[2]))
        else:
            print('Usage: python run_pipeline.py [--status|--buy|--sell|--value]')
    else:
        print('=' * 60)
        print('  每日选股流水线')
        print('=' * 60)

        # Step 1: Update ZT pool
        print('\n[Step 1/7] 更新当日涨停池...')
        try:
            from zt_pool import update_zt_pool
            update_zt_pool()
        except Exception as e:
            print(f'[Warning] ZT pool update failed: {e}')

        # Step 2: Update K-line (only ZT pool stocks, Sina API fast)
        print('\n[Step 2/7] 更新K线数据(涨停池标的)...')
        try:
            update_data()
        except Exception as e:
            print(f'[Warning] Data update failed: {e}')

        # Step 3: Update historical ZT pool
        print('\n[Step 3/7] 更新历史涨停池...')
        try:
            from active_pool import update as update_active_pool
            update_active_pool()
        except Exception as e:
            print(f'[Warning] Active pool update failed: {e}')

        # Step 4: Screen candidates
        print('\n[Step 4/7] 筛选候选标的...')
        try:
            screen_candidates()
        except Exception as e:
            print(f'[Error] Screening failed: {e}')

        if not fast_mode:
            # Step 5: Generate report
            print('\n[Step 5/7] 生成每日报告...')
            try:
                from generate_report import generate
                generate()
            except: pass

            # Step 6: Review yesterday's top-3 recommendations
            print('\n[Step 6/7] 回看昨日推荐前三...')
            try:
                from review_recommendations import review_previous_day
                review_previous_day()
            except Exception as e:
                print(f'[Warning] 推荐回看失败: {e}')

            # Step 7: T-board minute
            print('\n[Step 7/8] 捕获T字板分钟K线...')
            try:
                from capture_tboard_minute import main as capture_tboard
                capture_tboard()
            except: pass

            # Step 8: Data health check
            print('\n[Step 8/8] 数据体检...')
            try:
                from data_health_check import main as health_check
                health_check()
            except Exception as e:
                print(f'[Warning] 数据体检失败: {e}')

            # Step 9: 数据上云同步 (2026-08-16新增, 自动push关键快照到GitHub)
            print('\n[Step 9] 数据上云同步...')
            try:
                from sync_cloud import sync
                sync()
            except Exception as e:
                print(f'[Warning] 数据上云失败: {e}')
        else:
            print('\n[轻量模式] 跳过LHB/报告/T字板')

        print_status()
        print('流水线完成。')


if __name__ == '__main__':
    main()
