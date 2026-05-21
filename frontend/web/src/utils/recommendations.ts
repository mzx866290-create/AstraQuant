import type { TagProps } from 'element-plus'

export type RatingLevel = 'A' | 'B' | 'C' | string

export interface ScoreBreakdownItem {
  key: string
  label: string
  delta: number | string
  status?: string
  message?: string
  source?: string
  features?: RecommendationCapitalFlowFeatures
}

export interface RecommendationCapitalFlowFeatures {
  source?: string
  signal?: string
  status?: string
  latest_date?: string | null
  latest_main_inflow?: number | null
  main_inflow_3d?: number | null
  main_inflow_5d?: number | null
  positive_days?: number
  sample_size?: number
  updated_at?: string
  snapshot_date?: string | null
  warnings?: string[]
}

export interface StrategyWeightedFactor {
  factor?: string
  dimension?: string
  delta?: number | string
  weight?: number | null
  neutral_weight?: number
  multiplier?: number
  weighted_delta?: number
  label?: string
}

export interface StrategyScoreBlending {
  base_weight?: number | null
  weighted_weight?: number | null
  multiplier_min?: number | null
  multiplier_max?: number | null
  anchor?: number | null
}

export interface RiskVetoItem {
  key?: string
  type?: string
  severity?: string
  detail?: string
  score_delta?: number | string | null
  handling?: string
}

export type ReviewOffset = 'T+1' | 'T+5' | 'T+20'

export interface ReviewResultItem {
  review_date?: string
  close_price?: number | string | null
  return_pct?: number | null
  falsification_triggered?: boolean
  risk_signal_valid?: boolean
}

export interface ReviewSummary {
  latest_snapshot_date?: string
  strategy_id?: string
  base_price?: number | string | null
  reviews?: Partial<Record<ReviewOffset, ReviewResultItem | null>>
}

export interface RecentReviewsResponse {
  status: string
  items?: Record<string, ReviewSummary>
  missing_symbols?: string[]
}

export interface RecommendationItem {
  symbol: string
  name?: string
  market?: string
  sector?: string
  strategy_id?: string
  market_regime?: string
  pe_ttm?: number | string | null
  pb?: number | string | null
  total_mv?: number | string | null
  industry_themes?: string[]
  updated_at?: string
  snapshot_date?: string | null
  candidate_source?: string
  source?: string
  warnings?: string[]
  review_summary?: ReviewSummary
  review_unavailable?: boolean
  score?: number
  base_score?: number | null
  strategy_score?: number | null
  strategy_score_delta?: number | null
  strategy_score_blending?: StrategyScoreBlending
  strategy_weighted_factors?: StrategyWeightedFactor[]
  strategy_filter_result?: {
    passed?: boolean
    reasons?: string[]
    warnings?: string[]
    [key: string]: unknown
  }
  rating?: {
    level?: RatingLevel
    text?: string
  }
  price?: number | string
  change_pct?: number | string
  lot_cost?: number | string
  reasons?: string[]
  risk_flags?: string[]
  score_breakdown?: ScoreBreakdownItem[]
  capital_flow_features?: RecommendationCapitalFlowFeatures
  capital_flow_status?: string
  data_grade?: {
    grade?: string
    label?: string
    analysis_scope?: string
    warnings?: string[]
  }
  data_source_summary?: Record<string, string>
  evidence_chain?: Array<{
    factor?: string
    dimension?: string
    label?: string
    value?: unknown
    threshold?: string
    source?: string
    freshness?: string
    confidence?: string
    impact?: number
    direction?: string
    explanation?: string
    strategy_id?: string
  }>
  theme_validation?: {
    status?: string
    theme_heat?: {
      level?: string
      themes?: string[]
      evidence?: Array<{
        title?: string
        source?: string
        date?: string
      }>
    }
    chain_position?: {
      stage?: string
      sector?: string
      reason?: string
    }
    business_relevance?: {
      level?: string
      reason?: string
    }
    verification?: {
      level?: string
      signals?: string[]
      evidence?: Array<{
        type?: string
        title?: string
        source?: string
        date?: string
        matched?: string
      }>
    }
    concept_risk?: {
      level?: string
      warnings?: string[]
    }
    strategy_id?: string
  }
  bull_case?: Array<{
    factor?: string
    argument?: string
    strength?: string
  }>
  bear_case?: Array<{
    factor?: string
    argument?: string
    strength?: string
  }>
  key_disagreement?: Array<{
    topic?: string
    bull_view?: string
    bear_view?: string
  }>
  falsification?: Array<{
    condition?: string
  }>
  veto_result?: {
    passed?: boolean
    level?: string
    veto_reason?: string | null
    vetoes?: RiskVetoItem[]
    warnings?: RiskVetoItem[]
  }
  summary_text?: string | null
  // 分层与观察动作（次日作战台）
  tier?: 'A' | 'B' | 'C' | null
  tier_reason?: string | null
  priority_score?: number | null
  observation_action?: string | null
  observation_bucket?: string | null
  observation_bucket_label?: string | null
  trigger_condition?: string | null
  invalidation_condition?: string | null
  risk_warning?: string | null
  chase_high_penalty?: {
    original_score?: number
    penalized_score?: number
    multiplier?: number
    reason?: string
  } | null
}

