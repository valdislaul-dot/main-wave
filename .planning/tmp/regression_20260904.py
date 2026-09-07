"""2026-09-03/04 审查修复回归验证 — 覆盖本次改动的代码路径(离线, 不动生产数据)"""
import json, os, sys, tempfile, shutil

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, 'scripts', 'daily'))

PASS, FAIL = [], []


def check(name, cond, detail=''):
    (PASS if cond else FAIL).append(name)
    print(('✅ ' if cond else '❌ ') + name + (f' — {detail}' if detail else ''))


# ══════ 1. sell_engine: 断板分支顺序 + loss_pct基准 ══════
import sell_engine as se

KL = [
    {'date': '2026-09-01', 'open': 9.0, 'close': 10.0, 'high': 10.1, 'low': 8.9,
     'volume': 1000, 'pct_change': 9.9, 'amount_10k_cny': 950, 'volume_lots': 1000},
    {'date': '2026-09-02', 'open': 9.5, 'close': 9.0, 'high': 9.8, 'low': 8.8,
     'volume': 2000, 'pct_change': -10.0, 'amount_10k_cny': 1800, 'volume_lots': 2000},
]
se._load_klines = lambda code, name=None: KL


def run(gap, buy_price=9.5, buy_date='2026-08-20'):
    open_px = round(9.0 * (1 + gap / 100), 2)
    return se.sell_signal({'code': 'TEST01', 'name': '测试', 'buy_date': buy_date,
                           'buy_price': buy_price, 'shares': 1000},
                          {'gap_pct': gap, 'open': open_px, 'prev_close': 9.0})


s1 = run(6.0)
check('S1 深炸+gap≥5 → 弱转强反包优先(分支顺序修复)', s1['action'] == 'watch' and '反包' in s1['reason'],
      s1['reason'][:40])

s2 = run(-4.5)
check('S2 loss_pct用前日收盘基准 → 大亏等冲高(旧代码open基准会误判小亏竞价走)',
      s2['action'] == 'watch' and '等冲高' in s2['reason'], s2['reason'][:40])

s3 = run(-10.0, buy_price=8.0)
check('S3 跌停开 → 竞价排队卖', s3['action'] == 'sell' and '排队' in s3['reason'], s3['reason'][:30])

s4 = run(4.5)
check('S4 断板+gap≥4 → 持有', s4['action'] == 'hold', s4['reason'][:30])

KL_LU = [
    {'date': '2026-09-01', 'open': 8.0, 'close': 8.2, 'high': 8.3, 'low': 7.9,
     'volume': 800, 'pct_change': 2.5, 'amount_10k_cny': 700, 'volume_lots': 800},
    {'date': '2026-09-02', 'open': 8.18, 'close': 9.0, 'high': 9.0, 'low': 8.1,
     'volume': 1500, 'pct_change': 9.9, 'amount_10k_cny': 1300, 'volume_lots': 1500},
]
se._load_klines = lambda code, name=None: KL_LU
s5 = se.sell_signal({'code': 'TEST02', 'name': '测试2', 'buy_date': '2026-08-28',
                     'buy_price': 8.5, 'shares': 1000},
                    {'gap_pct': -2.0, 'open': 8.82, 'prev_close': 9.0})
check('S5 昨涨停+低开 → 竞价全卖', s5['action'] == 'sell' and '低开' in s5['reason'], s5['reason'][:30])

# ══════ 2. trading_journal: record_buy崩溃 + record_sell多笔合并 ══════
import trading_journal as tj

tmpd = tempfile.mkdtemp(prefix='gogo_regress_')
tj.PORTFOLIO_FILE = os.path.join(tmpd, 'portfolio.json')
tj.JOURNAL_FILE = os.path.join(tmpd, 'journal.json')

# 2a. 全新空仓(无positions键) → 原TypeError崩溃
tj.record_buy('楚天龙', '003040', 14.987, 1500, 1500 * 14.987)
pf = tj.load_portfolio()
check('J1 record_buy空仓启动不崩溃且落盘', len(pf.get('positions', [])) == 1 and pf['position']['code'] == '003040')

# 2b. 同码加仓第二笔 → 整仓卖 → 合并全部批次
tj.record_buy('楚天龙', '003040', 15.80, 1400, 1400 * 15.80)
tj.record_sell('楚天龙', '003040', 15.50)
pf = tj.load_portfolio()
expected_cash = 200000 - 1500 * 14.987 - 1400 * 15.80 + 2900 * 15.50
check('J2 同码两笔整仓卖→残仓清空', all(p['code'] != '003040' for p in pf.get('positions', [])))
check('J3 现金=卖出合并总额', abs(pf['cash'] - expected_cash) < 0.01, f'cash={pf["cash"]:.2f} 期望{expected_cash:.2f}')
check('J4 加权成本盈亏正确', abs(pf['total_pnl'] - (2900 * 15.50 - (1500 * 14.987 + 1400 * 15.80))) < 0.01)
check('J5 卖空后position=None', pf['position'] is None)

