# AI 模型分析 + 管理后台 — 实施计划

> 为平台接入 AI 大语言模型（Claude / GPT / DeepSeek 等），让用户选择模型对当前股票进行智能分析；  
> 管理员通过后台界面管理模型配置、用户权限、使用统计和调用日志。

---

## 功能概览

```
┌──────────────────────────────────────────────────────────────┐
│                     前端 (Vue 3 + Element Plus)              │
│                                                              │
│  ┌─────────────────────┐    ┌──────────────────────────────┐ │
│  │ 用户端               │    │ 管理后台 (/admin)             │ │
│  │                     │    │                              │ │
│  │ StockDetail 页面     │    │ /admin/models   模型管理     │ │
│  │ ┌─────────────────┐ │    │ /admin/users    用户管理     │ │
│  │ │ AI 分析卡片      │ │    │ /admin/stats    使用统计     │ │
│  │ │ · 选择模型       │ │    │ /admin/logs     调用日志     │ │
│  │ │ · 输入问题       │ │    │                              │ │
│  │ │ · 查看分析报告   │ │    │ 功能:                        │ │
│  │ │ · 剩余额度显示   │ │    │ · 模型 CRUD + API Key 管理   │ │
│  │ └─────────────────┘ │    │ · 用户角色 + 配额管理        │ │
│  └─────────────────────┘    │ · 调用量/Token/费用统计      │ │
│                              │ · 调用日志查询 + 导出        │ │
│                              └──────────────────────────────┘ │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                   后端 API (FastAPI)                          │
│                                                              │
│  用户服务 (:8002)                                             │
│  ├── [修复] GET  /api/v1/auth/me          获取当前用户        │
│  ├── [新增] 认证中间件 get_current_user / require_admin       │
│  └── [修改] JWT payload 加入 role 字段                        │
│                                                              │
│  分析服务 (:8003)                                             │
│  ├── [新增] POST /api/v1/analysis/ai/analyze   AI 分析       │
│  ├── [新增] GET  /api/v1/analysis/ai/models    可用模型列表   │
│  ├── [新增] GET  /api/v1/analysis/ai/quota     用户配额查询   │
│  ├── [新增] CRUD /api/v1/admin/models          模型管理       │
│  ├── [新增] CRUD /api/v1/admin/users           用户管理       │
│  ├── [新增] GET  /api/v1/admin/stats           统计数据       │
│  └── [新增] GET  /api/v1/admin/logs            调用日志       │
└──────────────────────────┬───────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────┐
│                   数据库 (PostgreSQL / SQLite)                │
│                                                              │
│  [新增] ai_models       AI 模型配置 (名称/provider/key/参数) │
│  [新增] ai_usage_logs   调用日志 (用户/模型/token/费用/状态)  │
│  [新增] user_quotas     用户配额 (每日/每月限制与已用量)      │
│  [修改] users           新增 admin 默认账号                   │
└──────────────────────────────────────────────────────────────┘
```

---

## 实施步骤

### Step 1：新增数据库模型 + Pydantic Schema

**目标**：定义 3 张新表和对应的请求/响应 DTO

#### 1.1 新增 ORM 模型 (`backend/shared/models.py`)

