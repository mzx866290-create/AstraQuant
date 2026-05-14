# 股票数据分析平台

A股数据研究辅助平台——把散落的行情、财报、新闻、AI分析聚合为一个有数据质量标注的研究工作台。

> **产品定位**：发现值得继续研究的线索、理解原因、跟踪风险。不是荐股工具，不碰用户资金，不产生交易信号。所有AI分析和评分结果仅供参考，不构成买入、卖出、仓位或收益建议。完整的产品承诺、数据可信等级和上线门槛见 [`docs/product-mvp.md`](docs/product-mvp.md)。

---

## 核心功能

### 行情与图表
- **实时行情**：价格、涨跌幅、成交量、换手率、PE/PB、市值
- **K线图**：日/周/月/分钟K线，前复权/后复权/不复权切换，MA叠加
- **分时图**：当日走势 + 均价线 + 昨收线
- **资金流向**：超大单/大单/中单/小单净流入

### 分析引擎（后端全部完成，前端已接入）
- **技术评分**：5维度评分（动量/技术/价值/质量/情绪），个股综合评分 0-100
- **技术指标**：MA、MACD、KDJ、BOLL、RSI，K线形态识别（头肩/双底/锤子线等9种）
- **财务分析**：核心指标（营收/净利润YoY、ROE、毛利率、经营现金流）、F-Score、杜邦分解
- **估值分析**：PE/PB/PS/EV-EBITDA/DCF，历史估值分位参考
- **多股对比**：技术指标对比 + 区间涨跌幅对比

### AI深度分析
- **多模型路由**：支持 OpenAI / Anthropic / 兼容接口，健康检查 + 自动 failover
- **数据质量注入**：每次分析都标注数据等级（A/B/C/D）、来源、缺失项，AI不补脑
- **合规清洗**（ReportGuard）：过滤买入/卖出/止损/目标价等投资建议用语
- **结构化报告**：快速摘要 / 专业版 / 教学版，支持追问
- **本地规则兜底**：AI调用失败时自动降级为结构化规则摘要

### 每日观察池
- 基于规则的多策略筛选（零售小盘/价值质量/成长动量/反转/事件驱动/红利防御）
- 每个候选股附带：评分明细、证据链、多空辩论、证伪条件
- 风险硬否决：ST股/退市风险/数据D级/涨跌停/数据缺失 → 自动排除
- 研究复盘：T+1/T+5/T+20 收益跟踪，策略胜率/因子归因/权重优化建议

### 用户功能
- **自选股**：分组管理，AI批量摘要
- **价格预警**：价格上穿/下穿/日涨跌幅超限，后台5分钟轮询
- **用户系统**：注册/登录（JWT + bcrypt），配额管理（日/月用量限制）

### 管理后台
- AI模型 CRUD + 连通性测试 + 启停
- 用户管理（配额编辑/角色修改/启用禁用）
- AI用量统计（按日/模型/用户）+ 操作日志
- 策略复盘仪表盘：权重建议 → 审计 → 补丁提案 → 应用/回滚

---

## 技术栈

| 层 | 技术 |
|---|---|
| 后端语言 | Python 3.11+ |
| 后端框架 | FastAPI + Uvicorn |
| 数据库 | PostgreSQL 16（业务）+ ClickHouse 24（时序）+ Redis 7（缓存）|
| ORM | SQLAlchemy 2.0 + Alembic |
| 任务调度 | APScheduler 3.10 |
| AI SDK | OpenAI SDK + Anthropic SDK |
| 数据源 | AkShare（主）+ Tushare（备）+ 东方财富 + 新浪/腾讯 |
| 前端框架 | Vue 3.3 + TypeScript 5.3 |
| 构建工具 | Vite 5 |
| UI 组件 | Element Plus 2.4 |
| 图表 | ECharts 5.4 |
| 状态管理 | Pinia 2.1 |
| 监控 | Prometheus + Grafana + Alertmanager |

---

## 服务端口

| 服务 | 本地端口 | 说明 |
|---|---|---|
| 行情服务 | 8001 | 实时行情、K线、搜索、财务、新闻、公告 |
| 用户服务 | 8002 | 注册/登录/JWT、自选股 |
| 分析服务 | 8003 | 技术分析、AI分析、评分、观察池、管理后台 |
| 前端 | 5175 | Vue 3 SPA |
| Grafana | 3000 | 监控大盘 |
| Prometheus | 9090 | 指标采集 |

---

## 快速启动

### 本地开发（推荐）

项目只推荐两条启动入口：

```bash
# 本地开发
python scripts/start_local.py
# 或
make dev

# 容器全栈
docker compose up -d
# 或
make stack
```

