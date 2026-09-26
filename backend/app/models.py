"""请求数据模型：2~5 段三次贝塞尔，整数控制点，统一最大曲率。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class Point(BaseModel):
    x: int
    y: int


class BezierSegment(BaseModel):
    points: list[Point] = Field(
        ..., min_length=4, max_length=4,
        description="一段三次贝塞尔的 4 个整数控制点，按 P0..P3 顺序",
    )


class AuditRequest(BaseModel):
    max_curvature: float = Field(..., gt=0, description="统一的最大曲率限值")
    segments: list[BezierSegment] = Field(
        ..., min_length=2, max_length=5,
        description="按行进顺序排列的 2~5 段三次贝塞尔曲线",
    )
