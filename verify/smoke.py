"""业务冒烟：通过审计 API 的 HTTP 调用验证核心业务行为。

覆盖：健康检查、合格曲线（含精确曲率值）、曲率超限、端点断接、
切向断接、零切向量、参数校验。全部通过返回退出码 0，否则 1。
"""

import copy
import os
import sys
import time

import httpx

API = os.environ.get("API_URL", "http://api:8000").rstrip("/")
WEB = os.environ.get("WEB_URL", "http://web").rstrip("/")

VALID = {
    "max_curvature": 1.0,
    "segments": [
        {"points": [{"x": 0, "y": 0}, {"x": 1, "y": 0},
                    {"x": 2, "y": 1}, {"x": 3, "y": 3}]},
        {"points": [{"x": 3, "y": 3}, {"x": 4, "y": 5},
                    {"x": 5, "y": 6}, {"x": 6, "y": 6}]},
    ],
}

failures = []


def check(name, cond, info=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" | {info}" if info else ""),
          flush=True)
    if not cond:
        failures.append(name)


def wait_api_ready(timeout_s=60):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if httpx.get(f"{API}/health", timeout=2).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def post(payload):
    return httpx.post(f"{API}/api/audit", json=payload, timeout=10)


def main():
    check("api ready", wait_api_ready())

    # ---- Web 健康与页面 ----
    try:
        r = httpx.get(f"{WEB}/healthz", timeout=5)
        check("web healthz", r.status_code == 200, f"status={r.status_code}")
        r = httpx.get(f"{WEB}/", timeout=5)
        check("web page served", r.status_code == 200 and "审计" in r.text)
    except Exception as exc:  # noqa: BLE001
        check("web reachable", False, repr(exc))

    # ---- 1. 合格曲线：两段抛物线弧，各段最大曲率恰为 2/3 ----
    r = post(VALID)
    data = r.json() if r.status_code == 200 else {}
    check("qualified http 200", r.status_code == 200, f"status={r.status_code}")
    check("qualified ok=true", data.get("ok") is True, str(data.get("failure")))
    segs = data.get("segments") or []
    if len(segs) == 2:
        check("seg0 max_curvature == 2/3 @ t=0",
              abs(segs[0]["max_curvature"] - 2.0 / 3.0) < 1e-9
              and abs(segs[0]["t"]) < 1e-9
              and abs(segs[0]["point"]["x"]) < 1e-9
              and abs(segs[0]["point"]["y"]) < 1e-9,
              str(segs[0]))
        check("seg1 max_curvature == 2/3 @ t=1",
              abs(segs[1]["max_curvature"] - 2.0 / 3.0) < 1e-9
              and abs(segs[1]["t"] - 1.0) < 1e-9
              and abs(segs[1]["point"]["x"] - 6.0) < 1e-9
              and abs(segs[1]["point"]["y"] - 6.0) < 1e-9,
              str(segs[1]))
    else:
        check("qualified returns 2 segment results", False, str(data))

    # ---- 2. 曲率超限：最早问题段为第 1 段（index 0），t=0，坐标 (0,0) ----
    d = post(dict(VALID, max_curvature=0.5)).json()
    f = d.get("failure") or {}
    check("curvature_exceeded reported",
          d.get("ok") is False and f.get("reason") == "curvature_exceeded"
          and f.get("segment_index") == 0
          and abs(f.get("t", 1)) < 1e-9
          and abs((f.get("point") or {}).get("x", 1)) < 1e-9
          and abs((f.get("point") or {}).get("y", 1)) < 1e-9,
          str(f))

    # ---- 3. 端点断接 ----
    bad = copy.deepcopy(VALID)
    bad["segments"][1]["points"][0] = {"x": 3, "y": 4}
    d = post(bad).json()
    f = d.get("failure") or {}
    check("endpoint_mismatch reported",
          d.get("ok") is False and f.get("reason") == "endpoint_mismatch"
          and f.get("segment_index") == 1
          and abs(f.get("t", 1)) < 1e-9
          and (f.get("point") or {}).get("x") == 3.0
          and (f.get("point") or {}).get("y") == 4.0,
          str(f))

    # ---- 4. 切向断接 ----
    bad = copy.deepcopy(VALID)
    bad["segments"][1]["points"][1] = {"x": 4, "y": 6}
    d = post(bad).json()
    f = d.get("failure") or {}
    check("tangent_mismatch reported",
          d.get("ok") is False and f.get("reason") == "tangent_mismatch"
          and f.get("segment_index") == 1,
          str(f))

    # ---- 5. 零切向量不可运行 ----
    bad = copy.deepcopy(VALID)
    bad["segments"][0]["points"][1] = {"x": 0, "y": 0}  # P0 == P1 -> B'(0)=0
    d = post(bad).json()
    f = d.get("failure") or {}
    check("zero_tangent reported",
          d.get("ok") is False and f.get("reason") == "zero_tangent"
          and f.get("segment_index") == 0
          and abs(f.get("t", 1)) < 1e-9,
          str(f))

    # ---- 6. 参数校验 ----
    r = post({"max_curvature": 1.0, "segments": VALID["segments"][:1]})
    check("reject single segment (422)", r.status_code == 422, f"status={r.status_code}")
    r = post({"max_curvature": -1.0, "segments": VALID["segments"]})
    check("reject nonpositive limit (422)", r.status_code == 422, f"status={r.status_code}")
    r = post({"max_curvature": 1.0, "segments": VALID["segments"] * 3})
    check("reject six segments (422)", r.status_code == 422, f"status={r.status_code}")

    if failures:
        print(f"SMOKE FAILED: {len(failures)} case(s): {failures}", flush=True)
        return 1
    print("SMOKE PASSED", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
