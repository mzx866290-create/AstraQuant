/**
 * 用户状态管理 - Pinia Store
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { userApi } from '@/api'

export const useUserStore = defineStore('user', () => {
  const token = ref(localStorage.getItem('access_token') || '')
  const userInfo = ref<any>(null)

  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => userInfo.value?.role === 'admin')

  function setToken(newToken: string) {
    token.value = newToken
    localStorage.setItem('access_token', newToken)
  }

  function setUserInfo(info: any) {
    userInfo.value = info
  }

  function logout() {
    token.value = ''
    userInfo.value = null
    localStorage.removeItem('access_token')
  }

  async function login(username: string, password: string) {
    const resp = await userApi.login(username, password)
    setToken(resp.access_token)
    await fetchMe()
    return resp
  }

  async function fetchMe() {
    const storedToken = localStorage.getItem('access_token')
    if (!storedToken && !token.value) return null
    try {
      const resp = await userApi.getProfile()
      setUserInfo(resp)
      return resp
    } catch (e) {
      logout()
      return null
    }
  }

  return {
    token,
    userInfo,
    isLoggedIn,
    isAdmin,
    setToken,
    setUserInfo,
    logout,
    login,
    fetchMe,
  }
})