| 模型 | 表名 | 核心字段 |
|------|------|----------|
| `AIModel` | `ai_models` | `name`, `provider`(openai/anthropic/deepseek/custom), `model_id`, `api_base_url`, `api_key_encrypted`, `description`, `config`(JSON), `is_active`, `sort_order`, `allowed_roles`, `created_by` |
| `AIUsageLog` | `ai_usage_logs` | `user_id`, `model_id`, `stock_symbol`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost`, `status`(success/error/timeout), `error_message`, `response_time_ms` |
| `UserQuota` | `user_quotas` | `user_id`(unique), `daily_limit`, `monthly_limit`, `daily_used`, `monthly_used`, `last_reset_daily`, `last_reset_monthly` |

#### 1.2 新增 Pydantic Schema (`backend/shared/schemas.py`)

| Schema | 用途 |
|--------|------|
| `AIModelCreate` / `AIModelUpdate` | 管理员创建/更新模型 |
| `AIModelResponse` | 管理员视角的完整模型信息 |
| `AIModelPublicResponse` | 用户视角的模型信息（隐藏 API Key 等敏感字段）|
| `AIAnalysisRequest` | 用户发起 AI 分析请求 (`model_id` + `symbol` + 可选 `question`) |
| `AIAnalysisResponse` | AI 分析结果 (Markdown 格式报告 + token 统计) |
| `AIUsageLogResponse` | 调用日志条目 |
| `UserQuotaResponse` / `UserQuotaUpdate` | 用户配额查询/管理员修改 |
| `AdminStatsResponse` | 统计面板数据 |
| `AdminUserResponse` / `AdminUserUpdate` | 管理员用户管理 |

#### 1.3 更新数据库初始化

| 文件 | 改动 |
|------|------|
| `infra/postgres/init.sql` | 新增 3 张表的 DDL + 索引 + 默认 admin 账号 |
| `init_sqlite.py` | 新增 admin 用户 (admin/admin123) + 默认配额数据 |

#### 涉及文件
```
backend/shared/models.py        ← 新增 3 个 class
backend/shared/schemas.py       ← 新增 ~12 个 Schema
infra/postgres/init.sql         ← 新增 3 张表 DDL
init_sqlite.py                  ← 新增 admin 用户 + 配额
```

---

### Step 2：修复认证中间件 + 角色权限守卫

**目标**：让整个系统具备可用的用户认证和角色权限控制

#### 2.1 修改 JWT 生成 (`backend/shared/security.py`)

```python
# 改动: create_access_token 的 payload 中加入 role
def create_access_token(data: dict, expires_delta=None):
    to_encode = data.copy()  # data 应包含 {"sub": user_id, "username": ..., "role": ...}
    ...
```

#### 2.2 新增认证依赖 (`backend/shared/auth.py` — 新文件)

```python
# get_current_user(token) → User       从 JWT 解析用户，查 DB 验证
# require_role(*roles)    → Depends    角色守卫装饰器
# require_admin           → Depends    管理员专用守卫
# require_active_user     → Depends    活跃用户守卫

# 每个依赖都通过 HTTP Header "Authorization: Bearer <token>" 获取 JWT
# 从 JWT 取 sub(user_id) 查数据库获取完整用户对象
```

#### 2.3 修复 `/auth/me` 端点 (`backend/services/user_service/app/api/v1/auth.py`)

```python
# 当前状态: 返回 501 "待接入认证中间件"
# 改为: 使用 get_current_user 依赖注入，返回真实的 UserResponse
@router.get("/me", response_model=UserResponse)
async def get_me(current_user = Depends(get_current_user), db = Depends(get_db)):
    return current_user
```

#### 2.4 修改登录端点，JWT 中加入 role

```python
# auth.py login 端点中
token_data = {"sub": str(user.id), "username": user.username, "role": user.role}
token = create_access_token(token_data)
```

#### 涉及文件
```
backend/shared/security.py                        ← 修改 JWT payload
backend/shared/auth.py                             ← 新建，认证+权限依赖
backend/services/user_service/app/api/v1/auth.py   ← 修复 /me, 登录加 role
```

---

### Step 3：管理员后台 API

**目标**：提供模型管理、用户管理、统计、日志 4 组 REST API

#### 3.1 模型管理 (`analysis_service/api/v1/admin_models.py` — 新文件)

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/admin/models` | 模型列表（含分页、筛选）|
| `POST` | `/api/v1/admin/models` | 创建模型（API Key 加密存储）|
| `PUT` | `/api/v1/admin/models/{id}` | 更新模型配置 |
| `DELETE` | `/api/v1/admin/models/{id}` | 删除模型 |
| `POST` | `/api/v1/admin/models/{id}/test` | 测试模型连通性（发送测试请求）|

> 所有端点需要 `require_admin` 守卫

**API Key 加密方案**：使用 Fernet 对称加密，密钥从环境变量 `AI_ENCRYPTION_KEY` 读取

