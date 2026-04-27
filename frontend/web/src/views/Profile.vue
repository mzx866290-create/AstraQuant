<template>
  <div class="profile-page">
    <el-card shadow="never">
      <template #header>
        <span>个人中心</span>
      </template>

      <el-empty v-if="!isLoggedIn" description="请先登录">
        <el-button type="primary" @click="$router.push('/login')">去登录</el-button>
      </el-empty>

      <el-descriptions v-else :column="1" border>
        <el-descriptions-item label="用户名">{{ user.username }}</el-descriptions-item>
        <el-descriptions-item label="邮箱">{{ user.email }}</el-descriptions-item>
        <el-descriptions-item label="角色">{{ user.role === 'premium' ? '付费会员' : '免费用户' }}</el-descriptions-item>
        <el-descriptions-item label="注册时间">{{ user.created_at }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { userApi } from '@/api'

const user = ref<any>({})
const isLoggedIn = computed(() => !!localStorage.getItem('access_token'))

onMounted(async () => {
  if (isLoggedIn.value) {
    try {
      const res: any = await userApi.getProfile()
      user.value = res
    } catch {
      // ignore
    }
  }
})
</script>

<style scoped>
.profile-page {
  max-width: 600px;
  margin: 0 auto;
}
</style>
