<template>
  <div class="settings-page">
    <h2 class="page-title">系统设置</h2>

    <el-card class="config-card">
      <template #header>
        <span>API 配置</span>
      </template>

      <el-form label-width="120px">
        <el-form-item label="API 地址">
          <el-input
            v-model="apiBaseUrl"
            placeholder="http://localhost:8001"
            clearable
          />
          <div class="form-tip">例如: http://localhost:8001 或 http://192.168.1.100:8001</div>
        </el-form-item>

        <el-form-item>
          <el-button type="primary" @click="saveSettings">保存设置</el-button>
          <el-button @click="resetSettings">恢复默认</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="config-card" style="margin-top: 16px">
      <template #header>
        <span>连接测试</span>
      </template>

      <el-form label-width="120px">
        <el-form-item label="测试地址">
          <el-input v-model="testUrl" placeholder="/api/v1/stocks" />
        </el-form-item>

        <el-form-item>
          <el-button type="success" @click="testConnection" :loading="testing">
            {{ testing ? '测试中...' : '测试连接' }}
          </el-button>
        </el-form-item>

        <el-form-item v-if="testResult" label="测试结果">
          <el-alert
            :type="testResult.success ? 'success' : 'error'"
            :title="testResult.success ? '连接成功' : '连接失败'"
            :description="testResult.message"
            show-icon
            :closable="false"
          />
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="config-card" style="margin-top: 16px">
      <template #header>
        <span>当前配置信息</span>
      </template>

      <el-descriptions :column="1" border>
        <el-descriptions-item label="API 地址">{{ currentBaseURL }}</el-descriptions-item>
        <el-descriptions-item label="Token">{{ hasToken ? '已设置' : '未设置' }}</el-descriptions-item>
        <el-descriptions-item label="前端版本">0.1.0</el-descriptions-item>
      </el-descriptions>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'

const apiBaseUrl = ref('')
const testUrl = ref('/api/v1/stocks')
const testing = ref(false)
const testResult = ref<{ success: boolean; message: string } | null>(null)

const currentBaseURL = computed(() => {
  return localStorage.getItem('api_base_url') || 'http://localhost:8001 (默认)'
})

const hasToken = computed(() => {
  return !!localStorage.getItem('access_token')
})

onMounted(() => {
  apiBaseUrl.value = localStorage.getItem('api_base_url') || 'http://localhost:8001'
})

function saveSettings() {
  const url = apiBaseUrl.value.trim()
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
  apiBaseUrl.value = 'http://localhost:8001'
  ElMessage.info('已恢复默认设置')
}

async function testConnection() {
  testing.value = true
  testResult.value = null
  const base = apiBaseUrl.value.trim() || 'http://localhost:8001'
  try {
    const res = await axios.get(`${base}${testUrl.value}`, { timeout: 5000 })
    testResult.value = {
      success: true,
      message: `响应状态: ${res.status}, 数据: ${JSON.stringify(res.data).substring(0, 200)}`
    }
  } catch (e: any) {
    testResult.value = {
      success: false,
      message: e.message || '连接失败'
    }
  } finally {
    testing.value = false
  }
}
</script>

<style scoped>
.page-title {
  margin-bottom: 20px;
}

.config-card {
  max-width: 700px;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
</style>
