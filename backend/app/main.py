"""FastAPI 入口：健康检查与曲线审计接口。"""

from __future__ import annotations

from fastapi import FastAPI

from .geometry import audit_curve
from .models import AuditRequest

app = FastAPI(
    title="岸桥小车导轨拼接曲线审计 API",
    version="1.0.0",
    description="复核 2~5 段三次贝塞尔导轨拼接曲线的连续性、零切向量与最大曲率。",
)


@app.get("/")
def root():
    return {
        "service": "railcurve-audit-api",
        "health": "/health",
        "docs": "/docs",
        "audit": "POST /api/audit",
    }


@app.get("/health")
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/audit")
def audit(req: AuditRequest):
    segments = [[[p.x, p.y] for p in seg.points] for seg in req.segments]
    result = audit_curve(segments, req.max_curvature)
    result["segment_count"] = len(segments)
    result["max_curvature_limit"] = req.max_curvature
    return result
