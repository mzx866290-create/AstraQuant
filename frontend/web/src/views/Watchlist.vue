<template>
  <div class="watchlist-page">
    <el-card class="watchlist-card dashboard-card" shadow="never">
      <template #header>
        <div class="card-header">
          <span>我的自选股</span>
          <div class="header-actions">
            <el-button size="small" :loading="summaryLoading" @click="loadBatchSummary(true)">
              刷新AI摘要
            </el-button>
            <el-button type="primary" size="small" @click="openAddDialog">
              + 添加股票
            </el-button>
          </div>
        </div>
      </template>

      <el-empty v-if="watchlistItems.length === 0" description="暂无自选股，点击上方按钮添加" />

      <el-table v-else :data="watchlistItems" stripe class="watchlist-table">
        <el-table-column prop="symbol" label="代码" width="140" />
        <el-table-column prop="name" label="名称" width="200" />
        <el-table-column prop="market" label="市场" width="80" />
        <el-table-column label="AI短评" min-width="320">
          <template #default="{ row }">
            <div class="summary-cell">
              {{ summaryMap[row.symbol]?.summary || '等待批量摘要' }}
              <span v-if="summaryMap[row.symbol]?.batch_cache_hit" class="cache-mark">缓存</span>
              <span v-if="summaryMap[row.symbol]?.model_status === 'error'" class="error-mark">异常</span>
              <DataQualityPanel
                v-if="summaryMap[row.symbol]?.data_quality"
                class="summary-quality"
                :quality="summaryMap[row.symbol]?.data_quality || null"
              />
            </div>
          </template>
        </el-table-column>
        <el-table-column label="风险灯" width="220">
          <template #default="{ row }">
            <div class="risk-cell">
              <span
                v-for="risk in riskList(summaryMap[row.symbol]?.risk_lights)"
                :key="risk.key"
                class="risk-dot"
                :class="risk.level"
                :title="risk.message"
              >
                {{ risk.label }}
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button type="primary" link @click="goDetail(row)">查看</el-button>
            <el-button type="danger" link @click="removeStock(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showAddDialog" title="添加自选股" width="400px">
      <el-input
        v-model="addSymbol"
        placeholder="输入6位股票代码，如 600519"
        maxlength="6"
        @input="onInput"
        @keyup.enter="confirmAdd"
      />
      <div class="add-tip">
        输入代码后按回车或点击「添加」
      </div>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmAdd" :disabled="addSymbol.trim().length < 6">添加</el-button>
      </template>
    </el-dialog>

    <Disclaimer />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { analysisApi, watchlistApi } from '@/api'
import Disclaimer from '@/components/common/Disclaimer.vue'
import DataQualityPanel from '@/components/common/DataQualityPanel.vue'
import type { DataQualityItem } from '@/utils/dataQuality'

const router = useRouter()

interface WatchlistItem {
  stock_id: number
  symbol: string
  name?: string
  market?: string
}

interface WatchlistGroup {
  id: number
  items?: WatchlistItem[]
}

interface RiskLight {
  key: string
  label?: string
  level?: string
  message?: string
}

interface BatchSummaryItem {
  symbol: string
  summary?: string
  batch_cache_hit?: boolean
  model_status?: string
  risk_lights?: Record<string, Omit<RiskLight, 'key'>>
  data_quality?: DataQualityItem
}

const watchlistItems = ref<WatchlistItem[]>([])
const watchlistId = ref<number | null>(null)
const showAddDialog = ref(false)
const addSymbol = ref('')
const summaryMap = ref<Record<string, BatchSummaryItem>>({})
const summaryLoading = ref(false)

function onInput(val: string) {
  addSymbol.value = val.replace(/[^0-9]/g, '').slice(0, 6)
}

function openAddDialog() {
  addSymbol.value = ''
  showAddDialog.value = true
}

async function loadWatchlist() {
  try {
    const res = await watchlistApi.getWatchlists()
    const data = Array.isArray(res) ? res : ((res as { data?: WatchlistGroup[] }).data || res)
    if (Array.isArray(data) && data.length > 0) {
      watchlistId.value = data[0].id
      watchlistItems.value = data[0].items || []
      await loadBatchSummary()
    }
  } catch (e) {
    console.error('加载自选股失败:', e)
  }
}

async function loadBatchSummary(forceRefresh = false) {
  const symbols = watchlistItems.value.map((item) => item.symbol).filter(Boolean)
  if (!symbols.length) {
    summaryMap.value = {}
    return
  }
  try {
    summaryLoading.value = true
    const resp = await analysisApi.getBatchSummary<{ items?: BatchSummaryItem[] }>(symbols, 'summary', 'beginner', true, forceRefresh)
    const next: Record<string, BatchSummaryItem> = {}
    for (const item of resp.items || []) {
      next[item.symbol] = item
    }
    summaryMap.value = next
  } catch (e) {
    console.error('加载批量摘要失败:', e)
  } finally {
    summaryLoading.value = false
  }
}

function riskList(risks?: Record<string, Omit<RiskLight, 'key'>>) {
  if (!risks) return []
  return Object.entries(risks).map(([key, value]) => ({ key, ...value }))
}

async function confirmAdd() {
  const code = addSymbol.value.trim()
  if (code.length < 6 || !watchlistId.value) return
  try {
    await watchlistApi.addToWatchlist(watchlistId.value, undefined, code)
    showAddDialog.value = false
    addSymbol.value = ''
    await loadWatchlist()
  } catch (error) {
    const msg = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '添加失败'
    ElMessage.error(msg)
  }
}

async function removeStock(row: WatchlistItem) {
  if (!watchlistId.value) return
  try {
    await watchlistApi.removeFromWatchlist(watchlistId.value, row.stock_id)
    await loadWatchlist()
  } catch {
    ElMessage.error('删除失败')
  }
}

function goDetail(row: WatchlistItem) {
  router.push(`/stocks/${row.symbol}`)
}

onMounted(() => { loadWatchlist() })
</script>

<style scoped>
.watchlist-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.watchlist-card {
  overflow: hidden;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
}

.card-header span {
  color: var(--color-text);
  font-size: 18px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.header-actions {
  display: flex;
  gap: var(--space-2);
  align-items: center;
}

.watchlist-table {
  width: 100%;
}

.watchlist-table :deep(.el-table__cell) {
  font-variant-numeric: tabular-nums;
}

.watchlist-table :deep(.el-table__body-wrapper) {
  overflow-x: auto;
}

.summary-cell {
  color: var(--color-text-secondary);
  font-size: 13px;
  line-height: 1.55;
}

.summary-quality {
  margin: 6px 0 0;
}

.cache-mark,
.error-mark {
  display: inline-block;
  margin-left: 6px;
  border-radius: 999px;
  padding: 1px 6px;
  font-size: 11px;
  font-weight: 700;
}

.cache-mark {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.error-mark {
  background: var(--color-danger-soft);
  color: #b91c1c;
}

.risk-cell {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}

.risk-dot {
  border-radius: 999px;
  padding: 2px 7px;
  font-size: 12px;
  font-weight: 700;
  background: var(--color-surface-muted);
  color: var(--color-text-secondary);
}

.risk-dot.green {
  background: #ecfdf5;
  color: #047857;
}

.risk-dot.yellow {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.risk-dot.red {
  background: var(--color-danger-soft);
  color: #b91c1c;
}

.add-tip {
  margin-top: 6px;
  color: #999;
  font-size: 12px;
}

@media (max-width: 760px) {
  .card-header {
    align-items: stretch;
    flex-direction: column;
  }

  .header-actions {
    justify-content: space-between;
  }
}
</style>
