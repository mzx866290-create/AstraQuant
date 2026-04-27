@echo off
echo 股票数据分析平台 - 启动脚本
echo.

echo [1] 检查Docker Desktop是否运行...
call docker version >nul 2>&1
if %errorlevel% neq 0 (
    echo 错误: Docker Desktop未运行！
    echo 请手动启动Docker Desktop后再运行此脚本。
    pause
    exit /b 1
)
echo ✓ Docker Desktop正在运行
echo.

echo [2] 创建环境配置文件...
if not exist .env copy .env.example .env
echo ✓ 环境文件已创建
echo.

echo [3] 构建Docker镜像...
docker-compose build
if %errorlevel% neq 0 (
    echo 错误: 镜像构建失败
    pause
    exit /b 1
)
echo ✓ 镜像构建完成
echo.

echo [4] 启动所有服务...
docker-compose up -d
if %errorlevel% neq 0 (
    echo 错误: 服务启动失败
    pause
    exit /b 1
)
echo.
echo ✓ 所有服务已启动！
echo.
echo ============= 访问地址 =============
echo.
echo 前端界面: http://localhost:5175
echo 行情服务文档: http://localhost:8001/api/v1/docs
echo 用户服务文档: http://localhost:8002/api/v1/docs
echo Grafana监控: http://localhost:3000
echo Prometheus: http://localhost:9090
echo.
echo ====================================
echo.
echo 查看日志: docker-compose logs -f
echo 停止服务: docker-compose down
echo.
pause