#### 3.2 用户管理 (`analysis_service/api/v1/admin_users.py` — 新文件)

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/admin/users` | 用户列表（含配额信息、分页、搜索）|
| `PUT` | `/api/v1/admin/users/{id}` | 修改用户角色/状态 |
| `PUT` | `/api/v1/admin/users/{id}/quota` | 修改用户配额（每日/月上限）|
| `POST` | `/api/v1/admin/users/{id}/reset-quota` | 重置用户当前配额 |

#### 3.3 使用统计 (`analysis_service/api/v1/admin_stats.py` — 新文件)

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/admin/stats/overview` | 总览（用户数/模型数/调用量/Token/费用）|
| `GET` | `/api/v1/admin/stats/calls-by-day` | 按日统计调用量（折线图数据）|
| `GET` | `/api/v1/admin/stats/calls-by-model` | 按模型统计（饼图数据）|
| `GET` | `/api/v1/admin/stats/top-users` | 调用量 Top 用户 |
| `GET` | `/api/v1/admin/stats/cost-trend` | 费用趋势（按日/月）|

#### 3.4 调用日志 (`analysis_service/api/v1/admin_logs.py` — 新文件)

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/admin/logs` | 日志列表（分页 + 多条件筛选）|
| `GET` | `/api/v1/admin/logs/export` | 导出 CSV |

**筛选参数**：`user_id`, `model_id`, `status`, `stock_symbol`, `date_from`, `date_to`

#### 3.5 注册路由 (`analysis_service/app/main.py`)

```python
# 新增路由挂载
app.include_router(admin_models_router, prefix="/api/v1/admin/models")
app.include_router(admin_users_router, prefix="/api/v1/admin/users")
app.include_router(admin_stats_router, prefix="/api/v1/admin/stats")
app.include_router(admin_logs_router, prefix="/api/v1/admin/logs")
```

#### 3.6 分析服务接入数据库

当前 analysis_service 是无状态的（无 DB 依赖）。需要：
- `requirements.txt` 添加 `sqlalchemy`, `aiosqlite`/`psycopg2-binary`, `cryptography`
- `app/main.py` 添加数据库初始化 lifespan
- `docker-compose.yml` 给 analysis-service 添加 postgres/redis 依赖

#### 涉及文件
```
backend/services/analysis_service/api/v1/admin_models.py  ← 新建
backend/services/analysis_service/api/v1/admin_users.py   ← 新建
backend/services/analysis_service/api/v1/admin_stats.py   ← 新建
backend/services/analysis_service/api/v1/admin_logs.py    ← 新建
backend/services/analysis_service/app/main.py             ← 注册路由+DB初始化
backend/services/analysis_service/requirements.txt        ← 添加依赖
docker-compose.yml                                        ← analysis-service 加 DB 依赖
```

---

### Step 4：AI 分析 API（调用大模型 + 配额控制）

**目标**：用户选择模型，提交股票代码，后端调用 AI 大模型生成分析报告

#### 4.1 AI 调用客户端 (`analysis_service/engine/ai_client.py` — 新文件)

```python
class AIClient:
    """统一的 AI 模型调用客户端"""

    async def analyze(self, provider, model_id, api_key, api_base_url, config, prompt) -> dict:
        """
        根据 provider 路由到不同 SDK:
        - openai:    使用 openai SDK (兼容 GPT-4o / GPT-4-turbo 等)
        - anthropic: 使用 anthropic SDK (Claude 3.5/4 系列)
        - deepseek:  使用 openai SDK (兼容接口)
        - custom:    使用 openai SDK + 自定义 base_url

        返回: {content, prompt_tokens, completion_tokens, total_tokens}
        """
```

**Prompt 构造策略**：
```
系统提示:
  你是一位专业的 A 股市场分析师。请基于以下股票数据进行深度分析，
  用中文输出 Markdown 格式的分析报告。

用户提示:
  ## 股票信息
  - 代码: {symbol}
  - 名称: {name}
  - 最新价: {price}, 涨跌幅: {change_pct}%
  - 市盈率: {pe}, 市值: {market_cap}
  - 近期K线数据: {...}
  - 技术指标: MA/MACD/KDJ/RSI 等

  ## 分析要求
  {用户自定义问题 或 默认: "请进行综合分析，包括趋势研判、技术面、风险提示"}
