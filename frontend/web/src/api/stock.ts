import api from './client'
import type { UnavailableFeatureResponse } from './unavailableFeature'
import { unavailableFeature } from './unavailableFeature'

export const stockApi = {
  getStocks: <T = unknown>(market?: string) =>
    api.get<T>('/api/v1/stocks', { params: { market } }),

  getStockDetail: <T = unknown>(symbol: string) =>
    api.get<T>(`/api/v1/stocks/${symbol}`),

  getKline: <T = unknown>(symbol: string, period: string = '1d', limit: number = 200) =>
    api.get<T>(`/api/v1/kline/${symbol}`, {
      params: { period, limit },
    }),

  getQuote: <T = unknown>(symbol: string) =>
    api.get<T>(`/api/v1/quotes/${symbol}`),

  getMoneyFlow: <T = unknown>(symbol: string, days: number = 20) =>
    api.get<T>(`/api/v1/quotes/${symbol}/money-flow`, { params: { days } }),

  searchStocks: <T = unknown>(query: string) =>
    api.get<T>('/api/v1/search', { params: { q: query } }),

  getSectors: <T = UnavailableFeatureResponse>() =>
    unavailableFeature<T>('sectors', '板块数据暂未接入真实数据源，当前不可用'),

  getDragonTiger: <T = unknown>(tradeDate?: string) =>
    api.get<T>('/api/v1/dragon-tiger', { params: { trade_date: tradeDate } }),

  getStockDragonTiger: <T = unknown>(symbol: string, days: number = 30) =>
    api.get<T>(`/api/v1/dragon-tiger/${symbol}`, { params: { days } }),

  getIndices: <T = UnavailableFeatureResponse>() =>
    unavailableFeature<T>('indices', '大盘指数行情暂未接入真实数据源，当前不可用'),

  getIndexDetail: <T = UnavailableFeatureResponse>(_symbol: string) =>
    unavailableFeature<T>('index-detail', '指数详情暂未接入真实行情数据源，当前不可用'),

  getMarketOverview: <T = UnavailableFeatureResponse>() =>
    unavailableFeature<T>('market-overview', '市场概览暂未接入真实数据源，当前不可用'),
}
