<template>
  <div class="admin-stats">
    <div class="page-header">
      <div>
        <h1 class="page-title">使用统计</h1>
        <p class="page-subtitle">系统运行数据总览</p>
      </div>
    </div>

    <div v-if="loading" class="skeleton-stats">
      <div v-for="i in 6" :key="i" class="skeleton-stat-card">
        <div class="skeleton-value"></div>
        <div class="skeleton-label"></div>
      </div>
    </div>

    <template v-else-if="stats">
      <!-- 数据卡片 -->
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-icon users">
            <el-icon :size="24"><User /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ formatNumber(stats.total_users) }}</div>
            <div class="stat-label">总用户数</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon active">
            <el-icon :size="24"><TrendCharts /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ formatNumber(stats.active_users_today) }}</div>
            <div class="stat-label">今日活跃用户</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon models">
            <el-icon :size="24"><Cpu /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ stats.active_models }}</div>
            <div class="stat-label">启用模型数</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon calls">
            <el-icon :size="24"><Connection /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ formatNumber(stats.total_api_calls_today) }}</div>
            <div class="stat-label">今日调用次数</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon tokens">
            <el-icon :size="24"><DataLine /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">{{ formatNumber(stats.total_tokens_today) }}</div>
            <div class="stat-label">今日 Token</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon cost">
            <el-icon :size="24"><Money /></el-icon>
          </div>
          <div class="stat-body">
            <div class="stat-value">${{ stats.total_cost_month?.toFixed(4) || '0.0000' }}</div>
            <div class="stat-label">本月费用</div>
          </div>
        </div>
      </div>

      <!-- 图表区域 -->
      <div class="charts-grid">
        <div class="chart-card chart-main">
          <div class="chart-header">
            <h3>每日调用量趋势</h3>
            <span v-if="callsByDay.length" class="chart-period">近 {{ callsByDay.length }} 天</span>
          </div>
          <div v-if="callsByDay.length" class="chart-bar-chart">
            <div
              v-for="item in callsByDay"
              :key="item.date"
              class="bar-group"
              :style="{ height: `${(item.count / maxCalls * 100)}%` }"
            >
              <div class="bar" :style="{ height: '100%' }"></div>
              <span class="bar-count">{{ item.count }}</span>
              <span class="bar-date">{{ formatDate(item.date) }}</span>
            </div>
          </div>
          <div v-else class="chart-empty">暂无数据</div>
        </div>

        <div class="chart-card chart-side">
          <h3>模型调用占比</h3>
          <div v-if="callsByModel.length" class="model-ranking">
            <div
              v-for="(item, index) in callsByModel.slice(0, 8)"
              :key="item.model_name"
              class="ranking-item"
            >
              <span class="rank-number">{{ index + 1 }}</span>
              <span class="rank-name">{{ item.model_name }}</span>
              <div class="rank-bar-container">
                <div
                  class="rank-bar"
                  :style="{ width: `${(item.count / maxModelCalls * 100)}%` }"
                ></div>
              </div>
              <span class="rank-count">{{ item.count }}</span>
            </div>
          </div>
          <div v-else class="chart-empty">暂无数据</div>
        </div>
      </div>

      <!-- Top 用户 -->
      <div class="top-users-card">
        <h3>活跃用户排行</h3>
        <div v-if="topUsers.length" class="users-list">
          <div
            v-for="(item, index) in topUsers"
            :key="item.username"
            class="user-item"
            :class="{ top3: index < 3 }"
          >
            <span class="user-rank">{{ index + 1 }}</span>
            <div class="user-info">
              <span class="user-name">{{ item.username }}</span>
              <span class="user-count">{{ item.count }} 次调用</span>
            </div>
            <div class="user-bar-container">
              <div
                class="user-bar"
                :style="{ width: `${(item.count / maxUserCalls * 100)}%` }"
              ></div>
            </div>
          </div>
        </div>
        <div v-else class="chart-empty">暂无数据</div>
      </div>
    </template>

    <div v-else class="error-state">
      <el-icon :size="48" class="error-icon"><WarningFilled /></el-icon>
      <h3>数据加载失败</h3>
      <p>请稍后重试</p>
      <el-button type="primary" @click="loadStats">重试</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  User,
  TrendCharts,
  Cpu,
  Connection,
  DataLine,
  WarningFilled,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api'

