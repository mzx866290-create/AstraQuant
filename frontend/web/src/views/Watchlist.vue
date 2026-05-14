<template>
  <div class="watchlist-page">
    <!-- 页面头部 -->
    <div class="page-header">
      <div>
        <h1 class="page-title">我的自选股</h1>
        <p class="page-subtitle">关注股票智能分析与监控</p>
      </div>
      <div class="header-actions">
        <el-button size="small" @click="exportWatchlist">
          <el-icon><Download /></el-icon>
          <span>导出</span>
        </el-button>
        <el-button size="small" @click="openImportDialog">
          <el-icon><Upload /></el-icon>
          <span>导入</span>
        </el-button>
        <el-button
          type="primary"
          size="small"
          :loading="summaryLoading"
          @click="loadBatchSummary(true)"
          class="refresh-btn"
        >
          <el-icon><Refresh /></el-icon>
          <span>刷新AI摘要</span>
        </el-button>
        <el-button
          type="primary"
          size="small"
          @click="openAddDialog"
          class="add-btn"
        >
          <el-icon><Plus /></el-icon>
          <span>添加股票</span>
        </el-button>
      </div>
    </div>

    <!-- 骨架屏 -->
    <div v-if="loading" class="skeleton-grid">
      <div v-for="i in 4" :key="i" class="skeleton-card">
        <div class="skeleton-header">
          <div class="skeleton-avatar"></div>
          <div class="skeleton-titles">
            <div class="skeleton-title"></div>
            <div class="skeleton-subtitle"></div>
          </div>
        </div>
        <div class="skeleton-body">
          <div class="skeleton-line"></div>
          <div class="skeleton-line short"></div>
        </div>
        <div class="skeleton-tags">
          <div class="skeleton-tag"></div>
          <div class="skeleton-tag"></div>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-else-if="watchlistItems.length === 0" class="empty-state">
      <el-icon :size="64" class="empty-icon"><Star /></el-icon>
      <h2>暂无自选股</h2>
      <p>点击上方按钮添加您关注的股票</p>
      <el-button type="primary" @click="openAddDialog">
        <el-icon><Plus /></el-icon>
        <span>添加第一只股票</span>
      </el-button>
    </div>

    <!-- 卡片网格 -->
    <div v-else class="watchlist-grid">
      <div
        v-for="(item, index) in watchlistItems"
        :key="item.symbol"
        class="watch-card"
        draggable="true"
        :class="{ dragging: draggedStockId === item.stock_id }"
        :style="{ animationDelay: `${index * 0.05}s` }"
        @dragstart="handleDragStart(item)"
        @dragover.prevent
        @drop="handleDrop(index)"
        @dragend="handleDragEnd"
      >
        <!-- 卡片头部 -->
        <div class="card-header" @click="goDetail(item)">
          <div class="stock-identity">
            <div class="stock-avatar">
              <span class="avatar-text">{{ item.name?.charAt(0) }}</span>
            </div>
            <div class="stock-names">
              <h3 class="stock-name">{{ item.name }}</h3>
              <span class="stock-symbol">{{ item.symbol }}</span>
            </div>
          </div>
          <el-tag size="small" effect="light" class="market-tag">
            {{ item.market || '-' }}
          </el-tag>
        </div>

        <!-- AI 摘要 -->
        <div class="card-summary" @click="goDetail(item)">
          <div v-if="summaryMap[item.symbol]?.summary" class="summary-text">
            {{ summaryMap[item.symbol].summary }}
          </div>
          <div v-else-if="summaryLoading && !summaryMap[item.symbol]" class="summary-loading">
            <el-icon class="loading-icon"><Loading /></el-icon>
            <span>AI 分析中...</span>
          </div>
          <div v-else class="summary-empty">
            <span>等待批量摘要</span>
          </div>

          <div class="summary-meta">
            <el-tag
              v-if="summaryMap[item.symbol]?.batch_cache_hit"
              size="small"
              effect="light"
              class="cache-tag"
            >
              缓存
            </el-tag>
            <el-tag
              v-if="summaryMap[item.symbol]?.model_status === 'error'"
              size="small"
              type="danger"
              effect="light"
              class="error-tag"
            >
              分析异常
            </el-tag>
            <DataQualityPanel
              v-if="summaryMap[item.symbol]?.data_quality"
              class="summary-quality"
              :quality="summaryMap[item.symbol]?.data_quality || null"
            />
          </div>
        </div>

        <!-- 风险灯 -->
        <div v-if="riskList(summaryMap[item.symbol]?.risk_lights).length" class="card-risks">
          <div class="risk-header">
            <el-icon :size="14"><Warning /></el-icon>
            <span>风险指标</span>
          </div>
          <div class="risk-chips">
            <span
              v-for="risk in riskList(summaryMap[item.symbol]?.risk_lights)"
              :key="risk.key"
              class="risk-chip"
              :class="risk.level"
              :title="risk.message"
            >
              {{ risk.label }}
            </span>
          </div>
        </div>

        <!-- 卡片操作 -->
        <div class="card-actions">
          <el-button type="primary" link @click="goDetail(item)">
            <el-icon><View /></el-icon>
            <span>查看详情</span>
          </el-button>
          <el-button type="danger" link @click="removeStock(item)">
            <el-icon><Delete /></el-icon>
            <span>移除</span>
          </el-button>
        </div>
      </div>
    </div>

    <Disclaimer />

    <!-- 添加股票弹窗 -->
    <el-dialog
      v-model="showAddDialog"
      title="添加自选股"
      width="400px"
      :close-on-click-modal="false"
    >
      <div class="add-dialog-content">
        <el-input
          v-model="addSymbol"
          size="large"
          placeholder="输入6位股票代码，如 600519"
          maxlength="6"
          @input="onInput"
          @keyup.enter="confirmAdd"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <p class="add-tip">输入代码后按回车或点击「添加」</p>
      </div>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="addSymbol.trim().length < 6"
          @click="confirmAdd"
        >
          添加
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="showImportDialog"
      title="导入自选股"
      width="460px"
      :close-on-click-modal="false"
    >
      <div class="import-dialog-content">
        <el-input
          v-model="importText"
          type="textarea"
          :rows="8"
          placeholder="粘贴股票代码，支持逗号、空格、换行分隔，如：600519, 000858"
        />
        <p class="add-tip">将自动跳过已存在或格式无效的代码。</p>
      </div>
      <template #footer>
        <el-button @click="showImportDialog = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="confirmImport">
          导入
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  Refresh,
  Plus,
  Star,
  Loading,
  Warning,
  View,
  Delete,
  Search,
  Download,
  Upload,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { analysisApi, watchlistApi } from '@/api'
