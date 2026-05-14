import api from './client'

export type WatchlistAddPayload = {
  stock_id?: number
  symbol?: string
  name?: string
  market?: string
  sector?: string
}

export const watchlistApi = {
  getWatchlists: <T = unknown>() =>
    api.get<T>('/api/v1/watchlists'),

  createWatchlist: <T = unknown>(name: string) =>
    api.post<T>('/api/v1/watchlists', { name }),

  addToWatchlist: (watchlist_id: number, payload: WatchlistAddPayload) =>
    api.post(`/api/v1/watchlists/${watchlist_id}/items`, payload),

  reorderWatchlistItems: <T = unknown>(watchlist_id: number, stock_ids: number[]) =>
    api.put<T>(`/api/v1/watchlists/${watchlist_id}/items/reorder`, { stock_ids }),

  removeFromWatchlist: (watchlist_id: number, stock_id: number) =>
    api.delete(`/api/v1/watchlists/${watchlist_id}/items/${stock_id}`),
}