```

#### 4.2 AI 分析端点 (`analysis_service/api/v1/ai_analysis.py` — 新文件)

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/v1/analysis/ai/models` | 获取当前用户可用的模型列表（按 role 过滤）|
| `GET` | `/api/v1/analysis/ai/quota` | 获取当前用户配额（剩余次数）|
| `POST` | `/api/v1/analysis/ai/analyze` | 发起 AI 分析 |

**`POST /analyze` 流程**：

```
1. 认证 → get_current_user
2. 配额检查 → 查 user_quotas 表，自动重置过期计数
3. 获取模型配置 → 查 ai_models 表，检查 is_active + allowed_roles
4. 获取股票数据 → 调用 market_service 获取行情+K线+指标
5. 构造 Prompt → 组装系统提示 + 股票数据 + 用户问题
6. 调用 AI → AIClient.analyze()
7. 记录日志 → 写入 ai_usage_logs
8. 更新配额 → daily_used++, monthly_used++
9. 返回结果 → AIAnalysisResponse (Markdown 报告)
```

**错误处理**：
- 配额超限 → 403 "今日/本月调用次数已用完"
- 模型不可用 → 404 "模型已禁用或不存在"
- AI 调用失败 → 500 记录错误日志，返回友好提示
- 超时 → 408 (默认 60 秒超时)

#### 4.3 依赖安装

```
# analysis_service/requirements.txt 新增
openai>=1.0.0        # GPT + DeepSeek + 兼容接口
anthropic>=0.30.0    # Claude 系列
cryptography>=41.0   # API Key 加密
httpx>=0.25.0        # 异步 HTTP
```

#### 涉及文件
```
backend/services/analysis_service/engine/ai_client.py     ← 新建，AI调用客户端
backend/services/analysis_service/api/v1/ai_analysis.py   ← 新建，用户端API
backend/services/analysis_service/app/main.py             ← 注册路由
backend/services/analysis_service/requirements.txt        ← 添加 openai/anthropic
```

---

### Step 5：前端管理后台页面

**目标**：管理员独立的后台界面，4 个管理页面 + 侧边栏布局

#### 5.1 管理后台布局 (`views/admin/AdminLayout.vue` — 新文件)

```
┌────────────────────────────────────────────┐
│  📈 股票分析平台 — 管理后台     [退出管理] │
├──────────┬─────────────────────────────────┤
│          │                                 │
│  侧边栏   │        主内容区                 │
│          │                                 │
│  📊 统计  │   <router-view />              │
│  🤖 模型  │                                 │
│  👥 用户  │                                 │
│  📋 日志  │                                 │
│          │                                 │
└──────────┴─────────────────────────────────┘
```

#### 5.2 模型管理页 (`views/admin/AdminModels.vue`)

| 功能 | 说明 |
|------|------|
| 模型列表 | 表格展示所有模型，含 provider 图标、状态开关、排序 |
| 新增模型 | 弹窗表单：名称、provider 选择、model_id、API Key、基础URL、描述、参数配置 |
| 编辑模型 | 同新增弹窗，API Key 显示为 `sk-****` 遮罩 |
| 删除模型 | 二次确认弹窗 |
| 测试连通 | 按钮发送测试请求，显示成功/失败 |
| 启用/禁用 | 表格行内 Switch 切换 |
| 角色权限 | 多选 Checkbox：free / premium / admin |

**UI 原型**：
```
┌─────────────────────────────────────────────────────────┐
│  AI 模型管理                          [+ 新增模型]      │
├─────────────────────────────────────────────────────────┤
│ 名称            │ 提供商   │ 模型ID          │ 状态 │ 操作 │
│ Claude 4 Sonnet │ Anthropic│ claude-sonnet.. │ ✅   │ ✏️🗑 │
│ GPT-4o          │ OpenAI   │ gpt-4o          │ ✅   │ ✏️🗑 │
│ DeepSeek V3     │ DeepSeek │ deepseek-chat   │ ⛔   │ ✏️🗑 │
└─────────────────────────────────────────────────────────┘
```

