"""gap 窗口权重单测
2026-09-04用户拍板: 硬边界4-8%改平滑 (形状: [4,8]核心=1, 边缘带[3,4)/(8,9]线性衰减, 带外=0)
2026-09-13用户拍板: 现行配置改回硬边界4-8% (gap_band=0), 对齐v3_sim_hold.py模拟口径
2026-09-22用户拍板: 下限下调 4%→0% (硬边界0-8%), 依据见 test_active_config_is_hard_boundary
—— 平滑窗数学仍保留可测(band>0显式传config), 现行定稿口径由 test_active_config_is_hard_boundary 锁定
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts', 'daily'))

from scoring import gap_weight

# 平滑窗测试用配置(band=1.0): 与2026-09-04定稿形状一致
CFG_SMOOTH = {'buy_window': [4.0, 8.0], 'gap_band': 1.0}


def test_core_full_weight():
    assert gap_weight(4.0) == 1.0
    assert gap_weight(6.0) == 1.0
    assert gap_weight(8.0) == 1.0


def test_outside_zero():
    assert gap_weight(-0.1) == 0.0
    assert gap_weight(9.1) == 0.0
    assert gap_weight(-1.0) == 0.0
    assert gap_weight(12.0) == 0.0


def test_enter_band_linear():
    # [3,4) 线性 0→1
    assert abs(gap_weight(3.0, config=CFG_SMOOTH) - 0.0) < 1e-9
    assert abs(gap_weight(3.5, config=CFG_SMOOTH) - 0.5) < 1e-9
    assert abs(gap_weight(3.9, config=CFG_SMOOTH) - 0.9) < 1e-9


def test_exit_band_linear():
    # (8,9] 线性 1→0
    assert abs(gap_weight(8.5, config=CFG_SMOOTH) - 0.5) < 1e-9
    assert abs(gap_weight(8.9, config=CFG_SMOOTH) - 0.1) < 1e-9
    assert abs(gap_weight(9.0, config=CFG_SMOOTH) - 0.0) < 1e-9


def test_band_zero_degenerates_to_hard():
    # 配置 gap_band=0 时退化为硬边界(向后兼容开关)
    cfg = {'buy_window': [4.0, 8.0], 'gap_band': 0}
    assert gap_weight(3.99, config=cfg) == 0.0
    assert gap_weight(4.0, config=cfg) == 1.0
    assert gap_weight(8.0, config=cfg) == 1.0
    assert gap_weight(8.01, config=cfg) == 0.0


def test_active_config_is_hard_boundary():
    """现行定稿口径(2026-09-22): 真实配置必须为硬边界0-8%; 上界8%外与低开(<0)一律排除

    2026-09-22 用户拍板下限 4%→0% (40个交易日2716票次, 真实口径=每日只买评分Top3):
      [4,8] -1.77%/胜43.9%  |  [3,8] -1.69%  |  [2,8] -1.57%
      [1,8] -0.78%          |  [0,8] -0.47%/胜56.5%
    跨期检验(训练段07-28~08-25 / 检验段08-26~09-22)方向一致, 两段均为 [0,8] 优于 [4,8]。
    低开(gap<0)仍排除 —— 与知识库「低开=第一卖点」一致。

    原因: V3为负分累加制, 综合分=评分×gap权重 在负分域会反转
    (实测边缘带gap3.5%综合分-2.50 反超核心带gap6.0%的-5.00) → 必须用硬边界使权重恒为1
    """
    for g, exp in [(-0.1, 0.0), (0.0, 1.0), (2.0, 1.0), (3.5, 1.0), (4.0, 1.0),
                   (6.0, 1.0), (8.0, 1.0), (8.01, 0.0), (8.5, 0.0)]:
        assert gap_weight(g) == exp, f'gap={g} 期望{exp}, 实际{gap_weight(g)}'
