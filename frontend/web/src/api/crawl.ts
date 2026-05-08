import api from './client'

export const crawlApi = {
  crawlNews: <T = unknown>(symbol: string) =>
    api.post<T>(`/api/v1/crawl/${symbol}/news`),
  crawlAnnouncements: <T = unknown>(symbol: string) =>
    api.post<T>(`/api/v1/crawl/${symbol}/announcements`),
  crawlFinancials: <T = unknown>(symbol: string) =>
    api.post<T>(`/api/v1/crawl/${symbol}/financials`),
  getCrawlStatus: <T = unknown>(symbol: string) =>
    api.get<T>(`/api/v1/crawl/${symbol}/status`),
}
