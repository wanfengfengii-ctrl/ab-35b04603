# 岸桥小车导轨拼接曲线审计

港口岸桥改造前，复核小车导轨拼接曲线：录入按行进顺序排列的 **2~5 段三次贝塞尔曲线**
（每段 4 个**整数**控制点）与**统一最大曲率**，服务端解析审计后判定是否合格，
避免各段端点看似接上、段内却存在超过转向架能力的急弯。

## 系统组成

| 服务 | 说明 | 默认宿主机端口 |
| --- | --- | --- |
| `web` | nginx 托管的单页应用（草稿编辑/保存、发起审计、结果展示），`/api` 反代到后端 | `WEB_PORT`（默认 8080） |
| `api` | FastAPI 审计服务：`GET /health`、`POST /api/audit` | `API_PORT`（默认 8000） |
| `verify` | 一次性验证服务（profile=`verify`）：构建检查 → 代码测试 → 业务冒烟，以退出码报告结果 | — |

`web` 与 `api` 均配置了 Docker HEALTHCHECK 与 Compose healthcheck。

## 快速开始

```bash
cp .env.example .env        # 可选：修改 API_PORT / WEB_PORT
docker compose up --build -d
# 打开 http://localhost:8080
```

## 一次性验证（构建 + 代码测试 + 业务冒烟）

```bash
docker compose --profile verify up --build --exit-code-from verify verify
echo $?   # 0 = 全部通过；非 0 = 失败
```

`verify` 等待 `api`、`web` 健康后执行：

1. **构建检查**：`compileall` 编译全部 Python 源码；
2. **代码测试**：`pytest` 运行几何核心与 API 单元测试；
3. **业务冒烟**：通过 HTTP 调用审计 API —— 合格曲线（校验精确的每段最大曲率与位置）、
   曲率超限、端点断接、切向断接、零切向量、非法参数（422）。

## 审计规则

- **段间连续**（整数控制点，精确判定）：
  - 端点连续：上一段 `P3` 与下一段 `P0` 完全重合；
  - 一阶切向量连续：接缝两侧切向量 `3(P3−P2)` 与 `3(Q1−Q0)` 共线且同向
    （G1：叉积为 0 且点积为正；模长不要求相等，因模长是参数化产物而非几何特征）。
- **零切向量**：段内任意 `t ∈ [0,1]` 使 `B'(t)=0`（`x'`、`y'` 有公共实根）即不可运行。
- **最大曲率（解析法，非离散采样）**：
  `κ(t) = |A(t)| / S(t)^{3/2}`，其中 `A = x'y'' − y'x''`，`S = x'² + y'²`。
  `d(κ²)/dt = A·(2A'S − 3AS') / S⁴`，故驻点为 `A=0`（≤3 次）与
  `2A'S − 3AS' = 0`（≤6 次）的实根。用伴随矩阵特征值法（`numpy.roots`）求全部实根，
  在**每段端点及曲率平方导数的全部驻点**上评估曲率取最大值，与统一限值比较。

## API

### `POST /api/audit`

请求：

```json
{
  "max_curvature": 1.0,
  "segments": [
    {"points": [{"x":0,"y":0},{"x":1,"y":0},{"x":2,"y":1},{"x":3,"y":3}]},
    {"points": [{"x":3,"y":3},{"x":4,"y":5},{"x":5,"y":6},{"x":6,"y":6}]}
  ]
}
```

合格响应（HTTP 200）：

```json
{
  "ok": true,
  "segments": [
    {"index": 0, "max_curvature": 0.6666666666666666, "t": 0.0, "point": {"x": 0.0, "y": 0.0}},
    {"index": 1, "max_curvature": 0.6666666666666666, "t": 1.0, "point": {"x": 6.0, "y": 6.0}}
  ],
  "failure": null,
  "segment_count": 2,
  "max_curvature_limit": 1.0
}
```

不合格响应（HTTP 200，结果确定可复现）：

```json
{
  "ok": false,
  "segments": null,
  "failure": {
    "reason": "curvature_exceeded",
    "segment_index": 0,
    "t": 0.0,
    "point": {"x": 0.0, "y": 0.0},
    "message": "第1段最大曲率 0.666667 超过限值 0.5（t=0，位置 (0, 0)）",
    "max_curvature": 0.6666666666666666,
    "limit": 0.5
  }
}
```

`failure.reason` 取值：

| reason | 含义 |
| --- | --- |
| `curvature_exceeded` | 段内最大曲率超限（附 `max_curvature`、`limit`） |
| `endpoint_mismatch` | 相邻段端点不重合（附 `detail.prev_end/curr_start`） |
| `tangent_mismatch` | 相邻段切向量方向不连续（附 `detail.prev_tangent/curr_tangent`） |
| `zero_tangent` | 段内存在零切向量，不可运行 |

约定：

- `segment_index` 为 **0 基**；按行进顺序检查（段内零切向量 → 段内曲率 → 与下一段拼接），
  报告**最早**发现的问题，同一输入永远返回同一结果。
- 拼接断接报告在**后一段**（`segment_index = i+1`，`t = 0`，坐标为其起点），
  并附 `adjacent_segment_index = i`；该段是行进方向上首个无法接入的段。
- 参数校验失败（段数非 2~5、控制点非 4 个整数、限值非正数等）返回 HTTP 422。

## 本地开发（不用 Docker）

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest tests -q          # 单元测试
uvicorn app.main:app --reload      # 启动 API（:8000）
# 前端为纯静态页：可用任意静态服务器托管 frontend/static，
# 并将 /api 反代到 http://localhost:8000（参考 frontend/nginx.conf）
```

## 目录结构

```
├── docker-compose.yml        # web / api / verify（一次性）
├── .env.example              # API_PORT、WEB_PORT
├── backend/
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py           # FastAPI：/health、/api/audit
│   │   ├── geometry.py       # 解析法曲率/零切向量/连续性核心
│   │   └── models.py
│   └── tests/                # pytest 单元测试
├── frontend/
│   ├── Dockerfile            # nginx 静态托管 + /api 反代
│   ├── nginx.conf
│   └── static/               # 单页应用（草稿编辑、审计、结果展示）
└── verify/
    ├── Dockerfile            # 一次性验证镜像（含后端源码与测试）
    ├── run.sh                # 构建检查 → pytest → 冒烟，退出码即结果
    └── smoke.py              # 业务冒烟
```
