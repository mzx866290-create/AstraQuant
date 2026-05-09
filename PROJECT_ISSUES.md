# 项目问题盘点与改进方向

> 适用范围：`D:/Apps/Demo4` 股票数据分析平台（FastAPI 微服务 + Vue3 前端 + PostgreSQL/ClickHouse/Redis）。
> 编写日期：2026-05-06。本文档不替代代码 review，仅梳理结构性、工程化与产品层面的主要短板及其落地方向。

---

## 一、整体架构与工程化

### 1.1 启动入口/根目录混乱
- **现象**：根目录同时存在 `run_project.py`、`run_simple_api.py`、`start_all_sqlite.py`、`start_market.py`、`start_user.py`、`start_simple.py`、`start_sqlite.py`、`start_services.bat`、`scripts/start_local.py`、`docker-compose.yml`，README 又只推荐 `scripts/start_local.py`。
- **风险**：新人/CI 不知道哪个是“正确入口”；多个脚本之间端口、数据库（SQLite vs PG/CH）、依赖加载顺序不一致，容易踩坑。
- **改进方向**：
  1. 保留 **两条** 官方入口：`scripts/start_local.py`（本地 SQLite）、`docker-compose up`（容器全栈）。
  2. 其余 `start_*.py / run_*.py / *.bat` 全部移入 `scripts/legacy/` 或直接删除，README 顶部明确写出唯一推荐入口。
  3. 在 `Makefile` 暴露 `make dev / make stack / make test / make lint`，统一约定。

### 1.2 仓库脏文件与日志入库
- **现象**：根目录提交了 `*.log`（`analysis-service.err.log`、`vite-ai-template.out.log` 等）、`*.db`（`stock_platform.db` 出现在根目录与每个服务目录），`venv/` 也疑似被纳入，`git status` 显示几十个修改文件未提交。
- **风险**：仓库膨胀、敏感运行日志泄露、SQLite 文件冲突、CI 缓存命中率低。
- **改进方向**：
  1. 完善 `.gitignore`：`*.log`、`*.db`、`venv/`、`__pycache__/`、`node_modules/`、`dist/`、`.env`、`*.out.log`、`*.err.log`。
  2. 用 `git rm --cached` 把已追踪但应忽略的文件从索引中去除，开一个“仓库清理”commit。
  3. 日志统一写入 `logs/{service}/{date}.log`（已有 `logs/` 目录但未真正使用）。

### 1.3 数据库形态不统一
- **现象**：每个服务目录都有 `stock_platform.db`，README 说默认 SQLite，但 `docker-compose.yml` 里又是 PostgreSQL + ClickHouse；`init_sqlite.py` 与 `infra/postgres/init.sql` 并存，schema 容易漂移。
- **改进方向**：
  1. 让 `shared/database.py` 通过统一的 `DATABASE_URL`/`CLICKHOUSE_URL` 切换，单一 schema 由 Alembic 维护。
  2. 引入 **Alembic** 做迁移，废弃手写 SQL 与 `init_sqlite.py`。
  3. SQLite 仅作为开发兜底，CI/E2E 必须跑 PG + CH（用 `testcontainers` 或 docker-compose.test.yml）。

### 1.4 共享模块与服务边界
- **现象**：`backend/shared/` 同时包含 `auth/audit/cache/database/observability/security/validators` 等横切关注点，但 `analysis_service` 体积特别大（`ai_analysis.py` 1202 行、`scoring.py` 1151 行），单文件承担了路由 + 业务 + 规则。
- **风险**：路由层过厚导致测试困难、AI 调用与评分逻辑无法独立演进。
- **改进方向**：
  1. 拆分：`api/v1/ai_analysis.py` → `services/ai/{prompt,client,parser}.py` + `api/v1/ai_analysis.py`（仅做 schema/路由）。
  2. `scoring.py` 拆为 `scoring/{rules,pipeline,recommend}.py`，规则配置外置 YAML，便于策略调参。
  3. 共享层只放真正“跨服务复用”的代码，业务 helper 下沉到各服务内部。

---

## 二、后端质量

### 2.1 单文件超长 + 圈复杂度
- `analysis_service/api/v1/ai_analysis.py` 1202 行、`scoring.py` 1151 行、`market_service/app/api/v1/kline.py` 318 行——这些都是典型的“God file”。
- **改进方向**：以 *router-only* 为目标，单文件控制在 ~250 行内；新增 `engine/` 与 `services/` 层做编排；引入 `radon cc` 做圈复杂度阈值（≥ C 拒绝合并）。

