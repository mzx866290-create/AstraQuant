import api from './client'

export const alertApi = {
  getAlerts: <T = unknown>() => api.get<T>('/api/v1/alerts'),
  createAlert: <T = unknown>(data: unknown) => api.post<T>('/api/v1/alerts', data),
  deleteAlert: <T = unknown>(id: number) => api.delete<T>(`/api/v1/alerts/${id}`),
  toggleAlert: <T = unknown>(id: number) => api.put<T>(`/api/v1/alerts/${id}/toggle`),
  checkAlerts: <T = unknown>() => api.post<T>('/api/v1/alerts/check'),
  getSchedulerStatus: <T = unknown>() => api.get<T>('/api/v1/alerts/scheduler/status'),
}
