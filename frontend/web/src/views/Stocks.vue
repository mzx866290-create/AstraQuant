<template>
  <div class="stocks-page">
    <!-- 搜索栏 -->
    <div class="search-section">
      <div class="search-container">
        <el-input
          v-model="searchQuery"
          size="large"
          placeholder="搜索 A 股代码/名称 (如 600519 或 贵州茅台)"
          clearable
          class="search-input"
          @keyup.enter="doSearch"
          @clear="resetAndLoadStockList"
        >
          <template #prefix>
            <el-icon :size="18" class="search-icon"><Search /></el-icon>
          </template>
        </el-input>
        <el-button
          type="primary"
          size="large"
          class="search-btn"
          @click="doSearch"
        >
          <el-icon><Search /></el-icon>
          <span>搜索</span>
        </el-button>
      </div>

      <div class="filter-bar">
        <el-checkbox-group v-model="selectedMarkets" size="small" class="market-filters" aria-label="市场筛选">
          <el-checkbox-button value="SH">
            <el-icon><TrendCharts /></el-icon>
            <span>沪市</span>
          </el-checkbox-button>
          <el-checkbox-button value="SZ">
            <el-icon><TrendCharts /></el-icon>
            <span>深市</span>
          </el-checkbox-button>
          <el-checkbox-button value="BJ">
            <el-icon><TrendCharts /></el-icon>
            <span>北交所</span>
          </el-checkbox-button>
        </el-checkbox-group>
      </div>
    </div>

    <!-- 提示信息 -->
    <el-alert
      v-if="listNotice"
      class="list-notice"
      type="warning"
      show-icon
      :closable="false"
      :title="listNotice"
    />

    <!-- 骨架屏 -->
    <div v-if="loading" class="skeleton-grid">
      <div v-for="i in 8" :key="i" class="skeleton-card">
        <div class="skeleton-header">
          <div class="skeleton-title"></div>
          <div class="skeleton-badge"></div>
        </div>
        <div class="skeleton-line"></div>
        <div class="skeleton-line short"></div>
      </div>
    </div>

    <!-- 结果数量 -->
    <div v-else-if="stockList.length" class="result-info">
      <span class="result-count">显示 {{ stockList.length }} / {{ totalAvailable || stockList.length }} 只股票</span>
      <span v-if="isSampleList" class="sample-tag">示例数据</span>
    </div>

    <!-- 卡片网格 -->
    <div v-if="stockList.length" class="stocks-grid">
      <div
        v-for="(stock, index) in stockList"
        :key="stock.symbol"
        class="stock-card"
        role="button"
        tabindex="0"
        :style="{ animationDelay: `${index * 0.04}s` }"
        @click="goDetail(stock)"
        @keyup.enter="goDetail(stock)"
        @keyup.space.prevent="goDetail(stock)"
      >
        <div class="card-header">
          <div class="stock-info">
            <h3 class="stock-name">{{ stock.name }}</h3>
            <span class="stock-symbol">{{ stock.symbol }}</span>
          </div>
          <el-tag
            size="small"
            :type="marketTagType(stock.market)"
            effect="light"
            class="market-tag"
          >
            {{ marketLabel(stock.market) }}
          </el-tag>
        </div>

        <div v-if="stock.sector" class="stock-sector">
          <el-icon :size="14"><OfficeBuilding /></el-icon>
          <span>{{ stock.sector }}</span>
        </div>

        <div class="card-footer">
          <el-button type="primary" link class="view-btn">
            <el-icon><View /></el-icon>
            <span>查看详情</span>
          </el-button>
          <el-icon :size="16" class="arrow-icon"><ArrowRight /></el-icon>
        </div>
      </div>
    </div>

    <div v-if="canLoadMore" class="load-more">
      <el-button :loading="loadingMore" @click="loadMoreStocks">
        加载更多
      </el-button>
    </div>

    <!-- 空状态 -->
    <div v-else-if="!loading && !stockList.length" class="empty-state">
      <el-icon :size="64" class="empty-icon"><Search /></el-icon>
      <h3>未找到相关股票</h3>
      <p>尝试输入完整的股票代码或名称</p>
      <el-button type="primary" @click="searchQuery = ''; loadStockList()">
        显示全部
      </el-button>
    </div>

    <Disclaimer />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  Search,
  TrendCharts,
  OfficeBuilding,
  View,
  ArrowRight,
} from '@element-plus/icons-vue'
import { stockApi } from '@/api'
import Disclaimer from '@/components/common/Disclaimer.vue'

interface StockListItem {
  symbol: string
  name: string
  market: string
  sector?: string
}

interface StockListResponse {
  stocks?: StockListItem[]
  results?: StockListItem[]
  total?: number
  count?: number
}

const router = useRouter()

