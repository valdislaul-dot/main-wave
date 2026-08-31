"""
同花顺官方金融数据API客户端 (2026-08-31接入, 官方免费)
用途: ①涨停池爬虫失败时的兜底源 ②每日双源校验(家数/连板数) ③备用竞价快照/连板天梯
文档: https://fuyao.aicubes.cn/docs/ | 仓库: HiThink-Tech/Financial-API
鉴权: Header X-api-key (token在 data/hithink_token.txt, 已gitignore, 不入库)
"""
import os, json, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
API_BASE = 'https://fuyao.aicubes.cn'
TOKEN_FILE = os.path.join(BASE, 'data', 'hithink_token.txt')

# 与主流程同口径: 只留主板(60/00开头), 排除创业/科创/北交
_EXCLUDE_PREFIX = ('300', '301', '688', '8', '9')


def load_token():
    try:
        with open(TOKEN_FILE, encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        return ''


def _get(path, params=None, timeout=30):
    url = API_BASE + path
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'X-api-key': load_token()})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _date_to_ms(date_str):
    """'YYYY-MM-DD' → Asia/Shanghai 00:00 毫秒戳"""
    dt = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=timezone(timedelta(hours=8)))
    return int(dt.timestamp() * 1000)


def _is_main_board(code):
    return not str(code).startswith(_EXCLUDE_PREFIX)


def fetch_limit_up_pool(date_str=None, main_board_only=True):
    """涨停池(官方)。date_str None=今日; 支持近2年历史。
    返回: [{code,name,price,pct,limit_days,first_seal,seal_fund,max_seal_fund,industry,is_st,is_new}]
    官方无炸板次数/换手率/流通市值(炸板见 fetch_limit_break_pool)"""
    params = {'sort_field': 'continue_day_cnt', 'sort_dir': 'desc', 'size': 200}
    if date_str:
        params['date_ms'] = _date_to_ms(date_str)
    items, page = [], 1
    while True:
        p = dict(params, page=page)
        d = _get('/api/a-share/special-data/limit-up-pool', p)
        data = d.get('data') or {}
        batch = data.get('item', [])
        items.extend(batch)
        pg = data.get('pagination', {})
        if not batch or page >= int(pg.get('pages', 1) or 1):
            break
        page += 1
    out = []
    for x in items:
        code = str(x.get('ticker', '')).zfill(6)
        if main_board_only and not _is_main_board(code):
            continue
        out.append({
            'code': code,
            'name': x.get('name', ''),
            'price': float(x.get('last_price', 0) or 0),
            'pct': round(float(x.get('price_change_ratio_pct', 0) or 0), 2),
            'limit_days': int(x.get('continue_day_cnt', 1) or 1),
            'first_seal': str(x.get('limit_up_time', '') or ''),
            'seal_fund': float(x.get('seal_money', 0) or 0),
            'max_seal_fund': float(x.get('max_seal_money', 0) or 0),
            'industry': str(x.get('limit_up_reason', '') or ''),
            'is_st': bool(x.get('is_st', False)),
            'is_new': bool(x.get('is_new', False)),
        })
    return out


def fetch_limit_break_pool(date_str=None, main_board_only=True):
    """炸板池(官方, 炸板未回封)。date_str None=今日。返回同 fetch_limit_up_pool 结构(无封单字段)"""
    params = {'size': 200}
    if date_str:
        params['date_ms'] = _date_to_ms(date_str)
    items, page = [], 1
    while True:
        p = dict(params, page=page)
        d = _get('/api/a-share/special-data/limit-break-pool', p)
        data = d.get('data') or {}
        batch = data.get('item', [])
        items.extend(batch)
        pg = data.get('pagination', {})
        if not batch or page >= int(pg.get('pages', 1) or 1):
            break
        page += 1
    out = []
    for x in items:
        code = str(x.get('ticker', '')).zfill(6)
        if main_board_only and not _is_main_board(code):
            continue
        out.append({'code': code, 'name': x.get('name', ''), 'industry': str(x.get('limit_up_reason', '') or '')})
    return out


def fetch_ladder():
    """连板天梯: 近30个交易日连板梯队矩阵(每档最多4只)"""
    return _get('/api/a-share/special-data/limit-up-ladder')


def auction_snapshot(codes, stage='final'):
    """竞价快照。codes: 纯代码列表(≤100), 自动转 thscode。
    返回官方原始 item 列表(含竞价量比/流通市值等)"""
    if not codes:
        return []
    ths = []
    for c in codes:
        c = str(c).zfill(6)
        suf = '.SH' if c.startswith(('6', '9')) else ('.BJ' if c.startswith(('4', '8')) else '.SZ')
        ths.append(c + suf)
    d = _get('/api/a-share/auction/snapshot', {'thscodes': ','.join(ths[:100]), 'stage': stage})
    return (d.get('data') or {}).get('item', [])


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    args = sys.argv[1:]
    if args and args[0] == '--today':
        pool = fetch_limit_up_pool()
        print(f'官方今日涨停池(主板): {len(pool)} 只')
        for x in pool[:5]:
            print(f"  {x['code']} {x['name']} {x['limit_days']}板 封单{x['seal_fund']:,.0f} {x['industry'][:20]}")
    elif args and args[0] == '--date':
        pool = fetch_limit_up_pool(args[1])
        print(f'官方 {args[1]} 涨停池(主板): {len(pool)} 只')
        for x in pool[:5]:
            print(f"  {x['code']} {x['name']} {x['limit_days']}板 {x['industry'][:20]}")
    else:
        print('用法: hithink_api.py --today | --date YYYY-MM-DD')