# 2c. 两只持仓卖其一 → 剩余持仓保留(L128修复)
tj.record_buy('英力特', '000635', 8.254, 4500, 4500 * 8.254)
tj.record_buy('欢瑞世纪', '000892', 3.5, 1000, 3500)
tj.record_sell('欢瑞世纪', '000892', 3.6)
pf = tj.load_portfolio()
check('J6 卖一只后剩余持仓保留', pf['position'] is not None and pf['position']['code'] == '000635')
shutil.rmtree(tmpd, ignore_errors=True)

# ══════ 3. morning_check: meta/turnover/T字过滤链 ══════
import morning_check as mc
meta = mc.stock_scoring_meta('002909')
check('M1 K线新鲜度守卫存在且为True', meta.get('kline_fresh') is True)
check('M2 现场分detail含turnover(漏传修复)', 'turnover' in (meta.get('detail') or {}))
check('M3 集泰股份现场分可算', isinstance(meta.get('score'), (int, float)))

cands = json.load(open(os.path.join(BASE, 'logs', 'candidates_2026-09-03.json'), encoding='utf-8'))
jt = next(c for c in cands['candidates'] if c['code'] == '002909')
one = jt.get('one_line', False)
cons = jt.get('cons', 0)
check('M4 集泰股份候选one_line=True(T字覆盖)且4板+一字过滤条件触发',
      one is True and int(cons) >= 4 and one, f'cons={cons} one_line={one}')

# ══════ 4. auction_pool: 夜间采集守卫(不落盘) ══════
import auction_pool as ap
ap2_dir = os.path.join(BASE, 'data', 'auction')
f_before = os.path.join(ap2_dir, '2026-09-04.json')
res = ap.capture_auction()  # 00:xx非竞价窗口 → 守卫拒绝
check('A1 非竞价窗口采集被拒(不写快照)',
      res is None and not os.path.exists(f_before))

# ══════ 5. capture_market_state: 非交易日守卫(不落盘) ══════
import capture_market_state as cms
_ms_path = os.path.join(BASE, 'data', 'market_state.json')
_mtime_before = os.path.getmtime(_ms_path)


class _FakeDT(cms.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 9, 5, 10, 0, 0)  # 周六


_orig_dt = cms.datetime
cms.datetime = _FakeDT
cms.main()
cms.datetime = _orig_dt
check('C1 非交易日跳过且market_state未被改写', os.path.getmtime(_ms_path) == _mtime_before)

# ══════ 6. review_recommendations: simulate高开执行价 + 卖单FIFO逻辑 ══════
import review_recommendations as rr
px, note = rr.simulate(10.0, True, 10.0, {'open': 10.6, 'high': 11.0, 'low': 10.2, 'close': 10.8})
exp = round(0.7 * (11.0 + 10.6) / 2 + 0.3 * 10.8, 3)
check('R1 昨涨停大高开≥5按执行价公式结算', abs(px - exp) < 0.001 and '分歧卖点' in note, f'{px} vs {exp}')
px2, note2 = rr.simulate(10.0, True, 10.0, {'open': 10.3, 'high': 10.5, 'low': 10.1, 'close': 10.4})
check('R2 昨涨停小高开(<5%)维持持有收盘', abs(px2 - 10.4) < 0.001)
# FIFO封顶逻辑(复制自review_date, 断言不产生负股数)
buys = [{'price': 10, 'shares': 100}, {'price': 10.5, 'shares': 50}]
sells = [{'price': 11, 'shares': 120}, {'price': 11.2, 'shares': 80}]  # 卖200>买150
total_sh = sum(b['shares'] for b in buys)
realized, sold_sh = 0.0, 0
for s in sells:
    take = min(s['shares'], total_sh - sold_sh)
    if take <= 0:
        break
    realized += s['price'] * take
    sold_sh += take
remain_sh = total_sh - sold_sh
check('R3 卖单FIFO封顶无负股数', remain_sh == 0 and sold_sh == 150 and abs(realized - (120 * 11 + 30 * 11.2)) < 0.01)

# ══════ 7. scoring: sector_bucket缺省改诚实低档 ══════
import scoring as sc
kl = json.load(open(os.path.join(BASE, 'data', 'kline_data', '002909.json'), encoding='utf-8'))
kl = kl.get('data', kl) if isinstance(kl, dict) else kl
base = {'seal_time': '0935', 'final_seal_time': '1000', 'zhaban': 0,
        'sector_count': 1, 'turnover': 5}
s_low, _ = sc.score_v4('002909', kl, dict(base, sector_bucket='<3'))
s_miss, _ = sc.score_v4('002909', kl, dict(base))  # 缺sector_bucket
s_high, _ = sc.score_v4('002909', kl, dict(base, sector_bucket='>=10'))
check('SC1 缺失sector_bucket与显式<3同分(不再默认最高档)', s_low == s_miss, f'{s_low} vs {s_miss}')
check('SC2 >=10档仍高于<3档(档位本身有效)', s_high > s_low)

# ══════ 汇总 ══════
print(f'\n==== 回归结果: {len(PASS)}通过 / {len(FAIL)}失败 ====')
if FAIL:
    print('失败项:', FAIL)
    sys.exit(1)
