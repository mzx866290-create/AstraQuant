<template>
  <div class="admin-logs">
    <div class="header">
      <h1>Logs</h1>
      <button v-if="activeTab === 'usage'" @click="exportLogs" class="btn-secondary">Export CSV</button>
    </div>

    <div class="tabs" role="tablist" aria-label="Admin logs">
      <button
        class="tab-button"
        :class="{ active: activeTab === 'usage' }"
        @click="switchTab('usage')"
      >
        AI Usage
      </button>
      <button
        class="tab-button"
        :class="{ active: activeTab === 'activity' }"
        @click="switchTab('activity')"
      >
        User Activity
      </button>
    </div>

    <div v-if="activeTab === 'usage'" class="filters">
      <input v-model="usageFilters.stock_symbol" placeholder="Stock symbol" class="filter-input" />
      <select v-model="usageFilters.status" class="filter-select">
        <option value="">All status</option>
        <option value="success">Success</option>
        <option value="error">Error</option>
        <option value="timeout">Timeout</option>
      </select>
      <button @click="searchLogs" class="btn-primary">Search</button>
    </div>

    <div v-else class="filters">
      <input v-model="activityFilters.action" placeholder="Action" class="filter-input" />
      <input v-model="activityFilters.target" placeholder="Target" class="filter-input" />
      <input v-model="activityFilters.user_id" placeholder="User ID" class="filter-input short" />
      <input v-model="activityFilters.ip_address" placeholder="IP" class="filter-input short" />
      <button @click="searchLogs" class="btn-primary">Search</button>
    </div>

    <div v-if="loading" class="loading">Loading...</div>

    <table v-else-if="activeTab === 'usage'" class="logs-table">
      <thead>
        <tr>
          <th>Created At</th>
          <th>User</th>
          <th>Model</th>
          <th>Stock</th>
          <th>Tokens</th>
          <th>Cost</th>
          <th>Status</th>
          <th>Latency</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="log in usageLogs" :key="log.id">
          <td>{{ formatDate(log.created_at) }}</td>
          <td>{{ formatUser(log) }}</td>
          <td>{{ log.model_name || '-' }}</td>
          <td>{{ log.stock_symbol || '-' }}</td>
          <td>{{ log.total_tokens ?? 0 }}</td>
          <td>${{ formatCost(log.cost) }}</td>
          <td>
            <span :class="log.status === 'success' ? 'status-success' : 'status-error'">
              {{ log.status }}
            </span>
          </td>
          <td>{{ log.response_time_ms ?? 0 }}ms</td>
        </tr>
        <tr v-if="!usageLogs.length">
          <td colspan="8" class="no-data">No logs</td>
        </tr>
      </tbody>
    </table>

    <table v-else class="logs-table">
      <thead>
        <tr>
          <th>Created At</th>
          <th>Action</th>
          <th>Target</th>
          <th>User</th>
          <th>IP</th>
          <th>User Agent</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="log in activityLogs" :key="log.id">
          <td>{{ formatDate(log.created_at) }}</td>
          <td>{{ log.action }}</td>
          <td>{{ log.target || '-' }}</td>
          <td>{{ formatUser(log) }}</td>
          <td>{{ log.ip_address || '-' }}</td>
          <td class="user-agent" :title="log.user_agent || ''">{{ log.user_agent || '-' }}</td>
        </tr>
        <tr v-if="!activityLogs.length">
          <td colspan="6" class="no-data">No activity logs</td>
        </tr>
      </tbody>
    </table>

    <div class="pagination">
      <button @click="prevPage" :disabled="page <= 1" class="btn-small">Previous</button>
      <span>Page {{ page }}</span>
      <button @click="nextPage" :disabled="currentRows.length < limit" class="btn-small">Next</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { adminApi } from '@/api'
import { ElMessage } from 'element-plus'

type LogTab = 'usage' | 'activity'

interface UsageLog {
  id: number
  created_at: string
  username?: string | null
  user_id?: number | null
  model_name?: string | null
  stock_symbol?: string | null
  total_tokens?: number
  cost?: number
  status: 'success' | 'error' | 'timeout' | string
  response_time_ms?: number
}

