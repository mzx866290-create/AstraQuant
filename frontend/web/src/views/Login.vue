<template>
  <div class="login-page">
    <div class="login-container">
      <!-- 左侧品牌区域 -->
      <div class="login-brand">
        <div class="brand-content">
          <div class="brand-logo">
            <span class="logo-mark">S</span>
          </div>
          <h1 class="brand-title">股票数据分析平台</h1>
          <p class="brand-desc">智能分析 · 数据驱动 · 辅助决策</p>
          <div class="brand-features">
            <div class="feature-item">
              <el-icon :size="20" class="feature-icon"><TrendCharts /></el-icon>
              <span>实时行情</span>
            </div>
            <div class="feature-item">
              <el-icon :size="20" class="feature-icon"><Cpu /></el-icon>
              <span>AI 智能分析</span>
            </div>
            <div class="feature-item">
              <el-icon :size="20" class="feature-icon"><DataLine /></el-icon>
              <span>多维度数据</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧表单区域 -->
      <div class="login-form-section">
        <div class="form-wrapper">
          <div class="form-header">
            <h2 class="form-title">{{ isLogin ? '欢迎回来' : '创建账号' }}</h2>
            <p class="form-subtitle">{{ isLogin ? '登录以访问您的投资组合' : '注册开始使用智能分析' }}</p>
          </div>

          <el-form
            ref="formRef"
            :model="form"
            :rules="rules"
            class="login-form"
            @submit.prevent="handleSubmit"
          >
            <el-form-item prop="username">
              <el-input
                v-model="form.username"
                size="large"
                placeholder="请输入用户名"
                :prefix-icon="User"
                clearable
              />
            </el-form-item>

            <el-form-item v-if="!isLogin" prop="email">
              <el-input
                v-model="form.email"
                size="large"
                placeholder="请输入邮箱"
                :prefix-icon="Message"
                clearable
              />
            </el-form-item>

            <el-form-item prop="password">
              <el-input
                v-model="form.password"
                size="large"
                type="password"
                show-password
                placeholder="请输入密码"
                :prefix-icon="Lock"
                @keyup.enter="handleSubmit"
              />
            </el-form-item>

            <el-form-item>
              <el-button
                type="primary"
                size="large"
                class="submit-btn"
                :loading="loading"
                @click="handleSubmit"
              >
                {{ isLogin ? '登 录' : '注 册' }}
              </el-button>
            </el-form-item>
          </el-form>

          <div class="form-footer">
            <div class="divider">
              <span class="divider-text">或</span>
            </div>
            <el-button
              link
              type="primary"
              class="toggle-btn"
              @click="isLogin = !isLogin"
            >
              {{ isLogin ? '没有账号？立即注册' : '已有账号？立即登录' }}
            </el-button>
          </div>

          <p class="form-disclaimer">
            登录即表示您同意我们的服务条款和隐私政策
          </p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { User, Lock, Message, TrendCharts, Cpu, DataLine } from '@element-plus/icons-vue'
import { userApi } from '@/api'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const isLogin = ref(true)
const loading = ref(false)
const formRef = ref()

const form = reactive({
  username: '',
  email: '',
  password: '',
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  email: [{ required: true, message: '请输入邮箱', trigger: 'blur' }],
  password: [{ required: true, min: 8, message: '密码至少8位', trigger: 'blur' }],
}

function getSafeRedirect() {
  const raw = route.query.redirect
  const redirect = Array.isArray(raw) ? raw[0] : raw
  if (!redirect || !redirect.startsWith('/') || redirect.startsWith('//')) return '/'

  try {
    const url = new URL(redirect, window.location.origin)
    if (url.origin !== window.location.origin) return '/'
    return `${url.pathname}${url.search}${url.hash}` || '/'
  } catch {
    return '/'
  }
}

async function handleSubmit() {
  if (!formRef.value) return
  await formRef.value.validate()
  loading.value = true
  try {
    if (isLogin.value) {
      await userStore.login(form.username, form.password)
      ElMessage.success('登录成功')
      router.push(getSafeRedirect())
    } else {
      await userApi.register(form.username, form.email, form.password)
      ElMessage.success('注册成功，请登录')
      isLogin.value = true
    }
  } catch (error) {
    const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
    const msg = Array.isArray(detail) ? detail.map((d) => (d as { msg?: string }).msg).filter(Boolean).join('; ') : (detail || '操作失败')
    ElMessage.error(msg as string)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  background: linear-gradient(135deg, #f4f7fb 0%, #e8ecf4 100%);
}

.login-container {
  display: grid;
  grid-template-columns: 1fr 1fr;
  width: 100%;
  max-width: 1200px;
  margin: 0 auto;
  min-height: 100vh;
}

/* 左侧品牌区域 */
.login-brand {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-8);
  background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #1d4ed8 100%);
  position: relative;
  overflow: hidden;
}

.login-brand::before {
  content: '';
  position: absolute;
  top: -50%;
  right: -50%;
  width: 100%;
  height: 100%;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.3) 0%, transparent 70%);
}

