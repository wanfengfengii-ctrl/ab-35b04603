#!/bin/sh
# 一次性验证流程：构建检查 -> 代码测试 -> 业务冒烟；任一步失败即非零退出。
set -e

cd /verify

echo "== [1/3] 构建检查：编译全部 Python 源码 =="
python -m compileall -q app tests smoke.py

echo "== [2/3] 代码测试：pytest =="
python -m pytest tests -q

echo "== [3/3] 业务冒烟：调用审计 API =="
python smoke.py

echo "VERIFY PASSED"