#### 5.3 用户管理页 (`views/admin/AdminUsers.vue`)

| 功能 | 说明 |
|------|------|
| 用户列表 | 表格：用户名、邮箱、角色(Tag)、状态、注册时间、今日/本月用量 |
| 搜索筛选 | 按用户名/邮箱搜索，按角色筛选 |
| 修改角色 | 下拉选择 free/premium/admin |
| 配额管理 | 弹窗修改每日/每月上限 |
| 重置配额 | 一键重置当日/当月已用次数 |
| 禁用账号 | Switch 切换 is_active |

**UI 原型**：
```
┌──────────────────────────────────────────────────────────────────┐
│  用户管理                    🔍 搜索用户...  [角色▼] [状态▼]     │
├──────────────────────────────────────────────────────────────────┤
│ 用户名  │ 邮箱            │ 角色    │ 今日用量  │ 月用量   │ 操作  │
│ test   │ test@mail.com   │ 🟢免费  │ 3/10    │ 15/100  │ ✏️   │
│ vip01  │ vip@mail.com    │ 🟡会员  │ 8/50    │ 120/500 │ ✏️   │
│ admin  │ admin@mail.com  │ 🔴管理  │ 2/∞     │ 5/∞     │ ✏️   │
└──────────────────────────────────────────────────────────────────┘
```

#### 5.4 使用统计页 (`views/admin/AdminStats.vue`)

```
┌────────────────────────────────────────────────────────┐
│  使用统计                                [今日] [本月] │
│                                                        │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐        │
│  │ 128  │ │ 45   │ │  5   │ │ 3    │ │$2.35 │        │
│  │总用户 │ │今日活跃│ │模型数 │ │启用中 │ │本月费用│        │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘        │
│                                                        │
│  ┌────────────────────┐  ┌────────────────────┐       │
│  │  每日调用量趋势      │  │  各模型调用占比      │       │
│  │  (ECharts 折线图)    │  │  (ECharts 饼图)     │       │
│  │       ╱╲             │  │    ┌───┐            │       │
│  │     ╱    ╲           │  │   ╱ GPT ╲           │       │
│  │   ╱      ╲          │  │  │Claude│           │       │
│  └────────────────────┘  └────────────────────┘       │
│                                                        │
│  ┌────────────────────┐                               │
│  │  Top 用户排行        │                               │
│  │  1. test    45次    │                               │
│  │  2. vip01   32次    │                               │
│  │  3. user03  18次    │                               │
│  └────────────────────┘                               │
└────────────────────────────────────────────────────────┘
```

#### 5.5 调用日志页 (`views/admin/AdminLogs.vue`)

| 功能 | 说明 |
|------|------|
| 日志表格 | 时间、用户、模型、股票、Token数、费用、状态、耗时 |
| 筛选栏 | 用户/模型/状态/日期范围 多条件组合筛选 |
| 详情弹窗 | 点击行查看完整错误信息 |
| 导出 CSV | 按当前筛选条件导出 |
| 分页 | 每页 20 条，前后翻页 |

#### 5.6 路由与权限

```typescript
// router/index.ts 新增路由
{
  path: '/admin',
  component: AdminLayout,
  meta: { requiresAuth: true, requiresAdmin: true },
  children: [
    { path: '',        redirect: '/admin/stats' },
    { path: 'stats',   component: AdminStats },
    { path: 'models',  component: AdminModels },
    { path: 'users',   component: AdminUsers },
    { path: 'logs',    component: AdminLogs },
  ]
}

// 全局前置守卫 router.beforeEach
// - requiresAuth: 检查 localStorage token
// - requiresAdmin: 解析 JWT 检查 role === 'admin'
```

#### 5.7 导航入口

- `App.vue` 顶部导航栏：当用户 role 为 admin 时，显示「管理后台」入口链接
- 管理后台左上角：「返回前台」链接

