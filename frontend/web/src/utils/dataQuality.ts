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
  message?: string
  next_allowed_at?: string
  cooldown_seconds?: number
  saved?: number
  saved_count?: number
}

export interface ApiErrorLike {
  response?: {
    status?: number
    data?: {
      detail?: unknown
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
  return Array.from(new Set(item?.warning ? [item.warning, ...warnings] : warnings))
}

const profileInfoWarnings = new Set([
  'stock_sector_missing',
  'stock_list_date_missing',
  'stock_profile_public_source_fallback',
])

const emptyDataWarnings = new Set([
  'money_flow_empty',
  'no news available',
  'no announcements available',
  'no financial reports available',
  'no telegraph news available',
])

const informationalWarnings = new Set([
  ...profileInfoWarnings,
  ...emptyDataWarnings,
])

const riskWarningLabels: Record<string, string> = {
  kline_stale: '风险：K线数据过旧',
  quote_price_zero: '风险：行情价格为0',
  quote_trade_fields_missing_or_zero: '风险：行情交易字段缺失',
  quote_volume_zero_or_suspended: '风险：成交量为0，可能停牌',
}

export function formatQualityWarning(warning: string) {
  const mapping: Record<string, string> = {
    stock_name_missing: '股票名称暂缺',
    stock_sector_missing: '行业信息暂缺',
    stock_list_date_missing: '上市日期暂缺',
    stock_profile_public_source_fallback: '由公开行情源补充，部分公司资料可能缺失',
    kline_stale: 'K线数据过旧，请结合最新行情谨慎参考',
    quote_price_zero: '行情价格为0，可能暂不可用',
    quote_trade_fields_missing_or_zero: '开盘价、最高价或最低价缺失，行情可能处于停牌或无成交状态',
    quote_volume_zero_or_suspended: '成交量为0，可能停牌或暂无成交',
    money_flow_empty: '资金流数据暂不可用',
    'no news available': '暂无相关新闻数据',
    'no announcements available': '暂无公告数据',
    'no financial reports available': '暂无财报数据',
    'no telegraph news available': '暂无快讯数据',
  }
  return mapping[warning] || warning
}

export function qualityRiskTags(item: DataQualityItem | null | undefined) {
  if (!item) return []

  const tags: string[] = []
  const source = item.source?.toLowerCase() || ''
  const status = item.status?.toLowerCase() || ''
  const freshness = item.freshness?.toLowerCase() || ''
  const effectiveStatus = status || source || freshness
  const warnings = qualityWarnings(item)
  const isBenignEmpty = status === 'empty' || freshness === 'empty' || warnings.some((warning) => emptyDataWarnings.has(warning))
  const isPublicSourceFallback = item.is_fallback && ['akshare', 'eastmoney', 'eastmoney+tencent', 'tencent', 'sina-tencent'].some((value) => source.includes(value))
  const isDevelopmentFallback = !source || source === 'mock' || source === 'fallback' || source.includes('dev')
  if (((item.is_fallback && isDevelopmentFallback) || effectiveStatus === 'fallback') && !isPublicSourceFallback) tags.push('\u98ce\u9669\uff1a\u5f00\u53d1\u515c\u5e95\u6570\u636e')
  if (effectiveStatus === 'unavailable' && !isBenignEmpty) tags.push('\u98ce\u9669\uff1a\u6570\u636e\u6e90\u4e0d\u53ef\u7528')
  warnings.forEach((warning) => {
    if (riskWarningLabels[warning]) tags.push(riskWarningLabels[warning])
  })
  if (warnings.some((warning) => !informationalWarnings.has(warning) && !riskWarningLabels[warning])) tags.push('\u98ce\u9669\uff1a\u5b58\u5728\u6570\u636e\u544a\u8b66')
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

export function formatConfidenceLabel(confidence?: string | number) {
  const value = formatConfidence(confidence)
  const mapping: Record<string, string> = {
    high: '高',
    medium: '中',
    low: '低',
    unknown: '未知',
  }
  return mapping[value.toLowerCase()] || value
}

export function formatQualitySource(source?: string) {
  const mapping: Record<string, string> = {
    akshare: 'AKShare',
    'akshare-kline': 'AKShare 日K',
    cailianshe: '财联社',
    cninfo: '巨潮资讯',
    database: '本地数据库',
    eastmoney: '东方财富',
    'eastmoney-kline': '东方财富日K',
    'eastmoney-bj920-alias': '东方财富（920新代码）',
    'eastmoney-bj920-alias-stale': '东方财富（920新代码，过旧）',
    'eastmoney+tencent': '东方财富/腾讯行情',
    'financial_reports': '财报库',
    unavailable: '暂不可用',
    unknown: '未知',
    mock: '模拟数据',
    fallback: '降级数据',
    'live-news-chain': '多源实时新闻',
    'local-fallback': '本地兜底',
    'news-db': '本地新闻库',
    'sina-tencent': '新浪/腾讯行情',
    'sina-tencent-bj920-alias': '新浪/腾讯行情（920新代码）',
    'sina-tencent-bj920-alias-stale': '新浪/腾讯行情（920新代码，过旧）',
    'sina-tencent-stale': '新浪/腾讯行情（过旧）',
    'akshare-bj920-alias': 'AKShare（920新代码）',
    'akshare-bj920-alias-stale': 'AKShare（920新代码，过旧）',
    tencent: '腾讯行情',
  }
  const text = source?.trim()
  if (!text) return ''
  const key = text.toLowerCase()
  if (mapping[key]) return mapping[key]
  if (text.includes('+') || text.includes('/')) {
    return text
      .split(/[+/]/)
      .map((part) => mapping[part.trim().toLowerCase()] || part.trim())
      .filter(Boolean)
      .join('/')
  }
  return text
}

export function formatQualityStatus(status?: string) {
  const mapping: Record<string, string> = {
    ok: '正常',
    degraded: '降级',
    partial: '部分可用',
    fallback: '降级',
    unavailable: '不可用',
    empty: '暂无数据',
    error: '异常',
  }
  return status ? mapping[status.toLowerCase()] || status : ''
}

export function formatFreshness(freshness?: string) {
  const mapping: Record<string, string> = {
    error: '异常',
    generated: '模拟生成',
    profile: '基础资料',
    today: '今日',
    recent: '近期',
    realtime: '实时',
    'daily-kline': '日线降级',
    unavailable: '不可用',
    empty: '暂无数据',
    stale: '过旧',
  }
  return freshness ? mapping[freshness.toLowerCase()] || freshness : ''
}

const crawlStatusText: Record<string, string> = {
  success: '采集成功',
  no_saved: '采集完成，但没有新增或更新数据',
  partial: '采集部分成功，仍有部分数据缺失',
  empty: '采集完成，但数据源返回为空',
  fresh: '近期已更新，无需重复采集',
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
  if (statusText === 'fresh') return 'info'
  return 'info'
}

export function crawlStatusReason(status: CrawlStatus | null | undefined) {
  if (!status?.status) return ''
  if (status.status === 'fresh' && status.message) return status.message
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
  const detail = error.response?.data?.detail
  return typeof detail === 'string' && detail.trim() ? detail : error.message || `${label}采集失败`
}

export function readableApiError(error: unknown, fallback = '数据暂不可用') {
  const err = error as ApiErrorLike
  const status = err.response?.status
  const detail = err.response?.data?.detail

  if (status === 401) return '当前未登录或登录已过期，暂未展示真实数据'
  if (status === 403) return '当前账号没有查看该数据的权限'
  if (Array.isArray(detail)) {
    const validation = detail
      .map((item) => (typeof item === 'object' && item && 'msg' in item ? String(item.msg) : ''))
      .filter(Boolean)
      .join('；')
    if (validation) return validation
  }
  if (typeof detail === 'string' && detail.trim()) return detail
  if (status === 404) return '数据接口或标的暂未找到'
  if (status === 429) return '请求过于频繁，请稍后再试'
  if (status && status >= 500) return '数据服务暂时不可用，请稍后重试'
  if (!status) return '无法连接数据服务，请稍后重试'
  return err.message && !/^Request failed with status code/i.test(err.message) ? err.message : fallback
}