export interface RecommendationsResponse {
  recommendations?: RecommendationItem[]
  status?: string
  candidate_source?: string
  warnings?: string[]
  market?: string
  count?: number
  candidate_count?: number
  candidate_universe_count?: number
  scored_count?: number
  max_candidates?: number
  concurrency?: number
  market_regime?: {
    regime?: string
    confidence?: string
    signals?: Array<{
      indicator?: string
      value?: string
      detail?: string
    }>
    suggested_strategies?: string[]
  }
  active_strategy?: {
    id?: string
    name?: string
    selection_mode?: string
    selection_reason?: string
    engine_strategy?: string
  }
  selection?: {
    mode?: string
    rotation_date?: string
    universe_count?: number
    evaluated_count?: number
  }
  initial_full_scan?: {
    enabled?: boolean
    used?: boolean
    status?: string
    scanned_count?: number
    universe_count?: number
    cap?: number
    next_mode?: string
  }
  method?: {
    name?: string
    description?: string
    strategy?: string
    strategy_label?: string
  }
  phase?: string
  pipeline_status?: string
  disclaimer?: string
  cache_hit?: boolean
  updated_at?: string
  data_date?: string | null
  data_date_note?: string
  target_date?: string | null
  target_date_note?: string
  pool_phase?: string
  pool_phase_label?: string
  pool_phase_message?: string
  pool_recovery?: boolean
  pool_recovery_reason?: string
  news_enriched_count?: number
  pool_summary?: {
    pool_style?: string
    recommended_strategy?: string
    biggest_risk?: string
    tier_counts?: { A?: number; B?: number; C?: number }
    action_counts?: Record<string, number>
    highlight_symbols?: Array<{ symbol: string; name: string; action: string }>
  }
}

export type RecommendationTrustLevel = 'stable' | 'warning' | 'blocked'

export interface RecommendationTrustState {
  level: RecommendationTrustLevel
  label: string
  message: string
  reasons: string[]
  actionable: boolean
}

export interface RetailRiskHint {
  level: 'low' | 'medium' | 'high'
  label: string
  message: string
}

export function ratingTag(level?: string): TagProps['type'] {
  if (level === 'A') return 'success'
  if (level === 'B') return 'primary'
  if (level === 'C') return 'warning'
  return 'info'
}

export function tierTag(tier?: string | null): TagProps['type'] {
  if (tier === 'A') return 'success'
  if (tier === 'B') return 'primary'
  if (tier === 'C') return 'info'
  return 'info'
}

export function tierLabel(tier?: string | null): string {
  if (tier === 'A') return 'A档｜优先观察'
  if (tier === 'B') return 'B档｜条件观察'
  if (tier === 'C') return 'C档｜低优先级'
  return '待分层'
}

export function observationActionTag(action?: string | null): TagProps['type'] {
  if (action === '回踩承接') return 'success'
  if (action === '放量突破') return 'warning'
  if (action === '缩量企稳') return 'primary'
  if (action === '只看不追') return 'info'
  if (action === '消息验证') return 'warning'
  return 'info'
}

export function scoreReferenceText(score?: number | null): string {
  const value = Number(score)
  if (!Number.isFinite(value)) return '暂无评分'
  if (value >= 60) return '强烈关注'
  if (value >= 50) return '值得观察'
  if (value >= 40) return '一般观察'
  return '谨慎观察'
}

export function scoreReferenceDetail(score?: number | null): string {
  const value = Number(score)
  if (!Number.isFinite(value)) return '评分不足，先看数据完整性。'
  if (value >= 60) return '60分以上：信号较强，但仍需等风险确认。'
  if (value >= 50) return '50-60分：值得观察，不等于适合买入。'
  if (value >= 40) return '40-50分：信号一般，适合继续跟踪。'
  return '40分以下：优先排查风险和数据质量。'
}

