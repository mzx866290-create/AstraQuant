<template>
  <div class="profile-page">
    <!-- 未登录状态 -->
    <div v-if="!isLoggedIn" class="login-prompt-card">
      <div class="login-prompt-content">
        <el-icon :size="64" class="prompt-icon"><User /></el-icon>
        <h2>请先登录</h2>
        <p>登录后查看您的个人信息和设置</p>
        <el-button type="primary" size="large" @click="$router.push('/login')">
          去登录
        </el-button>
      </div>
    </div>

    <!-- 已登录状态 -->
    <template v-else>
      <!-- 用户信息卡片 -->
      <div class="profile-card">
        <div class="profile-header">
          <div class="avatar-section">
            <div class="avatar">
              <span class="avatar-text">{{ user.username?.charAt(0)?.toUpperCase() }}</span>
            </div>
            <div class="avatar-info">
              <h2 class="user-name">{{ user.username }}</h2>
              <el-tag
                size="small"
                :type="roleTagType(user.role)"
                effect="light"
                class="role-tag"
              >
                {{ roleLabel(user.role) }}
              </el-tag>
            </div>
          </div>
          <el-button
            type="primary"
            size="small"
            class="edit-btn"
            @click="openPasswordDialog"
          >
            <el-icon><Lock /></el-icon>
            <span>修改密码</span>
          </el-button>
        </div>

        <div class="profile-body">
          <div class="info-grid">
            <div class="info-item">
              <div class="info-icon">
                <el-icon :size="20"><Message /></el-icon>
              </div>
              <div class="info-content">
                <span class="info-label">邮箱</span>
                <span class="info-value">{{ user.email || '未设置' }}</span>
              </div>
            </div>
            <div class="info-item">
              <div class="info-icon">
                <el-icon :size="20"><Calendar /></el-icon>
              </div>
              <div class="info-content">
                <span class="info-label">注册时间</span>
                <span class="info-value">{{ user.created_at || '-' }}</span>
              </div>
            </div>
            <div class="info-item">
              <div class="info-icon">
                <el-icon :size="20"><Key /></el-icon>
              </div>
              <div class="info-content">
                <span class="info-label">用户 ID</span>
                <span class="info-value">{{ user.id || '-' }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 快捷操作 -->
      <div class="quick-actions">
        <router-link to="/watchlist" class="action-card">
          <div class="action-icon">
            <el-icon :size="24"><Star /></el-icon>
          </div>
          <div class="action-content">
            <h3>我的自选</h3>
            <p>管理您关注的股票</p>
          </div>
          <el-icon :size="18" class="action-arrow"><ArrowRight /></el-icon>
        </router-link>

        <router-link to="/alerts" class="action-card">
          <div class="action-icon warning">
            <el-icon :size="24"><Bell /></el-icon>
          </div>
          <div class="action-content">
            <h3>价格预警</h3>
            <p>设置股票提醒</p>
          </div>
          <el-icon :size="18" class="action-arrow"><ArrowRight /></el-icon>
        </router-link>

        <router-link to="/settings" class="action-card">
          <div class="action-icon info">
            <el-icon :size="24"><Setting /></el-icon>
          </div>
          <div class="action-content">
            <h3>系统设置</h3>
            <p>配置和调试</p>
          </div>
          <el-icon :size="18" class="action-arrow"><ArrowRight /></el-icon>
        </router-link>
      </div>
    </template>

    <!-- 修改密码弹窗 -->
    <el-dialog
      v-model="passwordDialogVisible"
      title="修改密码"
      width="min(480px, calc(100vw - 32px))"
      :close-on-click-modal="!changingPassword"
      :close-on-press-escape="!changingPassword"
      @closed="resetPasswordForm"
      class="password-dialog"
    >
      <el-form
        ref="passwordFormRef"
        :model="passwordForm"
        :rules="passwordRules"
        label-position="top"
        class="password-form"
        @submit.prevent
      >
        <el-form-item label="当前密码" prop="currentPassword">
          <el-input
            v-model="passwordForm.currentPassword"
            type="password"
            show-password
            autocomplete="current-password"
            placeholder="请输入当前密码"
            size="large"
          />
        </el-form-item>

        <el-form-item label="新密码" prop="newPassword">
          <el-input
            v-model="passwordForm.newPassword"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="请输入新密码"
            size="large"
          />
        </el-form-item>

        <el-form-item label="确认密码" prop="confirmPassword">
          <el-input
            v-model="passwordForm.confirmPassword"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="请再次输入新密码"
            size="large"
            @keyup.enter="submitPasswordChange"
          />
        </el-form-item>

        <div class="password-hints">
          <p>密码要求：</p>
          <ul>
            <li :class="{ met: hasMinLength }">至少 8 个字符</li>
            <li :class="{ met: hasUpperCase }">包含大写字母</li>
            <li :class="{ met: hasLowerCase }">包含小写字母</li>
            <li :class="{ met: hasNumber }">包含数字</li>
            <li :class="{ met: isDifferent }">与当前密码不同</li>
          </ul>
        </div>
      </el-form>

      <template #footer>
        <div class="dialog-footer">
          <el-button :disabled="changingPassword" @click="closePasswordDialog">
            取消
          </el-button>
          <el-button
            type="primary"
            :loading="changingPassword"
            @click="submitPasswordChange"
          >
            保存新密码
          </el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  User,
  Lock,
  Message,
  Calendar,
  Key,
  Star,
  Bell,
  Setting,
  ArrowRight,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { userApi } from '@/api'
import { useUserStore, type UserInfo } from '@/stores/user'

const userStore = useUserStore()
const user = computed<UserInfo>(() => userStore.userInfo || { id: 0, username: '' })
const isLoggedIn = computed(() => userStore.isLoggedIn)
const passwordFormRef = ref<FormInstance>()
const changingPassword = ref(false)
const passwordDialogVisible = ref(false)
const passwordForm = reactive({
  currentPassword: '',
  newPassword: '',
  confirmPassword: '',
})

// Password strength indicators
const hasMinLength = computed(() => passwordForm.newPassword.length >= 8)
const hasUpperCase = computed(() => /[A-Z]/.test(passwordForm.newPassword))
const hasLowerCase = computed(() => /[a-z]/.test(passwordForm.newPassword))
const hasNumber = computed(() => /\d/.test(passwordForm.newPassword))
const isDifferent = computed(() => passwordForm.currentPassword !== passwordForm.newPassword && passwordForm.newPassword.length > 0)

const validateNewPassword = (_rule: unknown, value: string, callback: (error?: Error) => void) => {
  if (!value) {
    callback()
    return
  }
  if (!/[A-Z]/.test(value)) {
    callback(new Error('新密码需包含至少一个大写字母'))
    return
  }
  if (!/[a-z]/.test(value)) {
    callback(new Error('新密码需包含至少一个小写字母'))
    return
  }
  if (!/\d/.test(value)) {
    callback(new Error('新密码需包含至少一个数字'))
    return
  }
  if (passwordForm.currentPassword && value === passwordForm.currentPassword) {
    callback(new Error('新密码不能和当前密码相同'))
    return
  }
  callback()
}

const validateConfirmPassword = (_rule: unknown, value: string, callback: (error?: Error) => void) => {
  if (!value) {
    callback(new Error('请再次输入新密码'))
    return
  }
  if (value !== passwordForm.newPassword) {
    callback(new Error('两次输入的新密码不一致'))
    return
  }
  callback()
}

const passwordRules: FormRules = {
  currentPassword: [
    { required: true, message: '请输入当前密码', trigger: 'blur' },
  ],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, max: 128, message: '新密码长度需为 8-128 位', trigger: 'blur' },
    { validator: validateNewPassword, trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    { validator: validateConfirmPassword, trigger: ['blur', 'change'] },
  ],
}

