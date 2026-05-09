<template>
  <div id="app" class="app-container">
    <el-container>
      <el-header class="app-header">
        <div class="header-content">
          <router-link to="/" class="brand">
            <span class="brand-mark">S</span>
            <span class="brand-text">股票数据分析平台</span>
          </router-link>
          <nav class="header-nav" aria-label="主导航">
            <router-link to="/" class="nav-link">首页</router-link>
            <router-link to="/stocks" class="nav-link">股票</router-link>
            <router-link to="/recommendations" class="nav-link">每日观察</router-link>
            <router-link to="/watchlist" class="nav-link">自选股</router-link>
            <router-link to="/alerts" class="nav-link">预警</router-link>
            <router-link to="/profile" class="nav-link">我的</router-link>
            <router-link to="/admin" class="nav-link admin-link" v-if="isAdmin">管理后台</router-link>
            <router-link to="/login" class="nav-link" v-if="!isLoggedIn">登录</router-link>
            <button v-else type="button" class="nav-link nav-button" @click="logout">退出</button>
          </nav>
        </div>
      </el-header>
      <el-main class="app-main">
        <div class="main-shell">
          <router-view v-slot="{ Component }">
            <transition name="page-fade" mode="out-in">
              <component :is="Component" />
            </transition>
          </router-view>
        </div>
      </el-main>
      <el-footer class="app-footer">
        <p>© {{ new Date().getFullYear() }} 股票数据分析平台 | 仅供参考，不构成投资建议</p>
      </el-footer>
    </el-container>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()

const isLoggedIn = computed(() => userStore.isLoggedIn)
const isAdmin = computed(() => userStore.isAdmin)

onMounted(async () => {
  await userStore.fetchMe()
})

function logout() {
  userStore.logout()
  ElMessage.success('已退出')
  router.push('/')
}
</script>

<style scoped>
.app-container {
  min-height: 100vh;
  background: var(--color-bg);
}

.app-header {
  position: sticky;
  top: 0;
  z-index: 20;
  height: auto;
  padding: 0;
  background: rgba(255, 255, 255, 0.94);
  border-bottom: 1px solid var(--color-border);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.04);
  backdrop-filter: blur(16px);
}

.header-content {
  max-width: 1440px;
  min-height: 64px;
  margin: 0 auto;
  padding: 0 var(--space-6);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-6);
}

.brand {
  display: inline-flex;
  align-items: center;
  gap: var(--space-3);
  color: var(--color-text);
  text-decoration: none;
  white-space: nowrap;
  transition: transform var(--transition-fast);
}

.brand:hover {
  transform: scale(1.02);
}

.brand-mark {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: linear-gradient(135deg, #0f172a 0%, #1d4ed8 100%);
  color: #fff;
  font-weight: 800;
  letter-spacing: -0.05em;
  transition: all var(--transition-fast);
  box-shadow: 0 2px 8px rgba(29, 78, 216, 0.2);
}

.brand:hover .brand-mark {
  box-shadow: 0 4px 16px rgba(29, 78, 216, 0.3);
  transform: rotate(-3deg);
}

.brand-text {
  font-size: 18px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.header-nav {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  overflow-x: auto;
}

.nav-link {
  position: relative;
  padding: 8px 12px;
  border-radius: 999px;
  color: var(--color-text-secondary);
  text-decoration: none;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: color 0.2s ease, background 0.2s ease;
  white-space: nowrap;
}

.nav-button {
  border: 0;
  background: transparent;
  font: inherit;
}

.nav-link:hover {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.nav-link.router-link-active {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-weight: 700;
}

.nav-link.router-link-active::after {
  content: '';
  position: absolute;
  bottom: -2px;
  left: 50%;
  transform: translateX(-50%);
  width: 20px;
  height: 3px;
  background: var(--color-primary);
  border-radius: 999px;
}

.nav-link:active {
  transform: scale(0.95);
}

.admin-link {
  color: #7c3aed;
  background: #f5f3ff;
}

.admin-link:hover {
  background: #ede9fe;
  color: #6d28d9;
}

.app-main {
  flex: 1;
  padding: var(--space-6);
}

.main-shell {
  width: min(1440px, 100%);
  margin: 0 auto;
}

.app-footer {
  height: auto;
  background: transparent;
  color: var(--color-text-muted);
  text-align: center;
  padding: var(--space-5);
  border-top: 1px solid var(--color-border);
}

.app-footer p {
  margin: 0;
  font-size: 12px;
}

/* Page transition */
.page-fade-enter-active,
.page-fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.page-fade-enter-from {
  opacity: 0;
  transform: translateY(8px);
}

.page-fade-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

@media (max-width: 960px) {
  .header-content {
    align-items: flex-start;
    flex-direction: column;
    padding: var(--space-4);
    gap: var(--space-3);
  }

  .header-nav {
    width: 100%;
    padding-bottom: 2px;
  }

  .app-main {
    padding: var(--space-4);
  }
}
@media (max-width: 720px) {
  .header-content {
    padding: var(--space-3);
  }

  .brand-text {
    font-size: 16px;
  }

  .nav-link {
    padding: 7px 10px;
    font-size: 13px;
  }

  .app-main {
    padding: var(--space-3);
  }
}
</style>
