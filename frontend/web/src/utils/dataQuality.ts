export interface DataQualityItem {
  source?: string
  status?: string
  updated_at?: string
  freshness?: string
  confidence?: string | number
  is_fallback?: boolean
  warning?: string
  warnings?: string[]
}

export interface CrawlStatus {
  status?: string
  finished_at?: string
  error_message?: string
  saved?: number
  saved_count?: number
}

export interface ApiErrorLike {
  response?: {
    status?: number
    data?: {
      detail?: string
    }
  }
  message?: string
}

function hasQualityValue(value: unknown) {
  return value !== undefined && value !== null && value !== ''
}

export function pickDataQuality(dataQuality: Record<string, DataQualityItem> | DataQualityItem | null | undefined, key: string) {
  if (!dataQuality) return null
  const source = dataQuality as Record<string, DataQualityItem>
  const item = source[key] || dataQuality as DataQualityItem
  if (!item?.source && !item?.status && !item?.updated_at && !hasQualityValue(item?.confidence) && !item?.freshness && !item?.is_fallback && !item?.warning && !item?.warnings?.length) return null
  return item
}

export function qualityWarnings(item: DataQualityItem | null | undefined) {
  const warnings = Array.isArray(item?.warnings) ? item.warnings : []
  return item?.warning ? [item.warning, ...warnings] : warnings
}

export function qualityRiskTags(item: DataQualityItem | null | undefined) {
  if (!item) return []

  const tags: string[] = []
  const status = item.status || item.source || item.freshness
  if (item.is_fallback || status === 'fallback') tags.push('\u98ce\u9669\uff1a\u5f00\u53d1\u515c\u5e95\u6570\u636e')
  if (status === 'unavailable') tags.push('\u98ce\u9669\uff1a\u6570\u636e\u6e90\u4e0d\u53ef\u7528')
  if (status === 'empty') tags.push('\u98ce\u9669\uff1a\u6570\u636e\u4e3a\u7a7a')
  if (qualityWarnings(item).length) tags.push('\u98ce\u9669\uff1a\u5b58\u5728\u6570\u636e\u544a\u8b66')
  return Array.from(new Set(tags))
}

export function formatQualityTime(time?: string) {
  return time ? String(time).slice(0, 16).replace('T', ' ') : ''
}

export function formatConfidence(confidence?: string | number) {
  if (confidence === undefined || confidence === null || confidence === '') return ''
  if (typeof confidence === 'number') {
    return confidence <= 1 ? `${Math.round(confidence * 100)}%` : String(confidence)
  }
  return confidence
}

const crawlStatusText: Record<string, string> = {
  success: '采集成功',
  no_saved: '采集完成，但没有新增或更新数据',
  partial: '采集部分成功，仍有部分数据缺失',
  empty: '采集完成，但数据源返回为空',
  not_implemented: '当前采集能力尚未实现',
  empty_symbol_pool: '候选股票池为空，无法开始采集',
  error: '采集失败',
  unavailable: '采集服务或数据源不可用',
}

export function crawlStatusLevel(status: CrawlStatus | string | null | undefined) {
  const statusText = typeof status === 'string' ? status : status?.status
  if (statusText === 'success') return 'success'
  if (statusText === 'error' || statusText === 'unavailable') return 'error'
  if (statusText === 'no_saved' || statusText === 'partial' || statusText === 'empty' || statusText === 'empty_symbol_pool') return 'warning'
  if (statusText === 'not_implemented') return 'info'
  return 'info'
}

export function crawlStatusReason(status: CrawlStatus | null | undefined) {
  if (!status?.status) return ''
  if (status.status === 'error') return status.error_message || crawlStatusText.error
  return crawlStatusText[status.status] || `采集状态：${status.status}`
}

export function formatCrawlStatus(status: CrawlStatus | null | undefined, unit = '条') {
  if (!status) return ''
  const time = formatQualityTime(status.finished_at)
  const statusText = status.status || 'unknown'
  const readableStatus = crawlStatusReason(status) || '采集状态未知'
  const timeText = time ? ` · ${time}` : ''
  if (statusText === 'error') return `最近采集：${readableStatus}${timeText}`
  const saved = status.saved ?? status.saved_count ?? 0
  return `最近采集：${readableStatus}${timeText} · 保存/更新 ${saved} ${unit}`
}

export function formatCrawlError(error: ApiErrorLike, label: string) {
  if (error.response?.status === 401) return `请先登录后再采集${label}`
  if (error.response?.status === 403) return `当前账号没有采集${label}权限`
  return error.response?.data?.detail || error.message || `${label}采集失败`
}
