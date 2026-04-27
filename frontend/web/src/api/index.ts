import axios from 'axios'

const getBaseURL = (): string => {
  // 开发模式用空字符串走 Vite proxy，生产模式用 VITE_API_BASE_URL
  // 也可以通过 localStorage 手动指定
  return localStorage.getItem('api_base_url') ||
    import.meta.env.VITE_API_BASE_URL ||
    ''
}

const api = axios.create({
  baseURL: getBaseURL(),
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
api.interceptors.request.use(
  (config) => {
    config.baseURL = localStorage.getItem('api_base_url') ||
      import.meta.env.VITE_API_BASE_URL ||
      ''
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('access_token')
      // TODO: 重定向到登录页
    }
    return Promise.reject(error)
  }
)

// 行情接口
export const stockApi = {
  // 获取股票列表
  getStocks: (market?: string) =>
    api.get('/api/v1/stocks', { params: { market } }),

  // 获取股票详情
  getStockDetail: (symbol: string) =>
    api.get(`/api/v1/stocks/${symbol}`),

  // 获取K线数据
  getKline: (symbol: string, period: string = '1d', limit: number = 200) =>
    api.get(`/api/v1/kline/${symbol}`, {
      params: { period, limit }
    }),

  // 获取实时行情
  getQuote: (symbol: string) =>
    api.get(`/api/v1/quotes/${symbol}`),

  // 获取资金流向
  getMoneyFlow: (symbol: string, days: number = 20) =>
    api.get(`/api/v1/quotes/${symbol}/money-flow`, { params: { days } }),

  // 搜索股票
  searchStocks: (query: string) =>
    api.get('/api/v1/search', { params: { q: query } }),

  // 获取板块列表
  getSectors: () =>
    api.get('/api/v1/sectors'),

  // 获取龙虎榜
  getDragonTiger: (tradeDate?: string) =>
    api.get('/api/v1/dragon-tiger', { params: { trade_date: tradeDate } }),

  // 获取大盘指数
  getIndices: () =>
    api.get('/api/v1/indices'),

  // 获取指数详情
  getIndexDetail: (symbol: string) =>
    api.get(`/api/v1/indices/${symbol}`),

  // 获取市场概览
  getMarketOverview: () =>
    api.get('/api/v1/indices/summary/market-overview'),
}

// 用户接口
export const userApi = {
  // 用户注册
  register: (username: string, email: string, password: string) =>
    api.post('/api/v1/auth/register', { username, email, password }),

  // 用户登录
  login: (username: string, password: string) =>
    api.post('/api/v1/auth/login', { username, password }),

  // 获取用户信息
  getProfile: () =>
    api.get('/api/v1/auth/me'),

  // 更新用户信息
  updateProfile: (data: any) =>
    api.put('/api/v1/auth/me', data)
}

// 预警接口
export const alertApi = {
  getAlerts: () => api.get('/api/v1/alerts'),
  createAlert: (data: any) => api.post('/api/v1/alerts', data),
  deleteAlert: (id: number) => api.delete(`/api/v1/alerts/${id}`),
  toggleAlert: (id: number) => api.put(`/api/v1/alerts/${id}/toggle`),
}

// 分析接口
export const analysisApi = {
  // 技术指标分析
  getTechnical: (symbol: string, indicators: string = 'ma5,ma20,macd,boll,kdj,rsi') =>
    api.get(`/api/v1/analysis/technical/${symbol}`, { params: { indicators } }),

  // 多股对比
  compare: (symbols: string, indicators: string = 'ma5,ma20,macd,rsi') =>
    api.get('/api/v1/analysis/compare', { params: { symbols, indicators } }),

  // 区间涨跌幅对比
  comparePerformance: (symbols: string, periods: string = '1d,5d,20d,60d') =>
    api.get('/api/v1/analysis/compare/performance', { params: { symbols, periods } }),

  // 综合评分
  getScore: (symbol: string) =>
    api.get(`/api/v1/analysis/score/${symbol}`),

  // 推荐股票
  getRecommendations: (market: string = 'SH', limit: number = 10) =>
    api.get('/api/v1/analysis/score/batch/recommend', { params: { market, limit } }),

  // K线形态检测
  detectPatterns: (symbol: string) =>
    api.get(`/api/v1/analysis/patterns/${symbol}`),

  // AI 模型列表
  getAIModels: () =>
    api.get('/api/v1/analysis/ai/models'),

  // AI 配额查询
  getAIQuota: () =>
    api.get('/api/v1/analysis/ai/quota'),

  // AI 股票分析
  analyzeStock: (model_id: number, symbol: string, question?: string, framework?: string) =>
    api.post('/api/v1/analysis/ai/analyze', { model_id, symbol, question, framework }),

  // 财务分析
  getFinancialAnalysis: (symbol: string) =>
    api.get(`/api/v1/analysis/financial/${symbol}`),
  getDuPont: (symbol: string) =>
    api.get(`/api/v1/analysis/financial/${symbol}/dupont`),
  getFScore: (symbol: string) =>
    api.get(`/api/v1/analysis/financial/${symbol}/fscore`),

  // 估值分析
  getValuation: (symbol: string) =>
    api.get(`/api/v1/analysis/valuation/${symbol}`),
  getPEBand: (symbol: string) =>
    api.get(`/api/v1/analysis/valuation/${symbol}/pe-band`),
  getPBBand: (symbol: string) =>
    api.get(`/api/v1/analysis/valuation/${symbol}/pb-band`),
}

// 新闻与公告接口
export const newsApi = {
  // 个股新闻
  getStockNews: (symbol: string, params?: { sentiment?: string; limit?: number }) =>
    api.get(`/api/v1/news/${symbol}`, { params }),

  // 财联社电报
  getTelegraph: (limit: number = 30) =>
    api.get('/api/v1/news/telegraph/latest', { params: { limit } }),

  // 个股公告
  getAnnouncements: (symbol: string, params?: { category?: string; limit?: number }) =>
    api.get(`/api/v1/announcements/${symbol}`, { params }),

  // 个股财报
  getFinancials: (symbol: string) =>
    api.get(`/api/v1/financials/${symbol}`),
}

// 管理员接口
export const adminApi = {
  // 模型管理
  getModels: () =>
    api.get('/api/v1/admin/models'),
  createModel: (data: any) =>
    api.post('/api/v1/admin/models', data),
  updateModel: (id: number, data: any) =>
    api.put(`/api/v1/admin/models/${id}`, data),
  deleteModel: (id: number) =>
    api.delete(`/api/v1/admin/models/${id}`),
  toggleModel: (id: number) =>
    api.patch(`/api/v1/admin/models/${id}/toggle`),
  testModel: (id: number) =>
    api.post(`/api/v1/admin/models/${id}/test`),

  // 用户管理
  getUsers: (params?: any) =>
    api.get('/api/v1/admin/users', { params }),
  getUser: (id: number) =>
    api.get(`/api/v1/admin/users/${id}`),
  updateUser: (id: number, data: any) =>
    api.put(`/api/v1/admin/users/${id}`, data),
  updateUserQuota: (id: number, data: any) =>
    api.put(`/api/v1/admin/users/${id}/quota`, data),
  resetUserQuota: (id: number) =>
    api.post(`/api/v1/admin/users/${id}/reset-quota`),

  // 统计
  getStatsOverview: () =>
    api.get('/api/v1/admin/stats/overview'),
  getCallsByDay: (days?: number) =>
    api.get('/api/v1/admin/stats/calls-by-day', { params: { days } }),
  getCallsByModel: () =>
    api.get('/api/v1/admin/stats/calls-by-model'),
  getTopUsers: (limit?: number) =>
    api.get('/api/v1/admin/stats/top-users', { params: { limit } }),

  // 日志
  getLogs: (params?: any) =>
    api.get('/api/v1/admin/logs', { params }),
  getLogCount: (params?: any) =>
    api.get('/api/v1/admin/logs/count', { params }),
  exportLogs: (params?: any) =>
    api.get('/api/v1/admin/logs/export', { params, responseType: 'blob' }),
}

// 自选股接口
export const watchlistApi = {
  // 获取自选股列表
  getWatchlists: () =>
    api.get('/api/v1/watchlists'),

  // 创建自选股分组
  createWatchlist: (name: string) =>
    api.post('/api/v1/watchlists', { name }),

  // 添加股票到自选股（支持 stock_id 或 symbol）
  addToWatchlist: (watchlist_id: number, stock_id?: number, symbol?: string) =>
    api.post(`/api/v1/watchlists/${watchlist_id}/items`, { stock_id, symbol }),

  // 从自选股移除
  removeFromWatchlist: (watchlist_id: number, stock_id: number) =>
    api.delete(`/api/v1/watchlists/${watchlist_id}/items/${stock_id}`)
}

export default api

