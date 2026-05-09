<template>
  <div class="admin-users">
    <div class="page-header">
      <div>
        <h1 class="page-title">用户管理</h1>
        <p class="page-subtitle">管理系统用户和配额</p>
      </div>
    </div>

    <div v-if="loading" class="skeleton-list">
      <div v-for="i in 6" :key="i" class="skeleton-user">
        <div class="skeleton-avatar"></div>
        <div class="skeleton-body">
          <div class="skeleton-line"></div>
          <div class="skeleton-line short"></div>
        </div>
      </div>
    </div>

    <div v-else-if="users.length" class="users-list">
      <div
        v-for="user in users"
        :key="user.id"
        class="user-card"
        :class="{ inactive: !user.is_active }"
      >
        <div class="user-header">
          <div class="user-avatar">
            <span class="avatar-text">{{ user.username?.charAt(0)?.toUpperCase() }}</span>
          </div>
          <div class="user-info">
            <div class="user-name-row">
              <h3 class="user-name">{{ user.username }}</h3>
              <el-tag
                size="small"
                :type="user.is_active ? 'success' : 'info'"
                effect="light"
                class="status-tag"
              >
                {{ user.is_active ? '正常' : '禁用' }}
              </el-tag>
            </div>
            <span class="user-email">{{ user.email || '-' }}</span>
          </div>
          <div class="user-role">
            <span class="role-badge" :class="user.role">{{ roleLabel(user.role) }}</span>
          </div>
        </div>

        <div class="user-metrics">
          <div class="metric">
            <span class="metric-label">今日用量</span>
            <span class="metric-value" :class="quotaClass(user.daily_used, user.daily_limit)">
              {{ user.daily_used }} / {{ user.daily_limit }}
            </span>
          </div>
          <div class="metric">
            <span class="metric-label">本月用量</span>
            <span class="metric-value" :class="quotaClass(user.monthly_used, user.monthly_limit)">
              {{ user.monthly_used }} / {{ user.monthly_limit }}
            </span>
          </div>
        </div>

        <div class="user-actions" @click.stop>
          <el-button type="primary" link @click="editQuota(user)">
            <el-icon><Edit /></el-icon>
            <span>配额</span>
          </el-button>
          <el-button type="warning" link @click="resetQuota(user)">
            <el-icon><Refresh /></el-icon>
            <span>重置</span>
          </el-button>
          <el-button
            type="danger"
            link
            :disabled="!canDeleteUser(user)"
            :title="deleteDisabledReason(user)"
            @click="deleteUser(user)"
          >
            <el-icon><Delete /></el-icon>
            <span>删除</span>
          </el-button>
        </div>
      </div>
    </div>

    <div v-else class="empty-state">
      <el-icon :size="64" class="empty-icon"><User /></el-icon>
      <h3>暂无用户</h3>
      <p>还没有用户注册</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Edit, Refresh, Delete, User } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi } from '@/api'
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

function roleLabel(role: string) {
  const labels: Record<string, string> = {
    admin: '管理员',
    premium: '付费会员',
    free: '免费用户',
  }
  return labels[role] || role
}

function quotaClass(used: number, limit: number) {
  const ratio = used / limit
  if (ratio >= 0.9) return 'danger'
  if (ratio >= 0.7) return 'warning'
  return ''
}

function canDeleteUser(user: AdminUser) {
  return user.id !== userStore.userInfo?.id && user.role !== 'admin'
}

function deleteDisabledReason(user: AdminUser) {
  if (user.id === userStore.userInfo?.id) return '不能删除当前登录账号'
  if (user.role === 'admin') return '不能删除管理员账号'
  return '删除用户'
}

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
    await ElMessageBox.confirm(
      `确定重置用户 "${user.username}" 的配额吗?`,
      '确认重置',
      { type: 'warning' }
    )
    await adminApi.resetUserQuota(user.id)
    ElMessage.success('配额已重置')
    loadUsers()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error('重置失败')
  }
}

