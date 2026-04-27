.PHONY: help up down logs build dev-market dev-user dev-analysis dev-frontend dev-all test clean

help:
	@echo "股票数据分析平台 - 开发命令"
	@echo ""
	@echo "=== 容器命令 (Docker) ==="
	@echo "  make up              启动所有Docker容器"
	@echo "  make down            停止所有Docker容器"
	@echo "  make logs            查看容器日志"
	@echo "  make build           构建Docker镜像"
	@echo ""
	@echo "=== 开发命令 (热重载) ==="
	@echo "  make dev-frontend    启动前端 (localhost:5175)"
	@echo "  make dev-market      启动行情服务 (localhost:8001)"
	@echo "  make dev-user        启动用户服务 (localhost:8002)"
	@echo "  make dev-analysis    启动分析服务 (localhost:8003)"
	@echo "  make dev-all         启动全部后端服务"
	@echo ""
	@echo "=== 测试命令 ==="
	@echo "  make test            运行单元测试"
	@echo "  make test-source     测试A股数据源连接"
	@echo ""
	@echo "=== 清理命令 ==="
	@echo "  make clean           清理Docker容器和卷"

up:
	cp .env.example .env 2>/dev/null; true
	docker-compose up -d
	@echo ""
	@echo "访问地址:"
	@echo "  前端:        http://localhost:5175"
	@echo "  行情服务文档: http://localhost:8001/api/v1/docs"
	@echo "  用户服务文档: http://localhost:8002/api/v1/docs"
	@echo "  Grafana:     http://localhost:3000"
	@echo "  Prometheus:  http://localhost:9090"

down:
	docker-compose down
	@echo "所有服务已停止"

logs:
	docker-compose logs -f

build:
	docker-compose build

dev-frontend:
	@echo "启动前端开发服务器..."
	cd frontend/web && npx vite --host 0.0.0.0

dev-market:
	@echo "启动行情服务 (热重载)..."
	cd backend/services/market_service && python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload

dev-user:
	@echo "启动用户服务 (热重载)..."
	cd backend/services/user_service && python -m uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload

dev-all:
	@echo "启动所有后端服务..."
	@echo "行情服务 → :8001"
	cd backend/services/market_service && python -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload &
	@sleep 2
	@echo "用户服务 → :8002"
	cd backend/services/user_service && python -m uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload &
	@sleep 2
	@echo "后端服务已启动"

test:
	@echo "运行后端测试..."
	PYTHONPATH=. python -m pytest backend/tests/ -v

test-source:
	@echo "测试A股数据源..."
	PYTHONPATH=. python -c "
import asyncio
from backend.services.data_crawler.sources.eastmoney_source import EastMoneySource
from backend.services.data_crawler.sources.akshare_source import AKShareSource

async def test():
    em = EastMoneySource()
    print('=== 测试东方财富 ===')
    ok = await em.health_check()
    print(f'健康检查: {ok}')
    if ok:
        quote = await em.fetch_realtime_quote('600519')
        print(f'贵州茅台行情: {quote[\"price\"]}')
        kline = await em.fetch_daily_kline('600519', adjust='1')
        print(f'日K线: {len(kline)}条')
asyncio.run(test())
"

clean:
	docker-compose down -v
	@echo "已清理所有容器和数据卷"
