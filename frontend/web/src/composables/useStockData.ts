/**
 * 股票数据获取 Composable
 * 封装行情/K线/搜索等API调用
 */
import { ref } from 'vue'
import { stockApi } from '@/api'
import type { DataQualityItem } from '@/utils/dataQuality'

export interface KLineItem {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  change_pct?: number
  turnover_rate?: number
  amplitude?: number
}

export interface QuoteData {
  symbol: string
  name: string
  price: number
  change: number
  change_pct: number
  high: number
  low: number
  open: number
  volume: number
  turnover: number
  turnover_rate: number
  pe_ttm: number
  total_mv: number
  circ_mv: number
  up_limit: number
  down_limit: number
  timestamp: string
  source: string
  data_quality?: DataQualityItem
}

export interface StockSearchItem {
  symbol: string
  name: string
  market?: string
  sector?: string
}

interface KLineResponse {
  data?: KLineItem[]
  indicators?: Record<string, number[]>
  source?: string
  data_quality?: DataQualityItem
}

interface StockSearchResponse {
  results?: StockSearchItem[]
}

interface ApiErrorLike {
  message?: string
}

export function useStockData() {
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchKLine(
    symbol: string,
    period: string = '1d',
    _indicators: string[] = []
  ): Promise<{
    data: KLineItem[]
    indicators: Record<string, number[]>
    source: string
    data_quality: DataQualityItem | null
  }> {
    loading.value = true
    error.value = null
    try {
      const res = await stockApi.getKline<KLineResponse>(symbol, period, 200)
      return {
        data: res.data || [],
        indicators: res.indicators || {},
        source: res.source || res.data_quality?.source || 'unknown',
        data_quality: res.data_quality || null,
      }
    } catch (e) {
      error.value = (e as ApiErrorLike).message || '获取K线数据失败'
      if (import.meta.env.DEV && import.meta.env.VITE_ALLOW_MOCK_KLINE === 'true') {
        return generateMockKLine()
      }
      return {
        data: [],
        indicators: {},
        source: 'unavailable',
        data_quality: {
          source: 'unavailable',
          updated_at: new Date().toISOString(),
          freshness: 'error',
          confidence: 'low',
          is_fallback: true,
          warnings: [error.value || '获取K线数据失败'],
        },
      }
    } finally {
      loading.value = false
    }
  }

  async function fetchQuote(symbol: string): Promise<QuoteData | null> {
    loading.value = true
    error.value = null
    try {
      const res = await stockApi.getQuote<QuoteData>(symbol)
      return res
    } catch (e) {
      error.value = (e as ApiErrorLike).message || '获取行情失败'
      return null
    } finally {
      loading.value = false
    }
  }

  async function searchStocks(query: string): Promise<StockSearchItem[]> {
    loading.value = true
    try {
      const res = await stockApi.searchStocks<StockSearchResponse>(query)
      return res.results || []
    } catch {
      return []
    } finally {
      loading.value = false
    }
  }

  return {
    loading,
    error,
    fetchKLine,
    fetchQuote,
    searchStocks
  }
}

/**
 * 生成模拟K线数据（开发调试用）
 */
function generateMockKLine(count: number = 120): {
  data: KLineItem[]
  indicators: Record<string, number[]>
  source: string
  data_quality: DataQualityItem
} {
  const data: KLineItem[] = []
  let price = 1700
  const now = new Date()

  for (let i = count - 1; i >= 0; i--) {
    const date = new Date(now)
    date.setDate(date.getDate() - i)
    // 跳过周末
    if (date.getDay() === 0 || date.getDay() === 6) continue

    const change = (Math.random() - 0.48) * 30
    const open = price
    const close = +(price + change).toFixed(2)
    const high = +(Math.max(open, close) + Math.random() * 15).toFixed(2)
    const low = +(Math.min(open, close) - Math.random() * 15).toFixed(2)
    const volume = Math.floor(Math.random() * 5000000 + 1000000)

    data.push({
      date: date.toISOString().slice(0, 10),
      open,
      high,
      low,
      close,
      volume,
      change_pct: +(change / price * 100).toFixed(2),
      turnover_rate: +(Math.random() * 2).toFixed(2),
      amplitude: +((high - low) / open * 100).toFixed(2),
    })
    price = close
  }

  return {
    data,
    indicators: {},
    source: 'mock',
    data_quality: {
      source: 'mock',
      updated_at: new Date().toISOString(),
      freshness: 'generated',
      confidence: 'low',
      is_fallback: true,
      warnings: ['仅开发环境模拟K线，不能作为交易或研究依据'],
    },
  }
}
