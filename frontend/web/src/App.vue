<template>
  <div id="app" class="app-container">
    <el-container>
      <el-header class="app-header">
        <div class="header-content">
          <h1>📈 股票数据分析平台</h1>
          <div class="header-nav">
            <router-link to="/" class="nav-link">首页</router-link>
            <router-link to="/stocks" class="nav-link">股票</router-link>
            <router-link to="/watchlist" class="nav-link">自选股</router-link>
            <router-link to="/alerts" class="nav-link">预警</router-link>
            <router-link to="/profile" class="nav-link">我的</router-link>
            <router-link to="/admin" class="nav-link admin-link" v-if="isAdmin">管理后台</router-link>
            <router-link to="/login" class="nav-link" v-if="!isLoggedIn">登录</router-link>
            <a v-else class="nav-link" @click="logout" style="cursor:pointer">退出</a>
          </div>
        </div>
      </el-header>
      <el-main class="app-main">
        <router-view />
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
  if (localStorage.getItem('access_token')) {
    await userStore.fetchMe()
  }
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
  display: flex;
  flex-direction: column;
}

.app-header {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  padding: 20px 40px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-content h1 {
  margin: 0;
  font-size: 24px;
}

.header-nav {
  display: flex;
  gap: 20px;
}

.nav-link {
  color: white;
  text-decoration: none;
  font-weight: 500;
  transition: opacity 0.3s;
}

.nav-link:hover {
  opacity: 0.8;
}

.admin-link {
  background: rgba(255,255,255,0.2);
  padding: 4px 12px;
  border-radius: 4px;
}

.app-main {
  flex: 1;
  padding: 20px;
}

.app-footer {
  background: #f5f7fa;
  color: #606266;
  text-align: center;
  padding: 20px;
  border-top: 1px solid #dcdfe6;
}

.app-footer p {
  margin: 0;
}
</style>