根目录历史脚本（`run_*.py`、`start_*.sh`）只作为兼容入口保留，不再是推荐路径。

首次启动后同步股票主数据（5247只沪深A股）：

```bash
python scripts/sync_stock_master.py
```

初始化常用股票财报数据（避免分析时财报全部 missing）：

```bash
python scripts/init_financials.py
```

### 安全清理运行时文件

生成物、日志、SQLite 数据库、前端 `dist/` 等运行时文件通过清理脚本处理。默认只做 dry-run 预览，不删除任何文件：

```bash
python scripts/cleanup_runtime_artifacts.py
make clean-runtime
```

确认清单无误后再执行删除：

```bash
python scripts/cleanup_runtime_artifacts.py --apply
make clean-runtime-apply
```

### 交付与密钥卫生门禁

```bash
# 全量验证（后端单测/类型检查/前端lint/build/smoke）
python scripts/verify_delivery.py

# 仅密钥卫生（提交前快速检查）
python scripts/verify_secret_hygiene.py
make secret-hygiene
```

### 生产环境

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
```

生产运维文档：
- 生产发布：[`docs/ops/production-deploy.md`](docs/ops/production-deploy.md)
- 监控告警：[`docs/ops/monitoring-runbook.md`](docs/ops/monitoring-runbook.md)
- 备份恢复：[`docs/ops/backup-restore.md`](docs/ops/backup-restore.md)
- CI/部署演练：[`docs/ops/ci-deployment-drill-record.md`](docs/ops/ci-deployment-drill-record.md)
- 演练归档：[`docs/ops/ops-drill-archive-runbook.md`](docs/ops/ops-drill-archive-runbook.md)
- 研究复盘：[`docs/ops/research-review-runbook.md`](docs/ops/research-review-runbook.md)

---

## 项目结构

```
Demo4/
├── backend/
│   ├── shared/                     # 公共库：auth/database/cache/models/security/rate_limit
│   ├── migrations/                 # Alembic 迁移版本
│   ├── tests/                      # 95个测试文件，760个用例
│   └── services/
│       ├── market_service/         # 行情/K线/搜索/财务/新闻/公告/预警（端口8001）
│       ├── user_service/           # 注册/登录/自选股（端口8002）
│       ├── analysis_service/       # 分析引擎/AI/评分/管理后台（端口8003）
│       │   └── engine/             # 核心引擎：strategy/scoring/risk/ai/review
│       └── data_crawler/           # 后台ETL：定时采集行情/财务/新闻
├── frontend/web/
│   ├── src/views/                  # 页面：Home/StockDetail/Recommendations/Watchlist/Alerts/Admin
│   ├── src/components/             # 组件：KLineChart/AIAnalysisCard/FinancialReportTable等
│   └── src/api/                    # API客户端：stock/analysis/crawl/admin
├── infra/                          # Postgres/ClickHouse/Prometheus/Grafana 配置
├── docs/
│   ├── ops/                        # 运维手册：deploy/monitoring/backup/review
│   └── architecture/               # 架构文档：migrations/test-environment
└── scripts/
    ├── start_local.py              # 本地一键启动
    ├── verify_delivery.py          # 交付验证门禁
    ├── sync_stock_master.py        # 股票主数据同步
    ├── init_financials.py          # 财报初始化
    └── verify_secret_hygiene.py    # 密钥卫生检查
