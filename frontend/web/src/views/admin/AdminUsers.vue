<template>
  <div class="admin-users">
    <h1>用户管理</h1>

    <div v-if="loading" class="loading">加载中...</div>

    <table v-else class="users-table">
      <thead>
        <tr>
          <th>ID</th>
          <th>用户名</th>
          <th>邮箱</th>
          <th>角色</th>
          <th>状态</th>
          <th>今日用量</th>
          <th>本月用量</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="user in users" :key="user.id">
          <td>{{ user.id }}</td>
          <td>{{ user.username }}</td>
          <td>{{ user.email }}</td>
          <td>
            <span :class="'role-' + user.role">{{ user.role }}</span>
          </td>
          <td>
            <span :class="user.is_active ? 'status-active' : 'status-inactive'">
              {{ user.is_active ? '正常' : '禁用' }}
            </span>
          </td>
          <td>{{ user.daily_used }} / {{ user.daily_limit }}</td>
          <td>{{ user.monthly_used }} / {{ user.monthly_limit }}</td>
          <td>
            <button @click="editQuota(user)" class="btn-small">配额</button>
            <button @click="resetQuota(user)" class="btn-small">重置</button>
            <button
              @click="deleteUser(user)"
              class="btn-small btn-danger"
              :disabled="!canDeleteUser(user)"
              :title="deleteDisabledReason(user)"
            >
              删除
            </button>
          </td>
        </tr>
        <tr v-if="!users.length">
          <td colspan="8" class="no-data">暂无用户</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { adminApi } from '@/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'

interface AdminUser {
  id: number
  username: string
  email?: string
  role: string
  is_active: boolean
  daily_used: number
  daily_limit: number
  monthly_used: number
  monthly_limit: number
}

interface ApiErrorLike {
  response?: {
    data?: {
      detail?: string
    }
  }
}

const loading = ref(true)
const users = ref<AdminUser[]>([])
const userStore = useUserStore()

async function loadUsers() {
  try {
    loading.value = true
    users.value = await adminApi.getUsers<AdminUser[]>()
  } catch (e) {
    ElMessage.error('加载用户失败')
  } finally {
    loading.value = false
  }
}

async function editQuota(user: AdminUser) {
  try {
    const { value: daily } = await ElMessageBox.prompt('设置每日配额:', '配额设置', {
      inputValue: String(user.daily_limit),
      inputPattern: /^\d+$/,
      inputErrorMessage: '请输入非负整数',
    })
    const { value: monthly } = await ElMessageBox.prompt('设置每月配额:', '配额设置', {
      inputValue: String(user.monthly_limit),
      inputPattern: /^\d+$/,
      inputErrorMessage: '请输入非负整数',
    })
    await adminApi.updateUserQuota(user.id, {
      daily_limit: parseInt(daily, 10),
      monthly_limit: parseInt(monthly, 10),
    })
    ElMessage.success('配额已更新')
    loadUsers()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error('更新失败')
  }
}

async function resetQuota(user: AdminUser) {
  try {
    await ElMessageBox.confirm(`确定重置用户 "${user.username}" 的配额吗?`, '确认重置', { type: 'warning' })
    await adminApi.resetUserQuota(user.id)
    ElMessage.success('配额已重置')
    loadUsers()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error('重置失败')
  }
}

function canDeleteUser(user: AdminUser) {
  return user.id !== userStore.userInfo?.id && user.role !== 'admin'
}

function deleteDisabledReason(user: AdminUser) {
  if (user.id === userStore.userInfo?.id) return '不能删除当前登录账号'
  if (user.role === 'admin') return '不能删除管理员账号'
  return '删除用户'
}

async function deleteUser(user: AdminUser) {
  if (!canDeleteUser(user)) {
    ElMessage.warning(deleteDisabledReason(user))
    return
  }
  try {
    await ElMessageBox.confirm(`确定要删除用户 "${user.username}" 吗？此操作不可撤销！`, '确认删除', { type: 'warning' })
    await adminApi.deleteUser(user.id)
    ElMessage.success(`用户 "${user.username}" 已删除`)
    loadUsers()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error((error as ApiErrorLike)?.response?.data?.detail || '删除失败')
    }
  }
}

onMounted(loadUsers)
</script>

<style scoped>
h1 { margin-bottom: 20px; }

.loading, .no-data {
  text-align: center;
  padding: 40px;
  color: #999;
}

.users-table {
  width: 100%;
  background: #fff;
  border-radius: 8px;
  border-collapse: collapse;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.users-table th,
.users-table td {
  padding: 12px 15px;
  text-align: left;
  border-bottom: 1px solid #eee;
}

.users-table th {
  background: #f9f9f9;
  font-weight: 600;
}

.role-free { background: #10a37f; color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.role-premium { background: #d97706; color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.role-admin { background: #dc2626; color: #fff; padding: 2px 8px; border-radius: 4px; font-size: 12px; }

.status-active { color: #10a37f; }
.status-inactive { color: #dc2626; }

.btn-small {
  padding: 4px 8px;
  margin-right: 5px;
  border: 1px solid #ddd;
  background: #fff;
  border-radius: 4px;
  cursor: pointer;
}

.btn-danger {
  border-color: #dc2626;
  color: #dc2626;
}

.btn-danger:hover {
  background: #dc2626;
  color: #fff;
}

.btn-small:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.btn-danger:disabled:hover {
  background: #fff;
  color: #dc2626;
}
</style>
