"""🧊冰点修复信号测试 (2026-09-08晚拍板A+B)
条件: 昨日温度<40(极弱) → 昨池1板分歧票(涨停+大振幅>=10% 且 vr20>=2)
依据: 全样本3220笔分歧信号温度分层, 极弱分歧段均笔+3.88%/51%胜 (报告 logs/analysis/a_mode_backtest_2026-09-08.md)
monkeypatch文件IO, 符合套件断网约束。"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'scripts', 'daily'))
import morning_check as mc  # noqa: E402


def _klines(vol_last=250, amp=11.0, lu=True, n=25):
    """构造K线: 前n-1根volume=100收10, 末根volume=vol_last
    amp=末根振幅%, lu=末根是否涨停"""
    base_close = 10.0
    out = []
    for i in range(n - 1):
        out.append({'date': f'2026-08-{10 + i:02d}', 'open': 10, 'close': base_close,
                    'high': base_close + 0.1, 'low': base_close - 0.1, 'volume': 100})
    lo = base_close * (1 - amp / 100 / 2)
    hi = base_close * (1 + amp / 100 / 2)
    cl = base_close * 1.10 if lu else base_close * 1.03
    out.append({'date': '2026-09-07', 'open': 10.05, 'close': cl,
                'high': hi, 'low': lo, 'volume': vol_last})
    return out


@pytest.fixture
def setup_pool(monkeypatch, tmp_path):
    """BASE指向tmp, 昨池返回构造stocks, get_prev_pool_file返回20260907.json"""
    def _go(stocks, klines_map):
        monkeypatch.setattr(mc, 'BASE', str(tmp_path))
        kdir = tmp_path / 'data' / 'kline_data'
        kdir.mkdir(parents=True)
        for code, kls in klines_map.items():
            (kdir / f'{code}.json').write_text(
                json.dumps({'data': kls}), encoding='utf-8')
        monkeypatch.setattr(mc, '_load_prev_pool', lambda: (stocks, []))
        monkeypatch.setattr('zt_pool.get_prev_pool_file', lambda *a, **k: '20260907.json')
    return _go


def test_non_ice_env_empty(setup_pool):
    # 非冰点(>=40) → 空, 不读文件
    assert mc.ice_repair_stocks({'zt_n': 85}) == {}


def test_none_env_empty():
    assert mc.ice_repair_stocks(None) == {}


def test_ice_identifies_repair(setup_pool):
    stocks = [{'code': '600001', 'name': '修复票', 'limit_days': 1}]
    setup_pool(stocks, {'600001': _klines(vol_last=250, amp=11.0, lu=True)})
    r = mc.ice_repair_stocks({'zt_n': 38})
    assert '600001' in r
    assert r['600001']['vr'] >= 2.0
    assert r['600001']['amp'] >= 10


def test_ice_excludes_low_vr(setup_pool):
    stocks = [{'code': '600002', 'name': '缩量票', 'limit_days': 1}]
    setup_pool(stocks, {'600002': _klines(vol_last=120, amp=11.0, lu=True)})
    r = mc.ice_repair_stocks({'zt_n': 38})
    assert r == {}


def test_ice_excludes_small_amp(setup_pool):
    stocks = [{'code': '600003', 'name': '小振幅票', 'limit_days': 1}]
    setup_pool(stocks, {'600003': _klines(vol_last=250, amp=6.0, lu=True)})
    r = mc.ice_repair_stocks({'zt_n': 38})
    assert r == {}


def test_ice_excludes_cons2(setup_pool):
    stocks = [{'code': '600004', 'name': '二板票', 'limit_days': 2}]
    setup_pool(stocks, {'600004': _klines(vol_last=250, amp=11.0, lu=True)})
    r = mc.ice_repair_stocks({'zt_n': 38})
    assert r == {}


def test_ice_excludes_300(setup_pool):
    stocks = [{'code': '300001', 'name': '创业板票', 'limit_days': 1}]
    setup_pool(stocks, {'300001': _klines(vol_last=250, amp=11.0, lu=True)})
    r = mc.ice_repair_stocks({'zt_n': 38})
    assert r == {}


def test_ice_stale_kline_skipped(setup_pool):
    # K线末bar日期≠昨日池日期 → 跳过(防错日评分)
    stocks = [{'code': '600005', 'name': '陈旧K线票', 'limit_days': 1}]
    kls = _klines()
    kls[-1]['date'] = '2026-09-04'  # 滞后
    setup_pool(stocks, {'600005': kls})
    r = mc.ice_repair_stocks({'zt_n': 38})
    assert r == {}
