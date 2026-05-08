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

## 产品边界

当前 MVP 聚焦“发现值得继续研究的线索、理解原因、跟踪风险”，不是荐股工具。每日观察池、AI 分析和评分结果都只用于辅助研究，不构成买入、卖出、仓位或收益建议。更完整的产品承诺、数据可信等级和上线门槛见 [`docs/product-mvp.md`](docs/product-mvp.md)。

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

### 官方入口

项目只推荐两条启动入口：

- 本地开发：`python scripts/start_local.py` 或 `make dev`
- 容器全栈：`docker compose up -d` 或 `make stack`

根目录历史脚本（例如 `run_*.py`、`start_*.py`、`*.bat`）只作为兼容入口保留，不再作为新开发和 CI 的推荐路径。后续仓库清理时应逐步移入 `scripts/legacy/`。

### 安全清理生成/运行时文件
生成物、日志、SQLite 数据库、前端 `dist/` 等运行时文件统一通过清理脚本处理。默认只做 dry-run 预览，不会删除任何文件：

```bash
python scripts/cleanup_runtime_artifacts.py
make clean-runtime
```

确认清理清单无误后，再显式执行删除：

```bash
python scripts/cleanup_runtime_artifacts.py --apply
make clean-runtime-apply
```

`make clean` 仍只负责 Docker 容器和卷清理，不承担源码或业务配置删除。

### 交付与密钥卫生门禁

本地交付验证统一走 `python scripts/verify_delivery.py` 或 `make verify`，会先运行 ops drill readiness preflight，再运行密钥卫生门禁，随后执行后端编译/单测/coverage 和前端 lint/type-check/API 兼容/数据质量契约/build/smoke。

密钥卫生门禁也可以单独运行，用于提交前或发布前快速检查误提交的 token、默认密码和生产密钥痕迹：

```bash
python scripts/verify_secret_hygiene.py
make secret-hygiene
```

### 本地开发一键启动（推荐）

当前开发环境默认使用 SQLite 和本地微服务端口：

- 行情服务：`http://localhost:8001`
- 用户服务：`http://localhost:8002`
- 分析服务：`http://localhost:8003`
- 前端：`http://localhost:5175`

在项目根目录运行：

```bash
python scripts/start_local.py
# 或
make dev
```

该脚本会先清理 `8001/8002/8003/5175` 上的旧进程，再启动后端三个服务和 Vite 前端，并检查健康状态。若首页“今日观察”显示空数据，优先使用这个脚本重启，避免浏览器连到旧的 analysis-service。

健康检查：

```http
GET http://localhost:8003/api/v1/analysis/system-health
```

### 每日观察池说明

首页的“今日观察”不是买入推荐，也不是模型直接喊单。它是基于公开行情/K线、估值、财务、新闻情绪、行业/社会事件和数据质量的规则筛选池，偏向单手成本友好、市值不过分庞大、风险灯较少的沪深 A 股候选标的。

观察池会返回：

- `score`：规则综合评分。
- `reasons`：入选理由摘要。
- `risk_flags`：需要先看的风险点。
- `score_breakdown`：结构化加分/扣分明细。
- `data_grade`：数据完整度等级。

接口：

```http
GET /api/v1/analysis/score/batch/recommend?market=ALL&limit=10&strategy=retail_small
```

重要提醒：观察池只用于发现值得继续研究的线索，不构成证券买卖建议。

### 价格预警

预警支持价格上穿、价格下穿和日涨跌幅超限。用户可以在前端“预警”页面手动点击“立即检查”，行情服务也会在后台自动扫描启用中的预警，命中后写入触发时间并自动禁用该规则。

相关接口：

```http
GET /api/v1/alerts
POST /api/v1/alerts
POST /api/v1/alerts/check
GET /api/v1/alerts/scheduler/status
```

自动检查可通过环境变量调整：

```bash
ALERT_SCHEDULER_ENABLED=true
ALERT_SCHEDULER_INTERVAL_SECONDS=300
ALERT_SCHEDULER_MAX_ALERTS=200
```

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
docker compose up -d
# 或
make stack
```

### 5. 访问应用

- **前端界面**: http://localhost 或 http://<你的局域网IP>
- **行情服务API文档**: http://localhost:8001/api/v1/docs
- **用户服务API文档**: http://localhost:8002/api/v1/docs
- **Grafana监控**: http://localhost:3000 (admin / 使用 `.env` 中的 `GRAFANA_PASS`)
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
    "password": "DemoPass123"
}
```

#### 用户登录
```http
POST /api/v1/auth/login
Content-Type: application/json

{
    "username": "test",
    "password": "DemoPass123"
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

生产部署、监控和备份恢复不再只停留在 README 摘要中，入口文档如下：

- 生产发布：[`docs/ops/production-deploy.md`](docs/ops/production-deploy.md)
- 监控告警：[`docs/ops/monitoring-runbook.md`](docs/ops/monitoring-runbook.md)
- 告警 Webhook 演练：[`docs/ops/monitoring-runbook.md#alert-delivery`](docs/ops/monitoring-runbook.md#alert-delivery)
- 备份恢复：[`docs/ops/backup-restore.md`](docs/ops/backup-restore.md)
- CI/部署演练记录：[`docs/ops/ci-deployment-drill-record.md`](docs/ops/ci-deployment-drill-record.md)
- 演练证据归档与封存包：[`docs/ops/ops-drill-archive-runbook.md`](docs/ops/ops-drill-archive-runbook.md)

演练封存脚本支持 `--summary-json` 输出机器可读结果，适合挂到 CI artifact、发布单或运维日志；summary 文件应放在封存目录外，避免污染正式证据包。

正式演练建议按这个顺序执行：先运行 `python scripts/ops/verify_ops_drill_readiness.py --env-file .env.production` 与 `python scripts/verify_secret_hygiene.py`；再运行 `python scripts/ops/ops_drill_archive_smoke.py` 本地验证归档脚本链路；随后执行真实 CI、`Alert Webhook Drill`（`send=true`、`status=both`）和部署 smoke；最后下载两份 artifact，运行 `prepare_ops_drill_archive.py`、补全 `completed/`、执行 `finalize_ops_drill_archive.py` 并复验封存包。

基础启动命令：

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
```

生产环境必须使用 `.env.production.example` 生成真实密钥配置，并通过部署平台注入；不要提交 `.env.production`。

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