### 2.2 测试覆盖偏薄且偏“场景化”
- **现象**：`backend/tests/` 13 个测试，多半是“某次回归/某次漏洞”的命题作文（`test_admin_health_regression.py`、`test_ai_trust_boundaries.py`、`test_kline_period_sources.py` 等），**没有针对核心域（评分、K 线计算、技术指标、缓存层）的单元测试**，前端零测试（`@playwright/test` 装了但目录不存在）。
- **改进方向**：
  1. 制定覆盖率目标：核心模块（scoring、technical、ai_client、etl）≥ 80% 行覆盖。
  2. 引入 `pytest-cov` + GitHub Actions（或本地 `make test-cov`），低于阈值禁止合并。
  3. 为前端补 Playwright e2e（登录 → 自选股 → K 线 → 预警），并在 `scripts/frontend_smoke.mjs` 之外加 Vitest 组件测试。

### 2.4 异常与日志规范
- **现象**：每个服务都自带 `*_err.log`、`*_out.log` 重定向，没有统一 logger 配置（`shared/observability.py` 存在但未必被普遍调用）。错误处理散落在 router 中，少见统一异常映射。
- **改进方向**：
  1. 在 `shared/observability.py` 中统一 `structlog`/`logging.dictConfig`，每个服务在 `app/main.py` 启动时一次性注入。
  2. 引入全局 `exception_handler`：业务异常 → 4xx，未知异常 → 5xx + trace id；trace id 进 response header 与日志，便于问题回查。
  3. 接入 OpenTelemetry → Prometheus/Grafana（已部署 Grafana，但缺埋点），把 `request_duration_seconds`、`cache_hit_total`、`crawler_failure_total` 暴露出来。

### 2.5 缓存与限流
- **现象**：`shared/cache.py` 存在但未看到限流；`AkShare`、`Tushare` 抓取频率高时容易被风控；`alerts/check` 这类接口缺乏防刷。
- **改进方向**：
  1. Redis + `slowapi`（或 fastapi-limiter）做 IP/用户级限流，至少覆盖 `/auth/*`、`/alerts/check`、`/score/*`。
  2. 数据源层加 **circuit breaker**（`pybreaker`）+ 退避重试，并把状态写入 Prometheus。
  3. 行情快照、K 线、搜索这些读多写少接口走 Redis 缓存，明确 TTL（实时 1–5s，日 K 24h，搜索结果 5min）。

### 2.6 安全
- **现象**：`.env.example`、`.env.production` 都在 git 中变更，存在密码/Token 明文落地的风险；JWT、密码策略、CSRF/CORS 未在文档中体现；admin 路由 (`admin_users/admin_logs/admin_models/admin_stats`) 鉴权强度未知。
- **改进方向**：
  1. 把 `.env.production` 从仓库移除，使用 `.env.production.example` + 部署时注入（Docker secrets / Vault / 1Password CLI）。
  2. `shared/auth.py` 中显式区分 `require_user` / `require_admin`，对所有 `admin_*` 路由统一加 `Depends(require_admin)` 并补单测。
  3. 增加 `bandit`、`pip-audit`、`npm audit --production` 到 CI；密码使用 `argon2`，刷新 token 用旋转策略。
  4. 严格 CORS 白名单 + `SameSite=strict` cookie 选项；上线前做一次 OWASP ASVS 自检。

### 2.7 数据采集稳定性
- **现象**：`data_crawler/sources/` 有 `akshare/eastmoney/tushare/news_source/fallback_chain`，但没有可观测的成功率统计；`pipeline/etl.py / financial_etl.py / news_etl.py` 没有失败回放与幂等键。
- **改进方向**：
  1. 引入任务队列（Celery + Redis 或 APScheduler + Postgres job table），每个 ETL 任务持久化状态、重试次数、最近错误。
  2. 对每个 source 暴露 `success_rate / latency_p95 / last_error_at` 指标。
  3. 使用 `(symbol, date, source)` 作为唯一键做 upsert，保证幂等；落地“数据完整度等级”计算逻辑。

---

## 三、前端

### 3.1 工程结构
- **现象**：`src/api/index.ts` 单文件承载所有接口；`views/` 11 个页面但 `components/` 只有 `ai/charts/common/stock` 四类，缺乏页面级目录划分；`stores/` 数量未知，估计未做拆分。
- **改进方向**：
  1. 按模块切分 API：`src/api/{auth,market,analysis,admin,alerts}.ts`，统一通过 axios instance + 拦截器处理 401/限流/重试。
  2. 引入 **TanStack Query (Vue)** 或基于 Pinia 封装的请求缓存层，避免页面切换时重复拉取。
  3. 页面级目录：`views/Stocks/{index.vue, components/, composables/}`。

