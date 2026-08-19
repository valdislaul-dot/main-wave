"""
K线数据源统一封装 (2026-08-17)
================================
替换 baostock 后的数据源体系:

  增量主源  : 腾讯 fqkline (前复权, 当日实时, update_data 已有)
  增量备源  : Tushare Pro daily (不复权, 120积分, 权威, 当日更新及时)
  增量兜底  : 新浪 CN_MarketData (不复权, update_data 已有)

单位统一:
  volume(成交量) 统一为「股」(Tushare 返回「手」, 此处 ×100)
  与主库搜狐 hisHq 的 volume(股) 字段口径一致

Tushare token 读取顺序:
  1. 环境变量 TUSHARE_TOKEN
  2. data/tushare_token.txt (gitignored, 首行放token)

注: 东财 akshare stock_zh_a_hist 接口已失效(2025起东财反爬, akshare issue#5820/#6092), 弃用。
"""
import os

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOKEN_PATH = os.path.join(BASE, 'data', 'tushare_token.txt')


def _load_tushare_token():
    """Tushare token: 环境变量 > 配置文件(gitignored)"""
    tok = os.environ.get('TUSHARE_TOKEN', '').strip()
    if tok:
        return tok
    if os.path.exists(TOKEN_PATH):
        try:
            with open(TOKEN_PATH, encoding='utf-8') as f:
                tok = f.read().strip()
                if tok:
                    return tok
        except Exception:
            pass
    return None


def to_ts_code(code):
    """6位代码 → tushare ts_code (000001.SZ / 600000.SH / 8xxxxx.BJ)"""
    code = str(code).zfill(6)
    if code.startswith(('6', '9')):
        return f'{code}.SH'
    if code.startswith(('0', '3')):
        return f'{code}.SZ'
    if code.startswith(('8', '4')):
        return f'{code}.BJ'
    return f'{code}.SZ'


def _fmt_date(d):
    """YYYYMMDD → YYYY-MM-DD"""
    s = str(d)
    return f'{s[:4]}-{s[4:6]}-{s[6:]}' if len(s) >= 8 else s


def fetch_tushare_daily(code, start_date, end_date):
    """
    Tushare Pro daily (120积分, 不复权) → [{date, open, high, low, close, volume(股)}]
    用作: 增量备源 + 权威校准(校验免费源收盘价)
    """
    token = _load_tushare_token()
    if not token:
        return None
    try:
        import tushare as ts
        pro = ts.pro_api(token)
        df = pro.daily(
            ts_code=to_ts_code(code),
            start_date=str(start_date).replace('-', ''),
            end_date=str(end_date).replace('-', ''))
        if df is None or df.empty:
            return None
        rows = []
        prev_close = None
        for _, r in df.iterrows():
            close = round(float(r['close']), 2)
            row = {
                'date': _fmt_date(r['trade_date']),
                'open': round(float(r['open']), 2),
                'high': round(float(r['high']), 2),
                'low': round(float(r['low']), 2),
                'close': close,
                'volume': round(float(r['vol']) * 100, 2),  # 手→股
            }
            # pct_change 序列内计算 (不复权序列内自洽)
            if prev_close:
                row['pct_change'] = round((close - prev_close) / prev_close * 100, 2)
            prev_close = close
            # amount 千元→元 (与主库成交额口径对齐, 追加行补字段用)
            amt = r.get('amount')
            if amt is not None and float(amt) > 0:
                row['amount_10k_cny'] = round(float(amt) / 10, 2)
            rows.append(row)
        rows.sort(key=lambda x: x['date'])  # tushare默认降序, 转升序
        return rows or None
    except Exception:
        return None


if __name__ == '__main__':
    # 自测: 拉平安银行最近行情
    code = '000001'
    ts = fetch_tushare_daily(code, '2026-08-01', '2026-08-17')
    print('Tushare:', (ts[-1] if ts else '无token或失败'))
