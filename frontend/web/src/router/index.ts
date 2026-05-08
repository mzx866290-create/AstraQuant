import { createRouter, createWebHistory, RouteRecordRaw } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'Home',
    component: () => import('../views/Home.vue')
  },
  {
    path: '/stocks',
    name: 'Stocks',
    component: () => import('../views/Stocks.vue')
  },
  {
    path: '/recommendations',
    name: 'Recommendations',
    component: () => import('../views/Recommendations.vue')
  },
  {
    path: '/stocks/:symbol',
    name: 'StockDetail',
    component: () => import('../views/StockDetail.vue')
  },
  {
    path: '/watchlist',
    name: 'Watchlist',
    component: () => import('../views/Watchlist.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/alerts',
    name: 'Alerts',
    component: () => import('../views/Alerts.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('../views/Settings.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/about',
    name: 'About',
    component: () => import('../views/About.vue')
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue')
  },
  {
    path: '/profile',
    name: 'Profile',
    component: () => import('../views/Profile.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/403',
    name: 'Forbidden',
    component: () => import('../views/Forbidden.vue')
  },
  {
    path: '/admin',
    component: () => import('../views/admin/AdminLayout.vue'),
    meta: { requiresAuth: true, requiresAdmin: true },
    children: [
      { path: '', redirect: '/admin/stats' },
      { path: 'stats', component: () => import('../views/admin/AdminStats.vue') },
      { path: 'models', component: () => import('../views/admin/AdminModels.vue') },
      { path: 'users', component: () => import('../views/admin/AdminUsers.vue') },
      { path: 'logs', component: () => import('../views/admin/AdminLogs.vue') },
    ]
  }
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes
})

router.beforeEach(async (to, _from, next) => {
  const userStore = useUserStore()
  const storedToken = localStorage.getItem('access_token')
  const requiresUser = to.meta.requiresAuth || to.meta.requiresAdmin
  let profileRefreshFailed = false

  // 尝试恢复登录状态
  if (requiresUser && storedToken && (!userStore.isLoggedIn || !userStore.userInfo)) {
    userStore.syncTokenFromStorage()
    try {
      await userStore.fetchMe()
    } catch {
      profileRefreshFailed = true
      ElMessage.error(userStore.fetchMeError || '登录状态暂时无法刷新，请稍后重试')
    }
  }

  if (to.meta.requiresAuth && !userStore.isLoggedIn) {
    next({ name: 'Login', query: { redirect: to.fullPath } })
    return
  }

  if (to.meta.requiresAdmin && !userStore.isAdmin) {
    if (profileRefreshFailed && userStore.isLoggedIn) {
      next()
      return
    }
    ElMessage.warning('当前账号没有管理员权限')
    next({ name: 'Forbidden', query: { from: to.fullPath } })
    return
  }

  next()
})

export default router