async function deleteUser(user: AdminUser) {
  if (!canDeleteUser(user)) {
    ElMessage.warning(deleteDisabledReason(user))
    return
  }
  try {
    await ElMessageBox.confirm(
      `确定要删除用户 "${user.username}" 吗？此操作不可撤销！`,
      '确认删除',
      { type: 'warning' }
    )
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
.admin-users {
  max-width: 1200px;
}

.page-header {
  margin-bottom: var(--space-6);
}

.page-title {
  font-size: 24px;
  font-weight: 800;
  color: var(--color-text);
  margin: 0 0 var(--space-1);
  letter-spacing: -0.02em;
}

.page-subtitle {
  margin: 0;
  color: var(--color-text-muted);
  font-size: 14px;
}

/* Skeleton */
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.skeleton-user {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.skeleton-avatar {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
  flex-shrink: 0;
}

.skeleton-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.skeleton-line {
  width: 60%;
  height: 16px;
  border-radius: var(--radius-sm);
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
}

.skeleton-line.short {
  width: 30%;
}

@keyframes skeleton-loading {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* User cards */
.users-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.user-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  transition: all var(--transition-base);
  position: relative;
  overflow: hidden;
}

.user-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, #6366f1 0%, #8b5cf6 100%);
  opacity: 0;
  transition: opacity var(--transition-base);
}

.user-card:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-1px);
}

.user-card:hover::before {
  opacity: 1;
}

.user-card.inactive {
  opacity: 0.7;
  background: var(--color-surface-muted);
}

.user-header {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}

.user-avatar {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.avatar-text {
  color: #fff;
  font-size: 20px;
  font-weight: 800;
}

.user-info {
  flex: 1;
  min-width: 0;
}

.user-name-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: 2px;
}

.user-name {
  margin: 0;
  font-size: 18px;
  font-weight: 800;
  color: var(--color-text);
  letter-spacing: -0.01em;
}

.status-tag {
  font-weight: 700;
}

.user-email {
  font-size: 13px;
  color: var(--color-text-muted);
}

.user-role {
  flex-shrink: 0;
}

.role-badge {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
}

.role-badge.admin {
  background: rgba(239, 68, 68, 0.1);
  color: #dc2626;
  border: 1px solid rgba(239, 68, 68, 0.2);
}

.role-badge.premium {
  background: rgba(217, 119, 6, 0.1);
  color: #d97706;
  border: 1px solid rgba(217, 119, 6, 0.2);
}

.role-badge.free {
  background: rgba(16, 163, 127, 0.1);
  color: #10a37f;
  border: 1px solid rgba(16, 163, 127, 0.2);
}

/* Metrics */
.user-metrics {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-4);
  padding: var(--space-3) 0;
  border-top: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
  margin-bottom: var(--space-3);
}

.metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.metric-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.metric-value {
  font-size: 18px;
  font-weight: 800;
  color: var(--color-text);
  font-family: var(--font-number);
}

.metric-value.danger {
  color: var(--color-up);
}

.metric-value.warning {
  color: var(--color-warning);
}

/* Actions */
.user-actions {
  display: flex;
  gap: var(--space-1);
}

.user-actions .el-button {
  padding: 6px 12px;
  font-size: 13px;
  font-weight: 600;
}

/* Empty state */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-16) 0;
  text-align: center;
  color: var(--color-text-muted);
}

.empty-state h3 {
  margin: var(--space-3) 0 var(--space-1);
  font-size: 18px;
  font-weight: 700;
  color: var(--color-text);
}

.empty-state p {
  margin: 0;
  font-size: 14px;
}

.empty-icon {
  color: var(--color-border-strong);
}

/* Responsive */
@media (max-width: 768px) {
  .user-header {
    flex-wrap: wrap;
  }

  .user-role {
    width: 100%;
    margin-top: var(--space-2);
  }

  .user-metrics {
    grid-template-columns: 1fr;
  }

  .user-actions {
    flex-wrap: wrap;
  }
}
</style>
