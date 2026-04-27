# 股票数据分析平台 — 实施计划

> 以 **A 股为核心** 的全栈股票数据分析平台

---

## Phase 1：项目骨架搭建 (✅ 完成)

### 1.1 项目初始化
- [x] 后端项目骨架 (FastAPI + 微服务目录结构)
- [x] 前端项目骨架 (Vue 3 + TypeScript + ECharts)
- [x] Docker Compose 配置 (PostgreSQL + ClickHouse + Redis + Prometheus + Grafana)
- [x] 环境变量模板 (.env.example)
- [x] Makefile 快捷命令

### 1.2 数据库基础
- [x] PostgreSQL 业务表 (users/stocks/watchlists/price_alerts)
- [x] ClickHouse 时序表 (stock_daily/stock_minute + 周/月物化视图)
- [x] ClickHouse A股特色表 (money_flow/dragon_tiger/north_bound/sector_performance)
- [x] A 股代码体系校验逻辑 (沪/深/创/科创/北交)

### 1.3 A 股数据源接入（核心）
- [x] 数据源抽象基类 (BaseDataSource) + 熔断器 (CircuitBreaker)
- [x] 东方财富 (EastMoney) — 实时行情 + 历史 K 线 + 资金流向
- [x] AKShare — A 股全覆盖免费源 (K线/行情/搜索/板块/龙虎榜)
- [x] Tushare Pro — 专业 A 股备用源
- [x] 故障降级链管理器 (DataSourceChain)
- [x] 定时采集任务调度 (日K/周K/月K/实时/资金流向/龙虎榜)

---

## Phase 2：A 股行情展示 (✅ 完成)

### 2.1 API 层
- [x] K线数据 API（多周期 + 复权 + 技术指标实时计算）
- [x] 实时行情 API（最新价/涨跌幅/成交量/换手率/PE/市值/涨跌停）
- [x] 股票搜索 API（按代码/名称）
- [x] 板块 API (行业板块/概念板块)
- [x] 龙虎榜 API
- [x] 资金流向 API (超大单/大单/中单/小单)
- [x] 大盘指数 API (上证/深证/创业板/科创50/沪深300)
- [x] 市场概览 API (涨跌家数/涨跌停/成交额)
- [x] 请求追踪 + 统一异常处理 + CORS

### 2.2 前端核心组件
- [x] K 线图 (ECharts Candlestick): 周期切换 + MA指标叠加 + 涨跌停线
- [x] **分时图** (当日走势 + 均价线 + 昨收线 + 成交量)
- [x] 涨跌停价显示 (K 线图上虚线标记)
- [x] 复权切换 (前复权/后复权/不复权)
- [x] 个股详情页: K线/分时图切换 + 行情面板 + 资金流向 + 免责声明
- [x] 股票列表 + 搜索
- [x] 自选股管理
- [x] 资金流向图

### 2.3 缓存策略
- [x] Redis 多级缓存（实时行情 5s / 日K 1h / 股票信息 12h）
- [x] 缓存装饰器 / 统一管理器
- [x] 缓存失效策略

---

## Phase 3：用户系统 + 自选股 (✅ API完成，前端部分完成)

### 3.1 用户服务
- [x] 注册/登录 (JWT + bcrypt) — 后端API + 前端登录页
- [x] 用户资料管理 — 前端个人中心页
- [ ] 免费/付费会员体系

### 3.2 自选股
- [x] 自选股分组管理（默认组/自定义组）
- [x] 自选股列表 + 实时行情汇总
- [ ] 拖拽排序
- [ ] 自选股导入/导出

---

## Phase 4：A 股特色分析功能 (✅ 分析服务API全部完成)

### 4.1 技术指标引擎 + API
- [x] MA/EMA 均线系列 — 后端计算引擎
- [x] MACD — 含 DIF/DEA/柱状图
- [x] BOLL 布林带 — 含上中下轨
- [x] KDJ — 随机指标
- [x] RSI — 相对强弱指标
- [x] VOL 成交量均线
- [x] 批量计算引擎 (compute_all)
- [x] 技术指标API: `GET /api/v1/analysis/technical/{symbol}` 批量查询
- [x] 单指标API: `GET /api/v1/analysis/technical/{symbol}/single` 
- [x] 多股对比API: `GET /api/v1/analysis/compare`
- [x] 区间涨跌幅对比API: `GET /api/v1/analysis/compare/performance`

### 4.2 综合评分 + 形态识别
- [x] 5维度评分模型 (动量30%/技术25%/价值20%/质量15%/情绪10%)
- [x] 个股评分API: `GET /api/v1/analysis/score/{symbol}`
- [x] 推荐股票API: `GET /api/v1/analysis/score/batch/recommend`
- [x] K线形态识别 (doji/hammer/shooting_star/ engulfing/3 soldiers/3 crows/morning/evening)
- [x] 形态检测API: `GET /api/v1/analysis/patterns/{symbol}`

### 4.2 A 股特色
- [x] 资金流向分析 — 东方财富API + ClickHouse表
- [x] 北向资金持仓变化 — ClickHouse表
- [x] 龙虎榜追踪 — AKShare API + ClickHouse表
- [ ] 涨停板复盘 (涨停时间/封单金额/炸板)
- [x] 板块轮动 — API已定义，AKShare数据源已就绪
- [ ] 大宗交易

### 4.3 基本面数据
- [ ] 财务报表
- [ ] 核心指标可视化
- [ ] 分红送转记录
- [ ] 股东增减持

---

## Phase 5：高级功能 (部分完成)

### 5.1 价格预警
- [x] Schema已定义 (price_alerts表)
- [x] API端点已定义 (创建/查询/删除/检查)
- [ ] 前端预警管理页
- [ ] 推送通知

