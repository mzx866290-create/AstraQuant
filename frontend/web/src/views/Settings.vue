<template>
  <div class="settings-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">系统设置</h1>
        <p class="page-subtitle">配置 API 连接和调试选项</p>
      </div>
    </div>

    <div class="settings-grid">
      <!-- API 配置 -->
      <div class="setting-card">
        <div class="card-header">
          <div class="card-icon">
            <el-icon :size="24"><Connection /></el-icon>
          </div>
          <div class="card-title">
            <h3>API 配置</h3>
            <p>自定义后端服务地址</p>
          </div>
        </div>

        <el-form label-position="top" class="setting-form">
          <el-form-item>
            <template #label>
              <div class="form-label">
                <el-icon :size="14"><Link /></el-icon>
                <span>API 地址</span>
              </div>
            </template>
            <el-input
              v-model="apiBaseUrl"
              placeholder="留空使用当前站点"
              clearable
              size="large"
              class="url-input"
            >
              <template #prefix>
                <el-icon :size="16"><Link /></el-icon>
              </template>
            </el-input>
            <div class="form-tip">
              <el-icon :size="14"><InfoFilled /></el-icon>
              <span>推荐留空走同源网关；如需自定义，请填写统一网关地址，不要直连 8001/8002/8003。</span>
            </div>
          </el-form-item>

          <el-form-item>
            <div class="form-actions">
              <el-button type="primary" @click="saveSettings">
                <el-icon><Check /></el-icon>
                <span>保存设置</span>
              </el-button>
              <el-button @click="resetSettings">
                <el-icon><Refresh /></el-icon>
                <span>恢复默认</span>
              </el-button>
            </div>
          </el-form-item>
        </el-form>
      </div>

      <!-- 连接测试 -->
      <div class="setting-card">
        <div class="card-header">
          <div class="card-icon test">
            <el-icon :size="24"><Cpu /></el-icon>
          </div>
          <div class="card-title">
            <h3>连接测试</h3>
            <p>验证后端服务连通性</p>
          </div>
        </div>

        <el-form label-position="top" class="setting-form">
          <el-form-item>
            <template #label>
              <div class="form-label">
                <el-icon :size="14"><Link /></el-icon>
                <span>测试地址</span>
              </div>
            </template>
            <el-input
              v-model="testUrl"
              placeholder="/api/v1/stocks"
              size="large"
              class="url-input"
            >
              <template #prefix>
                <el-icon :size="16"><Link /></el-icon>
              </template>
            </el-input>
          </el-form-item>

          <el-form-item>
            <el-button
              type="success"
              :loading="testing"
              @click="testConnection"
            >
              <el-icon><Promotion /></el-icon>
              <span>{{ testing ? '测试中...' : '测试连接' }}</span>
            </el-button>
          </el-form-item>

          <el-form-item v-if="testResult">
            <div
              class="test-result"
              :class="testResult.success ? 'success' : 'error'"
            >
              <div class="test-result-header">
                <el-icon :size="24">
                  <SuccessFilled v-if="testResult.success" />
                  <CircleCloseFilled v-else />
                </el-icon>
                <div class="test-result-title">
                  <h4>{{ testResult.success ? '连接成功' : '连接失败' }}</h4>
                  <p>{{ testResult.message }}</p>
                </div>
              </div>
            </div>
          </el-form-item>
        </el-form>
      </div>

      <!-- 当前配置 -->
      <div class="setting-card">
        <div class="card-header">
          <div class="card-icon info">
            <el-icon :size="24"><InfoFilled /></el-icon>
          </div>
          <div class="card-title">
            <h3>当前配置</h3>
            <p>系统和会话信息</p>
          </div>
        </div>

        <div class="config-list">
          <div class="config-item">
            <div class="config-icon">
              <el-icon :size="18"><Link /></el-icon>
            </div>
            <div class="config-content">
              <span class="config-label">API 地址</span>
              <span class="config-value">{{ currentBaseURL }}</span>
            </div>
          </div>
          <div class="config-item">
            <div class="config-icon">
              <el-icon :size="18"><Key /></el-icon>
            </div>
            <div class="config-content">
              <span class="config-label">登录状态</span>
              <span class="config-value">
                <el-tag
                  :type="hasToken ? 'success' : 'info'"
                  size="small"
                  effect="light"
                >
                  {{ hasToken ? '已登录' : '未登录' }}
                </el-tag>
              </span>
            </div>
          </div>
          <div class="config-item">
            <div class="config-icon">
              <el-icon :size="18"><Version /></el-icon>
            </div>
            <div class="config-content">
              <span class="config-label">前端版本</span>
              <span class="config-value">0.1.0</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import {
  Connection,
  Link,
  InfoFilled,
  Check,
  Refresh,
  Cpu,
  Promotion,
  SuccessFilled,
  CircleCloseFilled,
  Key,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'
import { isDirectServiceBaseUrl, normalizeApiBaseUrl } from '@/api'
import { useUserStore } from '@/stores/user'

// Custom icon component
const Version = {
  render() {
    return h('svg', {
      xmlns: 'http://www.w3.org/2000/svg',
      viewBox: '0 0 24 24',
      fill: 'none',
      stroke: 'currentColor',
      'stroke-width': '2',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
      width: '1em',
      height: '1em',
    }, [
      h('path', { d: 'M4 7V4h3M4 17v3h3M20 7V4h-3M20 17v3h-3M9 9h6v6H9z' }),
    ])
  },
}

import { h } from 'vue'

interface ApiErrorLike {
  message?: string
}

const userStore = useUserStore()
const apiBaseUrl = ref('')
const testUrl = ref('/api/v1/stocks')
const testing = ref(false)
const testResult = ref<{ success: boolean; message: string } | null>(null)
const defaultBaseURLLabel = '同源网关代理（推荐）'

const currentBaseURL = computed(() => {
  return normalizeApiBaseUrl(localStorage.getItem('api_base_url')) || defaultBaseURLLabel
})

const hasToken = computed(() => userStore.isLoggedIn)

onMounted(() => {
  apiBaseUrl.value = normalizeApiBaseUrl(localStorage.getItem('api_base_url'))
})

function saveSettings() {
  const url = normalizeApiBaseUrl(apiBaseUrl.value)
  if (url && isDirectServiceBaseUrl(url)) {
    ElMessage.warning('请填写统一网关地址，不要直连 8001/8002/8003。')
    return
  }
  if (url) {
    localStorage.setItem('api_base_url', url)
    ElMessage.success('API 地址已保存')
  } else {
    localStorage.removeItem('api_base_url')
    ElMessage.success('已恢复为默认地址')
  }
}

function resetSettings() {
  localStorage.removeItem('api_base_url')
  apiBaseUrl.value = ''
  ElMessage.info('已恢复默认设置')
}

async function testConnection() {
  const base = normalizeApiBaseUrl(apiBaseUrl.value)
  if (base && isDirectServiceBaseUrl(base)) {
    ElMessage.warning('测试前请改成统一网关地址，或直接留空使用当前站点。')
    return
  }
  testing.value = true
  testResult.value = null
  try {
    const res = await axios.get(`${base}${testUrl.value}`, { timeout: 5000 })
    testResult.value = {
      success: true,
      message: `响应状态: ${res.status}，数据长度: ${JSON.stringify(res.data).length} 字符`,
    }
  } catch (error) {
    testResult.value = {
      success: false,
      message: (error as ApiErrorLike).message || '连接失败，请检查网络或 API 地址',
    }
  } finally {
    testing.value = false
  }
}
</script>

<style scoped>
.settings-page {
  max-width: 800px;
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

/* Settings Grid */
.settings-grid {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.setting-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
  box-shadow: var(--shadow-card);
  transition: all var(--transition-base);
}

.setting-card:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-card-hover);
}

