# 股票分析业务逻辑升级实施方案

> 目标：把当前“候选池 + 固定规则评分 + 风险灯 + AI总结”的链路，升级为“市场环境判断 + 策略选择 + 个股证据链 + 多空反驳 + 风险否决 + 复盘闭环”的研究逻辑系统。
>
> 原则：先做最能提升决策质量的外层编排，不急着推翻现有评分引擎。

---

## 1. 当前项目现状

结合现有代码，当前推荐链路已经具备以下基础能力：

- 接口入口：`backend/services/analysis_service/api/v1/scoring.py`
- 推荐核心：`backend/services/analysis_service/engine/recommendation_engine.py`
- 候选池：数据库轮转抽样 + 开发兜底候选
- 单股打分：`_score_daily_candidate`
- 分数拆解：`_build_score_breakdown`
- 风险提醒：`ai_analysis_fallbacks.build_risk_lights`
- 前端承接：`frontend/web/src/views/Recommendations.vue`

现阶段的主要问题不是“没有评分”，而是“缺少研究上下文”：

1. 没有市场环境层，同一套策略在不同市况下硬跑。
2. 策略只有 `retail_small` / `quality` 两档，业务语义不够清晰。
3. `score_breakdown` 能解释分数，但还不是标准化证据链。
4. 风险灯存在，但没有“一票否决”机制。
5. 没有“看多/看空/证伪条件”的反驳结构。
6. 没有把当日判断沉淀成可复盘的研究快照。

所以这次升级建议采用“外层编排增强，内核渐进改造”的方式，而不是直接重写 `recommendation_engine.py`。

---

## 2. 目标架构

### 2.1 升级前

```text
/batch/recommend
  -> scoring.py
  -> recommendation_engine.py
  -> score / score_breakdown / risk_flags
```

### 2.2 升级后

```text
/batch/recommend
  -> scoring.py
  -> research_pipeline.py
     -> market_regime.py
     -> strategy_config.py
     -> recommendation_engine.py
     -> evidence_chain.py
     -> debate_engine.py
     -> risk_veto.py
     -> review_tracker.py（异步落快照）
```

### 2.3 模块职责

| 模块 | 文件建议 | 职责 |
|------|------|------|
| 市场环境 | `engine/market_regime.py` | 判断强趋势 / 震荡 / 弱市 |
| 策略配置 | `engine/strategy_config.py` | 加载策略包、自动策略选择 |
| 研究编排 | `engine/research_pipeline.py` | 串联推荐全流程 |
| 证据链 | `engine/evidence_chain.py` | 将打分项结构化为研究证据 |
| 多空反驳 | `engine/debate_engine.py` | 生成 bull / bear / falsification |
| 风险否决 | `engine/risk_veto.py` | 执行 HARD / SOFT 风险规则 |
| 复盘追踪 | `engine/review_tracker.py` | 保存快照并生成 T+1 / T+5 / T+20 复盘 |

---

## 3. 实施原则

### 3.1 不推翻现有评分引擎

本次不建议一开始重写：

- `_evaluate_daily_candidate`
- `_score_daily_candidate`
- `_build_score_breakdown`

原因很简单：这些逻辑已经与现有前端、测试、候选池、缓存策略耦合。更稳妥的做法是：

1. 先把它们当成“个股基础评分内核”保留。
2. 在外层加市场环境、策略包、风险否决和证据链。
3. 之后再逐步把内部硬编码规则迁到策略配置。

### 3.2 编排层优先于算法细化

先解决“什么时候用什么逻辑”，再解决“每一分怎么打得更准”。

优先级顺序：

1. 市场环境
2. 策略包化
3. 风险否决
4. 证据链
5. 多空反驳
6. 复盘闭环

### 3.3 以兼容现有接口为前提

`/batch/recommend` 应继续向前兼容：

- 旧字段保留
- 新字段增量扩展
- 默认不返回过重的证据链和多空反驳明细，避免前端和响应体立刻膨胀

---

## 4. 第一阶段：补市场环境层

### 4.1 业务目标

先回答“今天适合什么风格”，再回答“今天看什么股票”。

目标输出：

```json
{
  "regime": "strong_trend",
  "confidence": "medium",
  "signals": [
    {
      "indicator": "hs300_vs_ma20",
      "value": "above",
      "detail": "沪深300位于MA20上方"
    }
  ],
  "suggested_strategies": ["growth_momentum", "event_driven"]
}
```

### 4.2 判定框架

