"""gap 平滑窗口权重单测 (2026-09-04用户拍板: 硬边界4-8%改平滑)
形状: [4,8]核心=1, 边缘带[3,4)/(8,9]线性衰减, 带外=0
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'daily'))

from scoring import gap_weight


def test_core_full_weight():
    assert gap_weight(4.0) == 1.0
    assert gap_weight(6.0) == 1.0
    assert gap_weight(8.0) == 1.0


def test_outside_zero():
    assert gap_weight(2.9) == 0.0
    assert gap_weight(9.1) == 0.0
    assert gap_weight(-1.0) == 0.0
    assert gap_weight(12.0) == 0.0


def test_enter_band_linear():
    # [3,4) 线性 0→1
    assert abs(gap_weight(3.0) - 0.0) < 1e-9
    assert abs(gap_weight(3.5) - 0.5) < 1e-9
    assert abs(gap_weight(3.9) - 0.9) < 1e-9


def test_exit_band_linear():
    # (8,9] 线性 1→0
    assert abs(gap_weight(8.5) - 0.5) < 1e-9
    assert abs(gap_weight(8.9) - 0.1) < 1e-9
    assert abs(gap_weight(9.0) - 0.0) < 1e-9


def test_band_zero_degenerates_to_hard():
    # 配置 gap_band=0 时退化为硬边界(向后兼容开关)
    cfg = {'buy_window': [4.0, 8.0], 'gap_band': 0}
    assert gap_weight(3.99, config=cfg) == 0.0
    assert gap_weight(4.0, config=cfg) == 1.0
    assert gap_weight(8.0, config=cfg) == 1.0
    assert gap_weight(8.01, config=cfg) == 0.0
