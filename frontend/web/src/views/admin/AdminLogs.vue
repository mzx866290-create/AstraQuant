<template>
  <div class="admin-logs">
    <div class="page-header">
      <div>
        <h1 class="page-title">调用日志</h1>
        <p class="page-subtitle">AI 使用和用户活动记录</p>
      </div>
      <el-button v-if="activeTab === 'usage'" type="primary" link @click="exportLogs">
        <el-icon><Download /></el-icon>
        <span>导出 CSV</span>
      </el-button>
    </div>

    <!-- Tabs -->
    <div class="tabs" role="tablist" aria-label="Admin logs">
      <button
        class="tab-button"
        :class="{ active: activeTab === 'usage' }"
        @click="switchTab('usage')"
      >
        <el-icon><DataLine /></el-icon>
        <span>AI 调用</span>
      </button>
      <button
        class="tab-button"
        :class="{ active: activeTab === 'activity' }"
        @click="switchTab('activity')"
      >
        <el-icon><User /></el-icon>
        <span>用户活动</span>
      </button>
    </div>

    <!-- Filters -->
    <div v-if="activeTab === 'usage'" class="filters">
      <el-input
        v-model="usageFilters.stock_symbol"
        placeholder="股票代码"
        clearable
        class="filter-input"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="usageFilters.status" placeholder="状态" clearable class="filter-select">
        <el-option label="全部" value="" />
        <el-option label="成功" value="success" />
        <el-option label="失败" value="error" />
        <el-option label="超时" value="timeout" />
      </el-select>
      <el-button type="primary" @click="searchLogs">
        <el-icon><Search /></el-icon>
        <span>搜索</span>
      </el-button>
    </div>

    <div v-else class="filters">
      <el-input v-model="activityFilters.action" placeholder="操作类型" clearable class="filter-input" />
      <el-input v-model="activityFilters.target" placeholder="目标" clearable class="filter-input" />
      <el-input v-model="activityFilters.user_id" placeholder="用户 ID" clearable class="filter-input short" />
      <el-input v-model="activityFilters.ip_address" placeholder="IP 地址" clearable class="filter-input short" />
      <el-button type="primary" @click="searchLogs">
        <el-icon><Search /></el-icon>
        <span>搜索</span>
      </el-button>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="skeleton-logs">
      <div v-for="i in 8" :key="i" class="skeleton-log">
        <div class="skeleton-cell"></div>
        <div class="skeleton-cell medium"></div>
        <div class="skeleton-cell short"></div>
      </div>
    </div>

    <!-- Logs Table -->
    <div v-else-if="currentRows.length" class="logs-table-wrapper">
      <div class="table-container">
        <table class="logs-table">
          <thead>
            <tr>
              <th v-for="col in currentColumns" :key="col.key">{{ col.label }}</th>
            </tr>
          </thead>
          <tbody v-if="activeTab === 'usage'">
            <tr v-for="log in usageLogs" :key="log.id">
              <td><span class="log-time">{{ formatDate(log.created_at) }}</span></td>
              <td><span class="log-user">{{ formatUser(log) }}</span></td>
              <td><span class="log-model">{{ log.model_name || '-' }}</span></td>
              <td><span class="log-stock">{{ log.stock_symbol || '-' }}</span></td>
              <td><span class="log-number">{{ log.total_tokens ?? 0 }}</span></td>
              <td><span class="log-cost">${{ formatCost(log.cost) }}</span></td>
              <td>
                <el-tag
                  size="small"
                  :type="log.status === 'success' ? 'success' : 'danger'"
                  effect="light"
                  class="status-tag"
                >
                  {{ log.status }}
                </el-tag>
              </td>
              <td><span class="log-number">{{ log.response_time_ms ?? 0 }}ms</span></td>
            </tr>
          </tbody>
          <tbody v-else>
            <tr v-for="log in activityLogs" :key="log.id">
              <td><span class="log-time">{{ formatDate(log.created_at) }}</span></td>
              <td>
                <el-tag size="small" type="info" effect="light" class="action-tag">
                  {{ log.action }}
                </el-tag>
              </td>
              <td><span class="log-target">{{ log.target || '-' }}</span></td>
              <td><span class="log-user">{{ formatUser(log) }}</span></td>
              <td><span class="log-ip">{{ log.ip_address || '-' }}</span></td>
              <td>
                <span class="log-ua" :title="log.user_agent || ''">
                  {{ log.user_agent || '-' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="pagination">
        <el-button
          :disabled="page <= 1"
          link
          @click="prevPage"
        >
          <el-icon><ArrowLeft /></el-icon>
          <span>上一页</span>
        </el-button>
        <span class="page-info">第 {{ page }} 页</span>
        <el-button
          :disabled="currentRows.length < limit"
          link
          @click="nextPage"
        >
          <span>下一页</span>
          <el-icon><ArrowRight /></el-icon>
        </el-button>
      </div>
    </div>

    <div v-else class="empty-state">
      <el-icon :size="48" class="empty-icon"><Document /></el-icon>
      <h3>暂无日志</h3>
      <p>当前筛选条件下没有数据</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  DataLine,
  User,
  Search,
  Download,
  ArrowLeft,
  ArrowRight,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api'

type LogTab = 'usage' | 'activity'

interface Column {
  key: string
  label: string
}

const usageColumns: Column[] = [
  { key: 'created_at', label: '时间' },
  { key: 'user', label: '用户' },
  { key: 'model', label: '模型' },
  { key: 'stock', label: '股票' },
  { key: 'tokens', label: 'Token' },
  { key: 'cost', label: '费用' },
  { key: 'status', label: '状态' },
  { key: 'latency', label: '耗时' },
]

const activityColumns: Column[] = [
  { key: 'created_at', label: '时间' },
  { key: 'action', label: '操作' },
  { key: 'target', label: '目标' },
  { key: 'user', label: '用户' },
  { key: 'ip', label: 'IP' },
  { key: 'ua', label: 'User Agent' },
]

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

const currentColumns = computed(() => activeTab.value === 'usage' ? usageColumns : activityColumns)
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
    ElMessage.error('加载 AI 调用日志失败')
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
    ElMessage.error('加载用户活动日志失败')
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
  const d = new Date(dateStr)
  return d.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatCost(cost?: number) {
  return (cost ?? 0).toFixed(6)
}

function formatUser(log: Pick<UsageLog | ActivityLog, 'username' | 'user_id'>) {
  return log.username || log.user_id || '-'
}

async function exportLogs() {
  try {
    ElMessage.info('正在导出...')
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
    ElMessage.success('导出成功')
  } catch (e) {
    ElMessage.error('导出失败')
  }
}

onMounted(loadLogs)
</script>

<style scoped>
.admin-logs {
  max-width: 1200px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--space-6);
  gap: var(--space-4);
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

/* Tabs */
.tabs {
  display: flex;
  gap: var(--space-1);
  margin-bottom: var(--space-4);
  border-bottom: 1px solid var(--color-border);
  padding-bottom: var(--space-1);
}

.tab-button {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 10px 16px;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--color-text-muted);
  cursor: pointer;
  font-weight: 600;
  font-size: 14px;
  transition: all var(--transition-fast);
  border-radius: var(--radius-sm) var(--radius-sm) 0 0;
}

.tab-button:hover {
  background: var(--color-surface-muted);
  color: var(--color-text-secondary);
}

.tab-button.active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
  font-weight: 700;
}

