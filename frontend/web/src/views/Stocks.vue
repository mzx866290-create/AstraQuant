<template>
  <div class="stocks-page">
    <!-- 搜索栏 -->
    <el-card shadow="never" class="search-card">
      <div class="search-grid">
        <el-input
          v-model="searchQuery"
          placeholder="搜索A股代码/名称 (如 600519 或 贵州茅台)"
          clearable
          @keyup.enter="doSearch"
          @clear="loadStockList"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
        <el-button type="primary" @click="doSearch">搜索</el-button>
        <el-checkbox-group v-model="selectedMarkets" size="small" class="market-filters" aria-label="市场筛选">
          <el-checkbox-button value="SH">沪市</el-checkbox-button>
          <el-checkbox-button value="SZ">深市</el-checkbox-button>
          <el-checkbox-button value="BJ">北交所</el-checkbox-button>
        </el-checkbox-group>
      </div>
    </el-card>

    <!-- 股票列表 -->
    <el-card shadow="never" class="stock-list-card">
      <template #header>
        <span>{{ tableTitle }}</span>
      </template>

      <el-alert
        v-if="listNotice"
        class="list-notice"
        type="warning"
        show-icon
        :closable="false"
        :title="listNotice"
      />

      <el-table
        :data="stockList"
        stripe
        class="stocks-table"
        v-loading="loading"
        @row-click="goDetail"
      >
        <el-table-column prop="symbol" label="代码" width="120">
          <template #default="{ row }">
            <span class="symbol-text">{{ row.symbol }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" width="160" />
        <el-table-column prop="market" label="市场" width="80">
          <template #default="{ row }">
            <el-tag :type="row.market === 'SH' ? undefined : 'success'" size="small">
              {{ row.market === 'SH' ? '沪市' : row.market === 'SZ' ? '深市' : '北交所' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="sector" label="行业" width="120" />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button type="primary" link @click.stop="goDetail(row)">
              查看详情
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <Disclaimer />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
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
}

const router = useRouter()

const searchQuery = ref('')
const stockList = ref<StockListItem[]>([])
const loading = ref(false)
const isSearching = ref(false)
const selectedMarkets = ref<string[]>(['SH', 'SZ'])
const listNotice = ref('')
const isSampleList = ref(false)

const tableTitle = computed(() => {
  if (isSearching.value) return '搜索结果'
  return isSampleList.value ? '本地示例入口' : 'A股股票列表'
})

// 本地示例只用于服务不可用时提供跳转入口，不代表热门排序或实时市场判断。
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

async function doSearch() {
  const q = searchQuery.value.trim()
  if (!q) {
    loadStockList()
    return
  }
  loading.value = true
  isSearching.value = true
  listNotice.value = ''
  isSampleList.value = false
  try {
    const res: { results?: StockListItem[] } = await stockApi.searchStocks(q)
    stockList.value = res.results || []
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

async function loadStockList() {
  isSearching.value = false
  loading.value = true
  listNotice.value = ''
  isSampleList.value = false
  try {
    const markets = selectedMarkets.value.length ? selectedMarkets.value : ['SH', 'SZ', 'BJ']
    const responses = await Promise.all(
      markets.map((market) => stockApi.getStocks<StockListResponse>(market))
    )
    const rows = responses.flatMap((res) => res.stocks || res.results || [])
    const seen = new Set<string>()
    stockList.value = rows.filter((row) => {
      if (!row.symbol || seen.has(row.symbol)) return false
      seen.add(row.symbol)
      return true
    })
    if (!stockList.value.length) {
      stockList.value = selectedSampleStocks()
      isSampleList.value = true
      listNotice.value = '股票列表服务暂未返回数据，当前显示本地示例入口，不代表热门排序或实时市场状态。'
    }
  } catch {
    stockList.value = selectedSampleStocks()
    isSampleList.value = true
    listNotice.value = '股票列表服务暂不可用，当前显示本地示例入口，不代表热门排序或实时市场状态。'
  } finally {
    loading.value = false
  }
}

function goDetail(row: StockListItem) {
  router.push(`/stocks/${row.symbol}`)
}

onMounted(() => {
  loadStockList()
})

watch(selectedMarkets, () => {
  if (!isSearching.value) loadStockList()
})
</script>

<style scoped>
.stocks-page {
  max-width: 1000px;
  margin: 0 auto;
}

.search-card {
  margin-bottom: 0;
}

.search-grid {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) auto minmax(260px, auto);
  align-items: center;
  gap: var(--space-4);
}

.market-filters {
  min-width: 0;
  overflow-x: auto;
  white-space: nowrap;
}

.stock-list-card {
  margin-top: 12px;
}

.list-notice {
  margin-bottom: 12px;
}

.stocks-table {
  width: 100%;
}

.symbol-text {
  font-family: monospace;
  font-weight: 600;
}

:deep(.el-table__row) {
  cursor: pointer;
}

@media (max-width: 768px) {
  .search-grid {
    grid-template-columns: 1fr;
  }

  .search-grid .el-button {
    width: 100%;
  }
}
</style>