interface StatsOverview {
  total_users: number
  active_users_today: number
  active_models: number
  total_api_calls_today: number
  total_tokens_today: number
  total_cost_month?: number
  calls_by_day?: CallsByDayItem[]
  calls_by_model?: CallsByModelItem[]
  top_users?: TopUserItem[]
}

interface CallsByDayItem {
  date: string
  count: number
}

interface CallsByModelItem {
  model_name: string
  count: number
}

interface TopUserItem {
  username: string
  count: number
}

const loading = ref(true)
const stats = ref<StatsOverview | null>(null)
const callsByDay = ref<CallsByDayItem[]>([])
const callsByModel = ref<CallsByModelItem[]>([])
const topUsers = ref<TopUserItem[]>([])

const maxCalls = computed(() => {
  if (!callsByDay.value.length) return 1
  return Math.max(...callsByDay.value.map(d => d.count))
})

const maxModelCalls = computed(() => {
  if (!callsByModel.value.length) return 1
  return Math.max(...callsByModel.value.map(m => m.count))
})

const maxUserCalls = computed(() => {
  if (!topUsers.value.length) return 1
  return Math.max(...topUsers.value.map(u => u.count))
})

function formatNumber(num?: number) {
  if (!num && num !== 0) return '-'
  return num.toLocaleString('zh-CN')
}

function formatDate(dateStr: string) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return `${d.getMonth() + 1}/${d.getDate()}`
}

async function loadStats() {
  try {
    loading.value = true
    const data = await adminApi.getStatsOverview<StatsOverview>()
    stats.value = data
    callsByDay.value = data.calls_by_day || []
    callsByModel.value = data.calls_by_model || []
    topUsers.value = data.top_users || []
  } catch (e) {
    ElMessage.error('加载统计失败')
    console.error('加载统计失败:', e)
  } finally {
    loading.value = false
  }
}

onMounted(loadStats)
</script>

<style scoped>
.admin-stats {
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
.skeleton-stats {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: var(--space-4);
}

.skeleton-stat-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.skeleton-value {
  width: 80px;
  height: 28px;
  border-radius: var(--radius-sm);
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
}

.skeleton-label {
  width: 60px;
  height: 14px;
  border-radius: var(--radius-sm);
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
}

@keyframes skeleton-loading {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Stats cards */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}

.stat-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  display: flex;
  align-items: center;
  gap: var(--space-4);
  transition: all var(--transition-base);
}

.stat-card:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-1px);
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-icon.users {
  background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%);
  color: #2563eb;
}

.stat-icon.active {
  background: linear-gradient(135deg, #dcfce7 0%, #bbf7d0 100%);
  color: #16a34a;
}

.stat-icon.models {
  background: linear-gradient(135deg, #f3e8ff 0%, #e9d5ff 100%);
  color: #9333ea;
}

.stat-icon.calls {
  background: linear-gradient(135deg, #ffedd5 0%, #fed7aa 100%);
  color: #ea580c;
}

.stat-icon.tokens {
  background: linear-gradient(135deg, #ccfbf1 0%, #99f6e4 100%);
  color: #0d9488;
}

.stat-icon.cost {
  background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%);
  color: #dc2626;
}

.stat-body {
  min-width: 0;
}

.stat-value {
  font-size: 28px;
  font-weight: 800;
  color: var(--color-text);
  font-family: var(--font-number);
  line-height: 1.2;
  letter-spacing: -0.02em;
}

.stat-label {
  color: var(--color-text-muted);
  font-size: 13px;
  font-weight: 600;
  margin-top: 2px;
}

/* Charts */
.charts-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: var(--space-5);
  margin-bottom: var(--space-5);
}

.chart-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
}

.chart-card h3 {
  margin: 0 0 var(--space-4);
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
}

.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-4);
}