建议先做三态即可：

| 状态 | 判定重点 | 策略倾向 |
|------|------|------|
| `strong_trend` | 指数站上中短均线，宽度改善，风险偏好上升 | 成长、动量、主题 |
| `range_bound` | 指数横盘，宽度中性，量能反复 | 小盘观察、价值质量 |
| `weak_market` | 指数弱于均线，宽度差，风险偏好下降 | 防守、红利、风险控制 |

### 4.3 数据来源方案

现状问题：

- `backend/services/market_service/app/api/v1/index_market.py` 当前不可直接复用为生产级输入。

建议分两层：

1. 第一版降级实现
   - 仅使用已有指数 K 线数据或可复用的行情抓取能力
   - 优先做趋势判断
   - 宽度与风险偏好不足时，降低 `confidence`
2. 第二版增强实现
   - 补市场宽度
   - 补涨跌停、创新高/新低、成交额环比

### 4.4 工程实现建议

新增文件：

- `backend/services/analysis_service/engine/market_regime.py`

核心接口建议：

```python
def detect_market_regime(as_of: date | None = None) -> dict:
    ...
```

返回字段建议：

| 字段 | 含义 |
|------|------|
| `regime` | 市场状态 |
| `confidence` | 置信度 |
| `signals` | 判定信号 |
| `suggested_strategies` | 推荐策略列表 |
| `data_quality` | 数据是否完整 |
| `updated_at` | 计算时间 |

### 4.5 缓存策略

市场环境是低频数据，建议使用“按日缓存”：

- cache category 可沿用 `daily_recommendations`
- key 形如：`market_regime:v1:{date}:{env}`

这样不会为每次推荐请求重复计算。

---

## 5. 第二阶段：策略包化

### 5.1 当前问题

当前 `strategy` 只有：

- `retail_small`
- `quality`

这在接口上够用，但在业务语义上不够。建议直接升级成标准策略包体系。

### 5.2 策略包列表

| 策略ID | 核心逻辑 | 默认适配市况 |
|------|------|------|
| `retail_small` | 单手成本友好、小中盘、数据质量优先 | `range_bound` |
| `value_quality` | 低估值、ROE/现金流稳定 | `weak_market` |
| `growth_momentum` | 收入利润增长 + 趋势向上 | `strong_trend` |
| `reversal_watch` | 超跌修复，基本面未继续恶化 | `weak_market` |
| `event_driven` | 主题/政策/公告催化 | `strong_trend`, `range_bound` |
| `dividend_defensive` | 高股息、低波动、防守 | `weak_market` |
| `auto` | 根据 `market_regime` 自动选主策略 | 所有 |

### 5.3 配置文件设计

建议用 JSON，避免额外依赖：

目录：

```text
backend/services/analysis_service/config/strategies/
  retail_small.json
  value_quality.json
  growth_momentum.json
  reversal_watch.json
  event_driven.json
  dividend_defensive.json
```

建议字段：

```json
{
  "id": "value_quality",
  "name": "价值质量",
  "preferred_regimes": ["weak_market", "range_bound"],
  "filters": {
    "price_range": [3, 80],
    "market_cap_range_yi": [50, 3000],
    "min_data_grade": "C"
  },
  "score_threshold": 58,
  "weights": {
    "retail_affordability": 0.00,
    "market_cap": 0.05,
    "data_quality": 0.10,
    "technical": 0.15,
    "valuation": 0.30,
    "financial": 0.30,
    "sentiment": 0.05,
    "industry_event": 0.05
  },
  "risk_policy": {
    "allow_soft_veto": true,
    "max_red_lights": 0,
    "max_yellow_lights": 2
  }
}
```

### 5.4 代码改造策略

建议分两步，不要一步到位重写评分：

1. 第一步：策略只影响“候选过滤 + 结果阈值 + 标签展示”
   - 最快落地
   - 对现有代码侵入最小
2. 第二步：策略逐步接管 `_score_daily_candidate` 内部权重
   - 把当前硬编码 if/else 迁到配置驱动

### 5.5 工程实现建议

新增文件：

- `backend/services/analysis_service/engine/strategy_config.py`

核心接口：

```python
def load_strategy(strategy_id: str) -> dict:
    ...

def resolve_strategy(requested: str, market_regime: dict) -> dict:
    ...
```

建议规则：

- 若 `strategy != auto`，优先使用用户指定
- 若 `strategy == auto`，优先取 `market_regime.suggested_strategies[0]`
- 若市场状态置信度低，默认回退 `retail_small`