#### 涉及文件
```
frontend/web/src/views/admin/AdminLayout.vue    ← 新建，管理后台布局
frontend/web/src/views/admin/AdminStats.vue     ← 新建，使用统计
frontend/web/src/views/admin/AdminModels.vue    ← 新建，模型管理
frontend/web/src/views/admin/AdminUsers.vue     ← 新建，用户管理
frontend/web/src/views/admin/AdminLogs.vue      ← 新建，调用日志
frontend/web/src/router/index.ts               ← 添加 admin 路由+守卫
frontend/web/src/api/index.ts                  ← 添加 adminApi 模块
frontend/web/src/App.vue                       ← 导航栏添加管理入口
frontend/web/src/stores/user.ts                ← 新建 Pinia store 管理用户状态
```

---

### Step 6：前端用户端 AI 分析组件

**目标**：在股票详情页添加 AI 分析卡片，用户可选择模型进行分析

#### 6.1 AI 分析卡片组件 (`components/ai/AIAnalysisCard.vue` — 新文件)

```
┌─────────────────────────────────────────────────┐
│  🤖 AI 智能分析                 剩余: 7/10 今日 │
│                                                  │
│  选择模型: [Claude 4 Sonnet    ▼]               │
│                                                  │
│  分析问题: [请分析该股票近期走势和买卖点_______]  │
│                                                  │
│              [开始分析]                           │
│                                                  │
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  │
│                                                  │
│  分析结果 (Markdown 渲染):                       │
│                                                  │
│  ## 贵州茅台 (600519) 综合分析                   │
│                                                  │
│  ### 趋势研判                                    │
│  当前股价处于中期上升通道，MA5 上穿 MA20 形成     │
│  金叉信号，MACD 红柱持续放大...                   │
│                                                  │
│  ### 技术面                                      │
│  - RSI(14): 62.5 — 中性偏强                     │
│  - KDJ: 金叉，J值回升至 75                      │
│  - 布林带: 股价运行在中轨上方                     │
│                                                  │
│  ### 风险提示                                    │
│  ⚠️ 短期涨幅较大，注意回调风险...                │
│                                                  │
│  ───────────────────────────                     │
│  📊 Claude 4 Sonnet · 用时 3.2s · 1,245 tokens  │
│  ⚠️ 以上分析仅供参考，不构成投资建议              │
└─────────────────────────────────────────────────┘
```

#### 6.2 组件功能

| 功能 | 说明 |
|------|------|
| 模型选择 | `el-select` 下拉选择可用模型，显示 provider 图标 |
| 问题输入 | `el-input` 文本框，可选，placeholder 为默认问题 |
| 开始分析 | 按钮 + loading 态，禁用重复提交 |
| 结果渲染 | 使用 `v-html` + markdown-it 渲染 Markdown |
| 配额显示 | 右上角显示今日剩余 / 月剩余 |
| 未登录态 | 显示「请先登录」提示 + 登录按钮 |
| 配额用完 | 显示升级提示 (free → premium) |
| 流式输出 | 可选: 使用 SSE 逐字输出分析结果（增强体验）|

#### 6.3 集成到 StockDetail.vue

```vue
<!-- StockDetail.vue 底部新增 AI 分析卡片 -->
<el-row :gutter="20" style="margin-top: 20px">
  <el-col :span="24">
    <AIAnalysisCard :symbol="symbol" :quote="quoteData" />
  </el-col>
</el-row>
```

#### 6.4 Markdown 渲染依赖

```bash
cd frontend/web
npm install markdown-it
npm install -D @types/markdown-it
```

#### 涉及文件
```
frontend/web/src/components/ai/AIAnalysisCard.vue   ← 新建，AI分析卡片
frontend/web/src/views/StockDetail.vue              ← 集成 AI 分析组件
frontend/web/src/api/index.ts                       ← 添加 analysisApi.aiAnalyze 等
frontend/web/package.json                           ← 添加 markdown-it
```

---

## Vite 代理更新

```typescript
// vite.config.ts 新增 admin 代理
'/api/v1/admin': {
  target: 'http://localhost:8003',
  changeOrigin: true
}
// 注: /api/v1/analysis 已有代理到 8003，ai/* 路由无需额外配置
```

---

