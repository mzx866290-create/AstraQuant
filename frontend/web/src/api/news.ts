import api from './client'

export const newsApi = {
  getStockNews: (symbol: string, params?: { sentiment?: string; limit?: number }) =>
    api.get(`/api/v1/news/${symbol}`, { params }),

  getTelegraph: (limit: number = 30) =>
    api.get('/api/v1/news/telegraph/latest', { params: { limit } }),

  getAnnouncements: (symbol: string, params?: { category?: string; limit?: number }) =>
    api.get(`/api/v1/announcements/${symbol}`, { params }),

  getFinancials: (symbol: string) =>
    api.get(`/api/v1/financials/${symbol}`),
}
