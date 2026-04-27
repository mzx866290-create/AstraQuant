# 股票数据分析平台

一个专注于A股市场的股票数据分析平台，提供实时行情、历史K线、技术指标分析、自选股管理等功能。

## 功能特性

- 📊 **A股市场覆盖**：沪深两市、科创板、创业板、北交所
- 📈 **实时行情**：实时股价、涨跌幅、成交量等
- 📉 **历史K线**：日K、周K、月K、分钟K线数据
- 🔍 **技术指标**：MA、MACD、KDJ、BOLL等常用指标
- ⭐ **自选股管理**：分组管理、实时监控
- 🔐 **用户系统**：注册登录、JWT认证
- 📱 **响应式设计**：适配桌面端和移动端
- 🐳 **容器化部署**：Docker Compose一键启动

## 技术栈

### 后端
- **语言**: Python 3.11+
- **框架**: FastAPI
- **数据库**: PostgreSQL (业务数据) + ClickHouse (时序行情数据) + Redis (缓存)
- **数据源**: AkShare (主力) + Tushare (备用)
- **任务调度**: APScheduler

### 前端
- **框架**: Vue 3 + TypeScript
- **构建工具**: Vite
- **UI组件**: Element Plus
- **图表库**: ECharts
- **状态管理**: Pinia
- **HTTP客户端**: Axios

## 快速启动

### 1. 前置条件

确保已安装：
- Docker & Docker Compose
- Git

### 2. 克隆项目

```bash
git clone <repository-url>
cd stock-platform
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑.env文件，按需修改配置
```

### 4. 启动所有服务

```bash
docker-compose up -d
```

### 5. 访问应用

- **前端界面**: http://localhost 或 http://<你的局域网IP>
- **行情服务API文档**: http://localhost:8001/api/v1/docs
- **用户服务API文档**: http://localhost:8002/api/v1/docs
- **Grafana监控**: http://localhost:3000 (admin/admin123)
- **Prometheus**: http://localhost:9090

### 6. 初始化数据

首次启动需要初始化股票基础数据：

```bash
# 进入数据采集容器
docker exec -it stock-platform-data-crawler bash

# 执行初始化脚本
python -m app.init_data
```

## 项目结构

```
stock-platform/
├── docker-compose.yml          # Docker Compose配置
├── .env.example                # 环境变量模板
├── README.md                   # 项目说明
├── backend/                    # 后端服务
│   ├── shared/                 # 公共模块
│   └── services/              # 微服务
│       ├── market_service/     # 行情服务
│       ├── data_crawler/       # 数据采集
│       └── user_service/       # 用户服务
├── frontend/                   # 前端
│   └── web/                    # Vue 3前端
└── infra/                      # 基础设施
    ├── postgres/              # PostgreSQL配置
    ├── clickhouse/            # ClickHouse配置
    └── prometheus/            # 监控配置
```

## 开发环境

### 后端开发

```bash
# 进入服务目录
cd backend/services/market_service

# 安装依赖
pip install -r requirements.txt

# 启动服务 (需要在Docker中运行数据库)
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 前端开发

```bash
# 进入前端目录
cd frontend/web

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

## 数据源

### 主要数据源 (免费)
- **AkShare**: A股全面数据，包括实时行情、历史K线、财务数据等
- **Tushare**: 备用数据源，需要token

### 数据采集策略
1. **实时行情**: 交易时段每1-5秒更新
2. **日K数据**: 盘后15:30后同步
3. **财务数据**: 季度财报发布后更新
4. **公司基础信息**: 首次访问时缓存

## API接口

### 行情服务 (market-service:8001)

#### 获取股票基本信息
```http
GET /api/v1/stocks/{symbol}
```

#### 获取K线数据
```http
GET /api/v1/stocks/{symbol}/kline?period=1d&limit=120&indicators=ma5,ma10
```

#### 搜索股票
```http
GET /api/v1/search?q=贵州茅台
```

### 用户服务 (user-service:8002)

#### 用户注册
```http
POST /api/v1/auth/register
Content-Type: application/json

{
    "username": "test",
    "email": "test@example.com",
    "password": "password123"
}
```

#### 用户登录
```http
POST /api/v1/auth/login
Content-Type: application/json

{
    "username": "test",
    "password": "password123"
}
```

#### 管理自选股
```http
GET /api/v1/watchlists                # 获取所有自选股列表
POST /api/v1/watchlists               # 添加自选股
DELETE /api/v1/watchlists/{stock_id}  # 移除自选股
```

## 局域网访问配置

平台默认已配置支持局域网访问：

1. 确保防火墙开放80端口
2. 在局域网内其他设备访问：`http://<宿主机的局域网IP>`
3. 如需域名访问，可配置本地hosts或DNS

## 监控告警

- **Prometheus**: 收集应用和系统指标
- **Grafana**: 可视化监控数据
- **预置仪表板**:
  - 应用性能监控
  - 数据采集任务状态
  - 数据库连接池状态
  - API请求统计

## 生产环境部署

1. 修改`.env`文件，设置生产环境配置
2. 更新`docker-compose.prod.yml`（需要创建）
3. 配置SSL证书
4. 设置备份策略
5. 配置日志收集（ELK）

## 故障排除

### 常见问题

1. **容器启动失败**
   - 检查端口冲突
   - 查看容器日志：`docker-compose logs <service_name>`

2. **数据库连接失败**
   - 检查数据库容器状态：`docker-compose ps`
   - 验证网络连通性

3. **数据采集异常**
   - 检查数据源API状态
   - 验证API密钥配置

## 贡献指南

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 开启 Pull Request

## 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 免责声明

本项目提供的股票数据仅供参考，不构成任何投资建议。投资有风险，入市需谨慎。
