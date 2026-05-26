import type { IntradayConfirmationResponse, RecommendationsResponse } from '@/utils/recommendations'
import api from './client'

const AI_ANALYSIS_TIMEOUT_MS = 300000
const AI_FOLLOW_UP_TIMEOUT_MS = 120000
const AI_BATCH_SUMMARY_TIMEOUT_MS = 120000

const LOCAL_CACHE_PREFIX = 'pool_fallback:'
const LOCAL_CACHE_TTL_MS = 86400_000

function getLocalCache<T>(key: string): (T & { _fallback_ts?: number }) | null {
  try {
    const raw = localStorage.getItem(`${LOCAL_CACHE_PREFIX}${key}`)
    if (!raw) return null
    const { data, ts } = JSON.parse(raw)
    if (Date.now() - ts > LOCAL_CACHE_TTL_MS) {
      localStorage.removeItem(`${LOCAL_CACHE_PREFIX}${key}`)
      return null
    }
    return { ...data, _fallback_ts: ts }
  } catch {
    return null
  }
}

function setLocalCache(key: string, data: unknown) {
  try {
    localStorage.setItem(`${LOCAL_CACHE_PREFIX}${key}`, JSON.stringify({ data, ts: Date.now() }))
  } catch { /* quota exceeded — ignore */ }
}