export function scoreTagType(score?: number | null): TagProps['type'] {
  const value = Number(score)
  if (!Number.isFinite(value)) return 'info'
  if (value >= 60) return 'success'
  if (value >= 50) return 'primary'
  if (value >= 40) return 'warning'
  return 'danger'
}

const BREAKDOWN_PLAIN_LABELS: Record<string, string> = {
  capital_flow: '资金流配合',
  volume_price: '量价配合',
  technical: '技术位置',
  continuity: '走势连续性',
  attention: '市场关注度',
  intensity: '异动强度',
  valuation: '估值位置',
  quality: '基本面质量',
  momentum: '动量表现',
}

export function recommendationPlainReason(row: RecommendationItem): string {
  const positives = topBreakdown(row)
    .filter((item) => Number(item.delta) > 0)
    .slice(0, 3)
    .map((item) => BREAKDOWN_PLAIN_LABELS[item.key] || item.label)
  const unique = Array.from(new Set(positives))
  if (unique.length >= 2) return `${unique.join('、')}表现较好，系统把它列入每日观察池。`
  if (unique.length === 1) return `${unique[0]}是主要入选线索，适合继续核查走势和风险。`
  if (row.bull_case?.[0]?.argument) return row.bull_case[0].argument
  return '当前有观察信号，但强度不突出，建议先作为跟踪线索。'
}

export function recommendationRiskHint(row: RecommendationItem): RetailRiskHint {
  const hardVeto = row.veto_result?.passed === false || row.veto_result?.level === 'hard'
  const warnings = recommendationRowWarnings(row)
  const change = Number(row.change_pct)
  const bearText = row.bear_case?.[0]?.argument || ''
  const vetoText = row.veto_result?.veto_reason || row.veto_result?.warnings?.[0]?.detail || ''

  if (hardVeto) {
    return {
      level: 'high',
      label: '高风险',
      message: vetoText || '风险规则已经触发否决，暂不适合直接跟进。',
    }
  }

  if (Number.isFinite(change) && change >= 8) {
    return {
      level: 'high',
      label: '注意追高',
      message: `当日涨幅已达 ${change.toFixed(2)}%，短线追高风险偏高。`,
    }
  }

  if (warnings.length || row.veto_result?.level === 'soft' || (row.veto_result?.warnings || []).length) {
    return {
      level: 'medium',
      label: '风险适中',
      message: warnings[0] || vetoText || '存在软性风险提示，先观察支撑和成交量是否延续。',
    }
  }

  if (bearText) {
    return {
      level: 'medium',
      label: '风险适中',
      message: bearText,
    }
  }

  return {
    level: 'low',
    label: '风险较低',
    message: '暂未触发明显风险否决，仍需控制仓位并跟踪走势变化。',
  }
}

export function riskHintTagType(hint: RetailRiskHint): TagProps['type'] {
  if (hint.level === 'high') return 'danger'
  if (hint.level === 'medium') return 'warning'
  return 'success'
}

export function topBreakdown(row: Pick<RecommendationItem, 'score_breakdown'>) {
  const items = Array.isArray(row.score_breakdown) ? row.score_breakdown : []
  return items
    .filter((item) => item.key !== 'base' && (item.key === 'capital_flow' || Number(item.delta) !== 0))
    .sort((a, b) => {
      if (a.key === 'capital_flow') return -1
      if (b.key === 'capital_flow') return 1
      return Math.abs(Number(b.delta || 0)) - Math.abs(Number(a.delta || 0))
    })
    .slice(0, 4)
}

export function capitalFlowLabel(row: Pick<RecommendationItem, 'capital_flow_status' | 'capital_flow_features'>): string {
  const signal = row.capital_flow_status || row.capital_flow_features?.signal
  if (signal === 'confirming') return '资金确认'
  if (signal === 'contradicting') return '资金背离'
  if (signal === 'neutral') return '资金中性'
  if (signal === 'unavailable') return '资金缺失'
  return '资金待验'
}

export function capitalFlowTagType(row: Pick<RecommendationItem, 'capital_flow_status' | 'capital_flow_features'>): TagProps['type'] {
  const signal = row.capital_flow_status || row.capital_flow_features?.signal
  if (signal === 'confirming') return 'success'
  if (signal === 'contradicting') return 'warning'
  if (signal === 'neutral') return 'info'
  return 'info'
}

