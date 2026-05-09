<template>
  <div class="admin-layout" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <aside class="sidebar">
      <div class="sidebar-header">
        <div class="brand">
          <span class="brand-icon">S</span>
          <h2>管理后台</h2>
        </div>
        <button class="sidebar-toggle" @click="sidebarCollapsed = !sidebarCollapsed">
          <el-icon><Fold v-if="!sidebarCollapsed" /><Expand v-else /></el-icon>
        </button>
      </div>
      <nav class="sidebar-nav">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
        >
          <el-icon class="nav-icon"><component :is="item.icon" /></el-icon>
          <span class="nav-text">{{ item.label }}</span>
          <el-tag v-if="item.badge" size="small" type="danger" class="nav-badge">{{ item.badge }}</el-tag>
        </router-link>
      </nav>
      <div class="sidebar-footer">
        <router-link to="/" class="back-link">
          <el-icon><ArrowLeft /></el-icon>
          <span>返回前台</span>
        </router-link>
        <button @click="logout" class="logout-btn">
          <el-icon><SwitchButton /></el-icon>
          <span>退出登录</span>
        </button>
      </div>
    </aside>
    <main class="main-content">
      <div class="content-wrapper">
        <router-view v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  Fold,
  Expand,
  ArrowLeft,
  SwitchButton,
  DataLine,
  Cpu,
  User,
  Document,
} from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()
const sidebarCollapsed = ref(false)

interface NavItem {
  path: string
  label: string
  icon: any
  badge?: string
}

const navItems: NavItem[] = [
  { path: '/admin/stats', label: '使用统计', icon: DataLine },
  { path: '/admin/models', label: 'AI 模型', icon: Cpu },
  { path: '/admin/users', label: '用户管理', icon: User },
  { path: '/admin/logs', label: '调用日志', icon: Document },
]

function logout() {
  userStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.admin-layout {
  display: flex;
  min-height: 100vh;
  background: var(--color-bg);
}

.sidebar {
  width: 240px;
  background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
  color: #e2e8f0;
  display: flex;
  flex-direction: column;
  position: fixed;
  top: 0;
  left: 0;
  bottom: 0;
  z-index: 50;
  transition: width var(--transition-base);
}

.sidebar-header {
  padding: var(--space-5) var(--space-4);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.brand-icon {
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: #fff;
  font-weight: 800;
  font-size: 16px;
}

.sidebar-header h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: #f8fafc;
}

.sidebar-toggle {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.15);
  color: #94a3b8;
  padding: 6px;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.sidebar-toggle:hover {
  background: rgba(255, 255, 255, 0.08);
  color: #e2e8f0;
}

.sidebar-nav {
  flex: 1;
  padding: var(--space-3) var(--space-2);
}

.nav-item {
  display: flex;
  align-items: center;
  padding: 10px var(--space-3);
  margin: 2px var(--space-2);
  color: #94a3b8;
  text-decoration: none;
  border-radius: var(--radius-md);
  transition: all var(--transition-fast);
  font-size: 14px;
  font-weight: 600;
  position: relative;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #e2e8f0;
}

.nav-item.router-link-active {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.2) 0%, rgba(139, 92, 246, 0.2) 100%);
  color: #e0e7ff;
}

.nav-item.router-link-active::before {
  content: '';
  position: absolute;
  left: -8px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 20px;
  background: linear-gradient(180deg, #6366f1 0%, #8b5cf6 100%);
  border-radius: 999px;
}

.nav-icon {
  margin-right: var(--space-3);
  font-size: 18px;
  flex-shrink: 0;
}

.nav-badge {
  margin-left: auto;
}

.sidebar-footer {
  padding: var(--space-4);
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.back-link,
.logout-btn {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 8px var(--space-3);
  border-radius: var(--radius-md);
  font-size: 13px;
  font-weight: 600;
  transition: all var(--transition-fast);
  cursor: pointer;
  text-decoration: none;
}

.back-link {
  color: #94a3b8;
  background: transparent;
}

.back-link:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #e2e8f0;
}

.logout-btn {
  color: #fca5a5;
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.2);
  justify-content: center;
}

.logout-btn:hover {
  background: rgba(239, 68, 68, 0.2);
  color: #fecaca;
}

.main-content {
  flex: 1;
  margin-left: 240px;
  min-height: 100vh;
  padding: var(--space-5);
  background: var(--color-bg);
  transition: margin-left var(--transition-base);
}

.content-wrapper {
  max-width: 1440px;
  margin: 0 auto;
}

/* Page transition */
.page-fade-enter-active,
.page-fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.page-fade-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.page-fade-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

/* Collapsed sidebar */
.sidebar-collapsed .sidebar {
  width: 64px;
}

.sidebar-collapsed .sidebar-header h2,
.sidebar-collapsed .nav-text,
.sidebar-collapsed .nav-badge,
.sidebar-collapsed .back-link span,
.sidebar-collapsed .logout-btn span {
  display: none;
}

.sidebar-collapsed .sidebar-header {
  justify-content: center;
}

.sidebar-collapsed .nav-item {
  justify-content: center;
  padding: 10px;
}

.sidebar-collapsed .nav-icon {
  margin-right: 0;
}

.sidebar-collapsed .main-content {
  margin-left: 64px;
}

/* Responsive */
@media (max-width: 768px) {
  .sidebar {
    transform: translateX(-100%);
    transition: transform var(--transition-base);
  }

  .sidebar.show {
    transform: translateX(0);
  }

  .main-content {
    margin-left: 0;
  }
}
</style>
