import type { TagProps } from 'element-plus'

export type RatingLevel = 'A' | 'B' | 'C' | string

export interface ScoreBreakdownItem {
  key: string
  label: string
  delta: number | string
  status?: string
  message?: string
}

export interface RecommendationItem {
  symbol: string
  name?: string
  market?: string
  sector?: string
  candidate_source?: string
  source?: string
  warnings?: string[]
  score?: number
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
  data_grade?: {
    grade?: string
    label?: string
    analysis_scope?: string
    warnings?: string[]
  }
  data_source_summary?: Record<string, string>
}

export interface RecommendationsResponse {
  recommendations?: RecommendationItem[]
  status?: string
  candidate_source?: string
  warnings?: string[]
  candidate_count?: number
  scored_count?: number
  cache_hit?: boolean
  updated_at?: string
}

export type RecommendationTrustLevel = 'stable' | 'warning' | 'blocked'

export interface RecommendationTrustState {
  level: RecommendationTrustLevel
  label: string
  message: string
  reasons: string[]
  actionable: boolean
}

export function ratingTag(level?: string): TagProps['type'] {
  if (level === 'A') return 'success'
  if (level === 'B') return 'primary'
  if (level === 'C') return 'warning'
  return 'info'
}

export function topBreakdown(row: Pick<RecommendationItem, 'score_breakdown'>) {
  const items = Array.isArray(row.score_breakdown) ? row.score_breakdown : []
  return items
    .filter((item) => item.key !== 'base' && Number(item.delta) !== 0)
    .sort((a, b) => Math.abs(Number(b.delta || 0)) - Math.abs(Number(a.delta || 0)))
    .slice(0, 3)
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
  if (row.data_grade?.grade) warnings.push(`数据等级 ${row.data_grade.grade}：${row.data_grade.label || '未说明'}`)
  if (row.data_grade?.analysis_scope) warnings.push(row.data_grade.analysis_scope)
  if (Array.isArray(row.data_grade?.warnings)) warnings.push(...row.data_grade.warnings)
  return Array.from(new Set(warnings.filter(Boolean)))
}
