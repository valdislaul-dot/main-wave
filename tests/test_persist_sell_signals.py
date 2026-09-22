"""卖点结论落盘测试 (2026-09-19)
morning_check.persist_sell_signals → logs/sell_signals.json, 供 review_sells 对照。
同日重跑覆盖为最新(幂等); 引擎失败的持仓不记录。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'scripts', 'daily'))
import morning_check as mc  # noqa: E402


def _row():
    return ({'code': '000993', 'name': '闽东电力'},
            {'gap_pct': 1.8,
             'quote': {'open': 18.3, 'prev_close': 17.97, 'current': 19.6},
             'signal': {'action': 'hold', 'urgency': 'normal', 'kind': '', 'reason': 'r',
                        'detail': 'd', 'reference_price': 19.77}})


def test_persist_writes_and_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, 'LOG_DIR', str(tmp_path))
    mc.persist_sell_signals([_row()])
    p = os.path.join(str(tmp_path), 'sell_signals.json')
    hist = json.load(open(p, encoding='utf-8'))
    assert len(hist) == 1
    rec = list(hist.values())[0]
    assert rec['signals'][0]['code'] == '000993'
    assert rec['signals'][0]['action'] == 'hold'
    assert rec['signals'][0]['gap_pct'] == 1.8
    # 同日重跑 → 覆盖, 不追加
    mc.persist_sell_signals([_row()])
    hist2 = json.load(open(p, encoding='utf-8'))
    assert len(hist2) == 1 and len(list(hist2.values())[0]['signals']) == 1


def test_persist_skips_failed_positions(tmp_path, monkeypatch):
    monkeypatch.setattr(mc, 'LOG_DIR', str(tmp_path))
    mc.persist_sell_signals([({'code': '1', 'name': 'a'}, None),
                             ({'code': '2', 'name': 'b'}, {'signal': None})])
    assert not os.path.exists(os.path.join(str(tmp_path), 'sell_signals.json'))


def test_persist_records_top1_override(tmp_path, monkeypatch):
    """Top1 覆盖规则改写后的 signal 才是最终生效版, 落盘应记录改写后内容"""
    monkeypatch.setattr(mc, 'LOG_DIR', str(tmp_path))
    pos, r = _row()
    r['signal'] = {'action': 'hold', 'urgency': 'normal', 'kind': '',
                   'reason': '当日V3 Top1仍是它(闽东电力) → 继续持有',
                   'detail': '2026-09-12拍板', 'reference_price': 0}
    mc.persist_sell_signals([(pos, r)])
    hist = json.load(open(os.path.join(str(tmp_path), 'sell_signals.json'), encoding='utf-8'))
    sig = list(hist.values())[0]['signals'][0]
    assert sig['action'] == 'hold' and 'Top1' in sig['reason']
