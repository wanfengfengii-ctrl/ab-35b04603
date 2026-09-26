FROM python:3.12-slim

WORKDIR /verify

# 与后端一致的依赖 + 测试/冒烟所需工具
COPY backend/requirements.txt backend/requirements-dev.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements-dev.txt

COPY backend/app ./app
COPY backend/tests ./tests
COPY verify/smoke.py verify/run.sh ./
RUN chmod +x run.sh

CMD ["./run.sh"]