export function capitalFlowSummary(row: Pick<RecommendationItem, 'capital_flow_features'>): string {
  const features = row.capital_flow_features
  if (!features) return ''
  const latest = Number(features.latest_main_inflow)
  const rolling = Number(features.main_inflow_3d)
  if (!Number.isFinite(latest) || !Number.isFinite(rolling)) return capitalFlowWarningText(row)
  const latestDate = features.latest_date ? `${features.latest_date} ` : ''
  const sample = features.sample_size ? ` · 样本${features.sample_size}日` : ''
  return `${latestDate}最新 ${formatMoneyFlow(latest)} / 3日 ${formatMoneyFlow(rolling)}${sample}`
}

export function capitalFlowWarningText(row: Pick<RecommendationItem, 'capital_flow_features'>): string {
  const warning = row.capital_flow_features?.warnings?.[0]
  const mapping: Record<string, string> = {
    akshare_money_flow_empty: 'AKShare暂无资金流数据',
    akshare_money_flow_disabled: '资金流验证已关闭',
    akshare_money_flow_source_error: 'AKShare资金流源不可用',
    akshare_money_flow_partial_schema: '资金流字段不完整',
  }
  return warning ? mapping[warning] || warning : ''
}

export function capitalFlowSourceText(row: Pick<RecommendationItem, 'capital_flow_features'>): string {
  const features = row.capital_flow_features
  if (!features) return ''
  const source = features.source || 'akshare'
  const updated = features.updated_at ? ` · ${String(features.updated_at).slice(0, 16).replace('T', ' ')}` : ''
  return `${source}${updated}`
}

function formatMoneyFlow(value: number): string {
  const abs = Math.abs(value)
  const sign = value > 0 ? '+' : value < 0 ? '-' : ''
  if (abs >= 100_000_000) return `${sign}${(abs / 100_000_000).toFixed(2)}亿`
  if (abs >= 10_000) return `${sign}${(abs / 10_000).toFixed(0)}万`
  return `${sign}${abs.toFixed(0)}`
}

export function breakdownType(item: ScoreBreakdownItem): TagProps['type'] {
  const delta = Number(item?.delta)
  if (delta > 0) return 'success'
  if (delta < 0) return 'warning'
  return 'info'
}

export function dataGradeTag(grade?: string): TagProps['type'] {
  if (grade === 'A') return 'success'
  if (grade === 'B') return 'primary'
  if (grade === 'C') return 'warning'
  return 'danger'
}

export function candidateSourceLabel(source?: string) {
  if (source === 'fallback') return '开发兜底'
  if (source === 'mixed') return '数据库+开发兜底'
  if (source === 'db') return '数据库候选'
  return source || '未知来源'
}

export function isFallbackCandidate(row: Pick<RecommendationItem, 'candidate_source' | 'source'>, metaSource?: string) {
  return row.candidate_source === 'fallback' || row.source === 'fallback' || (metaSource === 'fallback' && !row.candidate_source && !row.source)
}

export function recommendationTrustState(meta: RecommendationsResponse | null | undefined): RecommendationTrustState {
  if (!meta) {
    return {
      level: 'warning',
      label: '等待数据',
      message: '尚未拿到观察池元数据，先不要把当前页面解读为有效筛选结果。',
      reasons: [],
      actionable: false,
    }
  }

  if (meta.status === 'unavailable') {
    return {
      level: 'blocked',
      label: '不可用',
      message: '数据库候选池为空，系统没有生成真实候选结果。',
      reasons: meta.warnings || [],
      actionable: false,
    }
  }

  if (meta.candidate_source === 'fallback') {
    return {
      level: 'blocked',
      label: '调试数据',
      message: '当前使用开发兜底候选池，仅能验证界面流程，不能代表真实市场筛选。',
      reasons: meta.warnings || [],
      actionable: false,
    }
  }

  if (meta.candidate_source === 'mixed') {
    return {
      level: 'warning',
      label: '混合候选',
      message: '数据库候选池偏小，系统已用开发兜底候选补足；真实数据库候选与兜底候选已在单行标明。',
      reasons: meta.warnings || [],
      actionable: true,
    }
  }

  const warnings = meta.warnings || []
  if (warnings.length > 0 || Number(meta.scored_count || 0) <= 0) {
    return {
      level: 'warning',
      label: '需复核',
      message: warnings[0] || '有效评分数量不足，仅适合继续核查数据链路。',
      reasons: warnings.slice(0, 3),
      actionable: true,
    }
  }

  return {
    level: 'stable',
    label: '可观察',
    message: '候选来自数据库与规则评分，仍只适合作为进一步研究线索。',
    reasons: [],
    actionable: true,
  }
}

