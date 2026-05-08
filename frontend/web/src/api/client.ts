import axios, { type AxiosRequestConfig } from 'axios'

export type ApiClient = {
  get<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T>
  post<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T>
  put<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T>
  patch<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T>
  delete<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T>
}

const DIRECT_SERVICE_PORTS = new Set(['8001', '8002', '8003'])
const DIRECT_SERVICE_HOSTS = new Set(['market-service', 'user-service', 'analysis-service'])

export const normalizeApiBaseUrl = (value?: string | null): string => (value || '').trim().replace(/\/+$/, '')

export const isDirectServiceBaseUrl = (value?: string | null): boolean => {
  const normalized = normalizeApiBaseUrl(value)
  if (!normalized) return false

  try {
    const parsed = new URL(normalized, window.location.origin)
    if (DIRECT_SERVICE_HOSTS.has(parsed.hostname)) return true
    return ['localhost', '127.0.0.1'].includes(parsed.hostname) && DIRECT_SERVICE_PORTS.has(parsed.port)
  } catch {
    return false
  }
}

const resolveConfiguredBaseURL = (): string => {
  const configured = normalizeApiBaseUrl(localStorage.getItem('api_base_url') || import.meta.env.VITE_API_BASE_URL || '')
  if (configured && isDirectServiceBaseUrl(configured)) {
    console.warn('[api] Ignoring direct backend service base URL. Use the site gateway origin instead.')
    return ''
  }
  return configured
}

const getBaseURL = (): string => resolveConfiguredBaseURL()

export const axiosInstance = axios.create({
  baseURL: getBaseURL(),
  timeout: 60000,
  headers: {
    'Content-Type': 'application/json',
  },
})

let redirectingToLogin = false
let authStateClearer: (() => void) | null = null

export const registerAuthStateClearer = (clearer: () => void) => {
  authStateClearer = clearer
}

const clearAuthState = () => {
  localStorage.removeItem('access_token')
  authStateClearer?.()
}

const redirectToLogin = () => {
  if (redirectingToLogin || window.location.pathname === '/login') return

  redirectingToLogin = true
  const currentPath = `${window.location.pathname}${window.location.search}${window.location.hash}`
  window.location.replace(`/login?redirect=${encodeURIComponent(currentPath)}`)
}

axiosInstance.interceptors.request.use(
  (config) => {
    config.baseURL = getBaseURL()
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

axiosInstance.interceptors.response.use(
  (response) => response.data,
  async (error) => {
    if (error.response?.status === 401) {
      clearAuthState()
      redirectToLogin()
    }
    return Promise.reject(error)
  },
)

export const api = axiosInstance as unknown as ApiClient

export default api