export const analysisApi = {
  getTechnical: (symbol: string, indicators: string = 'ma5,ma20,macd,boll,kdj,rsi') =>
    api.get(`/api/v1/analysis/technical/${symbol}`, { params: { indicators } }),

  compare: (symbols: string, indicators: string = 'ma5,ma20,macd,rsi') =>
    api.get('/api/v1/analysis/compare', { params: { symbols, indicators } }),

  comparePerformance: (symbols: string, periods: string = '1d,5d,20d,60d') =>
    api.get('/api/v1/analysis/compare/performance', { params: { symbols, periods } }),

  getScore: (symbol: string) =>
    api.get(`/api/v1/analysis/score/${symbol}`),

  getStockDebate: <T = unknown>(symbol: string, strategy: string = 'auto', include_evidence: boolean = true) =>
    api.get<T>(`/api/v1/analysis/score/${symbol}/debate`, { params: { strategy, include_evidence } }),

  getRecommendations: async (
    market: string = 'ALL',
    limit: number = 10,
    force_refresh: boolean = false,
    strategy: string = 'auto',
    max_candidates: number = 200,
    include_evidence: boolean = true,
    include_debate: boolean = true,
    initial_full_scan: boolean = false,
  ): Promise<RecommendationsResponse> => {
    try {
      const cacheKey = `recommendations:${market}:${limit}:${strategy}:${max_candidates}:e${+include_evidence}:d${+include_debate}:f${+initial_full_scan}`
      const result = await api.get<RecommendationsResponse>('/api/v1/analysis/score/batch/recommend', {
        params: {
          market,
          limit,
          force_refresh,
          strategy,
          max_candidates,
          include_evidence,
          include_debate,
          initial_full_scan,
        },
        timeout: 180000,
      })
      setLocalCache(cacheKey, result)
      return result
    } catch (error) {
      const cacheKey = `recommendations:${market}:${limit}:${strategy}:${max_candidates}:e${+include_evidence}:d${+include_debate}:f${+initial_full_scan}`
      const cached = getLocalCache<RecommendationsResponse>(cacheKey)
      if (cached) {
        ;(cached as any).source = 'local_cache'
        ;(cached as any).stale = true
        return cached as RecommendationsResponse
      }
      throw error
    }
  },

  getIntradayConfirmation: async (
    market: string = 'ALL',
    limit: number = 20,
    strategy: string = 'auto',
    concurrency: number = 8,
  ): Promise<IntradayConfirmationResponse> => {
    try {
      return await api.get<IntradayConfirmationResponse>('/api/v1/analysis/score/batch/intraday-confirmation', {
        params: { market, limit, strategy, concurrency },
        timeout: 120000,
      })
    } catch (error) {
      console.warn('Intraday confirmation unavailable:', error)
      return {
        code: 200,
        data: { actionable: [], wait_pullback: [], watch_only: [], invalidated: [] },
        meta: { unavailable: true, unavailable_reason: String(error) },
      } as unknown as IntradayConfirmationResponse
    }
  },

  getRecentReviews: async <T = unknown>(
    symbols: string[],
    strategy: string = 'auto',
    offsets: string = 'T+1,T+5,T+20',
    limit_per_symbol: number = 1,
  ): Promise<T> => {
    try {
      return await api.get<T>('/api/v1/analysis/reviews/recent', {
        params: { symbols: symbols.join(','), strategy, offsets, limit_per_symbol },
      })
    } catch (error) {
      console.warn('Reviews unavailable:', error)
      return { code: 200, data: [], meta: { unavailable: true } } as unknown as T
    }
  },

  getObservationSummary: (symbol: string) =>
    api.get<{ symbol: string; summary_text: string | null; score?: number; snapshot_date?: string | null }>(
      `/api/v1/analysis/score/${symbol}/observation-summary`
    ),

  getSystemHealth: <T = unknown>() =>
    api.get<T>('/api/v1/analysis/system-health'),

  getPublicSystemHealth: <T = unknown>() =>
    api.get<T>('/api/v1/analysis/public-health'),

  detectPatterns: (symbol: string) =>
    api.get(`/api/v1/analysis/patterns/${symbol}`),

  getAIModels: <T = unknown>() =>
    api.get<T>('/api/v1/analysis/ai/models'),

  getAIModelHealth: <T = unknown>(refresh: boolean = false, analysis_grade: boolean = false) =>
    api.get<T>('/api/v1/analysis/ai/model-health', { params: { refresh, analysis_grade } }),

  getAIQuota: <T = unknown>() =>
    api.get<T>('/api/v1/analysis/ai/quota'),

  getAIReadiness: <T = unknown>(symbol: string) =>
    api.get<T>(`/api/v1/analysis/ai/readiness/${symbol}`),

  analyzeStock: <T = unknown>(
    model_id: number,
    symbol: string,
    question?: string,
    framework?: string,
    report_template: 'quick' | 'professional' | 'teaching' = 'quick',
    report_mode: 'summary' | 'detailed' = 'summary',
    audience: 'normal' | 'beginner' = 'normal',
    prompt_style: 'default' | 'plain' | 'beginner' | 'professional' | 'risk_control' = 'default',
    force_refresh: boolean = false,
  ) =>
    api.post<T>(
      '/api/v1/analysis/ai/analyze',
      { model_id, symbol, question, framework, report_template, report_mode, audience, prompt_style, force_refresh },
      { timeout: AI_ANALYSIS_TIMEOUT_MS },
    ),

  followUpAnalysis: <T = unknown>(
    model_id: number,
    symbol: string,
    question: string,
    analysis: string,
    report_meta?: unknown,
    prompt_style: 'default' | 'plain' | 'beginner' | 'professional' | 'risk_control' = 'default',
    audience: 'normal' | 'beginner' = 'normal',
  ) =>
    api.post<T>(
      '/api/v1/analysis/ai/follow-up',
      { model_id, symbol, question, analysis, report_meta, prompt_style, audience },
      { timeout: AI_FOLLOW_UP_TIMEOUT_MS },
    ),

  getBatchSummary: <T = unknown>(
    symbols: string[],
    report_mode: 'summary' | 'detailed' = 'summary',
    audience: 'normal' | 'beginner' = 'normal',
    include_news: boolean = true,
    force_refresh: boolean = false,
  ) =>
    api.post<T>(
      '/api/v1/analysis/ai/batch-summary',
      { symbols, report_mode, audience, include_news, force_refresh },
      { timeout: AI_BATCH_SUMMARY_TIMEOUT_MS },
    ),

  getFinancialAnalysis: (symbol: string) =>
    api.get(`/api/v1/analysis/financial/${symbol}`),
  getDuPont: (symbol: string) =>
    api.get(`/api/v1/analysis/financial/${symbol}/dupont`),
  getFScore: (symbol: string) =>
    api.get(`/api/v1/analysis/financial/${symbol}/fscore`),

  getValuation: (symbol: string) =>
    api.get(`/api/v1/analysis/valuation/${symbol}`),
  getPEBand: (symbol: string) =>
    api.get(`/api/v1/analysis/valuation/${symbol}/pe-band`),
  getPBBand: (symbol: string) =>
    api.get(`/api/v1/analysis/valuation/${symbol}/pb-band`),
}
