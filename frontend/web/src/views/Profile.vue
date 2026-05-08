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
        <el-descriptions-item label="角色">{{ roleLabel(user.role) }}</el-descriptions-item>
        <el-descriptions-item label="注册时间">{{ user.created_at }}</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useUserStore, type UserInfo } from '@/stores/user'

const userStore = useUserStore()
const user = computed<UserInfo>(() => userStore.userInfo || { id: 0, username: '' })
const isLoggedIn = computed(() => userStore.isLoggedIn)

function roleLabel(role?: string) {
  if (role === 'admin') return '管理员'
  if (role === 'premium') return '付费会员'
  return '免费用户'
}

onMounted(async () => {
  await userStore.fetchMe()
})
</script>

<style scoped>
.profile-page {
  max-width: 600px;
  margin: 0 auto;
}
</style>
