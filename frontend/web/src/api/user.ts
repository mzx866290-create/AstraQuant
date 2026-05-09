import api from './client'

export const userApi = {
  register: (username: string, email: string, password: string) =>
    api.post('/api/v1/auth/register', { username, email, password }),

  login: (username: string, password: string) =>
    api.post<{ access_token: string }>('/api/v1/auth/login', { username, password }),

  getProfile: <T = unknown>() =>
    api.get<T>('/api/v1/auth/me'),

  updateProfile: <T = unknown>(data: unknown) =>
    api.put<T>('/api/v1/auth/me', data),

  changePassword: <T = { message: string }>(currentPassword: string, newPassword: string) =>
    api.put<T>('/api/v1/auth/me/password', {
      current_password: currentPassword,
      new_password: newPassword,
    }),
}
