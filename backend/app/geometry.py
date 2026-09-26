"""小车导轨三次贝塞尔拼接曲线的几何审计核心。

数学约定
--------
每段为三次贝塞尔曲线 B(t) = sum_i C(3,i) (1-t)^(3-i) t^i P_i，t ∈ [0,1]。

曲率 κ(t) = |A(t)| / S(t)^{3/2}，其中
    A(t) = x'(t) y''(t) - y'(t) x''(t)   （一阶与二阶导向量的叉积）
    S(t) = x'(t)^2 + y'(t)^2             （速度平方）

κ² 的导数：
    d(κ²)/dt = A(t) · (2 A' S - 3 A S') / S^4

因此 κ² 的全部驻点为 A(t) = 0 与 G(t) = 2 A' S - 3 A S' = 0 的实根（S > 0 时）。
对三次贝塞尔，A 为不超过 3 次、G 为不超过 6 次的多项式，这里用伴随矩阵
特征值法（numpy.roots）求出 [0,1] 内全部实根，再在端点 t=0,1 与全部驻点
上评估曲率取最大值。全程解析求根，不做离散采样。

零切向量：存在 t ∈ [0,1] 使 B'(t) = 0（即 x' 与 y' 在 [0,1] 有公共实根），
视为不可运行。

段间连续性（控制点为整数，使用精确整数运算）：
    - 端点连续：P3 与下一段 P0 完全重合；
    - 一阶切向量连续：两端点处切向量共线且同向（G1，叉积为 0 且点积为正）。
"""

from __future__ import annotations

import numpy as np

# 根筛选容差：虚部相对容差（误收的近复根只会多评估一个合法曲率点，无害；
# 漏收实根才可能低估最大曲率，故虚部容差取宽）
_IMAG_RTOL = 1e-6
# 根落在 [0,1] 的区间容差
_INTERVAL_TOL = 1e-9
# x' 与 y' 公共根判定容差（相对系数规模）
_COMMON_ROOT_RTOL = 1e-7
# 曲率超限判定容差：k > limit + tol 才算超限，避免边界值浮点抖动
_CURVATURE_RTOL = 1e-9
# 并列最大曲率取较小 t 的比较裕量
_TIE_TOL = 1e-12


# ---------------------------------------------------------------------------
# 多项式工具（系数按降幂排列的一维数组）
# ---------------------------------------------------------------------------

def _trim(p, rtol=1e-12):
    """去除首端（最高次侧）近零系数。"""
    p = np.asarray(p, dtype=float).ravel()
    if p.size == 0:
        return np.zeros(1)
    scale = max(1.0, float(np.max(np.abs(p))))
    tol = rtol * scale
    nz = np.flatnonzero(np.abs(p) > tol)
    if nz.size == 0:
        return np.zeros(1)
    return p[nz[0]:]


def _padd(a, b):
    a = np.asarray(a, dtype=float).ravel()
    b = np.asarray(b, dtype=float).ravel()
    if a.size < b.size:
        a = np.concatenate([np.zeros(b.size - a.size), a])
    elif b.size < a.size:
        b = np.concatenate([np.zeros(a.size - b.size), b])
    return a + b


def _psub(a, b):
    return _padd(a, -np.asarray(b, dtype=float).ravel())


def _pmul(a, b):
    return np.convolve(
        np.asarray(a, dtype=float).ravel(), np.asarray(b, dtype=float).ravel()
    )


def _pder(p):
    p = np.asarray(p, dtype=float).ravel()
    n = p.size - 1
    if n <= 0:
        return np.zeros(1)
    return p[:-1] * np.arange(n, 0, -1)


def _roots_in_01(p):
    """多项式 p 在 [0,1] 内的全部实根（升序，端点处做钳制）。"""
    p = _trim(p)
    if p.size <= 1:
        return []
    out = []
    for r in np.roots(p):
        if abs(r.imag) <= _IMAG_RTOL * max(1.0, abs(r.real)):
            x = float(r.real)
            if -_INTERVAL_TOL <= x <= 1.0 + _INTERVAL_TOL:
                out.append(min(1.0, max(0.0, x)))
    return sorted(out)


# ---------------------------------------------------------------------------
# 贝塞尔基础
# ---------------------------------------------------------------------------