function roleLabel(role?: string) {
  if (role === 'admin') return '管理员'
  if (role === 'premium') return '付费会员'
  return '免费用户'
}

function roleTagType(role?: string) {
  if (role === 'admin') return 'danger'
  if (role === 'premium') return 'warning'
  return 'info'
}

function openPasswordDialog() {
  passwordDialogVisible.value = true
}

function closePasswordDialog() {
  if (changingPassword.value) return
  passwordDialogVisible.value = false
}

function resetPasswordForm() {
  passwordForm.currentPassword = ''
  passwordForm.newPassword = ''
  passwordForm.confirmPassword = ''
  passwordFormRef.value?.clearValidate()
}

async function submitPasswordChange() {
  if (!passwordFormRef.value || changingPassword.value) return

  const valid = await passwordFormRef.value.validate().catch(() => false)
  if (!valid) return

  changingPassword.value = true
  try {
    const result = await userApi.changePassword(passwordForm.currentPassword, passwordForm.newPassword)
    ElMessage.success(result.message || '密码已修改')
    passwordDialogVisible.value = false
  } catch (error) {
    const message = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    ElMessage.error(message || '修改密码失败')
  } finally {
    changingPassword.value = false
  }
}

onMounted(async () => {
  await userStore.fetchMe()
})
</script>

