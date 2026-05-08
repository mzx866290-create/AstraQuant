import api from './client'

export const watchlistApi = {
  getWatchlists: <T = unknown>() =>
    api.get<T>('/api/v1/watchlists'),

  createWatchlist: <T = unknown>(name: string) =>
    api.post<T>('/api/v1/watchlists', { name }),

  addToWatchlist: (watchlist_id: number, stock_id?: number, symbol?: string) =>
    api.post(`/api/v1/watchlists/${watchlist_id}/items`, { stock_id, symbol }),

  removeFromWatchlist: (watchlist_id: number, stock_id: number) =>
    api.delete(`/api/v1/watchlists/${watchlist_id}/items/${stock_id}`),
}