const searchQuery = ref('')
const stockList = ref<StockListItem[]>([])
const loading = ref(false)
const isSearching = ref(false)
const selectedMarkets = ref<string[]>(['SH', 'SZ', 'BJ'])
const listNotice = ref('')
const isSampleList = ref(false)
const pageSize = 50
const currentLimit = ref(pageSize)
const totalAvailable = ref(0)
const loadingMore = ref(false)

const canLoadMore = computed(() => (
  !loading.value &&
  !isSearching.value &&
  !isSampleList.value &&
  totalAvailable.value > stockList.value.length
))

const sampleStocks = [
  { symbol: '600519.SH', name: '贵州茅台', market: 'SH', sector: '食品饮料' },
  { symbol: '000858.SZ', name: '五粮液', market: 'SZ', sector: '食品饮料' },
  { symbol: '600036.SH', name: '招商银行', market: 'SH', sector: '银行' },
  { symbol: '000651.SZ', name: '格力电器', market: 'SZ', sector: '家电' },
  { symbol: '601398.SH', name: '工商银行', market: 'SH', sector: '银行' },
  { symbol: '000333.SZ', name: '美的集团', market: 'SZ', sector: '家电' },
  { symbol: '600276.SH', name: '恒瑞医药', market: 'SH', sector: '医药' },
  { symbol: '300750.SZ', name: '宁德时代', market: 'SZ', sector: '新能源' },
  { symbol: '601012.SH', name: '隆基绿能', market: 'SH', sector: '新能源' },
  { symbol: '000002.SZ', name: '万科A', market: 'SZ', sector: '房地产' },
  { symbol: '600030.SH', name: '中信证券', market: 'SH', sector: '证券' },
  { symbol: '002415.SZ', name: '海康威视', market: 'SZ', sector: '电子' },
]

function selectedSampleStocks() {
  const markets = selectedMarkets.value.length ? selectedMarkets.value : ['SH', 'SZ', 'BJ']
  return sampleStocks.filter((stock) => markets.includes(stock.market))
}

function marketTagType(market: string) {
  if (market === 'SH') return 'primary'
  if (market === 'SZ') return 'success'
  return 'warning'
}

function marketLabel(market: string) {
  if (market === 'SH') return '沪市'
  if (market === 'SZ') return '深市'
  if (market === 'BJ') return '北交所'
  return market
}

async function doSearch() {
  const q = searchQuery.value.trim()
  if (!q) {
    resetAndLoadStockList()
    return
  }
  loading.value = true
  isSearching.value = true
  listNotice.value = ''
  isSampleList.value = false
  totalAvailable.value = 0
  try {
    const markets = selectedMarkets.value.length ? selectedMarkets.value : ['SH', 'SZ', 'BJ']
    const responses = await Promise.all(
      markets.map((market) => stockApi.searchStocks<StockListResponse>(q, market, 50))
    )
    const rows = responses.flatMap((res) => res.results || res.stocks || [])
    const seen = new Set<string>()
    stockList.value = rows.filter((row) => {
      if (!row.symbol || seen.has(row.symbol)) return false
      seen.add(row.symbol)
      return true
    })
    totalAvailable.value = responses.reduce((sum, res) => sum + Number(res.total || res.count || 0), 0)
  } catch {
    stockList.value = selectedSampleStocks().filter(
      s => s.symbol.includes(q) || s.name.includes(q)
    )
    isSampleList.value = true
    listNotice.value = '搜索服务暂不可用，当前仅在本地示例入口中匹配，不代表真实搜索结果覆盖范围。'
  } finally {
    loading.value = false
  }
}

async function loadStockList(showLoading = true) {
  isSearching.value = false
  if (showLoading) loading.value = true
  listNotice.value = ''
  isSampleList.value = false
  try {
    const markets = selectedMarkets.value.length ? selectedMarkets.value : ['SH', 'SZ', 'BJ']
    const responses = await Promise.all(
      markets.map((market) => stockApi.getStocks<StockListResponse>(market, currentLimit.value, 0))
    )
    const rows = responses.flatMap((res) => res.stocks || res.results || [])
    const seen = new Set<string>()
    stockList.value = rows.filter((row) => {
      if (!row.symbol || seen.has(row.symbol)) return false
      seen.add(row.symbol)
      return true
    })
    totalAvailable.value = responses.reduce((sum, res) => sum + Number(res.total || res.count || 0), 0)
    if (!stockList.value.length) {
      stockList.value = selectedSampleStocks()
      totalAvailable.value = stockList.value.length
      isSampleList.value = true
      listNotice.value = '股票列表服务暂未返回数据，当前显示本地示例入口，不代表热门排序或实时市场状态。'
    }
  } catch {
    stockList.value = selectedSampleStocks()
    totalAvailable.value = stockList.value.length
    isSampleList.value = true
    listNotice.value = '股票列表服务暂不可用，当前显示本地示例入口，不代表热门排序或实时市场状态。'
  } finally {
    if (showLoading) loading.value = false
  }
}

