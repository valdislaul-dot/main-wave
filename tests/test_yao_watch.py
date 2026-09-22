"""🐲 妖股指纹层 测试 (2026-09-21)

覆盖两处修复:
  ① 板块计数 bug — 原用 industry **整串**做 Counter 精确匹配, 同花顺给的是
     "半导体存储+芯片扩产+业绩扭亏" 这类个股化复合串, 池内几乎两两不重样
     → 板块数恒等于 1 → 条件④永远为假 → 模块自 2026-08-20 换源起命中恒为 0
     (静默失效一个月). 修复: 改用 scoring.sector_resonance_count 按题材词拆词共振。
  ② 指纹层条件修订 (依据 logs/analysis/yaogu_theory_verification_2026-09-19.md §5,
     12636 个2板事件全样本复现): 删「前20日+3~8%」(1.04x 无预测力);
     启动价阈值 30元 → 10元 (<10元 1.36x, 10-30元 降至 0.70x)。
"""
import datetime
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'scripts', 'daily'))
import yao_watch as yw  # noqa: E402


def _klines(start=8.0, board=2, vol_last=50, n=40):
    """n 根K线: 前 n-board 根平盘(收=start), 末尾 board 根连续涨停。
    平盘段让 pre20 = 0%(落在原条件③ 3~8% 之外) → 用于验证条件③确已移除。"""
    kl = []
    d0 = datetime.date(2026, 7, 1)
    for i in range(n - board):
        kl.append({'date': (d0 + datetime.timedelta(days=i)).isoformat(),
                   'open': start, 'close': start, 'high': start, 'low': start, 'volume': 100})
    prev = start
    for i in range(board):
        nc = round(prev * 1.1, 2)
        kl.append({'date': (d0 + datetime.timedelta(days=n - board + i)).isoformat(),
                   'open': prev, 'close': nc, 'high': nc, 'low': prev, 'volume': 100})
        prev = nc
    kl[-1]['volume'] = vol_last          # 末日缩量 → vol_ratio = 50/100 = 0.5
    return kl


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    """隔离 yao_watch 的四个 IO 路径, 返回 (写K线, 写state) 两个辅助函数"""
    kdir, adir = tmp_path / 'kline', tmp_path / 'auction'
    kdir.mkdir()
    adir.mkdir()
    state_f = tmp_path / 'state.json'
    watch_f = tmp_path / 'yao_watch.json'
    monkeypatch.setattr(yw, 'KLINE_DIR', str(kdir))
    monkeypatch.setattr(yw, 'AUCTION_DIR', str(adir))
    monkeypatch.setattr(yw, 'ZT_STATE', str(state_f))
    monkeypatch.setattr(yw, 'WATCH_FILE', str(watch_f))

    def write_klines(code, klines):
        (kdir / f'{code}.json').write_text(
            json.dumps({'data': klines}, ensure_ascii=False), encoding='utf-8')

    def write_state(rows):
        state_f.write_text(json.dumps({'stocks': rows}, ensure_ascii=False), encoding='utf-8')

    def read_watch():
        return json.loads(watch_f.read_text(encoding='utf-8'))

    return write_klines, write_state, read_watch


def test_sector_count_word_level_not_exact_match(sandbox, capsys):
    """核心回归: 同花顺复合原因串下, 共享题材词的票板块数必须 >1。
    修复前 Counter 整串匹配 → 每只都是 1 → 条件④永远为假 → 命中恒为 0。"""
    write_klines, write_state, read_watch = sandbox
    write_state([
        {'code': '600001', 'name': '甲股', 'limit_days': 2,
         'industry': '半导体存储+芯片扩产+业绩扭亏'},
        {'code': '600002', 'name': '乙股', 'limit_days': 2,
         'industry': '半导体存储+光伏概念'},
    ])
    write_klines('600001', _klines())
    write_klines('600002', _klines())

    yw.main()
    out = capsys.readouterr().out

    # 两串整串互不相同(修复前 sector 会算成 1), 但共享「半导体存储」→ 板块 2 只
    assert '板块2只' in out
    assert '命中 2 只' in out
    assert '⭐ 命中 0 只' not in out
    assert {s['code'] for s in read_watch()['stocks']} == {'600001', '600002'}