---

## 6. 第三阶段：风险否决机制

### 6.1 目标

高分不等于可观察，某些风险必须直接阻断。

建议将现有 `risk_lights` 从“提示系统”升级为“两层风险控制”：

1. `risk_lights`：面向展示的风险灯
2. `risk_veto`：面向推荐准入的否决系统

### 6.2 否决等级

| 类型 | 处理方式 |
|------|------|
| `HARD` | 直接排除，不进入最终推荐 |
| `SOFT` | 保留，但打风险标签并降权 |

### 6.3 首批规则

#### HARD

- ST / *ST / 退市整理
- 数据等级 `D`
- 连续重大财务恶化
- 审计否定意见 / 无法表示意见
- 重大合规风险
- 关键价格或成交量数据缺失

#### SOFT

- 短期涨幅过大
- 近 5 日换手异常
- 经营现金流为负
- 行业主题存在但业务验证不足
- 风险灯存在多个黄灯

### 6.4 与现有代码的衔接

现有 `_evaluate_daily_candidate` 已有这段逻辑：

- `data_grade == D` 时直接 `return None`

建议保留这一层，同时把更完整的否决逻辑抽出为独立模块：

- `backend/services/analysis_service/engine/risk_veto.py`

核心接口：

```python
def evaluate_risk_veto(stock_data: dict, risk_lights: dict, strategy: dict) -> dict:
    ...
```

建议返回：

```json
{
  "passed": false,
  "level": "hard",
  "veto_reason": "st_risk",
  "vetoes": [
    {
      "type": "st_risk",
      "severity": "hard",
      "detail": "名称包含 ST"
    }
  ],
  "warnings": []
}
```

### 6.5 执行位置

建议在 `research_pipeline.py` 聚合阶段执行，而不是侵入候选池加载阶段。

原因：

- 候选评分结果仍可用于内部分析
- 但最终 `recommendations` 是否入池，由 `risk_veto` 最终裁决

---

## 7. 第四阶段：证据链升级

### 7.1 当前问题

当前 `score_breakdown` 结构类似：

```json
{
  "key": "valuation",
  "label": "估值",
  "delta": 10,
  "message": "PE 18.5，PB 2.3，估值字段可用"
}
```

它能解释“为什么加分”，但还不能支持：

- 溯源
- 新鲜度判断
- 置信度判断
- AI 报告复用
- 后续复盘验证

### 7.2 目标结构

建议新增 `evidence_chain` 字段，而不是替换 `score_breakdown`：

```json
{
  "factor": "valuation.pe_ttm",
  "dimension": "valuation",
  "value": 18.5,
  "threshold": "<=35",
  "impact": 10,
  "direction": "positive",
  "source": "financial_reports",
  "freshness": "latest_report",
  "confidence": "high",
  "explanation": "PE处于策略允许区间，估值不存在明显挤压"
}
```

### 7.3 设计原则

1. `score_breakdown` 继续保留给前端轻展示。
2. `evidence_chain` 用于深度研究和 AI 总结。
3. 两者共用同一批底层事实，避免出现解释不一致。

### 7.4 工程实现建议

新增文件：

- `backend/services/analysis_service/engine/evidence_chain.py`

核心接口：

```python
def build_evidence_chain(
    stock_data: dict,
    risk_lights: dict,
    strategy: dict,
    score_breakdown: list[dict] | None = None,
) -> list[dict]:
    ...
```

实现建议：

- 复用 `_build_score_breakdown` 已经判断过的条件
- 不要把规则写两遍
- 最好先把 `_build_score_breakdown` 的中间变量提炼为共享辅助函数

### 7.5 维度分组建议

建议至少覆盖：

- `market_context`
- `valuation`
- `technical`
- `financial_quality`
- `sentiment`
- `industry_theme`
- `risk`

---

## 8. 第五阶段：多空反驳与证伪条件

### 8.1 目标

让推荐结果从“单向加分结论”变成“可辩论结论”。

建议每只股票都输出：

- `bull_case`
- `bear_case`
- `key_disagreement`
- `falsification`

### 8.2 生成逻辑

不需要多 Agent，先做规则归类即可。

#### 看多来源

- 正向证据项
- 强催化主题
- 估值安全边际
- 财务改善

#### 看空来源

- 负向证据项
- 风险灯
- 估值过高
- 短期涨幅过快
- 现金流或盈利质量问题

