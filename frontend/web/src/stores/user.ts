/**
 * 用户状态管理 - Pinia Store
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { registerAuthStateClearer, userApi } from '@/api'

export interface UserInfo {
  id: number
  username: string
  email?: string
  role?: string
  created_at?: string
  is_active?: boolean
}

export const useUserStore = defineStore('user', () => {
  const token = ref(localStorage.getItem('access_token') || '')
  const userInfo = ref<UserInfo | null>(null)
  const initialized = ref(false)
  const fetchingMe = ref<Promise<UserInfo | null> | null>(null)
  const fetchingMeToken = ref('')
  const fetchMeError = ref<string>('')

  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => userInfo.value?.role === 'admin')

  function syncTokenFromStorage() {
    token.value = localStorage.getItem('access_token') || ''
    return token.value
  }

  function setToken(newToken: string) {
    token.value = newToken
    localStorage.setItem('access_token', newToken)
  }

  function setUserInfo(info: UserInfo | null) {
    userInfo.value = info
  }

  function logout() {
    token.value = ''
    userInfo.value = null
    fetchMeError.value = ''
    localStorage.removeItem('access_token')
  }

  async function login(username: string, password: string) {
    const resp = await userApi.login(username, password)
    setToken(resp.access_token)
    await fetchMe(true)
    return resp
  }

  async function fetchMe(force = false) {
    const requestToken = localStorage.getItem('access_token') || token.value
    if (!requestToken) {
      initialized.value = true
      return null
    }
    if (!force && fetchingMe.value && fetchingMeToken.value === requestToken) return fetchingMe.value
    fetchingMeToken.value = requestToken

    fetchingMe.value = userApi.getProfile<UserInfo>()
      .then((resp) => {
        if ((localStorage.getItem('access_token') || token.value) !== requestToken) {
          return userInfo.value
        }
        setUserInfo(resp)
        fetchMeError.value = ''
        initialized.value = true
        return resp
      })
      .catch((error) => {
        const status = (error as { response?: { status?: number } })?.response?.status
        if (status === 401 || status === 403) {
          if ((localStorage.getItem('access_token') || token.value) === requestToken) {
            logout()
          }
          initialized.value = true
          return null
        }

        fetchMeError.value = '用户信息暂时无法刷新，请稍后重试'
        initialized.value = true
        throw error
      })
      .finally(() => {
        if (fetchingMeToken.value === requestToken) {
          fetchingMe.value = null
          fetchingMeToken.value = ''
        }
      })

    return fetchingMe.value
  }

  return {
    token,
    userInfo,
    initialized,
    fetchMeError,
    isLoggedIn,
    isAdmin,
    syncTokenFromStorage,
    setToken,
    setUserInfo,
    logout,
    login,
    fetchMe,
  }
})

registerAuthStateClearer(() => {
  useUserStore().logout()
})