def test_isolated_sector_still_fails_condition(sandbox, capsys):
    """反向对照: 题材词完全不共享 → 板块=1 → 不命中, 落入接近命中并标注缺板块"""
    write_klines, write_state, _ = sandbox
    write_state([
        {'code': '600001', 'name': '甲股', 'limit_days': 2, 'industry': '半导体存储'},
        {'code': '600002', 'name': '乙股', 'limit_days': 2, 'industry': '白酒+免税'},
    ])
    write_klines('600001', _klines())
    write_klines('600002', _klines())

    yw.main()
    out = capsys.readouterr().out
    assert '命中 0 只' in out
    assert '缺: 板块≥2只' in out


def test_pre20_is_no_longer_a_filter(sandbox, capsys):
    """条件③「前20日+3~8%」已移除: pre20=0%(不合原区间)仍应命中 3 条件"""
    write_klines, write_state, _ = sandbox
    write_state([
        {'code': '600001', 'name': '甲股', 'limit_days': 2, 'industry': '半导体存储'},
        {'code': '600002', 'name': '乙股', 'limit_days': 2, 'industry': '半导体存储+光伏'},
    ])
    kl = _klines()
    assert yw.fingerprint('600001', kl, 2)['pre20'] == 0.0     # 确实落在原 3~8% 之外
    write_klines('600001', kl)
    write_klines('600002', _klines())

    yw.main()
    assert '命中 2 只' in capsys.readouterr().out


def test_price_threshold_10_not_30(sandbox, capsys):
    """启动价阈值 10元: 12元票应缺条件②(旧阈值30元下会被误判为命中)"""
    write_klines, write_state, _ = sandbox
    write_state([
        {'code': '600001', 'name': '甲股', 'limit_days': 2, 'industry': '半导体存储'},
        {'code': '600002', 'name': '乙股', 'limit_days': 2, 'industry': '半导体存储+光伏'},
        {'code': '600003', 'name': '丙股', 'limit_days': 2, 'industry': '半导体存储+光伏'},
    ])
    write_klines('600001', _klines(start=8.0))
    write_klines('600002', _klines(start=8.0))
    write_klines('600003', _klines(start=12.0))

    yw.main()
    out = capsys.readouterr().out
    assert '命中 2 只' in out
    assert '缺: 启动<10元' in out


def test_vol_ratio_thresholds_by_board():
    assert yw._vol_ratio_max(2) == 0.8
    assert yw._vol_ratio_max(3) == 1.2
    assert yw._vol_ratio_max(4) == 1.2


def test_constants_lock():
    """指纹阈值锁定 = 09-19 复现报告 §5 (防误改)"""
    assert (yw.BOARD_MIN, yw.BOARD_MAX) == (2, 4)
    assert yw.PRICE_MAX == 10.0
    assert yw.SECTOR_MIN == 2
    # 2026-09-22: 晋级判据不再硬编码, 跟随现行买入窗口 (原为 (4.0, 8.0))
    from scoring import get_buy_window
    assert (yw.GAP_MIN, yw.GAP_MAX) == tuple(get_buy_window())
    assert not hasattr(yw, 'PRE20_MIN'), '前20日条件应已移除'
    assert not hasattr(yw, 'PRE20_MAX'), '前20日条件应已移除'


def test_fingerprint_board_mismatch_and_short_klines():
    assert yw.fingerprint('600001', _klines(board=2), 3) is None      # 末尾不是3连板
    assert yw.fingerprint('600001', _klines(board=2)[:20], 2) is None  # K线不足
