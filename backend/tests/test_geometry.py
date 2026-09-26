"""几何核心单元测试。

注：只有测试侧允许用稠密采样做对照；服务端实现本身为解析求根。
"""

import numpy as np
import pytest

from app.geometry import (
    _first_derivative_polys,
    audit_curve,
    bezier_point,
    check_joint,
    find_zero_tangent,
    segment_max_curvature,
)

# 抛物线 y = x^2/3（x=3t, y=3t^2）：κ(t) = (2/3) / (1+4t^2)^1.5，t=0 处取最大值 2/3
PARABOLA = [[0, 0], [1, 0], [2, 1], [3, 3]]
# 与抛物线端点、切向量完全衔接的第二段：κ 最大值同样为 2/3（t=1 处）
PARABOLA_NEXT = [[3, 3], [4, 5], [5, 6], [6, 6]]


def _dense_max_curvature(P, n=20001):
    """测试对照用：稠密采样近似最大曲率（仅测试使用）。"""
    P = np.asarray(P, dtype=float)
    c0 = P[0]
    c1 = 3.0 * (P[1] - P[0])
    c2 = 3.0 * (P[2] - 2.0 * P[1] + P[0])
    c3 = P[3] - 3.0 * P[2] + 3.0 * P[1] - P[0]
    ts = np.linspace(0.0, 1.0, n)
    best = 0.0
    for t in ts:
        d = c1 + 2 * c2 * t + 3 * c3 * t * t
        dd = 2 * c2 + 6 * c3 * t
        cross = d[0] * dd[1] - d[1] * dd[0]
        speed2 = d[0] ** 2 + d[1] ** 2
        if speed2 > 0:
            best = max(best, abs(cross) / speed2 ** 1.5)
    return best


# ---------------------------------------------------------------- 最大曲率

def test_straight_line_zero_curvature():
    k, t = segment_max_curvature([[0, 0], [1, 1], [2, 2], [3, 3]])
    assert k == 0.0
    assert t == 0.0


def test_parabola_max_curvature_exact():
    k, t = segment_max_curvature(PARABOLA)
    assert k == pytest.approx(2.0 / 3.0, abs=1e-12)
    assert t == pytest.approx(0.0, abs=1e-12)


def test_symmetric_arc_interior_max():
    # 关于 t=0.5 对称的拱：κ(0.5) = 4/3，位置 (1.5, 1.5)
    P = [[0, 0], [1, 2], [2, 2], [3, 0]]
    k, t = segment_max_curvature(P)
    assert k == pytest.approx(4.0 / 3.0, abs=1e-12)
    assert t == pytest.approx(0.5, abs=1e-12)
    x, y = bezier_point(P, t)
    assert (x, y) == pytest.approx((1.5, 1.5))


def test_true_cubic_matches_dense_reference():
    # 真正的三次段（c3 ≠ 0），最大值在内部驻点
    P = [[0, 0], [1, 2], [3, 2], [4, 0]]
    k, t = segment_max_curvature(P)
    k_ref = _dense_max_curvature(P)
    assert k >= k_ref - 1e-9          # 解析值不低于采样下界
    assert k == pytest.approx(k_ref, abs=1e-4)
    assert 0.0 < t < 1.0              # 最大值确实在内部


def test_max_curvature_tie_prefers_smaller_t():
    # 直线段曲率处处为 0，结果稳定取 t=0
    k, t = segment_max_curvature([[5, 5], [6, 5], [8, 5], [9, 5]])
    assert k == 0.0 and t == 0.0


# ---------------------------------------------------------------- 零切向量

def _zt(P):
    dx, dy = _first_derivative_polys(np.asarray(P, dtype=float))
    return find_zero_tangent(dx, dy)


def test_zero_tangent_at_start():
    assert _zt([[0, 0], [0, 0], [1, 1], [2, 2]]) == pytest.approx(0.0)


def test_zero_tangent_interior_cusp():
    # x'(t) = 6(2t-1)^2，t=0.5 处速度为零（尖点）
    assert _zt([[0, 0], [2, 0], [0, 0], [2, 0]]) == pytest.approx(0.5, abs=1e-9)


def test_zero_tangent_degenerate_point():
    assert _zt([[1, 1], [1, 1], [1, 1], [1, 1]]) == pytest.approx(0.0)


def test_no_zero_tangent():
    assert _zt(PARABOLA) is None
    assert _zt([[0, 0], [2, 0], [1, 0], [3, 0]]) is None  # 共线但速度恒正


# ---------------------------------------------------------------- 段间连续性

def test_joint_exact_continuity_passes():
    assert check_joint(PARABOLA, PARABOLA_NEXT, 0) is None


def test_joint_proportional_tangent_passes():
    # G1：切向量同向但模长不同，几何上方向连续，应通过
    seg = [[3, 3], [5, 7], [6, 9], [7, 11]]  # 起点切向量 (6,12) = 2×(3,6)
    assert check_joint(PARABOLA, seg, 0) is None