## 配额策略默认值

| 角色 | 每日上限 | 每月上限 | 说明 |
|------|---------|---------|------|
| `free` | 10 | 100 | 免费用户 |
| `premium` | 50 | 500 | 付费会员 |
| `admin` | 1000 | 10000 | 管理员（基本无限制）|

> 管理员可在后台为任意用户自定义配额

---

## 环境变量新增

```bash
# .env.example 新增
AI_ENCRYPTION_KEY=your-fernet-key-here   # Fernet 对称加密密钥，用于加密 API Key
```

---

## 新增文件清单 (共 ~15 个文件)

### 后端 (7 个文件)
| 文件 | 说明 |
|------|------|
| `backend/shared/auth.py` | 认证中间件 + 角色守卫 |
| `backend/services/analysis_service/engine/ai_client.py` | AI 模型调用客户端 |
| `backend/services/analysis_service/api/v1/ai_analysis.py` | 用户 AI 分析 API |
| `backend/services/analysis_service/api/v1/admin_models.py` | 模型管理 API |
| `backend/services/analysis_service/api/v1/admin_users.py` | 用户管理 API |
| `backend/services/analysis_service/api/v1/admin_stats.py` | 统计 API |
| `backend/services/analysis_service/api/v1/admin_logs.py` | 日志 API |

### 前端 (7 个文件)
| 文件 | 说明 |
|------|------|
| `frontend/web/src/stores/user.ts` | Pinia 用户状态管理 |
| `frontend/web/src/views/admin/AdminLayout.vue` | 管理后台布局 |
| `frontend/web/src/views/admin/AdminStats.vue` | 统计面板 |
| `frontend/web/src/views/admin/AdminModels.vue` | 模型管理 |
| `frontend/web/src/views/admin/AdminUsers.vue` | 用户管理 |
| `frontend/web/src/views/admin/AdminLogs.vue` | 调用日志 |
| `frontend/web/src/components/ai/AIAnalysisCard.vue` | AI 分析卡片 |

### 修改文件 (~10 个文件)
| 文件 | 改动 |
|------|------|
| `backend/shared/models.py` | +3 ORM 模型 |
| `backend/shared/schemas.py` | +12 Pydantic Schema |
| `backend/shared/security.py` | JWT payload 加 role |
| `backend/services/user_service/app/api/v1/auth.py` | 修复 /me + 登录改动 |
| `backend/services/analysis_service/app/main.py` | 注册新路由 + DB 初始化 |
| `backend/services/analysis_service/requirements.txt` | 添加依赖 |
| `infra/postgres/init.sql` | +3 张表 DDL |
| `init_sqlite.py` | +admin 用户 + 配额 |
| `frontend/web/src/router/index.ts` | +admin 路由 + 守卫 |
| `frontend/web/src/api/index.ts` | +adminApi + aiApi |
| `frontend/web/src/App.vue` | +管理后台导航入口 |
| `frontend/web/src/views/StockDetail.vue` | +AI 分析组件 |
| `frontend/web/vite.config.ts` | +admin 代理 |
| `docker-compose.yml` | analysis-service 加 DB 依赖 |
| `.env.example` | +AI_ENCRYPTION_KEY |

---

## 实施顺序与依赖关系

```
Step 1: 数据库模型 + Schema
   │
   ▼
Step 2: 认证中间件 + 权限守卫
   │
   ├──────────────────┐
   ▼                  ▼
Step 3: 管理员API    Step 4: AI分析API
   │                  │
   ▼                  ▼
Step 5: 前端管理后台  Step 6: 前端AI分析组件
```

**预估工作量**：

| 步骤 | 预估时间 |
|------|---------|
| Step 1 | 0.5h |
| Step 2 | 1h |
| Step 3 | 2h |
| Step 4 | 2h |
| Step 5 | 3h |
| Step 6 | 1.5h |
| **合计** | **~10h** |

---

## 默认账号

| 用途 | 用户名 | 密码 | 角色 |
|------|--------|------|------|
| 普通测试 | `test` | `test123` | free |
| 管理后台 | `admin` | `admin123` | admin |