#### 证伪条件

优先提炼能在未来验证的条件：

- 跌破关键均线
- 下期利润继续恶化
- 事件催化未兑现
- 经营现金流继续为负

### 8.3 工程实现建议

新增文件：

- `backend/services/analysis_service/engine/debate_engine.py`

核心接口：

```python
def build_debate_view(
    stock_data: dict,
    evidence_chain: list[dict],
    veto_result: dict,
    strategy: dict,
) -> dict:
    ...
```

返回结构建议：

```json
{
  "bull_case": [],
  "bear_case": [],
  "key_disagreement": [],
  "falsification": []
}
```

### 8.4 输出约束

控制信息量：

- 每类最多 3 条
- 文案尽量短
- 必须基于证据链，不允许空泛生成

---

## 9. 第六阶段：研究编排入口

### 9.1 入口职责

新增 `research_pipeline.py` 作为 `/batch/recommend` 的统一编排入口。

### 9.2 推荐链路

```text
1. detect_market_regime()
2. resolve_strategy()
3. load and score candidates（复用 recommendation_engine）
4. build evidence chain
5. build bull/bear/falsification
6. evaluate risk veto
7. filter / downgrade / annotate
8. aggregate response
9. async save research snapshot
```

### 9.3 核心接口建议

```python
async def run_research_pipeline(
    *,
    market: str,
    limit: int,
    strategy: str,
    force_refresh: bool,
    max_candidates: int,
    concurrency: int,
    include_evidence: bool = False,
    include_debate: bool = False,
) -> dict:
    ...
```

### 9.4 与现有 `scoring.py` 的改造边界

建议方式：

1. 保留当前缓存、限流、候选池参数校验逻辑。
2. 将核心结果生成部分从：
   - `_load_recommendation_candidates`
   - `_evaluate_candidates_parallel`
   - `sort + cut`
   改为调用 `run_research_pipeline(...)`
3. 第一版不要改动 `/score/{symbol}` 接口。

---

## 10. 接口契约升级

### 10.1 请求参数

建议 `/api/v1/analysis/score/batch/recommend` 升级为：

| 参数 | 默认值 | 说明 |
|------|------|------|
| `strategy` | `auto` | 支持 6 套策略 + 自动选择 |
| `include_evidence` | `false` | 是否返回证据链 |
| `include_debate` | `false` | 是否返回多空反驳 |
| `force_refresh` | `false` | 保持现状 |
| `limit` | `10` | 保持现状 |
| `max_candidates` | `200` | 保持现状 |

### 10.2 响应结构

建议在兼容旧字段基础上扩展：

```json
{
  "market": "ALL",
  "status": "ok",
  "market_regime": {
    "regime": "range_bound",
    "confidence": "medium",
    "signals": [],
    "suggested_strategies": ["retail_small", "value_quality"]
  },
  "active_strategy": {
    "id": "retail_small",
    "name": "小而美观察"
  },
  "recommendations": [
    {
      "symbol": "000001.SZ",
      "score": 71,
      "reasons": [],
      "risk_flags": [],
      "score_breakdown": [],
      "evidence_chain": [],
      "bull_case": [],
      "bear_case": [],
      "key_disagreement": [],
      "falsification": [],
      "veto_result": {
        "passed": true
      }
    }
  ]
}
```

### 10.3 兼容策略

前端兼容顺序建议：

1. 先支持 `market_regime` 和 `active_strategy`
2. 再支持 `evidence_chain`
3. 最后支持 `bull_case` / `bear_case` / `falsification`

这样不会一次把前端改动面拉得太大。

---

## 11. 前端适配建议

### 11.1 当前承载点

主要改造文件：

- `frontend/web/src/views/Recommendations.vue`
- `frontend/web/src/api/analysis.ts`
- `frontend/web/src/utils/recommendations.ts`

### 11.2 第一优先级

#### P0

- 顶部展示市场环境条
- 策略切换扩展到 7 项
- `auto` 模式下显示“当前自动策略”
- 风险否决状态标签

#### P1

- 展开面板增加 `evidence_chain`
- 增加“看多 / 看空 / 证伪条件”区域

### 11.3 前端文案建议

不要把页面包装成“买入建议”，而是明确定位为：

- `研究观察池`
- `证据链`
- `风险与证伪条件`

这与当前产品边界更一致，也更适合已有免责声明。

---

## 12. 第七阶段：复盘闭环

### 12.1 为什么必须做