<style scoped>
.profile-page {
  max-width: 800px;
  margin: 0 auto;
}

/* Login prompt */
.login-prompt-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-12);
  text-align: center;
  box-shadow: var(--shadow-card);
}

.login-prompt-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-4);
}

.login-prompt-content h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 800;
  color: var(--color-text);
}

.login-prompt-content p {
  margin: 0;
  color: var(--color-text-muted);
  font-size: 14px;
}

.prompt-icon {
  color: var(--color-border-strong);
}

/* Profile card */
.profile-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
  box-shadow: var(--shadow-card);
  margin-bottom: var(--space-5);
}

.profile-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-6);
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border-bottom: 1px solid var(--color-border);
}

.avatar-section {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.avatar {
  width: 64px;
  height: 64px;
  border-radius: 50%;
  background: linear-gradient(135deg, #1d4ed8 0%, #6366f1 100%);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 4px 14px rgba(29, 78, 216, 0.25);
}

.avatar-text {
  font-size: 28px;
  font-weight: 800;
  color: #fff;
}

.avatar-info {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.user-name {
  margin: 0;
  font-size: 22px;
  font-weight: 800;
  color: var(--color-text);
  letter-spacing: -0.01em;
}

.role-tag {
  font-weight: 700;
  width: fit-content;
}

.edit-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

/* Profile body */
.profile-body {
  padding: var(--space-5);
}

.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: var(--space-4);
}

.info-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4);
  background: var(--color-surface-muted);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
  transition: all var(--transition-fast);
}

.info-item:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-card);
}

.info-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, #e8f0ff 0%, #f0f7ff 100%);
  color: var(--color-primary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.info-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.info-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.info-value {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Quick actions */
.quick-actions {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: var(--space-4);
}

.action-card {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-5);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  text-decoration: none;
  color: inherit;
  transition: all var(--transition-base);
  box-shadow: var(--shadow-card);
}

.action-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-2px);
}

.action-icon {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, #e8f0ff 0%, #f0f7ff 100%);
  color: var(--color-primary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.action-icon.warning {
  background: linear-gradient(135deg, #fff7e6 0%, #fff0d6 100%);
  color: var(--color-warning);
}

.action-icon.info {
  background: linear-gradient(135deg, #e6f7ff 0%, #d6f0ff 100%);
  color: #0ea5e9;
}

.action-content {
  flex: 1;
  min-width: 0;
}

.action-content h3 {
  margin: 0 0 2px;
  font-size: 15px;
  font-weight: 700;
  color: var(--color-text);
}

.action-content p {
  margin: 0;
  font-size: 13px;
  color: var(--color-text-muted);
}

.action-arrow {
  color: var(--color-text-muted);
  transition: all var(--transition-fast);
}

.action-card:hover .action-arrow {
  color: var(--color-primary);
  transform: translateX(4px);
}

/* Password dialog */
.password-dialog :deep(.el-dialog__header) {
  margin-right: 0;
  padding: var(--space-5) var(--space-5) 0;
}

.password-dialog :deep(.el-dialog__body) {
  padding: var(--space-4) var(--space-5);
}

.password-form :deep(.el-form-item__label) {
  font-weight: 700;
  color: var(--color-text);
  padding-bottom: 4px;
}

.password-hints {
  margin-top: var(--space-4);
  padding: var(--space-4);
  background: var(--color-surface-muted);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
}

.password-hints p {
  margin: 0 0 var(--space-2);
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text-secondary);
}

.password-hints ul {
  margin: 0;
  padding-left: var(--space-5);
  list-style: none;
}

.password-hints li {
  font-size: 13px;
  color: var(--color-text-muted);
  padding: 2px 0;
  position: relative;
}

.password-hints li::before {
  content: '○';
  position: absolute;
  left: -20px;
  font-size: 10px;
}

.password-hints li.met {
  color: var(--color-success);
  font-weight: 700;
}

.password-hints li.met::before {
  content: '✓';
  color: var(--color-success);
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-3);
}

/* Responsive */
@media (max-width: 640px) {
  .profile-header {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-4);
  }

  .edit-btn {
    width: 100%;
  }

  .info-grid {
    grid-template-columns: 1fr;
  }

  .quick-actions {
    grid-template-columns: 1fr;
  }
}
</style>