def _power_coeffs(P):
    """三次贝塞尔 -> 幂基系数：B(t) = c0 + c1 t + c2 t^2 + c3 t^3。"""
    P = np.asarray(P, dtype=float)
    c0 = P[0]
    c1 = 3.0 * (P[1] - P[0])
    c2 = 3.0 * (P[2] - 2.0 * P[1] + P[0])
    c3 = P[3] - 3.0 * P[2] + 3.0 * P[1] - P[0]
    return c0, c1, c2, c3


def bezier_point(P, t):
    """曲线上参数 t 处的坐标 (x, y)。"""
    c0, c1, c2, c3 = _power_coeffs(P)
    xy = ((c3 * t + c2) * t + c1) * t + c0
    return float(xy[0]), float(xy[1])


def _first_derivative_polys(P):
    _, c1, c2, c3 = _power_coeffs(P)
    dx = np.array([3.0 * c3[0], 2.0 * c2[0], c1[0]])
    dy = np.array([3.0 * c3[1], 2.0 * c2[1], c1[1]])
    return dx, dy


def _second_derivative_polys(P):
    _, _, c2, c3 = _power_coeffs(P)
    ddx = np.array([6.0 * c3[0], 2.0 * c2[0]])
    ddy = np.array([6.0 * c3[1], 2.0 * c2[1]])
    return ddx, ddy


# ---------------------------------------------------------------------------
# 零切向量检测
# ---------------------------------------------------------------------------

def find_zero_tangent(dx, dy):
    """若存在 t ∈ [0,1] 使 x'(t) = y'(t) = 0，返回最小的这样的 t，否则 None。"""
    px, py = _trim(dx), _trim(dy)
    x_zero = px.size == 1 and px[0] == 0.0
    y_zero = py.size == 1 and py[0] == 0.0
    if x_zero and y_zero:
        # 整段退化为一个点，处处零切向量
        return 0.0
    if x_zero:
        roots = _roots_in_01(py)
        return roots[0] if roots else None
    if y_zero:
        roots = _roots_in_01(px)
        return roots[0] if roots else None
    scale = max(1.0, float(np.max(np.abs(np.concatenate([px, py])))))
    tol = _COMMON_ROOT_RTOL * scale
    hits = []
    for r in _roots_in_01(px):
        if abs(float(np.polyval(py, r))) <= tol:
            hits.append(r)
    for r in _roots_in_01(py):
        if abs(float(np.polyval(px, r))) <= tol:
            hits.append(r)
    return min(hits) if hits else None


# ---------------------------------------------------------------------------
# 精确最大曲率
# ---------------------------------------------------------------------------

def segment_max_curvature(P):
    """精确求三次贝塞尔段的最大曲率。

    在端点 t=0,1 与 κ² 导数的全部驻点（A(t)=0 或 2A'S-3AS'=0 的实根）上
    评估曲率并取最大值；并列时取较小的 t 以保证结果稳定。
    调用前须保证段内无零切向量。
    返回 (max_curvature, t_star)。
    """
    P = np.asarray(P, dtype=float)
    dx, dy = _first_derivative_polys(P)
    ddx, ddy = _second_derivative_polys(P)
    A = _psub(_pmul(dx, ddy), _pmul(dy, ddx))
    S = _padd(_pmul(dx, dx), _pmul(dy, dy))
    a_trim = _trim(A)
    if a_trim.size == 1 and a_trim[0] == 0.0:
        # 直线段：曲率恒为零
        return 0.0, 0.0
    G = _psub(_pmul(2.0 * _pder(A), S), _pmul(3.0 * A, _pder(S)))
    candidates = [0.0, 1.0, *_roots_in_01(A), *_roots_in_01(G)]
    best_k, best_t = -1.0, 0.0
    for t in candidates:
        s = float(np.polyval(S, t))
        if s <= 0.0:
            continue  # 零切向量已在上游排除，此处仅为数值保险
        k = abs(float(np.polyval(A, t))) / (s ** 1.5)
        if k > best_k + _TIE_TOL:
            best_k, best_t = k, t
    return best_k, best_t


# ---------------------------------------------------------------------------
# 段间连续性（整数精确判定）
# ---------------------------------------------------------------------------

def _failure(reason, segment_index, t, point, message,
             adjacent=None, detail=None, extra=None):
    f = {
        "reason": reason,
        "segment_index": int(segment_index),
        "t": float(t),
        "point": {"x": float(point[0]), "y": float(point[1])},
        "message": message,
    }
    if adjacent is not None:
        f["adjacent_segment_index"] = int(adjacent)
    if detail is not None:
        f["detail"] = detail
    if extra:
        f.update(extra)
    return {"ok": False, "segments": None, "failure": f}