.card-header {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-5);
  background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
  border-bottom: 1px solid var(--color-border);
}

.card-icon {
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

.card-icon.test {
  background: linear-gradient(135deg, #dcfce7 0%, #bbf7d0 100%);
  color: #16a34a;
}

.card-icon.info {
  background: linear-gradient(135deg, #f3e8ff 0%, #e9d5ff 100%);
  color: #9333ea;
}

.card-title {
  flex: 1;
  min-width: 0;
}

.card-title h3 {
  margin: 0 0 2px;
  font-size: 18px;
  font-weight: 800;
  color: var(--color-text);
  letter-spacing: -0.01em;
}

.card-title p {
  margin: 0;
  font-size: 13px;
  color: var(--color-text-muted);
}

/* Form */
.setting-form {
  padding: var(--space-5);
}

.form-label {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  font-weight: 700;
  color: var(--color-text);
}

.url-input :deep(.el-input__wrapper) {
  border-radius: var(--radius-md);
  box-shadow: 0 0 0 1px var(--color-border-strong) inset;
  transition: all var(--transition-fast);
}

.url-input :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--color-primary) inset;
}

.url-input :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--color-primary) inset, 0 0 0 4px var(--color-primary-soft);
}

.form-tip {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  margin-top: var(--space-2);
  padding: var(--space-3);
  background: var(--color-warning-soft);
  border: 1px solid rgba(196, 122, 16, 0.15);
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--color-warning);
  line-height: 1.5;
}

.form-tip :deep(svg) {
  flex-shrink: 0;
  margin-top: 2px;
}

.form-actions {
  display: flex;
  gap: var(--space-3);
}

/* Test result */
.test-result {
  border-radius: var(--radius-md);
  overflow: hidden;
  animation: slideDown 0.3s ease-out;
}

.test-result.success {
  background: var(--color-success-bg);
  border: 1px solid rgba(22, 163, 106, 0.2);
}

.test-result.error {
  background: var(--color-danger-soft);
  border: 1px solid rgba(226, 59, 59, 0.15);
}

.test-result-header {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  padding: var(--space-4);
}

.test-result.success .test-result-header {
  color: var(--color-success);
}

.test-result.error .test-result-header {
  color: var(--color-up);
}

.test-result-title {
  flex: 1;
  min-width: 0;
}

.test-result-title h4 {
  margin: 0 0 var(--space-1);
  font-size: 16px;
  font-weight: 800;
  color: var(--color-text);
}

.test-result-title p {
  margin: 0;
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.5;
  word-break: break-all;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Config List */
.config-list {
  padding: var(--space-5);
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.config-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--color-surface-muted);
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border);
  transition: all var(--transition-fast);
}

.config-item:hover {
  border-color: var(--color-border-strong);
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.04);
}

.config-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-sm);
  background: linear-gradient(135deg, #e8f0ff 0%, #f0f7ff 100%);
  color: var(--color-primary);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.config-content {
  flex: 1;
  min-width: 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
}

.config-label {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}

.config-value {
  font-size: 13px;
  color: var(--color-text-secondary);
  font-weight: 600;
  font-family: var(--font-number);
}

/* Responsive */
@media (max-width: 640px) {
  .form-actions {
    flex-direction: column;
  }

  .form-actions .el-button {
    width: 100%;
  }

  .config-content {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-1);
  }
}
</style>
