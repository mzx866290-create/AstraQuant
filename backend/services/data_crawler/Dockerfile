# 数据采集服务 - Dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY backend/services/data_crawler/requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制共享模块 (需要用于 from backend.shared.validators 导入)
COPY backend/shared /backend/shared

# 复制项目文件
COPY backend/services/data_crawler .

# 设置环境变量
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# 启动服务
CMD ["python", "app/main.py"]