def check_joint(prev, curr, prev_index):
    """检查第 prev_index 段与下一段的拼接连续性。

    断接问题报告在行进方向上首先无法接入的段（即后一段，t=0 处）。
    连续返回 None，否则返回失败响应。
    """
    P = np.asarray(prev, dtype=int)
    Q = np.asarray(curr, dtype=int)
    i = prev_index
    j = prev_index + 1
    end = P[3]
    start = Q[0]
    if not np.array_equal(end, start):
        return _failure(
            "endpoint_mismatch", j, 0.0, start,
            f"第{j + 1}段起点 ({start[0]}, {start[1]}) 与第{i + 1}段终点 "
            f"({end[0]}, {end[1]}) 不重合，端点断接",
            adjacent=i,
            detail={
                "prev_end": {"x": int(end[0]), "y": int(end[1])},
                "curr_start": {"x": int(start[0]), "y": int(start[1])},
            },
        )
    t_prev = 3 * (P[3] - P[2])
    t_curr = 3 * (Q[1] - Q[0])
    if int(t_curr[0]) == 0 and int(t_curr[1]) == 0:
        return _failure(
            "zero_tangent", j, 0.0, start,
            f"第{j + 1}段起点处切向量为零，不可运行",
            adjacent=i,
        )
    if int(t_prev[0]) == 0 and int(t_prev[1]) == 0:
        # 理论上段内零切向量检查已先捕获，此处兜底
        return _failure(
            "zero_tangent", i, 1.0, end,
            f"第{i + 1}段终点处切向量为零，不可运行",
            adjacent=j,
        )
    cross = int(t_prev[0]) * int(t_curr[1]) - int(t_prev[1]) * int(t_curr[0])
    dot = int(t_prev[0]) * int(t_curr[0]) + int(t_prev[1]) * int(t_curr[1])
    if cross != 0 or dot <= 0:
        return _failure(
            "tangent_mismatch", j, 0.0, start,
            f"第{j + 1}段起点切向量 ({t_curr[0]}, {t_curr[1]}) 与第{i + 1}段终点"
            f"切向量 ({t_prev[0]}, {t_prev[1]}) 方向不连续，切向断接",
            adjacent=i,
            detail={
                "prev_tangent": {"x": int(t_prev[0]), "y": int(t_prev[1])},
                "curr_tangent": {"x": int(t_curr[0]), "y": int(t_curr[1])},
            },
        )
    return None


# ---------------------------------------------------------------------------
# 审计主流程
# ---------------------------------------------------------------------------

def _fmt(v):
    s = f"{float(v):.6f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def audit_curve(segments, max_curvature):
    """按行进顺序审计 2~5 段三次贝塞尔拼接曲线。

    检查顺序即行进顺序：段内零切向量 -> 段内最大曲率 -> 与下一段的拼接，
    遇到第一个问题即返回，保证“最早问题段”语义稳定确定。
    """
    limit = float(max_curvature)
    tol = _CURVATURE_RTOL * max(1.0, abs(limit))
    results = []
    n = len(segments)
    for i in range(n):
        P = np.asarray(segments[i], dtype=float)
        dx, dy = _first_derivative_polys(P)
        tz = find_zero_tangent(dx, dy)
        if tz is not None:
            x, y = bezier_point(P, tz)
            return _failure(
                "zero_tangent", i, tz, (x, y),
                f"第{i + 1}段在 t={_fmt(tz)} 处切向量为零，曲线不可运行"
                f"（位置 ({_fmt(x)}, {_fmt(y)})）",
            )
        k, t_star = segment_max_curvature(P)
        if k > limit + tol:
            x, y = bezier_point(P, t_star)
            return _failure(
                "curvature_exceeded", i, t_star, (x, y),
                f"第{i + 1}段最大曲率 {_fmt(k)} 超过限值 {_fmt(limit)}"
                f"（t={_fmt(t_star)}，位置 ({_fmt(x)}, {_fmt(y)})）",
                extra={"max_curvature": k, "limit": limit},
            )
        x, y = bezier_point(P, t_star)
        results.append({
            "index": i,
            "max_curvature": k,
            "t": t_star,
            "point": {"x": x, "y": y},
        })
        if i < n - 1:
            joint = check_joint(segments[i], segments[i + 1], i)
            if joint is not None:
                return joint
    return {"ok": True, "segments": results, "failure": None}