import Disclaimer from '@/components/common/Disclaimer.vue'
import DataQualityPanel from '@/components/common/DataQualityPanel.vue'
import type { DataQualityItem } from '@/utils/dataQuality'

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

const router = useRouter()
const watchlistItems = ref<WatchlistItem[]>([])
const watchlistId = ref<number | null>(null)
const showAddDialog = ref(false)
const showImportDialog = ref(false)
const addSymbol = ref('')
const importText = ref('')
const summaryMap = ref<Record<string, BatchSummaryItem>>({})
const summaryLoading = ref(false)
const loading = ref(false)
const importing = ref(false)
const draggedStockId = ref<number | null>(null)

function onInput(val: string) {
  addSymbol.value = val.replace(/[^0-9]/g, '').slice(0, 6)
}

function openAddDialog() {
  addSymbol.value = ''
  showAddDialog.value = true
}

function openImportDialog() {
  importText.value = ''
  showImportDialog.value = true
}

async function loadWatchlist() {
  loading.value = true
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
    ElMessage.error('加载自选股失败')
  } finally {
    loading.value = false
  }
}

function extractCodes(text: string) {
  const matches = text.match(/\d{6}/g) || []
  return Array.from(new Set(matches))
}

async function loadBatchSummary(forceRefresh = false) {
  const symbols = watchlistItems.value.map((item) => item.symbol).filter(Boolean)
  if (!symbols.length) {
    summaryMap.value = {}
    return
  }
  try {
    summaryLoading.value = true
    const resp = await analysisApi.getBatchSummary<{ items?: BatchSummaryItem[] }>(
      symbols,
      'summary',
      'beginner',
      true,
      forceRefresh
    )
    const next: Record<string, BatchSummaryItem> = {}
    for (const item of resp.items || []) {
      next[item.symbol] = item
    }
    summaryMap.value = next
  } catch (e) {
    console.error('加载批量摘要失败:', e)
    ElMessage.error('加载AI摘要失败')
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
    await watchlistApi.addToWatchlist(watchlistId.value, { symbol: code })
    showAddDialog.value = false
    addSymbol.value = ''
    ElMessage.success('添加成功')
    await loadWatchlist()
  } catch (error) {
    const msg = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '添加失败'
    ElMessage.error(msg)
  }
}

