export type MarketCode = 'SH' | 'SZ' | 'BJ'

export const marketLabels: Record<MarketCode, string> = {
  SH: '沪市',
  SZ: '深市',
  BJ: '北交所',
}

export function normalizeMarket(value?: string): MarketCode {
  const upper = (value || '').toUpperCase()
  if (upper === 'SH' || upper === 'SS') return 'SH'
  if (upper === 'BJ') return 'BJ'
  return 'SZ'
}

export function inferMarketFromCode(code: string): MarketCode {
  if (code.startsWith('4') || code.startsWith('8') || code.startsWith('920')) return 'BJ'
  if (code.startsWith('6') || code.startsWith('9') || code.startsWith('5')) return 'SH'
  return 'SZ'
}

export function parseStockSymbol(rawValue: string, fallback = '600519.SH'): { code: string; market: MarketCode } {
  const raw = (rawValue || fallback).trim().toUpperCase()
  const suffixed = raw.match(/^(\d{6})\.(SH|SZ|SS|BJ)$/)
  if (suffixed) {
    return { code: suffixed[1], market: normalizeMarket(suffixed[2]) }
  }

  const prefixed = raw.match(/^(SH|SZ|BJ)(\d{6})$/)
  if (prefixed) {
    return { code: prefixed[2], market: normalizeMarket(prefixed[1]) }
  }

  const code = raw.match(/\d{6}/)?.[0] || fallback.match(/\d{6}/)?.[0] || '600519'
  return { code, market: inferMarketFromCode(code) }
}

export function normalizeStockSymbol(rawValue: string, fallback = '600519.SH') {
  const parsed = parseStockSymbol(rawValue, fallback)
  return `${parsed.code}.${parsed.market}`
}

export function stockCode(rawValue: string, fallback = '600519.SH') {
  return parseStockSymbol(rawValue, fallback).code
}