function resetAndLoadStockList() {
  currentLimit.value = pageSize
  loadStockList()
}

async function loadMoreStocks() {
  loadingMore.value = true
  currentLimit.value += pageSize
  try {
    await loadStockList(false)
  } finally {
    loadingMore.value = false
  }
}

function goDetail(stock: StockListItem) {
  router.push(`/stocks/${stock.symbol}`)
}

onMounted(() => {
  resetAndLoadStockList()
})

let marketFilterTimer: ReturnType<typeof setTimeout> | null = null

watch(selectedMarkets, () => {
  if (marketFilterTimer) clearTimeout(marketFilterTimer)
  marketFilterTimer = setTimeout(() => {
    currentLimit.value = pageSize
    if (searchQuery.value.trim()) {
      doSearch()
    } else {
      loadStockList()
    }
  }, 300)
})

onBeforeUnmount(() => {
  if (marketFilterTimer) clearTimeout(marketFilterTimer)
})
</script>

<style scoped>
.stocks-page {
  max-width: 1200px;
  margin: 0 auto;
}

/* Search section */
.search-section {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  margin-bottom: var(--space-5);
  box-shadow: var(--shadow-card);
}

.search-container {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.search-input {
  flex: 1;
}

.search-input :deep(.el-input__wrapper) {
  border-radius: var(--radius-md);
  box-shadow: 0 0 0 1px var(--color-border-strong) inset;
  padding-left: var(--space-3);
}

.search-input :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--color-primary) inset;
}

.search-input :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px var(--color-primary) inset, 0 0 0 4px var(--color-primary-soft);
}

.search-icon {
  color: var(--color-text-muted);
}

.search-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: 0 24px;
  font-weight: 700;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, #1d4ed8 0%, #6366f1 100%);
  border: none;
}

/* Filter bar */
.filter-bar {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.market-filters {
  display: flex;
  gap: var(--space-2);
}

.market-filters :deep(.el-checkbox-button__inner) {
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  border-radius: var(--radius-sm);
  font-weight: 600;
}

/* Notice */
.list-notice {
  margin-bottom: var(--space-4);
  border-radius: var(--radius-md);
}

/* Result info */
.result-info {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
  padding: 0 var(--space-2);
}

.result-count {
  font-size: 14px;
  font-weight: 700;
  color: var(--color-text);
}

.sample-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.load-more {
  display: flex;
  justify-content: center;
  margin: var(--space-5) 0 var(--space-4);
}

/* Skeleton */
.skeleton-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
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
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-4);
}

.skeleton-title {
  width: 100px;
  height: 20px;
  border-radius: var(--radius-sm);
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
}

.skeleton-badge {
  width: 48px;
  height: 24px;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
}

.skeleton-line {
  height: 16px;
  width: 60%;
  border-radius: var(--radius-sm);
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
  margin-bottom: var(--space-2);
}

.skeleton-line.short {
  width: 40%;
}

@keyframes skeleton-loading {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Stock cards */
.stocks-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-4);
}

.stock-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  cursor: pointer;
  transition: all var(--transition-base);
  position: relative;
  overflow: hidden;
  animation: card-enter 0.4s ease-out backwards;
}

.stock-card::before {
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

.stock-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-2px);
}

.stock-card:hover::before {
  opacity: 1;
}

.stock-card:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
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

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.stock-info {
  min-width: 0;
  flex: 1;
}

.stock-name {
  margin: 0 0 var(--space-1);
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

.stock-sector {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  background: var(--color-surface-muted);
  border-radius: var(--radius-sm);
  font-size: 13px;
  color: var(--color-text-secondary);
  margin-bottom: var(--space-3);
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border);
}

.view-btn {
  font-weight: 700;
}

.arrow-icon {
  color: var(--color-text-muted);
  transition: all var(--transition-fast);
}

.stock-card:hover .arrow-icon {
  color: var(--color-primary);
  transform: translateX(4px);
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
  margin: 0 0 var(--space-4);
  font-size: 14px;
}

.empty-icon {
  color: var(--color-border-strong);
}

/* Responsive */
@media (max-width: 768px) {
  .search-container {
    flex-direction: column;
  }

  .search-btn {
    width: 100%;
    justify-content: center;
  }

  .market-filters {
    width: 100%;
    overflow-x: auto;
    white-space: nowrap;
    scrollbar-width: none;
  }

  .market-filters::-webkit-scrollbar {
    display: none;
  }

  .stocks-grid,
  .skeleton-grid {
    grid-template-columns: 1fr;
  }

  .stock-card {
    padding: var(--space-4);
  }
}
</style>
