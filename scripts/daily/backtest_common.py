"""
回测公共机制 (2026-09-04 用户定稿, 固化)

1. K线唯一数据源: data/kline_data/ — 回测只读已下载的本地历史数据,
   禁止网络抓取/临时拉取/编造。backtest_kline 已删除(2026-09-04)。
2. 窗口参数 (回测时由用户给出时间):
   --months N       从今天往前 N 个月 (3=三个月 5=五个月 12=一年 36=三年)
   --start YYYY-MM-DD [--end YYYY-MM-DD]  确定时间段 (如 2024-06-01 ~ 2024-09-30)
   缺省 = 各脚本默认窗口
3. 温度分档仓位 (2026-09-04 拍板): <40空仓 / 每10只一档仓位从40%起步 / ≥100全仓
"""
import os, sys
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KLINE_DIR = os.path.join(BASE, 'data', 'kline_data')  # 写死: 回测唯一K线源


def parse_window(default_start, default_end):
    """解析窗口参数 → (start, end) 'YYYY-MM-DD'; 缺省用脚本默认窗"""
    args = sys.argv[1:]
    start, end = default_start, default_end
    if '--months' in args:
        i = args.index('--months')
        if i + 1 < len(args):
            n = int(args[i + 1])
            end = datetime.now().strftime('%Y-%m-%d')
            start = (datetime.now() - timedelta(days=int(n * 30.44))).strftime('%Y-%m-%d')
    if '--start' in args:
        i = args.index('--start')
        if i + 1 < len(args):
            start = args[i + 1]
    if '--end' in args:
        i = args.index('--end')
        if i + 1 < len(args):
            end = args[i + 1]
    return start, end


def has_window_args():
    """是否用户给了窗口参数"""
    a = sys.argv[1:]
    return ('--months' in a) or ('--start' in a) or ('--end' in a)


def temp_position(zt_n):
    """温度分档仓位 (2026-09-04拍板: <40空仓, 每10只一档, 仓位从40%起步, ≥100全仓)"""
    if zt_n < 40:
        return 0.0
    return round(min(1.0, (zt_n // 10) * 0.1), 2)