### 3.2 测试与类型
- **现象**：装了 Playwright 没用到；`tsconfig` 严格度未知；缺少 `eslint` 强制规则（虽有 lint script）。
- **改进方向**：
  1. `tsconfig.strict: true`，禁用 `any`，把 `vue-tsc --noEmit` 接入 `npm run build` 前置。
  2. 加 ESLint + Prettier + `vue/recommended` + `@typescript-eslint`，pre-commit 跑 `lint-staged`。
  3. 关键路径补 Playwright e2e（登录、自选股、K 线、预警），跑在 CI。

### 3.3 性能与可访问性
- ECharts 全量打包体积大；首页“今日观察”、K 线、自选股都用 ECharts，未做按需引入。
- **改进方向**：`echarts/core` + 按需注册组件 + 异步加载；首屏代码分割（`defineAsyncComponent`）；表格用虚拟滚动；补 a11y（label/role/对比度）。

---

## 四、可观测与运维

### 4.1 监控告警闭环
- **现象**：`infra/prometheus/` 与 Grafana 部署了，但 `test_prometheus_alerting_config.py` 表明告警规则在演进，业务侧关键指标（采集失败率、AI 调用延迟、评分管道耗时）未必都暴露。
- **改进方向**：
  1. 统一 `metrics.py`：每个服务暴露 `service_info`、`http_request_*`、`task_*` 三组指标。
  2. Grafana 预置三张看板：业务（评分/AI/预警）、采集（成功率/延迟/source 健康）、系统（CPU/内存/慢查询）。
  3. 关键告警接 Webhook（飞书/钉钉/Slack 任一），并写运维手册（runbook）。

### 4.2 部署与发布
- **原始现象**：README 里“生产环境部署”一节曾提到 `docker-compose.prod.yml（需要创建）`，且没有 CI/CD 配置。
- **当前状态**：已补 `docker-compose.prod.yml`、`.github/workflows/ci.yml`、手动告警 Webhook 演练 workflow、生产部署 runbook、CI/部署演练记录、证据归档准备/校验/封存脚本；剩余缺口是必须在真实 GitHub Actions 与部署环境跑一次完整演练并归档证据。
- **改进方向**：
  1. 在真实发布窗口执行 `verify_ops_drill_readiness`、密钥卫生门禁、CI、告警 Webhook 演练、部署 smoke 与回滚检查。
  2. 下载 `ci-deployment-drill-record` 与 `alert-webhook-drill-record` 两份 artifact，补全 `completed/` 后封存归档。
  3. 引入版本号策略（语义化版本 + git tag），构建产物打 SHA tag。

### 4.3 备份与灾备
- **原始现象**：未见数据库备份脚本/策略；`stock_platform.db` 散落各处；ClickHouse/PG 都没有 dump 计划。
- **当前状态**：已补备份恢复 runbook 与 PostgreSQL/ClickHouse 备份脚本，生成/运行时文件清理脚本也已接入；下一步是按季度在隔离环境执行真实恢复演练。
- **改进方向**：
  1. PG 每日 `pg_dump` + WAL 归档；ClickHouse `BACKUP TABLE ... TO Disk`。
  2. 备份产物按日期落到对象存储（MinIO/S3），保留 7/30/90 天三档。
  3. 写一份“恢复演练”脚本，每季度验证一次。

---

## 五、产品与文档

### 5.1 文档碎片化
- **原始现象**：根目录三份 markdown：`README.md`、`PLAN.md`、`PLAN_AI_MODEL.md`，没有 `docs/` 目录；新人难以快速找到“接口 / 部署 / 数据字典 / 风险说明”。
- **当前状态**：已建立 `docs/ops/` 并把生产发布、监控、备份恢复、CI/部署演练和证据归档入口收敛到 README；后续可继续补 `architecture / api / data / decisions(ADR)`。
- **改进方向**：
  1. 建 `docs/`，按 `architecture / api / ops / data / decisions(ADR)` 分目录；README 只做导航。
  2. 用 `mkdocs-material` 或 VitePress 做一份可浏览站点，CI 自动发布。
  3. 引入 ADR（Architecture Decision Record），每个重大改动一个 markdown，记录“为什么这么做”。

### 5.2 “今日观察”等业务说明的合规
- README 已经写了“非投资建议”免责声明，但前端页面/AI 输出未必都做了同等提示。
- **改进方向**：在 `Recommendations.vue`、AI 分析输出、邮件/告警通知里统一插入风险提示模板，并在审计日志中可追溯地记录来源、规则版本、模型版本。

---