### 5.2 量化回测（轻量版）
- [ ] 简单策略回测引擎
- [ ] 收益率/最大回撤/夏普比率
- [ ] 回测结果可视化

### 5.3 大盘指数
- [x] API端点 (指数列表/详情/K线/市场概览)
- [ ] 前端指数看板

---

## Phase 6：生产化 (基础配置就绪)

### 6.1 部署
- [x] Docker Compose 全服务编排 + 健康检查
- [x] Nginx 反向代理
- [x] 容器健康检查
- [ ] SSL 证书
- [ ] CI/CD

### 6.2 可观测性
- [x] Prometheus 指标采集配置
- [x] Grafana 大盘
- [ ] 日志聚合

### 6.3 安全合规
- [x] 免责声明组件
- [x] 数据来源标记
- [ ] 用户协议 + 隐私政策
- [ ] API 频率限制

---

## 数据表进度

| 表名 | 用途 | 状态 |
|------|------|------|
| users | 用户认证 | ✅ |
| stocks | A股基础信息 | ✅ |
| watchlists | 自选股分组 | ✅ |
| watchlist_items | 自选股项目 | ✅ |
| user_activity_logs | 用户行为日志 | ✅ |
| price_alerts | 价格预警规则 | ✅ |
| stock_daily | 日K线(含A股字段) | ✅ |
| stock_minute | 分钟级行情 | ✅ |
| stock_weekly/monthly | 周/月K物化视图 | ✅ |
| stock_quotes | 实时行情快照 | ✅ |
| technical_indicators | 指标缓存 | ✅ |
| money_flow | 资金流向 | ✅ |
| dragon_tiger | 龙虎榜 | ✅ |
| north_bound | 北向资金 | ✅ |
| sector_performance | 板块涨跌 | ✅ |

## 数据源接入进度

| 数据源 | 类型 | 状态 |
|--------|------|------|
| 东方财富 | 免费 | ✅ 已实现 |
| AKShare | 免费开源 | ✅ 已实现 |
| Tushare Pro | 付费 | ✅ 已实现 |
| 新浪财经 | 免费 | 📅 计划中 |
| 故障降级链 | 框架 | ✅ |
| 熔断器 | 框架 | ✅ |

## 已完成文件清单

### 后端核心
- `backend/shared/models.py` — SQLAlchemy ORM (6表)
- `backend/shared/schemas.py` — Pydantic DTO
- `backend/shared/cache.py` — 多级缓存
- `backend/shared/database.py` — 连接池
- `backend/shared/security.py` — JWT+bcrypt
- `backend/shared/validators.py` — 数据校验
- `backend/shared/exceptions.py` — 异常体系

### A股数据采集
- `backend/services/data_crawler/sources/base.py` — 基类+熔断器+代码校验
- `backend/services/data_crawler/sources/fallback_chain.py` — 降级链
- `backend/services/data_crawler/sources/eastmoney_source.py` — 东方财富
- `backend/services/data_crawler/sources/akshare_source.py` — AKShare
- `backend/services/data_crawler/sources/tushare_source.py` — Tushare
- `backend/services/data_crawler/pipeline/etl.py` — ETL管道

### 行情服务 (market_service)
- `app/main.py` — FastAPI入口
- `app/api/v1/quotes.py` — 行情API
- `app/api/v1/kline.py` — K线+指标API
- `app/api/v1/search.py` — 搜索API
- `app/api/v1/sectors.py` — 板块API
- `app/api/v1/dragon_tiger.py` — 龙虎榜API
- `app/api/v1/alerts.py` — 预警API
- `app/api/v1/index_market.py` — 大盘指数API

### 分析服务 (analysis_service)
- `backend/services/analysis_service/engine/indicator_engine.py` — MA/EMA/MACD/BOLL/KDJ/RSI 指标计算引擎
- `backend/services/analysis_service/api/v1/technical.py` — 技术指标API (批量/单指标)
- `backend/services/analysis_service/api/v1/compare.py` — 多股对比API (指标/区间收益)
- `backend/services/analysis_service/api/v1/scoring.py` — 综合评分API (5维度评分/推荐)
- `backend/services/analysis_service/api/v1/patterns.py` — K线形态识别API (9种形态)
- `backend/services/analysis_service/app/main.py` — FastAPI入口 (端口8003)
- `backend/services/analysis_service/Dockerfile` — 容器配置
- `backend/services/analysis_service/requirements.txt` — 依赖

### 用户服务 (user_service)
- `app/main.py` — FastAPI入口
- `app/api/v1/auth.py` — JWT认证
- `app/api/v1/watchlist_routes.py` — 自选股CRUD

### 前端组件
- `components/charts/KLineChart.vue` — K线图
- `components/charts/TimeShareChart.vue` — 分时图
- `components/charts/MoneyFlowChart.vue` — 资金流向
- `components/stock/QuotePanel.vue` — A股行情面板
- `components/common/Disclaimer.vue` — 免责声明
- `views/StockDetail.vue` — 个股详情(K线/分时图切换)
- `views/Stocks.vue` — A股列表+搜索
- `views/Watchlist.vue` — 自选股
- `views/Login.vue` — 登录/注册
- `views/Profile.vue` — 个人中心
- `api/index.ts` — API客户端(含预警/指数端点)

### 基础设施
- `docker-compose.yml` — 全服务编排
- `infra/postgres/init.sql` — 6业务表
- `infra/clickhouse/init.sql` — 11时序表(含A股特色)
- `infra/prometheus/prometheus.yml` — 指标采集

---

## 图例
- [x] 已完成
- 📅 计划中