.login-brand::after {
  content: '';
  position: absolute;
  bottom: -30%;
  left: -30%;
  width: 80%;
  height: 80%;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.2) 0%, transparent 70%);
}

.brand-content {
  position: relative;
  z-index: 1;
  text-align: center;
  color: #fff;
}

.brand-logo {
  margin-bottom: var(--space-6);
}

.logo-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 80px;
  height: 80px;
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 20px;
  font-size: 36px;
  font-weight: 800;
  color: #fff;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
}

.brand-title {
  font-size: 28px;
  font-weight: 800;
  margin: 0 0 var(--space-3);
  letter-spacing: -0.02em;
}

.brand-desc {
  font-size: 16px;
  color: rgba(255, 255, 255, 0.7);
  margin: 0 0 var(--space-8);
}

.brand-features {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  align-items: center;
}

.feature-item {
  display: inline-flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-5);
  background: rgba(255, 255, 255, 0.08);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: var(--radius-md);
  font-size: 14px;
  font-weight: 600;
  color: rgba(255, 255, 255, 0.9);
  transition: all var(--transition-base);
}

.feature-item:hover {
  background: rgba(255, 255, 255, 0.15);
  transform: translateY(-2px);
}

.feature-icon {
  color: #818cf8;
}

/* 右侧表单区域 */
.login-form-section {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-8);
}

.form-wrapper {
  width: 100%;
  max-width: 420px;
}

.form-header {
  text-align: center;
  margin-bottom: var(--space-8);
}

.form-title {
  font-size: 28px;
  font-weight: 800;
  color: var(--color-text);
  margin: 0 0 var(--space-2);
  letter-spacing: -0.02em;
}

.form-subtitle {
  font-size: 14px;
  color: var(--color-text-muted);
  margin: 0;
}

.login-form :deep(.el-input__wrapper) {
  border-radius: var(--radius-md);
  box-shadow: 0 0 0 1px var(--color-border-strong) inset;
  transition: all var(--transition-fast);
}

.login-form :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--color-primary) inset;
}

.login-form :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--color-primary) inset, 0 0 0 4px var(--color-primary-soft);
}

.submit-btn {
  width: 100%;
  height: 48px;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.05em;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, #1d4ed8 0%, #6366f1 100%);
  border: none;
  transition: all var(--transition-base);
  box-shadow: 0 4px 14px rgba(29, 78, 216, 0.35);
}

.submit-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(29, 78, 216, 0.45);
}

.submit-btn:active {
  transform: translateY(0);
}

.form-footer {
  margin-top: var(--space-6);
  text-align: center;
}

.divider {
  position: relative;
  margin-bottom: var(--space-4);
}

.divider::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 0;
  right: 0;
  height: 1px;
  background: var(--color-border);
}

.divider-text {
  position: relative;
  display: inline-block;
  padding: 0 var(--space-3);
  background: #f4f7fb;
  color: var(--color-text-muted);
  font-size: 13px;
}

.toggle-btn {
  font-size: 14px;
  font-weight: 600;
}

.form-disclaimer {
  margin-top: var(--space-6);
  text-align: center;
  font-size: 12px;
  color: var(--color-text-muted);
  line-height: 1.5;
}

/* 动画 */
@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.login-brand {
  animation: fadeInUp 0.6s ease-out;
}

.login-form-section {
  animation: fadeInUp 0.6s ease-out 0.15s backwards;
}

/* 响应式 */
@media (max-width: 768px) {
  .login-container {
    grid-template-columns: 1fr;
  }

  .login-brand {
    display: none;
  }

  .login-form-section {
    padding: var(--space-5);
  }

  .form-wrapper {
    max-width: 100%;
  }
}
</style>