.chart-header h3 {
  margin: 0;
}

.chart-period {
  font-size: 12px;
  color: var(--color-text-muted);
  font-weight: 600;
  padding: 2px 8px;
  background: var(--color-surface-muted);
  border-radius: 999px;
}

.chart-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-12) 0;
  color: var(--color-text-muted);
  font-size: 14px;
}

/* Bar chart */
.chart-bar-chart {
  display: flex;
  align-items: flex-end;
  justify-content: space-around;
  height: 200px;
  gap: var(--space-2);
  padding-top: var(--space-4);
}

.bar-group {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  min-width: 0;
  position: relative;
  transition: all var(--transition-fast);
}

.bar-group:hover {
  transform: translateY(-4px);
}

.bar {
  width: 100%;
  max-width: 40px;
  background: linear-gradient(180deg, #6366f1 0%, #8b5cf6 100%);
  border-radius: 4px 4px 0 0;
  transition: all var(--transition-fast);
}

.bar-group:hover .bar {
  background: linear-gradient(180deg, #4f46e5 0%, #7c3aed 100%);
}

.bar-count {
  font-size: 11px;
  font-weight: 700;
  color: var(--color-text-secondary);
  margin-top: var(--space-1);
  font-family: var(--font-number);
}

.bar-date {
  font-size: 11px;
  color: var(--color-text-muted);
  margin-top: 2px;
  white-space: nowrap;
}

/* Model ranking */
.model-ranking {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.ranking-item {
  display: grid;
  grid-template-columns: 24px 1fr auto;
  align-items: center;
  gap: var(--space-3);
}

.rank-number {
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--color-surface-muted);
  color: var(--color-text-muted);
  font-size: 12px;
  font-weight: 700;
  font-family: var(--font-number);
}

.rank-name {
  font-size: 13px;
  color: var(--color-text);
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.rank-bar-container {
  display: none;
}

.rank-count {
  font-size: 13px;
  color: var(--color-text-secondary);
  font-weight: 700;
  font-family: var(--font-number);
}

/* Top users */
.top-users-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
}

.top-users-card h3 {
  margin: 0 0 var(--space-4);
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
}

.users-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.user-item {
  display: grid;
  grid-template-columns: 32px 1fr auto;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--color-border);
  transition: all var(--transition-fast);
}

.user-item:last-child {
  border-bottom: none;
}

.user-item:hover {
  background: var(--color-surface-muted);
  margin: 0 calc(-1 * var(--space-3));
  padding-left: var(--space-3);
  padding-right: var(--space-3);
  border-radius: var(--radius-sm);
}

.user-rank {
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--color-surface-muted);
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 800;
  font-family: var(--font-number);
}

.user-item.top3 .user-rank {
  background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%);
  color: #fff;
}

.user-info {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.user-name {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-count {
  font-size: 12px;
  color: var(--color-text-muted);
}

.user-bar-container {
  display: none;
}

/* Error state */
.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-16) 0;
  text-align: center;
  color: var(--color-text-muted);
}

.error-state h3 {
  margin: var(--space-3) 0 var(--space-1);
  font-size: 18px;
  font-weight: 700;
  color: var(--color-text);
}

.error-state p {
  margin: 0 0 var(--space-4);
  font-size: 14px;
}

.error-icon {
  color: var(--color-text-muted);
}

/* Responsive */
@media (max-width: 1024px) {
  .charts-grid {
    grid-template-columns: 1fr;
  }

  .stats-grid {
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  }
}

@media (max-width: 640px) {
  .stats-grid {
    grid-template-columns: 1fr 1fr;
  }

  .stat-card {
    flex-direction: column;
    align-items: flex-start;
    text-align: center;
  }

  .chart-bar-chart {
    height: 160px;
  }
}
</style>