```

---

## 数据采集策略

数据源按韧性设计，任一源故障自动降级：

| 数据类型 | 主源 | 备源 | 采集频率 |
|---|---|---|---|
| 实时行情 | 东方财富 | 新浪/腾讯 | 交易时段每5分钟 |
| 日K线 | AkShare（前复权） | 东方财富 | 盘后15:30 |
| 财务报表 | AkShare | Tushare | 每月1-5日凌晨 |
| 个股新闻 | 多源聚合 | — | 交易时段每5分钟（需开启） |
| 公司公告 | AkShare | — | 盘后16:30 |
| 资金流向 | 东方财富 | — | 盘后15:35 |

**按需采集**：用户在个股详情页可手动触发新闻/公告/财报补全（AI分析面板数据缺失时显示"一键补全数据"按钮）。

计划任务开关：

```bash
DATA_CRAWLER_ENABLE_SCHEDULER=true           # 总开关（默认开）
DATA_CRAWLER_ENABLE_SCHEDULED_NEWS=false     # 定时新闻采集（默认关，节省流量）
```

---

## 主要 API

### 行情服务（:8001）

```http
GET  /api/v1/stocks/{symbol}                  # 股票基本信息
GET  /api/v1/stocks/{symbol}/kline            # K线数据（period/limit/indicators）
GET  /api/v1/search?q=贵州茅台               # 股票搜索
GET  /api/v1/quotes/{symbol}                  # 实时行情
GET  /api/v1/alerts                           # 价格预警列表
POST /api/v1/alerts                           # 创建预警
POST /api/v1/crawl/{symbol}/news              # 手动触发新闻采集（登录用户）
POST /api/v1/crawl/{symbol}/financials        # 手动触发财报采集（管理员）
```

### 用户服务（:8002）

```http
POST /api/v1/auth/register                    # 注册
POST /api/v1/auth/login                       # 登录（返回JWT）
GET  /api/v1/auth/me                          # 当前用户信息
GET  /api/v1/watchlists                       # 自选股列表
POST /api/v1/watchlists/{id}/items            # 添加自选股
```

### 分析服务（:8003）

```http
GET  /api/v1/analysis/score/{symbol}          # 个股综合评分（5维度）
GET  /api/v1/analysis/score/batch/recommend   # 每日观察池
GET  /api/v1/analysis/technical/{symbol}      # 技术指标
GET  /api/v1/analysis/patterns/{symbol}       # K线形态识别
GET  /api/v1/analysis/financial/{symbol}      # 财务分析
GET  /api/v1/analysis/financial/{symbol}/dupont   # 杜邦分析
GET  /api/v1/analysis/financial/{symbol}/fscore   # F-Score
GET  /api/v1/analysis/valuation/{symbol}      # 估值分析
POST /api/v1/analysis/ai/analyze              # AI深度分析
POST /api/v1/analysis/ai/follow-up            # AI追问
POST /api/v1/analysis/ai/batch-summary        # 批量AI摘要（自选股用）
GET  /api/v1/analysis/public-health           # 健康检查（无需登录）
```

---

## 交付验证

```bash
# 全量验证（后端单测/类型检查/前端lint/build/smoke/密钥卫生）
python scripts/verify_delivery.py

# 仅密钥卫生检查（提交前快速验证）
python scripts/verify_secret_hygiene.py
```

---

## 监控

- **Grafana**：http://localhost:3000（密码见 `.env` 中 `GRAFANA_PASS`）
  - 业务概览：API调用量/模型健康/配额使用
  - 爬虫健康：采集任务状态/成功率
  - 系统总览：CPU/内存/数据库连接池
- **Prometheus**：http://localhost:9090
- **Alertmanager**：http://localhost:9093

运维手册入口：
- 生产发布：[`docs/ops/production-deploy.md`](docs/ops/production-deploy.md)
- 监控告警：[`docs/ops/monitoring-runbook.md`](docs/ops/monitoring-runbook.md)
- 备份恢复：[`docs/ops/backup-restore.md`](docs/ops/backup-restore.md)
- 研究复盘：[`docs/ops/research-review-runbook.md`](docs/ops/research-review-runbook.md)

---

## 故障排除

## 管理员账号

### 方式一：环境变量自动创建（推荐，新部署）

在 `.env` 中配置后启动服务，`init_db()` 会自动创建管理员账号（幂等，重启不会重复创建）：

```bash
ADMIN_USERNAME=admin
ADMIN_PASSWORD=your-strong-password
ADMIN_EMAIL=admin@example.com   # 可选，默认 admin@localhost
```

### 方式二：脚本手动创建（已有数据库）

```bash
# 交互式
python scripts/create_admin.py

# 非交互式
python scripts/create_admin.py --username admin --password your-password

# 提升已有普通用户为管理员
python scripts/create_admin.py --username existing_user --password any
```

### 本地开发

`AUTH_REQUIRED=false` 时自动创建 `dev` / `dev` 账号（`free` 角色）。
加 `ALLOW_DEV_ADMIN=true` 可将 dev 账号提升为 admin，用于本地调试管理后台。

---

## 故障排除

**前端白屏/观察池无数据**
```bash
python scripts/start_local.py    # 重启所有服务，清理旧进程
```

**财报/新闻缺失**
- 个股详情页 AI 分析面板 → 点击"一键补全数据"（新闻/公告）
- 财报批量初始化：`python scripts/init_financials.py`

**容器启动失败**
```bash
docker compose logs <service_name>    # 查看日志
docker compose ps                     # 检查容器状态
```

**数据库迁移**
```bash
alembic upgrade head
```

---

## 免责声明

本平台提供的所有数据和AI分析结果仅供研究参考，**不构成任何投资建议**。投资有风险，入市需谨慎。
