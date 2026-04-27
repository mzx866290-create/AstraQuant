<template>
  <div class="stock-detail" v-loading="loading">
    <!-- 股票标题 -->
    <div class="stock-header">
      <h2>{{ stockName || symbol }}</h2>
      <span class="stock-code">{{ symbol }}</span>
      <span class="stock-tag" :class="marketClass">{{ marketText }}</span>
    </div>

    <!-- 实时行情面板 -->
    <QuotePanel :quote="quote" />

    <!-- 图表切换 -->
    <el-card class="chart-card" shadow="never">
      <template #header>
        <div class="chart-tabs">
          <el-radio-group v-model="chartMode" size="small">
            <el-radio-button value="kline">K线图</el-radio-button>
            <el-radio-button value="timeshare">分时图</el-radio-button>
          </el-radio-group>
        </div>
      </template>
      <KLineChart v-if="chartMode === 'kline'" :symbol="symbol" />
      <TimeShareChart v-else :symbol="symbol" />
    </el-card>

    <!-- 资金流向 -->
    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :span="12">
        <el-card shadow="never">
          <MoneyFlowChart :symbol="symbol" />
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>
            <span class="card-title">个股信息</span>
          </template>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="股票名称">{{ stockInfo.name || '--' }}</el-descriptions-item>
            <el-descriptions-item label="所属行业">{{ stockInfo.sector || '--' }}</el-descriptions-item>
            <el-descriptions-item label="上市日期">{{ stockInfo.listDate || '--' }}</el-descriptions-item>
            <el-descriptions-item label="总市值">{{ formatMV(quote.total_mv) }}</el-descriptions-item>
            <el-descriptions-item label="市盈率(动)">{{ quote.pe_ttm ? quote.pe_ttm.toFixed(2) : '--' }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>

    <!-- AI 智能分析 -->
    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :span="24">
        <AIAnalysisCard :symbol="symbol" />
      </el-col>
    </el-row>

    <!-- 实时新闻 + 公告 -->
    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :span="14">
        <NewsFeed :symbol="rawSymbol" />
      </el-col>
      <el-col :span="10">
        <AnnouncementTimeline :symbol="rawSymbol" />
      </el-col>
    </el-row>

    <!-- 财务数据 -->
    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :span="24">
        <FinancialReportTable :symbol="rawSymbol" />
      </el-col>
    </el-row>

    <!-- 数据来源追溯 -->
    <SourceAttributionBanner :sources="dataSources" />

    <!-- 免责声明 -->
    <Disclaimer />

    <!-- 错误提示 -->
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      closable
      style="margin-top: 16px"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, reactive, computed } from 'vue'
import { useRoute } from 'vue-router'
import KLineChart from '@/components/charts/KLineChart.vue'
import TimeShareChart from '@/components/charts/TimeShareChart.vue'
import MoneyFlowChart from '@/components/charts/MoneyFlowChart.vue'
import QuotePanel from '@/components/stock/QuotePanel.vue'
import Disclaimer from '@/components/common/Disclaimer.vue'
import AIAnalysisCard from '@/components/ai/AIAnalysisCard.vue'
import NewsFeed from '@/components/stock/NewsFeed.vue'
import AnnouncementTimeline from '@/components/stock/AnnouncementTimeline.vue'
import FinancialReportTable from '@/components/stock/FinancialReportTable.vue'
import SourceAttributionBanner from '@/components/common/SourceAttributionBanner.vue'
import { useStockData, type QuoteData } from '@/composables/useStockData'
import { stockApi } from '@/api'

const route = useRoute()
const symbol = ref((route.params.symbol as string) || '600519.SH')
const stockName = ref('')
const loading = ref(false)
const error = ref<string | null>(null)
const chartMode = ref('kline')
const quote = reactive<Partial<QuoteData>>({})
const stockInfo = reactive({
  name: '',
  sector: '',
  listDate: '',
})
const { fetchQuote } = useStockData()

const rawSymbol = computed(() => symbol.value.replace(/\.(SH|SZ)$/, ''))
const dataSources = reactive({
  kline: '东方财富/AKShare',
  financial: 'AKShare',
  news: '东方财富/新浪/AKShare',
  announcements: 'AKShare/东方财富',
  financialFreshness: 'today',
})

const marketText = ref('沪市')
const marketClass = computed(() => marketText.value === '沪市' ? 'tag-sh' : 'tag-sz')

function formatMV(v?: number) {
  if (!v) return '--'
  if (v >= 1e12) return (v / 1e12).toFixed(2) + '万亿'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  return (v / 1e4).toFixed(2) + '万'
}

onMounted(async () => {
  // 从symbol解析市场
  const raw = symbol.value
  if (raw.endsWith('.SH')) marketText.value = '沪市'
  else if (raw.endsWith('.SZ')) marketText.value = '深市'
  else if (raw.startsWith('6')) marketText.value = '沪市'

  if (!raw.includes('.')) {
    // 自动补全 .SH
    symbol.value = raw.startsWith('6') ? `${raw}.SH` : `${raw}.SZ`
  }

  // 并行加载行情和个股信息
  loading.value = true
  try {
    const [q, info] = await Promise.all([
      fetchQuote(symbol.value).catch(() => null),
      stockApi.getStockDetail(symbol.value).catch(() => null),
    ])
    if (q) Object.assign(quote, q)
    if (info) {
      stockName.value = info.name || ''
      stockInfo.name = info.name || ''
      stockInfo.sector = info.sector || ''
      stockInfo.listDate = info.list_date || ''
    }
  } catch (e: any) {
    error.value = '数据加载失败: ' + (e.message || '')
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.stock-detail {
  max-width: 1200px;
  margin: 0 auto;
}

.stock-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.stock-header h2 {
  margin: 0;
  font-size: 22px;
  color: #303133;
}

.stock-code {
  color: #909399;
  font-size: 14px;
  font-family: monospace;
}

.stock-tag {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 500;
}

.tag-sh {
  background: #e6f7ff;
  color: #1890ff;
}

.tag-sz {
  background: #f6ffed;
  color: #52c41a;
}

.chart-card {
  margin-top: 12px;
}

.card-title {
  font-size: 14px;
  font-weight: 600;
}
</style>