没有复盘，前面的所有逻辑都只是“看起来合理”。

复盘的目标不是证明系统会预测，而是验证：

- 哪类市况下哪类策略更有效
- 哪些加分项是真有效因子
- 哪些风险灯能提前预警
- 哪些证伪条件最有价值

### 12.2 数据表设计

建议在 `backend/shared/models.py` 新增两张表。

#### `research_observations`

保存当天研究快照：

| 字段 | 含义 |
|------|------|
| `snapshot_date` | 快照日期 |
| `symbol` | 股票代码 |
| `strategy_id` | 使用策略 |
| `regime` | 市场环境 |
| `score` | 当天评分 |
| `score_breakdown_json` | 评分拆解快照 |
| `evidence_chain_json` | 证据链快照 |
| `debate_json` | bull/bear/falsification |
| `veto_result_json` | 风险裁决 |
| `close_price` | 当日收盘价 |

#### `observation_reviews`

保存复盘结果：

| 字段 | 含义 |
|------|------|
| `observation_id` | 对应研究快照 |
| `review_offset` | `T+1` / `T+5` / `T+20` |
| `review_date` | 复盘日期 |
| `close_price` | 复盘价 |
| `return_pct` | 收益率 |
| `max_drawdown_pct` | 最大回撤 |
| `falsification_triggered` | 是否触发证伪 |
| `risk_signal_valid` | 风险预警是否有效 |
| `notes` | 备注 |

### 12.3 工程实现建议

新增文件：

- `backend/services/analysis_service/engine/review_tracker.py`

建议能力：

1. `save_observation_snapshot(...)`
2. `run_scheduled_reviews(...)`
3. `build_review_report(...)`

### 12.4 触发方式

第一版建议简单实现：

- 每次 `/batch/recommend` 成功后，异步保存当日快照
- 通过脚本或定时任务运行 T+1 / T+5 / T+20 复盘

---

## 13. 分阶段排期建议

### 阶段 1：市场环境 + 策略包 + 风险否决

目标：让推荐具备“先看市况，再选策略，再控风险”的能力。

交付：

- `market_regime.py`
- `strategy_config.py`
- `risk_veto.py`
- `research_pipeline.py` 骨架
- `/batch/recommend?strategy=auto`

### 阶段 2：证据链 + 多空反驳

目标：让推荐结果能讲清楚“为什么看、为什么不看、什么条件下失效”。

交付：

- `evidence_chain.py`
- `debate_engine.py`
- 新响应字段
- 前端基础展示

### 阶段 3：复盘闭环

目标：把研究结果沉淀为可验证资产。

交付：

- 新数据表
- 快照落库
- T+1 / T+5 / T+20 复盘任务
- 首版策略有效性报表

---

## 14. 验收标准

### 14.1 业务验收

满足以下条件，说明升级方向成立：

1. 同一批候选股在不同 `market_regime` 下，所选策略和排序结果会发生合理变化。
2. 存在明显风险的个股，即使高分，也能被 `risk_veto` 排除或降级。
3. 每只推荐股都能给出可读、可验证的证据链。
4. 每只推荐股都能给出至少 1 条证伪条件。
5. 能沉淀并查询某日观察池快照。

### 14.2 工程验收

建议新增测试：

- `backend/tests/test_market_regime.py`
- `backend/tests/test_strategy_config.py`
- `backend/tests/test_risk_veto.py`
- `backend/tests/test_evidence_chain.py`
- `backend/tests/test_debate_engine.py`
- `backend/tests/test_research_pipeline.py`

同时补充前端契约测试，确保：

- `strategy=auto` 可正常展示
- `market_regime` 缺失时页面不崩
- `include_evidence=false` 时页面仍兼容旧返回

---

## 15. 关键风险与应对

### 15.1 最大风险：市场环境数据不完整

这是第一阶段最大风险。

应对方式：

- 第一版允许低置信度降级
- 不因宽度数据缺失阻断功能
- 先跑通“趋势判断 + auto策略”主链路

### 15.2 第二风险：策略配置和现有评分硬编码双轨

短期内这是可接受的。

应对方式：

- 明确第一版策略包只管“选择与约束”
- 第二版再逐步接管评分参数

### 15.3 第三风险：响应体膨胀

证据链和多空反驳会明显增加返回大小。

应对方式：

- 默认关闭 `include_evidence`
- 默认关闭 `include_debate`
- 前端按需拉取或折叠展示

---