## 六、改进路线图（按优先级落地）

| 阶段 | 周期 | 主要事项 |
|------|------|----------|
| P0：止血 | 1 周 | 清理仓库（log/db/env），统一启动入口，补 `.gitignore`，把 `admin_*` 路由的鉴权审一遍 |
| P1：基线 | 2–3 周 | 引入 Alembic、统一 logger/异常、CI（lint/test/coverage/secret-scan）、前端 ESLint+strict TS |
| P2：可观测 | 2 周 | Prometheus 业务指标、Grafana 三张看板、Webhook 告警、采集成功率指标 |
| P3：稳健 | 3–4 周 | 拆分超长路由文件、ETL 幂等与重放、限流熔断、Redis 缓存策略落地 |
| P4：质量 | 持续 | 核心模块单测覆盖率 ≥ 80%、Playwright e2e、ADR 与 docs 站点、灾备演练 |

---

## 七、可立刻执行的 5 个小动作

1. `git rm -r --cached venv logs *.log *.db backend/services/*/stock_platform.db` 并补 `.gitignore`。
2. 把 `start_*.py / run_*.py / *.bat` 移入 `scripts/legacy/`，README 顶部写明唯一入口。
3. `docker-compose.prod.yml` 起草（即使先复制 dev 版），让“生产部署”这一节不再悬空。
4. 给 `admin_*` 路由加 `Depends(require_admin)` 并补一个回归测试。
5. 在 `frontend/web` 里跑 `npm run type-check` 与 `npm run lint`，把现存告警一次性清掉，再把这两条接入 `npm run build` 前置。

---

## 八、执行状态（2026-05-07）

### P0 已完成/已收口
- `.gitignore` 已覆盖 `.env.production`、日志、SQLite 数据库、虚拟环境、构建产物与依赖目录。
- `.env.production` 已从 Git 索引移除，改用 `.env.production.example` 作为生产配置模板；真实密钥应由部署平台、Docker secrets、Vault 或 CI/CD 注入。
- README 已明确两条官方入口：`python scripts/start_local.py` / `make dev` 与 `docker compose up -d` / `make stack`；根目录历史脚本仅作为兼容入口保留。
- `Makefile` 已补齐 `dev`、`stack`、`test`、`lint`、`smoke`、`verify`，并把前端 ESLint、类型检查、浏览器 smoke 纳入本地门禁。
- `admin_*` 路由已统一使用 `Depends(require_admin())`，并已有回归测试覆盖开发默认管理员策略。

### P1/P2 已推进
- CI 已新增后端依赖安装、后端单测、自检脚本、前端 lint、类型检查、构建、Playwright Chromium 安装与前端 smoke。
- 前端已补 ESLint flat config，默认 `npm run lint` 只检查不改文件，`npm run lint:fix` 才执行自动修复。
- Prometheus 规则、服务健康检查、数据采集任务指标、产品 MVP 边界与前端可信状态提示已有测试保护。
- 已新增独立 `docker-compose.prod.yml`，生产环境使用镜像标签、避免后端/数据库端口外露，并接入 Grafana provisioning 与 Alertmanager。
- 已新增三张 Grafana 看板骨架（业务、采集、系统）、监控 runbook、生产部署 runbook、备份恢复 runbook 与 PostgreSQL/ClickHouse 备份脚本。
- 已新增运维静态合约测试，覆盖生产 compose、Grafana datasource/dashboard、Alertmanager、runbook 与备份恢复脚本。
- 已新增共享固定窗口限流模块，并接入 `/auth/*`、`/alerts/check`、`/analysis/score/*`；覆盖 Redis 计数、开发兜底、生产 fail-open/fail-closed 策略和路由接入测试。