async function confirmImport() {
  if (!watchlistId.value) return
  const existingCodes = new Set(watchlistItems.value.map((item) => item.symbol.slice(0, 6)))
  const codes = extractCodes(importText.value).filter((code) => !existingCodes.has(code))
  if (!codes.length) {
    ElMessage.warning('没有可导入的新股票代码')
    return
  }

  importing.value = true
  let success = 0
  try {
    for (const code of codes) {
      try {
        await watchlistApi.addToWatchlist(watchlistId.value, { symbol: code })
        success += 1
      } catch (error) {
        console.warn('导入自选股失败:', code, error)
      }
    }
    showImportDialog.value = false
    ElMessage.success(`导入完成，新增 ${success} 只`)
    await loadWatchlist()
  } finally {
    importing.value = false
  }
}

function exportWatchlist() {
  const content = watchlistItems.value
    .map((item) => [item.symbol, item.name || '', item.market || ''].join(','))
    .join('\n')
  const blob = new Blob([`symbol,name,market\n${content}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'watchlist.csv'
  link.click()
  URL.revokeObjectURL(url)
}

function handleDragStart(row: WatchlistItem) {
  draggedStockId.value = row.stock_id
}

function handleDragEnd() {
  draggedStockId.value = null
}

async function handleDrop(targetIndex: number) {
  if (!watchlistId.value || draggedStockId.value == null) return
  const fromIndex = watchlistItems.value.findIndex((item) => item.stock_id === draggedStockId.value)
  if (fromIndex < 0 || fromIndex === targetIndex) return
  const next = [...watchlistItems.value]
  const [moved] = next.splice(fromIndex, 1)
  next.splice(targetIndex, 0, moved)
  watchlistItems.value = next
  draggedStockId.value = null
  try {
    await watchlistApi.reorderWatchlistItems(watchlistId.value, next.map((item) => item.stock_id))
    ElMessage.success('排序已更新')
  } catch (error) {
    ElMessage.error('排序保存失败')
    await loadWatchlist()
  }
}

async function removeStock(row: WatchlistItem) {
  if (!watchlistId.value) return
  try {
    await watchlistApi.removeFromWatchlist(watchlistId.value, row.stock_id)
    ElMessage.success('已移除')
    await loadWatchlist()
  } catch {
    ElMessage.error('删除失败')
  }
}

function goDetail(row: WatchlistItem) {
  router.push(`/stocks/${row.symbol}`)
}

onMounted(() => {
  loadWatchlist()
})
</script>

<style scoped>
.watchlist-page {
  max-width: 1200px;
}

/* Page header */
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

.header-actions {
  display: flex;
  gap: var(--space-3);
  flex-shrink: 0;
}

.refresh-btn,
.add-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
}

/* Skeleton */
.skeleton-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: var(--space-4);
}

.skeleton-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
}

.skeleton-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.skeleton-avatar {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
  flex-shrink: 0;
}

.skeleton-titles {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.skeleton-title {
  width: 120px;
  height: 18px;
  border-radius: var(--radius-sm);
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
}

.skeleton-subtitle {
  width: 80px;
  height: 14px;
  border-radius: var(--radius-sm);
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
}

.skeleton-body {
  margin-bottom: var(--space-3);
}

.skeleton-line {
  width: 100%;
  height: 14px;
  border-radius: var(--radius-sm);
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
  margin-bottom: var(--space-2);
}

.skeleton-line.short {
  width: 60%;
}

.skeleton-tags {
  display: flex;
  gap: var(--space-2);
}

.skeleton-tag {
  width: 60px;
  height: 24px;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
}

@keyframes skeleton-loading {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Watchlist grid */
.watchlist-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: var(--space-4);
}

.watch-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  transition: all var(--transition-base);
  position: relative;
  overflow: hidden;
  animation: card-enter 0.4s ease-out backwards;
}

.watch-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, #1d4ed8 0%, #6366f1 100%);
  opacity: 0;
  transition: opacity var(--transition-base);
}

.watch-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-2px);
}

.watch-card:hover::before {
  opacity: 1;
}

.watch-card.dragging {
  opacity: 0.55;
  border-color: var(--color-primary);
}

@keyframes card-enter {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Card header */
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-4);
  cursor: pointer;
}

.stock-identity {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  min-width: 0;
  flex: 1;
}

.stock-avatar {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: linear-gradient(135deg, #1d4ed8 0%, #6366f1 100%);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 4px 14px rgba(29, 78, 216, 0.25);
}

.avatar-text {
  font-size: 20px;
  font-weight: 800;
  color: #fff;
}

.stock-names {
  min-width: 0;
  flex: 1;
}

.stock-name {
  margin: 0 0 2px;
  font-size: 18px;
  font-weight: 800;
  color: var(--color-text);
  letter-spacing: -0.01em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stock-symbol {
  font-family: var(--font-number);
  font-size: 13px;
  color: var(--color-text-muted);
}

.market-tag {
  font-weight: 700;
  flex-shrink: 0;
}

/* Summary section */
.card-summary {
  cursor: pointer;
  margin-bottom: var(--space-3);
  padding: var(--space-3);
  background: var(--color-surface-muted);
  border-radius: var(--radius-sm);
  border: 1px solid var(--color-border);
}

.summary-text {
  font-size: 14px;
  line-height: 1.7;
  color: var(--color-text-secondary);
  margin-bottom: var(--space-2);
}

.summary-loading {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: 14px;
  color: var(--color-text-muted);
}

.loading-icon {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.summary-empty {
  font-size: 14px;
  color: var(--color-text-muted);
}

.summary-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;
}

.cache-tag {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-weight: 700;
}

.error-tag {
  font-weight: 700;
}

.summary-quality {
  margin: 0;
}

/* Risks */
.card-risks {
  margin-bottom: var(--space-3);
}

.risk-header {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  font-size: 12px;
  font-weight: 700;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: var(--space-2);
}

.risk-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
}

.risk-chip {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  color: var(--color-text-secondary);
  cursor: default;
}

.risk-chip.green {
  background: var(--color-success-bg);
  color: var(--color-success);
  border-color: rgba(22, 163, 106, 0.2);
}

.risk-chip.yellow {
  background: var(--color-warning-soft);
  color: var(--color-warning);
  border-color: rgba(196, 122, 16, 0.2);
}

.risk-chip.red {
  background: var(--color-danger-soft);
  color: var(--color-up);
  border-color: rgba(226, 59, 59, 0.2);
}

/* Actions */
.card-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border);
}

.card-actions .el-button {
  font-weight: 700;
}

/* Empty state */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--space-16) var(--space-8);
  text-align: center;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-muted);
}

.empty-state h2 {
  margin: var(--space-4) 0 var(--space-2);
  font-size: 20px;
  font-weight: 800;
  color: var(--color-text);
}

.empty-state p {
  margin: 0 0 var(--space-4);
  font-size: 14px;
}

.empty-icon {
  color: var(--color-border-strong);
}

/* Add dialog */
.add-dialog-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.import-dialog-content {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.add-tip {
  margin: 0;
  font-size: 13px;
  color: var(--color-text-muted);
}

/* Responsive */
@media (max-width: 768px) {
  .page-header {
    flex-direction: column;
    align-items: stretch;
  }

  .header-actions {
    justify-content: space-between;
  }

  .watchlist-grid,
  .skeleton-grid {
    grid-template-columns: 1fr;
  }
}
</style>
