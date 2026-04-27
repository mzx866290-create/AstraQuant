<template>
  <div class="admin-layout">
    <aside class="sidebar">
      <div class="sidebar-header">
        <h2>管理后台</h2>
      </div>
      <nav class="sidebar-nav">
        <router-link to="/admin/stats" class="nav-item">
          <span class="nav-icon">📊</span>
          <span>使用统计</span>
        </router-link>
        <router-link to="/admin/models" class="nav-item">
          <span class="nav-icon">🤖</span>
          <span>AI 模型</span>
        </router-link>
        <router-link to="/admin/users" class="nav-item">
          <span class="nav-icon">👥</span>
          <span>用户管理</span>
        </router-link>
        <router-link to="/admin/logs" class="nav-item">
          <span class="nav-icon">📋</span>
          <span>调用日志</span>
        </router-link>
      </nav>
      <div class="sidebar-footer">
        <router-link to="/" class="back-link">← 返回前台</router-link>
        <button @click="logout" class="logout-btn">退出登录</button>
      </div>
    </aside>
    <main class="main-content">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const userStore = useUserStore()

function logout() {
  userStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.admin-layout {
  display: flex;
  min-height: 100vh;
}

.sidebar {
  width: 220px;
  background: #1a1a2e;
  color: #fff;
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 20px;
  border-bottom: 1px solid #333;
}

.sidebar-header h2 {
  margin: 0;
  font-size: 18px;
}

.sidebar-nav {
  flex: 1;
  padding: 10px 0;
}

.nav-item {
  display: flex;
  align-items: center;
  padding: 12px 20px;
  color: #aaa;
  text-decoration: none;
  transition: all 0.2s;
}

.nav-item:hover {
  background: #252540;
  color: #fff;
}

.nav-item.router-link-active {
  background: #4a4a6a;
  color: #fff;
  border-left: 3px solid #7c3aed;
}

.nav-icon {
  margin-right: 10px;
  font-size: 18px;
}

.sidebar-footer {
  padding: 20px;
  border-top: 1px solid #333;
}

.back-link {
  display: block;
  color: #aaa;
  text-decoration: none;
  margin-bottom: 10px;
}

.back-link:hover {
  color: #fff;
}

.logout-btn {
  width: 100%;
  padding: 8px;
  background: #dc2626;
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.logout-btn:hover {
  background: #b91c1c;
}

.main-content {
  flex: 1;
  padding: 20px;
  background: #f5f5f5;
  overflow-y: auto;
}
</style>