/* Filters */
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin-bottom: var(--space-5);
  padding: var(--space-4);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.filter-input {
  width: 180px;
}

.filter-input.short {
  width: 140px;
}

.filter-select {
  width: 140px;
}

/* Skeleton */
.skeleton-logs {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.skeleton-log {
  display: flex;
  gap: var(--space-4);
  padding: var(--space-3);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.skeleton-cell {
  height: 16px;
  width: 120px;
  border-radius: var(--radius-sm);
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
}

.skeleton-cell.medium {
  width: 80px;
}

.skeleton-cell.short {
  width: 60px;
}

@keyframes skeleton-loading {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Table */
.logs-table-wrapper {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.table-container {
  overflow-x: auto;
}

.logs-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.logs-table th {
  padding: 12px 16px;
  text-align: left;
  font-weight: 700;
  color: var(--color-text-secondary);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  background: var(--color-surface-muted);
  border-bottom: 1px solid var(--color-border);
  white-space: nowrap;
}

.logs-table td {
  padding: 12px 16px;
  border-bottom: 1px solid var(--color-border);
  vertical-align: middle;
  white-space: nowrap;
}

.logs-table tbody tr {
  transition: background var(--transition-fast);
}

.logs-table tbody tr:hover {
  background: var(--color-surface-muted);
}

.log-time {
  font-family: var(--font-number);
  font-size: 12px;
  color: var(--color-text-secondary);
}

.log-user {
  font-weight: 600;
  color: var(--color-text);
}

.log-model {
  color: var(--color-primary);
  font-weight: 600;
}

.log-stock {
  font-family: var(--font-number);
  color: var(--color-text-secondary);
}

.log-number {
  font-family: var(--font-number);
  color: var(--color-text-secondary);
}

.log-cost {
  font-family: var(--font-number);
  font-weight: 700;
  color: var(--color-warning);
}

.log-ip {
  font-family: var(--font-number);
  font-size: 12px;
  color: var(--color-text-muted);
}

.log-ua {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 12px;
  color: var(--color-text-muted);
}

.log-target {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.status-tag,
.action-tag {
  font-weight: 700;
}

/* Pagination */
.pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4);
  border-top: 1px solid var(--color-border);
}

.page-info {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-secondary);
  font-family: var(--font-number);
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
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
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
  .page-header {
    flex-direction: column;
    align-items: stretch;
  }

  .filters {
    flex-direction: column;
  }

  .filter-input,
  .filter-select {
    width: 100%;
  }

  .logs-table {
    font-size: 12px;
  }

  .logs-table th,
  .logs-table td {
    padding: 8px 10px;
  }

  .log-ua {
    max-width: 120px;
  }
}
</style>
