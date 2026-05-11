import type { RecommendationsResponse } from '@/utils/recommendations'
import api from './client'

const AI_ANALYSIS_TIMEOUT_MS = 300000
const AI_FOLLOW_UP_TIMEOUT_MS = 120000
const AI_BATCH_SUMMARY_TIMEOUT_MS = 120000
const RECOMMENDATIONS_TIMEOUT_MS = 180000

export const analysisApi = {
  getTechnical: (symbol: string, indicators: string = 'ma5,ma20,macd,boll,kdj,rsi') =>
    api.get(`/api/v1/analysis/technical/${symbol}`, { params: { indicators } }),

  compare: (symbols: string, indicators: string = 'ma5,ma20,macd,rsi') =>
    api.get('/api/v1/analysis/compare', { params: { symbols, indicators } }),

  comparePerformance: (symbols: string, periods: string = '1d,5d,20d,60d') =>
    api.get('/api/v1/analysis/compare/performance', { params: { symbols, periods } }),

  getScore: (symbol: string) =>
    api.get(`/api/v1/analysis/score/${symbol}`),

  getRecommendations: (
    market: string = 'ALL',
    limit: number = 10,
    force_refresh: boolean = false,
    strategy: string = 'auto',
    max_candidates: number = 200,
    include_evidence: boolean = true,
    include_debate: boolean = true,
    initial_full_scan: boolean = false,
  ) =>
    api.get<RecommendationsResponse>('/api/v1/analysis/score/batch/recommend', {
      params: { market, limit, force_refresh, strategy, max_candidates, include_evidence, include_debate, initial_full_scan },
      timeout: RECOMMENDATIONS_TIMEOUT_MS,
    }),

  getRecentReviews: <T = unknown>(
    symbols: string[],
    strategy: string = 'auto',
    offsets: string = 'T+1,T+5,T+20',
    limit_per_symbol: number = 1,
  ) =>
    api.get<T>('/api/v1/analysis/reviews/recent', {
      params: { symbols: symbols.join(','), strategy, offsets, limit_per_symbol },
    }),

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
