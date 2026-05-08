FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# 复制项目文件
COPY backend/services/market_service/requirements.txt .
COPY backend/shared ../shared
COPY backend/shared /backend/shared
COPY backend/services /backend/services

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/services/market_service/app ./app

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)" || exit 1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
