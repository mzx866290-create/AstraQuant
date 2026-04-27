<template>
  <div class="admin-stats">
    <h1>使用统计</h1>

    <div v-if="loading" class="loading">加载中...</div>

    <template v-else-if="stats">
      <div class="stats-cards">
        <div class="stat-card">
          <div class="stat-value">{{ stats.total_users }}</div>
          <div class="stat-label">总用户数</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ stats.active_users_today }}</div>
          <div class="stat-label">今日活跃用户</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ stats.active_models }}</div>
          <div class="stat-label">启用模型数</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ stats.total_api_calls_today }}</div>
          <div class="stat-label">今日调用次数</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{{ stats.total_tokens_today }}</div>
          <div class="stat-label">今日 Token</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">${{ stats.total_cost_month?.toFixed(4) || 0 }}</div>
          <div class="stat-label">本月费用</div>
        </div>
      </div>

      <div class="charts-row">
        <div class="chart-card">
          <h3>每日调用量趋势</h3>
          <div v-if="callsByDay.length" class="chart-placeholder">
            <div v-for="item in callsByDay" :key="item.date" class="chart-bar">
              <div class="bar-label">{{ item.date }}</div>
              <div class="bar-value" :style="{ height: (item.count / maxCalls * 100) + '%' }"></div>
            </div>
          </div>
          <div v-else class="no-data">暂无数据</div>
        </div>

        <div class="chart-card">
          <h3>模型调用占比</h3>
          <div v-if="callsByModel.length" class="model-list">
            <div v-for="item in callsByModel" :key="item.model_name" class="model-item">
              <span class="model-name">{{ item.model_name }}</span>
              <span class="model-count">{{ item.count }} 次</span>
            </div>
          </div>
          <div v-else class="no-data">暂无数据</div>
        </div>
      </div>

      <div class="top-users">
        <h3>Top 用户</h3>
        <div v-if="topUsers.length" class="users-list">
          <div v-for="(item, index) in topUsers" :key="item.username" class="user-item">
            <span class="user-rank">{{ index + 1 }}</span>
            <span class="user-name">{{ item.username }}</span>
            <span class="user-count">{{ item.count }} 次</span>
          </div>
        </div>
        <div v-else class="no-data">暂无数据</div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { adminApi } from '@/api'

const loading = ref(true)
const stats = ref<any>(null)
const callsByDay = ref<any[]>([])
const callsByModel = ref<any[]>([])
const topUsers = ref<any[]>([])

const maxCalls = computed(() => {
  if (!callsByDay.value.length) return 1
  return Math.max(...callsByDay.value.map(d => d.count))
})

async function loadStats() {
  try {
    loading.value = true
    const data = await adminApi.getStatsOverview()
    stats.value = data
    callsByDay.value = data.calls_by_day || []
    callsByModel.value = data.calls_by_model || []
    topUsers.value = data.top_users || []
  } catch (e) {
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

h1 {
  margin-bottom: 20px;
  color: #333;
}

.loading, .no-data {
  text-align: center;
  padding: 40px;
  color: #999;
}

.stats-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 15px;
  margin-bottom: 20px;
}

.stat-card {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  text-align: center;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.stat-value {
  font-size: 28px;
  font-weight: bold;
  color: #7c3aed;
}

.stat-label {
  color: #666;
  margin-top: 5px;
  font-size: 14px;
}

.charts-row {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 15px;
  margin-bottom: 20px;
}

.chart-card {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.chart-card h3 {
  margin: 0 0 15px;
  color: #333;
}

.chart-placeholder {
  display: flex;
  align-items: flex-end;
  height: 150px;
  gap: 2px;
}

.chart-bar {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.bar-label {
  font-size: 8px;
  color: #999;
  transform: rotate(-45deg);
  margin-top: 5px;
}

.bar-value {
  width: 100%;
  background: #7c3aed;
  border-radius: 2px 2px 0 0;
  min-height: 2px;
}

.model-list {
  max-height: 180px;
  overflow-y: auto;
}

.model-item {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid #eee;
}

.model-item:last-child {
  border-bottom: none;
}

.top-users {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.top-users h3 {
  margin: 0 0 15px;
  color: #333;
}

.users-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.user-item {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  background: #f9f9f9;
  border-radius: 4px;
}

.user-rank {
  width: 24px;
  height: 24px;
  background: #7c3aed;
  color: #fff;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  margin-right: 12px;
}

.user-name {
  flex: 1;
}

.user-count {
  color: #666;
}
</style>