### P3 本轮已推进
- 已新增共享轻量熔断模块 `backend/shared/resilience.py`，覆盖 closed/open/half-open 状态流转、失败阈值、恢复窗口与单测重置能力。
- 已将数据源熔断接入预警行情检查、评分 K 线数据源与评分资金流数据源；行情源熔断时返回明确 degraded/质量警告，避免继续打坏外部数据源。
- 已加固 ClickHouse ETL 写入幂等性：daily/minute/weekly/monthly/money_flow/dragon_tiger 均在共享写入层按业务键去重后再执行 delete + insert。
- 已补 ETL 幂等测试，覆盖跨批重跑替换、部分插入成功后重试、龙虎榜 `(trade_date, symbol, reason)` 去重且不同 reason 保留。
- 已新增 Alembic 迁移骨架与 baseline revision，配套迁移契约测试与数据库迁移说明文档。
- 已将缓存 TTL 收敛到集中策略，覆盖实时行情、分钟 K、日 K、周/月 K、搜索和每日观察池。
- 已补告警 Webhook 演练脚本与运行手册，默认 dry-run，支持生成演练记录模板和执行后预填记录。
- 已将 `market_service` 的 K 线路由下沉到 service 层，router 仅保留参数校验与响应拼装。
- 已新增 `docker-compose.test.yml` 与测试环境说明，固定 PostgreSQL、ClickHouse、Redis 的 CI/E2E 基础设施合约，并用静态测试保护端口、初始化脚本和临时存储策略。
- 已将根目录历史启动脚本收敛为轻量兼容 wrapper，真实维护入口统一指向 `scripts/start_local.py` 与 `docker compose up -d`，并新增 `scripts/legacy/` 说明与治理测试。
- 已新增 DB integration CI job 与 `scripts/verify_db_integration.py`，在 CI 中强制启动 PostgreSQL、ClickHouse、Redis 并执行 `SELECT 1`/`PING` smoke；本地无 Docker 时默认 skip。
- 已将 `scoring.py` 的每日观察池/推荐候选逻辑拆入 `analysis_service/engine/recommendation_engine.py`，保留路由兼容导入与推荐池回归测试。
- 已将 `scoring.py` 的 K 线/财报/新闻/资金流读取与熔断上下文拆入 `analysis_service/engine/scoring_data.py`，保留 `_fetch_*`、`_build_money_flow_context`、`_money_flow_breaker` 等旧路径兼容测试与 `patterns.py`。
- 已将 `scoring.py` 的动量、技术、价值、质量、情绪评分和评级映射拆入 `analysis_service/engine/scoring_calculations.py`，API 文件只保留路由、限流、缓存和响应拼装，文件规模降至 243 行。
- 已将 `ai_analysis.py` 的缓存 key、缓存响应清洗、模型正文清洗和可信边界拼装拆入 `analysis_service/engine/ai_analysis_support.py`，并保留信任边界测试。
- 已将 `ai_analysis.py` 的股票数据装配、实时行情兜底、公开资料抓取、K 线读取、技术指标与财报映射拆入 `analysis_service/engine/ai_analysis_data.py`，API 层保留旧私有函数别名兼容自检脚本。
- 已将 `ai_analysis.py` 的本地 fallback 报告、追问兜底、批量摘要、风险灯、异动提示和数据来源归因拆入 `analysis_service/engine/ai_analysis_fallbacks.py`，`ai_analysis.py` 已由 1124 行降至 524 行。
- 已将 `ai_analysis.py` 的模型列表、配额、就绪度、分析编排、追问、批量摘要和 crawl 状态查询下沉到 `analysis_service/engine/ai_analysis_service.py`，`api/v1/ai_analysis.py` 现在仅保留薄路由壳与兼容别名，文件规模降至 110 行。
- 已新增手动 `Alert Webhook Drill` GitHub Actions workflow，可在配置 `ALERT_WEBHOOK_URL` secret 后发送 firing/resolved 演练告警，并在同一次脚本执行中生成预填 `alert-webhook-drill-record` artifact。
- 已将 `Alert Webhook Drill` 记录模板升级为显式证据字段，覆盖 GitHub Actions run URL、`send=true`、`status=both`、firing/resolved HTTP 响应、实际收到时间与 artifact 名称；workflow 上传 artifact 时启用 `if-no-files-found: error`，且不再先上传空模板。
- 已新增 `docs/ops/ci-deployment-drill-record.md`，将 GitHub Actions、DB integration、告警演练、生产 smoke 与回滚检查收口为统一的人工演练记录模板，并在 README 中补充入口。
- 已新增 `scripts/ops/render_ci_deployment_drill_record.py` 与渲染脚本测试，可从命令行参数或 `DRILL_*` 环境变量生成 CI/部署演练记录，真实环境只需补 run URL、smoke 结果与负责人信息。
- CI 已新增 `ci-drill-record` 收尾 job，依赖 `db-integration` 与 `verify` 并使用 `if: always()`，会自动生成并上传 `ci-deployment-drill-record` artifact；渲染脚本支持从 GitHub Actions 环境自动推导 repository、commit、run URL、owner 与默认 UTC 时间。
- 已新增 `scripts/ops/validate_ci_deployment_drill_record.py` 与校验脚本测试，正式归档前可自动检查必填证据、占位值、关键 job 结果、真实告警发送、部署 smoke、回滚检查和最终结论是否合格。
- 已新增 `scripts/ops/validate_alert_webhook_drill_record.py` 与 `scripts/ops/validate_ops_drill_archive.py`，可分别校验告警演练记录和下载后的双 artifact 归档目录，防止缺少 `ci-deployment-drill-record` / `alert-webhook-drill-record`、send=false、dry-run、未收到 firing/resolved、泄露 webhook URL 或主记录未引用告警 artifact。
- 已新增 `scripts/ops/prepare_ops_drill_archive.py` 与 `docs/ops/ops-drill-archive-runbook.md`，固定 GitHub artifact 下载、标准归档目录生成、`raw/` 原始件保留、`completed/` 人工补全、`validation.txt` 留痕和外部运维/发布系统归档流程。
- 已加固 `validate_ops_drill_archive.py`，当校验目录内出现多份同名演练记录时直接失败，避免 `raw/` 与 `completed/` 混扫导致误归档。
- 已新增并持续加固 `scripts/ops/finalize_ops_drill_archive.py`，对准备好的归档根目录执行封存：校验 `completed/`、扫描 `raw/`/`completed/`/根说明文件中的敏感 webhook/token/密钥线索、写入带 UTC 时间的 `validation.txt`、`manifest.json`、`manifest.sha256` 和 `.sealed`，并生成 `<archive>.zip` 与 `<archive>.zip.sha256` 作为正式封存包；还新增了 `--verify` 复验模式、`--verify-package` 仅校验封存包模式和可选的 `--summary-json` 机器可读 sidecar。`prepare_ops_drill_archive.py --force` 也已拒绝覆盖带 `.sealed` 的正式归档目录。
- 已新增 `scripts/ops/ops_drill_archive_smoke.py`，用临时样例记录本地跑通 `prepare -> finalize -> verify -> verify-package` 全链路，默认自动清理临时目录，作为真实 GitHub Actions/部署演练前的脚本链路预检，不影响业务服务。