export function recommendationActionBlockedReason(
  row: Pick<RecommendationItem, 'candidate_source' | 'source'>,
  meta: RecommendationsResponse | null | undefined,
) {
  if (meta?.status === 'unavailable') {
    return '候选池不可用，暂无法添加'
  }
  if (isFallbackCandidate(row, meta?.candidate_source)) {
    return '开发兜底候选仅用于界面调试，不能直接加入自选'
  }
  return ''
}

export function recommendationEmptyReason(meta: RecommendationsResponse | null | undefined) {
  if (!meta) return '请先确认分析服务已启动，或点击刷新重新计算。'
  if (meta.status === 'unavailable') return '数据库候选池为空，系统没有生成真实候选结果。'
  if (meta.candidate_source === 'fallback') return '当前只有开发兜底候选池，仅用于调试展示。'
  if (meta.candidate_source === 'mixed') return '数据库候选池偏小，已用开发兜底候选补足，但当前没有通过评分的结果。'
  return (meta.warnings || [])[0] || '请先确认分析服务已启动，或点击刷新重新计算。'
}

export function recommendationRowWarnings(row: RecommendationItem, metaSource?: string) {
  const warnings = Array.isArray(row.warnings) ? [...row.warnings] : []
  if (isFallbackCandidate(row, metaSource)) warnings.unshift('开发兜底候选')
  if (row.data_grade?.grade && row.data_grade.grade !== 'A') warnings.push(`数据等级 ${row.data_grade.grade}：${row.data_grade.label || '未说明'}`)
  if (row.data_grade?.grade && row.data_grade.grade !== 'A' && row.data_grade?.analysis_scope) warnings.push(row.data_grade.analysis_scope)
  if (Array.isArray(row.data_grade?.warnings)) warnings.push(...row.data_grade.warnings)
  if (Array.isArray(row.veto_result?.warnings)) warnings.push(...row.veto_result.warnings.map((item) => item.detail || item.type || '').filter(Boolean))
  return Array.from(new Set(warnings.filter(Boolean)))
}

export function strategyLabel(id?: string) {
  const mapping: Record<string, string> = {
    auto: '自动策略',
    retail_small: '小而美观察',
    value_quality: '价值质量',
    growth_momentum: '成长动量',
    reversal_watch: '反转观察',
    event_driven: '事件驱动',
    dividend_defensive: '红利防御',
    quality: '质量优先',
  }
  return mapping[id || ''] || id || '未选择'
}

export function regimeLabel(regime?: string) {
  const mapping: Record<string, string> = {
    strong_trend: '强趋势',
    range_bound: '震荡市',
    weak_market: '弱市场',
  }
  return mapping[regime || ''] || regime || '未知'
}

export function regimeTagType(regime?: string): TagProps['type'] {
  if (regime === 'strong_trend') return 'success'
  if (regime === 'weak_market') return 'danger'
  return 'warning'
}

export function vetoTagType(veto?: RecommendationItem['veto_result']): TagProps['type'] {
  if (!veto) return 'info'
  if (veto.passed === false || veto.level === 'hard') return 'danger'
  if ((veto.warnings || []).length || veto.level === 'soft') return 'warning'
  return 'success'
}

export function vetoLabel(veto?: RecommendationItem['veto_result']) {
  if (!veto) return '未校验'
  if (veto.passed === false || veto.level === 'hard') return '已否决'
  if ((veto.warnings || []).length || veto.level === 'soft') return '软警告'
  return '已通过'
}

export function vetoDetailItems(veto?: RecommendationItem['veto_result']) {
  return [...(veto?.vetoes || []), ...(veto?.warnings || [])]
}

export function evidenceTopItems(row: RecommendationItem, limit = 4) {
  const items = Array.isArray(row.evidence_chain) ? row.evidence_chain : []
  return items
    .filter((item) => item.factor !== 'base')
    .sort((a, b) => Math.abs(Number(b.impact || 0)) - Math.abs(Number(a.impact || 0)))
    .slice(0, limit)
}

export function evidenceType(item: NonNullable<RecommendationItem['evidence_chain']>[number]): TagProps['type'] {
  const impact = Number(item?.impact)
  if (impact > 0) return 'success'
  if (impact < 0) return 'warning'
  return 'info'
}

export function evidenceValueText(value: unknown) {
  if (value == null) return 'N/A'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export function resolveRecentReviewStrategy(uiStrategy?: string, activeStrategyId?: string) {
  if (uiStrategy === 'auto' && activeStrategyId && activeStrategyId !== 'auto') {
    return activeStrategyId
  }
  return uiStrategy || 'auto'
}
