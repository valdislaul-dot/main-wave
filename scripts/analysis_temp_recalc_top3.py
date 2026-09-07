# -*- coding: utf-8 -*-
"""临时离线重算(2026-09-07): 用今早竞价快照 + 新vrU型A形状重算当日可买前三
复刻morning_check买入候选逻辑(665-720行), 不触网不重采集。
新形状已在 scoring_config.json 生效, score_v4自动读取。
"""
import json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'daily'))
sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import morning_check as mc
from scoring import gap_weight

# 固定用今早快照(不按datetime.now读)
auc_file = os.path.join(BASE, 'data', 'auction', '2026-09-07.json')
with open(auc_file, encoding='utf-8') as f:
    auc_data = json.load(f)
auction_stocks = auc_data.get('stocks', [])

# 候选评分查找表(盘后流水线 candidates, 仅兜底用)
candidate_scores = {}
cand_file = None
for name in ('candidates_2026-09-04.json', 'candidates.json'):
    p = os.path.join(BASE, 'data', name)
    if os.path.exists(p):
        cand_file = p
        break
if cand_file:
    with open(cand_file, encoding='utf-8') as f:
        cd = json.load(f)
    for c in (cd.get('candidates', []) if isinstance(cd, dict) else cd):
        candidate_scores[c['code']] = c
print(f'快照: {auc_data.get("date")} 采集 {auc_data.get("captured")} | 候选表: {cand_file or "无"}')

buyable = []
_stale_cnt = 0
for s in auction_stocks:
    code = s.get('code', '')
    gap = s.get('gap_pct', 0)
    is_one_line = s.get('one_line', False)
    is_300 = code.startswith(('300', '301', '688', '8', '9'))
    cand = candidate_scores.get(code, {})

    if is_300 or is_one_line or s.get('high_risk', False):
        continue
    if int(cand.get('cons', 0) or 0) >= 4 and cand.get('one_line', False):
        continue
    _gw = gap_weight(gap)
    if _gw > 0:
        meta = mc.stock_scoring_meta(code)
        if not meta.get('kline_fresh', True):
            _stale_cnt += 1
            continue
        auction_score = s.get('score', 0)
        cand_score = cand.get('score', 0)
        final_score = meta['score'] if meta['score'] is not None else \
            (auction_score if auction_score > 0 else cand_score)
        buyable.append({
            'code': code, 'name': s.get('name', ''),
            'gap': gap, 'score': final_score,
            'weighted': final_score * _gw, 'gap_w': _gw,
            'limit_days': meta['cons'] if meta['cons'] != '?' else s.get('limit_days', cand.get('cons', 1)),
            'industry': meta['industry'] or cand.get('industry', ''),
            'sector': meta['sector'],
            'vr20': cand.get('vr20', 0), 'turnover': cand.get('turnover', 0),
        })

if _stale_cnt:
    print(f'⚠ K线滞后跳过 {_stale_cnt} 只候选')
buyable.sort(key=lambda x: x['weighted'], reverse=True)

print(f'\n{"#":<3}{"标的":<14}{"评分":>6}{"竞价gap":>8}{"gap权重":>8}{"连板":>5}{"板块":>9}')
for i, b in enumerate(buyable[:8], 1):
    print(f'  {i:<3}{b["name"]}({b["code"]}){b["score"]:>8.0f}{b["gap"]:>+7.1f}%{b["gap_w"]:>8.2f}'
          f'{str(b["limit_days"]) + "板":>6}{str(b["sector"]) + "只":>6}')
print(f'\n快照自带 score 字段是旧形状打的, 本重算的"评分"列为现场新形状评分')
