import api from './client'

export {
  api,
  isDirectServiceBaseUrl,
  normalizeApiBaseUrl,
  registerAuthStateClearer,
  type ApiClient,
} from './client'
export {
  createUnavailableFeatureError,
  isFeatureUnavailableError,
  unavailableFeature,
  type UnavailableFeatureError,
  type UnavailableFeatureResponse,
} from './unavailableFeature'
export { adminApi } from './admin'
export { alertApi } from './alerts'
export { analysisApi } from './analysis'
export { crawlApi } from './crawl'
export { newsApi } from './news'
export { stockApi } from './stock'
export { userApi } from './user'
export { watchlistApi } from './watchlist'

export default api
