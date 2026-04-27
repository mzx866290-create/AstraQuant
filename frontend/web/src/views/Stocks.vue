<template>
  <div class="stocks-page">
    <!-- 搜索栏 -->
    <el-card shadow="never" class="search-card">
      <el-row :gutter="16" align="middle">
        <el-col :span="8">
          <el-input
            v-model="searchQuery"
            placeholder="搜索A股代码/名称 (如 600519 或 贵州茅台)"
            clearable
            @keyup.enter="doSearch"
            @clear="loadHotStocks"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </el-col>
        <el-col :span="4">
          <el-button type="primary" @click="doSearch">搜索</el-button>
        </el-col>
        <el-col :span="12">
          <el-checkbox-group v-model="selectedMarkets" size="small">
            <el-checkbox-button value="SH">沪市</el-checkbox-button>
            <el-checkbox-button value="SZ">深市</el-checkbox-button>
            <el-checkbox-button value="BJ">北交所</el-checkbox-button>
          </el-checkbox-group>
        </el-col>
      </el-row>
    </el-card>

    <!-- 股票列表 -->
    <el-card shadow="never" style="margin-top: 12px">
      <template #header>
        <span>{{ isSearching ? '搜索结果' : 'A股热门股票' }}</span>
      </template>

      <el-table
        :data="stockList"
        stripe
        style="width: 100%"
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
            <el-tag :type="row.market === 'SH' ? '' : 'success'" size="small">
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
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
import { stockApi } from '@/api'
import Disclaimer from '@/components/common/Disclaimer.vue'

const router = useRouter()

const searchQuery = ref('')
const stockList = ref<any[]>([])
const loading = ref(false)
const isSearching = ref(false)
const selectedMarkets = ref<string[]>(['SH', 'SZ'])

// A股热门股票
const hotStocks = [
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

async function doSearch() {
  const q = searchQuery.value.trim()
  if (!q) {
    loadHotStocks()
    return
  }
  loading.value = true
  isSearching.value = true
  try {
    const res: any = await stockApi.searchStocks(q)
    stockList.value = res.results || []
  } catch {
    stockList.value = hotStocks.filter(
      s => s.symbol.includes(q) || s.name.includes(q)
    )
  } finally {
    loading.value = false
  }
}

function loadHotStocks() {
  isSearching.value = false
  stockList.value = hotStocks
}

function goDetail(row: any) {
  router.push(`/stocks/${row.symbol}`)
}

onMounted(() => {
  loadHotStocks()
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

.symbol-text {
  font-family: monospace;
  font-weight: 600;
}

:deep(.el-table__row) {
  cursor: pointer;
}
</style>
