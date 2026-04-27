/**
 * 股票数据获取 Composable
 * 封装行情/K线/搜索等API调用
 */
import { ref } from 'vue'
import { stockApi } from '@/api'

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
}

export function useStockData() {
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchKLine(
    symbol: string,
    period: string = '1d',
    indicators: string[] = []
  ): Promise<{
    data: KLineItem[]
    indicators: Record<string, number[]>
    source: string
  }> {
    loading.value = true
    error.value = null
    try {
      const res: any = await stockApi.getKline(symbol, period, 200)
      return {
        data: res.data || [],
        indicators: res.indicators || {},
        source: res.source || 'unknown'
      }
    } catch (e: any) {
      error.value = e.message || '获取K线数据失败'
      // 返回模拟数据用于开发调试
      return generateMockKLine()
    } finally {
      loading.value = false
    }
  }

  async function fetchQuote(symbol: string): Promise<QuoteData | null> {
    loading.value = true
    error.value = null
    try {
      const res: any = await stockApi.getStockDetail(symbol)
      return res as QuoteData
    } catch (e: any) {
      error.value = e.message || '获取行情失败'
      return null
    } finally {
      loading.value = false
    }
  }

  async function searchStocks(query: string) {
    loading.value = true
    try {
      const res: any = await stockApi.searchStocks(query)
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

  return { data, indicators: {}, source: 'mock' }
}