- 已将 AI 分析/追问的 `AIUsageLog` 写入、成功配额递增与事务提交收口到 `_record_ai_usage` helper，并新增 `backend/tests/test_ai_analysis_usage_recording.py` 覆盖 success/error 两条审计路径。
- 已完成前端 API 模块化拆分：`client.ts` 承接 axios 实例、baseURL 校验、token 注入与 401 跳转；`unavailableFeature.ts` 承接不可用功能错误模型；`stock/user/alerts/analysis/news/crawl/admin/watchlist` 按业务域拆分；`src/api/index.ts` 继续作为兼容门面导出旧接口。
- 已新增无第三方依赖的后端 coverage 门禁 `scripts/verify_backend_coverage.py`，当前核心模块语句覆盖率基线提升至 81.37%（3634/4466），默认防回退阈值已从 50% 经 60% 抬升到 70%，并接入 `make test-cov`、CI 与 `scripts/verify_delivery.py`；本轮已将 `unittest discover` 纳入 trace wrapper 并新增门禁脚本自测，避免测试发现阶段导入漏采。
- 已新增前端 API 门面兼容测试 `frontend/web/scripts/api-compat.mjs` 与 `npm run test:api-compat`，覆盖 `@/api` 默认导出、基础工具导出和各业务 API 对象导出，并接入 `make lint`、CI 与交付验证。
- 已新增前端数据质量工具契约测试 `frontend/web/scripts/data-quality.mjs` 与 `npm run test:data-quality`，覆盖 `pickDataQuality`、`qualityWarnings`、`formatConfidence`、采集状态格式化和风险标签；并将 `DataQualityPanel` 的风险标签逻辑抽到 `qualityRiskTags`，修复 `confidence: 0` 被误判为空导致 0% 置信度不展示的问题，已接入 `make lint`、CI、ops readiness preflight 与交付验证。
- 已新增 AI 分析数据装配 helper 单测与 fallback 风控表达单测，覆盖 symbol 清洗、公开资料日期解析、K 线指标、涨跌幅兜底、财报估值来源补齐、风险灯、异动提示、批量错误项和数据来源归因。
- 已新增技术指标引擎单测，覆盖 MA/EMA/BOLL/KDJ/RSI/MACD、成交量均线和 `compute_all` 指标路由，保护技术评分底座。
- 已新增共享数据校验与来源归因单测，覆盖 OHLC 过滤、交易日连续性、价格异常波动、`full_validate` 汇总、symbol/email 校验、来源新鲜度分桶、引用去重和数值主张核查告警。
- 已扩展前端浏览器 smoke 的 `/alerts` 关键路径，mock 有状态 `/api/v1/alerts**` 流程，覆盖预警列表渲染、“立即检查”、创建规则、禁用规则与删除规则。
- 已新增财报 ETL 单测，覆盖公告清洗/保存、财报数值清洗、三表合并计算、空数据、幂等 rowcount 计数与异常 rollback/reraise。
- 已新增 AI 客户端与模型路由单测，覆盖 base URL 规范化、响应解析、provider 路由、错误包装、成本估算、健康检查缓存/probe、角色放行、候选排序、fallback 与错误聚合。
- 已新增行业事件影响分析单测，覆盖空新闻降级、主题规则匹配、正负方向、证据 scope、无行业时按个股名匹配、市场新闻过滤去重与 limit。
- 已新增财务分析与新闻情绪引擎单测，覆盖杜邦分解、Piotroski F-Score、Altman Z-Score、PE/PB Band、健康汇总、新闻历史基准、来源权重、时效影响与加权主导情绪；并修复“近 N 天无新闻”提示未插入天数的问题。
- 已新增推荐引擎质量单测，覆盖候选加载过滤/去重、fallback 来源标记、数据质量评分、风险灯扣分、D 级数据降级、异常降级与并发评估过滤。
- 已新增 AI 分析服务契约与追问/状态单测，覆盖模型列表角色过滤、健康状态、配额重置、缓存命中、成功审计、缓存写入、模型失败本地降级、错误 usage log、追问配额/模型/角色拒绝、追问合规清洗、免责声明去重、本地 fallback、分析就绪度与 crawl status 边界。
- 已新增 AI 客户端质量边界、auth 边界、config 边界、shared contract、resilience 与 model router health 单测，覆盖 provider 路由、OpenAI 响应解析、AI key / JWT / production settings、ORM 模型约束、HTTP exception helpers、熔断状态流转与模型健康缓存/探测路径。
- 已新增共享观测/审计/采集状态单测，覆盖 metrics 中间件、readiness 聚合、DB/Redis/ClickHouse 健康探测、审计日志截断/匿名跳过/错误吞吐，以及 crawl status 记录与 payload 序列化。
- 已新增 shared cache/auth/security 质量单测，覆盖内存/Redis 缓存读写与失效、缓存装饰器、Redis 初始化降级、角色鉴权、可选用户解析、配额重置/耗尽、AI Key 加解密、JWT 与 bcrypt 72 字节边界。
- 已新增评分计算质量单测，覆盖动量钳制、RSI 技术阈值、估值年线分段、PE/PB 边界、质量趋势、F-Score、情绪评分状态/钳制与 `to_rating` 等级映射。
- 已新增 AI 分析数据源单测，覆盖 `get_stock_data` 编排、synthetic quote、行情降级、公开资料多来源路径、K 线 clickhouse/secondary/unavailable 路径与财报估值来源边界。
- 已新增新闻 ETL、评分数据源、K 线服务、ContextBuilder 与模型健康调度质量单测，覆盖新闻清洗/情绪/保存失败回滚、评分数据源多源降级与资金流熔断、K 线周/月聚合与 fallback、上下文数据质量/就绪度、模型健康 scheduler start/stop/check_once 异常边界。
- 已新增 audit/resilience、source attribution、PromptBuilder 与 CI/部署演练记录渲染质量单测，覆盖审计截断/匿名/异常吞吐、熔断半开恢复、来源块/事实核查边界、PromptBuilder 格式化/模板/长文本截断/丰富数据拼装以及演练记录文件输出。
- 已新增 CI/部署演练记录校验质量单测，覆盖完整通过记录、空值/占位符、非通过结论、skipped/failure/cancelled/not-applicable 结果、告警演练 `send=false`、缺失必填行、转义管道符和 CLI 退出码。
- 已新增告警演练记录与 ops drill archive 校验质量单测，覆盖 send=true/status=both/HTTP 2xx、firing/resolved 到达确认、敏感 webhook URL 泄露拦截、双 artifact 缺失、子记录失败透传、嵌套 artifact 目录和 CLI 退出码。
- 已新增告警演练预填记录与 ops drill archive 准备脚本单测，覆盖 dry-run/send 预填、HTTP 响应脱敏、workflow 单步生成 artifact、标准目录生成、重复记录拒绝、force 重建和 CLI 错误码。
- 已新增 ops drill archive 封存脚本单测，覆盖校验成功写入 `validation.txt`、`manifest.json`、`manifest.sha256`、`.sealed`、zip 包与 zip sha256，raw/completed 敏感信息拦截、重复封存拒绝、校验失败不写封存产物、`--verify` 复验、`--verify-package` 封存包复验、`--summary-json` 成功/失败机器可读输出、summary 路径防污染护栏、CLI 成功/内容失败/运行失败返回码。
- 已新增 ops drill archive smoke 单测，覆盖默认自动清理、`--keep` 保留样例归档、CLI 成功输出和 summary 文件状态。
- 已新增 ops drill readiness preflight `scripts/ops/verify_ops_drill_readiness.py`，静态核对 workflow、compose、ops 脚本、runbook 和可选生产 env 必填项；已接入 GitHub Actions `verify` job 与 `scripts/verify_delivery.py`，支持 `--env-file` 与 `--summary-json`，summary JSON 继续作为封存包外的 sidecar。
- 已新增并接入密钥卫生门禁 `scripts/verify_secret_hygiene.py`：静态扫描生产 env 模板、生产 compose、GitHub Actions 和 ops runbook，拦截危险默认密码、真实 webhook URL、生产 secret fallback 和模板中 real-looking secret；GitHub Actions `verify` job、`scripts/verify_delivery.py`、`make secret-hygiene` 与 README 均已暴露入口，治理测试会保护该门禁必须早于后端编译和单测执行。
- 已补充生成/运行时文件的安全清理脚本与入口：`scripts/cleanup_runtime_artifacts.py` 默认 dry-run 预览，`make clean-runtime-apply` / `--apply` 显式确认后才会删除；新增 `backend/tests/test_cleanup_runtime_artifacts.py` 覆盖 dry-run、apply、越界拒绝和 CLI 行为，避免手工递归清理误伤源码或业务配置。
- 本轮进一步加固 ops 演练链路：`scripts/ops/validate_ci_deployment_drill_record.py` 现在会在通过结论下强制拦截有阻塞项或不一致的跟进字段，`scripts/ops/validate_ops_drill_archive.py` 会交叉校验 CI/告警两份记录的 run URL、receiver 和 send mode，`scripts/ops/prepare_ops_drill_archive.py` 也拒绝在未显式给出归档名时使用 `unknown` 版本号。
- 本轮验证通过：`python -m unittest backend.tests.test_validate_ci_deployment_drill_record backend.tests.test_validate_ops_drill_archive backend.tests.test_prepare_ops_drill_archive`、`python scripts/ops/verify_ops_drill_readiness.py`、`python -m unittest backend.tests.test_ops_production_contract backend.tests.test_repo_governance backend.tests.test_verify_ops_drill_readiness`、`python scripts/ops/ops_drill_archive_smoke.py`、`python scripts/verify_delivery.py`；完整 coverage 门禁内后端单测共 607 个通过，coverage 门禁为 81.37%。本轮已执行 `python scripts/cleanup_runtime_artifacts.py --apply` 清理 25 个运行产物路径，并用 dry-run 确认剩余运行产物为 0。
### 仍未完成
- 代码侧已完成 PG/CH integration、Alert Webhook Drill、CI/部署演练记录模板、渲染脚本、CI artifact 自动留痕、告警记录预填与校验、ops drill readiness preflight、标准归档包准备脚本、双 artifact 归档目录校验，以及带 `manifest.json`/`.sealed`/zip/sha256 的归档封存包生成；剩余 1 项不属于本地代码可直接完成：需要在真实 GitHub Actions/部署环境执行一次完整演练，发布窗口前先运行 `scripts/ops/verify_ops_drill_readiness.py --env-file .env.production`，再用 `scripts/ops/prepare_ops_drill_archive.py` 生成归档包、补全 `completed/` 下两份记录，最后用 `scripts/ops/finalize_ops_drill_archive.py <archive-dir>` 封存并归档正式演练证据。

## 九、本轮数据闭环修复（2026-05-08）

- 已补股票主数据同步闭环：新增 `scripts/sync_stock_master.py`，通过数据源降级链拉取沪深 A 股主数据并按 6 位代码 upsert；新增 `StockMasterETL`，默认不删除用户、自选股、预警或旧股票记录，只有显式 `--deactivate-missing` 才会停用源端缺失股票。
- 已将股票主数据同步接入 data-crawler 调度任务 `collect_stock_master`，工作日 08:30 自动刷新主数据；EastMoney 分页接口短断时会降级到 AKShare。
- 已完成本地 SQLite 主数据恢复：当前 `stocks` 表活跃股票数为 5247；每日观察接口验证为 `candidate_source=db`、`count=10`、`candidate_count=50`、`scored_count=40`，不再依赖开发兜底候选。
- 已加固生产态候选策略：生产环境候选池为空时返回 `unavailable`，候选不足时只使用数据库真实候选并返回明确 warning，绝不自动混入开发兜底数据。

> 以上结论基于目录结构与少量关键文件抽样，落地前建议针对每一项再做一次代码级核对。
