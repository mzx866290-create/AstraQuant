import type { AxiosRequestConfig } from 'axios'

export interface UnavailableFeatureResponse {
  available: false
  code: 'FEATURE_UNAVAILABLE'
  feature: string
  detail: string
}

export interface UnavailableFeatureError extends Error {
  isFeatureUnavailable: true
  isAxiosError: true
  config: AxiosRequestConfig
  request: {
    feature: string
  }
  response: {
    status: 501
    statusText: string
    data: UnavailableFeatureResponse
    headers: Record<string, never>
    config: AxiosRequestConfig
  }
  status: 501
  toJSON: () => Record<string, unknown>
}

export const createUnavailableFeatureError = (feature: string, detail: string): UnavailableFeatureError => {
  const error = new Error(detail) as UnavailableFeatureError
  const config: AxiosRequestConfig = {
    method: 'get',
    url: `feature-unavailable:${feature}`,
  }

  error.name = 'UnavailableFeatureError'
  error.isFeatureUnavailable = true
  error.isAxiosError = true
  error.config = config
  error.request = { feature }
  error.response = {
    status: 501,
    statusText: 'Not Implemented',
    data: {
      available: false,
      code: 'FEATURE_UNAVAILABLE',
      feature,
      detail,
    },
    headers: {},
    config,
  }
  error.status = 501
  error.toJSON = () => ({
    name: error.name,
    message: error.message,
    status: error.status,
    code: error.response.data.code,
    config: error.config,
    response: error.response,
  })
  return error
}

export const unavailableFeature = <T = UnavailableFeatureResponse>(feature: string, detail: string): Promise<T> =>
  Promise.reject(createUnavailableFeatureError(feature, detail))

export const isFeatureUnavailableError = (error: unknown): error is UnavailableFeatureError =>
  Boolean((error as { isFeatureUnavailable?: boolean })?.isFeatureUnavailable)