interface ActivityLog {
  id: number
  created_at: string
  username?: string | null
  user_id?: number | null
  action: string
  target?: string | null
  ip_address?: string | null
  user_agent?: string | null
}

interface UsageFilters {
  stock_symbol: string
  status: string
}

interface ActivityFilters {
  action: string
  target: string
  user_id: string
  ip_address: string
}

interface UsageQueryParams {
  skip: number
  limit: number
  stock_symbol?: string
  status?: string
}

interface ActivityQueryParams {
  skip: number
  limit: number
  action?: string
  target?: string
  user_id?: number
  ip_address?: string
}

const activeTab = ref<LogTab>('usage')
const loading = ref(true)
const usageLogs = ref<UsageLog[]>([])
const activityLogs = ref<ActivityLog[]>([])
const page = ref(1)
const limit = 20
const usageFilters = ref<UsageFilters>({ stock_symbol: '', status: '' })
const activityFilters = ref<ActivityFilters>({ action: '', target: '', user_id: '', ip_address: '' })

const currentRows = computed(() => activeTab.value === 'usage' ? usageLogs.value : activityLogs.value)

async function loadLogs() {
  if (activeTab.value === 'activity') {
    await loadActivityLogs()
  } else {
    await loadUsageLogs()
  }
}

async function loadUsageLogs() {
  try {
    loading.value = true
    const params: UsageQueryParams = {
      skip: (page.value - 1) * limit,
      limit,
      stock_symbol: usageFilters.value.stock_symbol || undefined,
      status: usageFilters.value.status || undefined,
    }
    usageLogs.value = await adminApi.getLogs<UsageLog[]>(params)
  } catch (e) {
    ElMessage.error('Failed to load AI usage logs')
  } finally {
    loading.value = false
  }
}

async function loadActivityLogs() {
  try {
    loading.value = true
    const userId = Number(activityFilters.value.user_id)
    const params: ActivityQueryParams = {
      skip: (page.value - 1) * limit,
      limit,
      action: activityFilters.value.action || undefined,
      target: activityFilters.value.target || undefined,
      user_id: Number.isFinite(userId) && userId > 0 ? userId : undefined,
      ip_address: activityFilters.value.ip_address || undefined,
    }
    activityLogs.value = await adminApi.getActivityLogs<ActivityLog[]>(params)
  } catch (e) {
    ElMessage.error('Failed to load user activity logs')
  } finally {
    loading.value = false
  }
}

function switchTab(tab: LogTab) {
  if (activeTab.value === tab) return
  activeTab.value = tab
  page.value = 1
  loadLogs()
}

function searchLogs() {
  page.value = 1
  loadLogs()
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

function formatCost(cost?: number) {
  return (cost ?? 0).toFixed(6)
}

function formatUser(log: Pick<UsageLog | ActivityLog, 'username' | 'user_id'>) {
  return log.username || log.user_id || '-'
}

async function exportLogs() {
  try {
    ElMessage.info('Exporting...')
    const blob = await adminApi.exportLogs<Blob>({
      stock_symbol: usageFilters.value.stock_symbol || undefined,
      status: usageFilters.value.status || undefined,
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'ai_usage_logs.csv'
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('Exported')
  } catch (e) {
    ElMessage.error('Export failed')
  }
}

onMounted(loadLogs)
</script>

<style scoped>
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

h1 { margin: 0; }

.tabs {
  display: flex;
  gap: 6px;
  margin-bottom: 14px;
  border-bottom: 1px solid #ddd;
}

.tab-button {
  padding: 9px 14px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: #555;
  cursor: pointer;
  font-weight: 600;
}

.tab-button.active {
  color: #4f46e5;
  border-bottom-color: #4f46e5;
}

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 15px;
}

.filter-input, .filter-select {
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  min-width: 150px;
}

.filter-input.short {
  min-width: 110px;
  width: 120px;
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
  vertical-align: top;
}

.logs-table th {
  background: #f9f9f9;
  font-weight: 600;
}

.user-agent {
  max-width: 360px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
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
  background: #4f46e5;
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