## 16. 推荐落地顺序

如果按最小风险、最大收益推进，建议顺序如下：

1. 在 `scoring.py` 上方增加 `research_pipeline.py` 编排入口。
2. 先做 `market_regime.py` 和 `strategy_config.py`，打通 `strategy=auto`。
3. 再做 `risk_veto.py`，把“高分但明显危险”的情况拦住。
4. 然后做 `evidence_chain.py`，把分数变成证据。
5. 再做 `debate_engine.py`，把证据变成多空反驳。
6. 最后做 `review_tracker.py`，把研究结论沉淀为可复盘资产。

---

## 17. 最终结论

这次升级的关键，不是把评分规则写得更复杂，而是把系统能力从“打分”提升为“研究”。

从项目现状看，最合适的技术路径不是重写推荐引擎，而是：

- 保留现有 `recommendation_engine.py` 作为基础评分内核
- 在外层增加研究编排层
- 用市场环境、策略包、风险否决建立研究框架
- 用证据链、多空反驳、复盘闭环提升研究质量

这样可以在不破坏现有功能的前提下，逐步把项目从：

`股票评分工具`

升级为：

`A股研究逻辑系统`

---

## 18. 实施进度 / 剩余事项 / 验证命令

### 18.1 已完成

- `market_regime`
- `strategy_config`
- `research_pipeline`
- `risk_veto`
- `evidence_chain`
- `debate_engine`
- `review_tracker`
- `strategy scoring rules`
- `risk_policy`
- `score_blending`
- 前端推荐页研究视图：市场环境、策略选择、证据链、主题验证、多空反驳、风险裁决、复盘摘要。
- 推荐接口缓存隔离：`include_evidence/include_debate` 已进入缓存 key，避免轻量/完整响应互相污染。
- 前端推荐响应类型已补齐 `strategy_score_blending`、`veto_result` 策略处理字段、顶层 `count/method/phase/disclaimer` 等契约字段。
- 前端推荐契约自动化测试：覆盖 `strategy=auto` 默认请求、`include_evidence=false` 兼容、风险裁决详情、复盘摘要策略一致性与推荐工具函数。
- 复盘闭环 smoke：新增 `backend/scripts/review_smoke.py`，用内存假会话跑通快照保存、待复盘识别、T+1 复盘生成与报告聚合。
- 运维自检修复：`backend/scripts/daily_recommendations_self_check.py` 已更新到新的推荐引擎导入路径。
- 生产复盘 readiness：新增 `build_review_readiness()`、管理员接口 `/api/v1/admin/stats/review-readiness` 与 `backend/scripts/review_readiness_check.py`，用于检查真实环境表、快照、待复盘与报告状态。
- Admin 前端复盘 readiness 面板：`AdminStats.vue` 已展示复盘表状态、观察快照、复盘记录、待复盘数量与最新日期，方便运营侧确认复盘闭环。
- 生产复盘 runbook：新增 `docs/ops/research-review-runbook.md`，覆盖真实环境前置条件、推荐入库、待复盘执行、readiness、Admin UI 验收和排障。
- 交付验证门禁：`scripts/verify_delivery.py` 已纳入 `review_smoke.py` 与前端推荐契约测试。

### 18.2 剩余事项

- 生产端到端复盘验证：在真实数据库和行情服务上跑通推荐、快照沉淀、T+1 / T+5 / T+20 复盘与报告输出。
- 可选增强：如后续引入组件测试框架，再补 `Recommendations.vue` 的真实 DOM 交互测试。

### 18.3 验证命令

```bash
venv\Scripts\python.exe -m unittest backend.tests.test_market_regime backend.tests.test_strategy_config backend.tests.test_strategy_scoring backend.tests.test_risk_veto backend.tests.test_evidence_chain backend.tests.test_debate_engine backend.tests.test_research_pipeline
venv\Scripts\python.exe -m unittest backend.tests.test_scoring_recommendation_flags -v
venv\Scripts\python.exe -m unittest backend.tests.test_review_tracker backend.tests.test_review_scheduler -v
venv\Scripts\python.exe backend/scripts/daily_recommendations_self_check.py
venv\Scripts\python.exe backend/scripts/review_smoke.py
venv\Scripts\python.exe backend/scripts/review_readiness_check.py --date 2026-05-11
cd frontend/web && npm run test:recommendations-contract
cd frontend/web && npm run test:api-compat
cd frontend/web && npm run type-check
python scripts/verify_delivery.py
```
