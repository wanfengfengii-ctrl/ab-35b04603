"""API 层测试：健康检查、审计响应结构、参数校验。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

VALID = {
    "max_curvature": 1.0,
    "segments": [
        {"points": [{"x": 0, "y": 0}, {"x": 1, "y": 0},
                    {"x": 2, "y": 1}, {"x": 3, "y": 3}]},
        {"points": [{"x": 3, "y": 3}, {"x": 4, "y": 5},
                    {"x": 5, "y": 6}, {"x": 6, "y": 6}]},
    ],
}


def test_health():
    for path in ("/health", "/api/health"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


def test_audit_qualified():
    r = client.post("/api/audit", json=VALID)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["failure"] is None
    assert data["segment_count"] == 2
    assert data["max_curvature_limit"] == 1.0
    assert len(data["segments"]) == 2
    s0 = data["segments"][0]
    assert s0["max_curvature"] == pytest.approx(2.0 / 3.0, abs=1e-12)
    assert s0["point"] == {"x": 0.0, "y": 0.0}


def test_audit_unqualified_structure():
    payload = dict(VALID, max_curvature=0.5)
    r = client.post("/api/audit", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data["segments"] is None
    f = data["failure"]
    assert f["reason"] == "curvature_exceeded"
    assert f["segment_index"] == 0
    assert f["t"] == pytest.approx(0.0)
    assert f["point"] == {"x": 0.0, "y": 0.0}
    assert "message" in f and f["message"]


def test_reject_single_segment():
    payload = dict(VALID, segments=VALID["segments"][:1])
    assert client.post("/api/audit", json=payload).status_code == 422


def test_reject_six_segments():
    seg = VALID["segments"][0]
    payload = dict(VALID, segments=[seg] * 6)
    assert client.post("/api/audit", json=payload).status_code == 422


def test_reject_segment_not_four_points():
    payload = dict(VALID, segments=[{"points": VALID["segments"][0]["points"][:3]},
                                    VALID["segments"][1]])
    assert client.post("/api/audit", json=payload).status_code == 422


def test_reject_non_integer_point():
    payload = dict(VALID, segments=[
        {"points": [{"x": 0, "y": 0}, {"x": 1.5, "y": 0},
                    {"x": 2, "y": 1}, {"x": 3, "y": 3}]},
        VALID["segments"][1],
    ])
    assert client.post("/api/audit", json=payload).status_code == 422


def test_reject_nonpositive_limit():
    payload = dict(VALID, max_curvature=0)
    assert client.post("/api/audit", json=payload).status_code == 422
    payload = dict(VALID, max_curvature=-1)
    assert client.post("/api/audit", json=payload).status_code == 422
