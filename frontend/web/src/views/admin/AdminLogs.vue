<template>
  <div class="admin-logs">
    <div class="header">
      <h1>调用日志</h1>
      <button @click="exportLogs" class="btn-secondary">导出 CSV</button>
    </div>

    <div class="filters">
      <input v-model="filters.stock_symbol" placeholder="股票代码" class="filter-input" />
      <select v-model="filters.status" class="filter-select">
        <option value="">全部状态</option>
        <option value="success">成功</option>
        <option value="error">失败</option>
      </select>
      <button @click="loadLogs" class="btn-primary">查询</button>
    </div>

    <div v-if="loading" class="loading">加载中...</div>

    <table v-else class="logs-table">
      <thead>
        <tr>
          <th>时间</th>
          <th>用户</th>
          <th>模型</th>
          <th>股票</th>
          <th>Token</th>
          <th>费用</th>
          <th>状态</th>
          <th>耗时</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="log in logs" :key="log.id">
          <td>{{ formatDate(log.created_at) }}</td>
          <td>{{ log.username || log.user_id }}</td>
          <td>{{ log.model_name }}</td>
          <td>{{ log.stock_symbol || '-' }}</td>
          <td>{{ log.total_tokens }}</td>
          <td>${{ log.cost?.toFixed(6) || 0 }}</td>
          <td>
            <span :class="log.status === 'success' ? 'status-success' : 'status-error'">
              {{ log.status }}
            </span>
          </td>
          <td>{{ log.response_time_ms }}ms</td>
        </tr>
        <tr v-if="!logs.length">
          <td colspan="8" class="no-data">暂无日志</td>
        </tr>
      </tbody>
    </table>

    <div class="pagination">
      <button @click="prevPage" :disabled="page <= 1" class="btn-small">上一页</button>
      <span>第 {{ page }} 页</span>
      <button @click="nextPage" :disabled="logs.length < limit" class="btn-small">下一页</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { adminApi } from '@/api'
import { ElMessage } from 'element-plus'

const loading = ref(true)
const logs = ref<any[]>([])
const page = ref(1)
const limit = 20
const filters = ref({ stock_symbol: '', status: '' })

async function loadLogs() {
  try {
    loading.value = true
    logs.value = await adminApi.getLogs({
      skip: (page.value - 1) * limit,
      limit,
      stock_symbol: filters.value.stock_symbol || undefined,
      status: filters.value.status || undefined,
    })
  } catch (e) {
    ElMessage.error('加载日志失败')
  } finally {
    loading.value = false
  }
}

function prevPage() {
  if (page.value > 1) {
    page.value--
    loadLogs()
  }
}

function nextPage() {
  page.value++
  loadLogs()
}

function formatDate(dateStr: string) {
  if (!dateStr) return '-'
  return new Date(dateStr).toLocaleString('zh-CN')
}

async function exportLogs() {
  try {
    ElMessage.info('正在导出...')
    const blob = await adminApi.exportLogs({
      stock_symbol: filters.value.stock_symbol || undefined,
      status: filters.value.status || undefined,
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'ai_usage_logs.csv'
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (e) {
    ElMessage.error('导出失败')
  }
}

onMounted(loadLogs)
</script>

<style scoped>
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

h1 { margin: 0; }

.filters {
  display: flex;
  gap: 10px;
  margin-bottom: 15px;
}

.filter-input, .filter-select {
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
}

.loading, .no-data {
  text-align: center;
  padding: 40px;
  color: #999;
}

.logs-table {
  width: 100%;
  background: #fff;
  border-radius: 8px;
  border-collapse: collapse;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.logs-table th,
.logs-table td {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid #eee;
  font-size: 13px;
}

.logs-table th {
  background: #f9f9f9;
  font-weight: 600;
}

.status-success { color: #10a37f; font-weight: 500; }
.status-error { color: #dc2626; font-weight: 500; }

.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 15px;
  margin-top: 20px;
}

.btn-small {
  padding: 6px 12px;
  border: 1px solid #ddd;
  background: #fff;
  border-radius: 4px;
  cursor: pointer;
}

.btn-small:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  padding: 8px 16px;
  background: #7c3aed;
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.btn-secondary {
  padding: 8px 16px;
  background: #fff;
  color: #333;
  border: 1px solid #ddd;
  border-radius: 4px;
  cursor: pointer;
}
</style>