def test_joint_endpoint_mismatch():
    seg = [[3, 4], [4, 5], [5, 6], [6, 6]]
    res = check_joint(PARABOLA, seg, 0)
    assert res["ok"] is False
    f = res["failure"]
    assert f["reason"] == "endpoint_mismatch"
    assert f["segment_index"] == 1
    assert f["adjacent_segment_index"] == 0
    assert f["t"] == 0.0
    assert f["point"] == {"x": 3.0, "y": 4.0}
    assert f["detail"]["prev_end"] == {"x": 3, "y": 3}


def test_joint_tangent_mismatch():
    seg = [[3, 3], [4, 6], [5, 6], [6, 6]]  # 起点切向量 (3,9) 与 (3,6) 不共线
    res = check_joint(PARABOLA, seg, 0)
    f = res["failure"]
    assert f["reason"] == "tangent_mismatch"
    assert f["segment_index"] == 1
    assert f["point"] == {"x": 3.0, "y": 3.0}


def test_joint_tangent_opposite_direction():
    seg = [[3, 3], [2, 1], [1, 0], [0, 0]]  # 起点切向量 (-3,-6)，反向
    res = check_joint(PARABOLA, seg, 0)
    assert res["failure"]["reason"] == "tangent_mismatch"


def test_joint_zero_tangent_at_next_start():
    seg = [[3, 3], [3, 3], [5, 5], [6, 6]]  # Q0 == Q1 -> 起点切向量为零
    res = check_joint(PARABOLA, seg, 0)
    f = res["failure"]
    assert f["reason"] == "zero_tangent"
    assert f["segment_index"] == 1


# ---------------------------------------------------------------- 审计主流程

def test_audit_qualified_two_segments():
    res = audit_curve([PARABOLA, PARABOLA_NEXT], 1.0)
    assert res["ok"] is True
    assert res["failure"] is None
    segs = res["segments"]
    assert len(segs) == 2
    assert segs[0]["max_curvature"] == pytest.approx(2.0 / 3.0, abs=1e-12)
    assert segs[0]["t"] == pytest.approx(0.0)
    assert segs[0]["point"] == {"x": 0.0, "y": 0.0}
    assert segs[1]["max_curvature"] == pytest.approx(2.0 / 3.0, abs=1e-12)
    assert segs[1]["t"] == pytest.approx(1.0)
    assert segs[1]["point"] == {"x": 6.0, "y": 6.0}


def test_audit_qualified_five_collinear_segments():
    segs = [[[3 * i, 0], [3 * i + 1, 0], [3 * i + 2, 0], [3 * i + 3, 0]]
            for i in range(5)]
    res = audit_curve(segs, 0.5)
    assert res["ok"] is True
    assert [s["max_curvature"] for s in res["segments"]] == [0.0] * 5


def test_audit_curvature_exceeded_reports_earliest():
    res = audit_curve([PARABOLA, PARABOLA_NEXT], 0.5)
    assert res["ok"] is False
    f = res["failure"]
    assert f["reason"] == "curvature_exceeded"
    assert f["segment_index"] == 0
    assert f["t"] == pytest.approx(0.0)
    assert f["point"] == {"x": 0.0, "y": 0.0}
    assert f["max_curvature"] == pytest.approx(2.0 / 3.0, abs=1e-12)
    assert f["limit"] == 0.5


def test_audit_curvature_at_limit_passes():
    res = audit_curve([PARABOLA, PARABOLA_NEXT], 2.0 / 3.0)
    assert res["ok"] is True


def test_audit_zero_tangent_not_runnable():
    bad = [[0, 0], [0, 0], [1, 1], [2, 2]]
    res = audit_curve([bad, PARABOLA_NEXT], 10.0)
    f = res["failure"]
    assert f["reason"] == "zero_tangent"
    assert f["segment_index"] == 0
    assert f["t"] == pytest.approx(0.0)


def test_audit_travel_order_earliest_failure():
    # 第 1 段曲率超限 + 拼接也断开：应报告更早的段内曲率问题
    broken_next = [[9, 9], [10, 10], [11, 11], [12, 12]]
    res = audit_curve([PARABOLA, broken_next], 0.5)
    f = res["failure"]
    assert f["reason"] == "curvature_exceeded"
    assert f["segment_index"] == 0


def test_audit_joint_failure_before_next_segment_analysis():
    # 拼接断开，且后一段本身也有零切向量：行进顺序上先报断接
    seg = [[3, 4], [3, 4], [5, 6], [6, 6]]
    res = audit_curve([PARABOLA, seg], 10.0)
    f = res["failure"]
    assert f["reason"] == "endpoint_mismatch"
    assert f["segment_index"] == 1


def test_audit_result_is_deterministic():
    args = ([PARABOLA, PARABOLA_NEXT], 0.5)
    assert audit_curve(*args) == audit_curve(*args)
