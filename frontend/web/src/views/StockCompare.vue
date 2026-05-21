<template>
  <div class="stock-compare-page">
    <section class="page-header dashboard-card">
      <div>
        <span class="eyebrow">横向研究</span>
        <h1>多股对比</h1>
      </div>
      <div class="compare-actions">
        <el-select
          v-model="selectedSymbol"
          filterable
          remote
          reserve-keyword
          clearable
          placeholder="搜索股票代码或名称"
          :remote-method="searchStocks"
          :loading="searchLoading"
          class="search-select"
        >
          <el-option
            v-for="item in searchResults"
            :key="item.symbol"
            :label="`${item.name} ${item.symbol}`"
            :value="item.symbol"
          />
        </el-select>
        <el-button @click="addSelectedStock" :disabled="!selectedSymbol || selectedSymbols.length >= 5">加入</el-button>
        <el-button type="primary" :loading="loading" :disabled="selectedSymbols.length < 2" @click="loadCompare">
          对比
        </el-button>
      </div>
    </section>

    <section class="selected-panel">
      <el-tag
        v-for="item in selectedSymbols"
        :key="item"
        closable
        size="large"
        @close="removeSymbol(item)"
      >
        {{ stockLabel(item) }}
      </el-tag>
    </section>

    <el-alert
      v-if="error"
      :title="error"
      type="warning"
      show-icon
      :closable="false"
    />

    <section class="chart-grid">
      <el-card class="dashboard-card" shadow="never">
        <template #header>
          <div class="dashboard-card-header">
            <h3 class="dashboard-card-title">区间涨跌幅</h3>
          </div>
        </template>
        <div ref="barChartRef" class="chart-box"></div>
      </el-card>

      <el-card class="dashboard-card" shadow="never">
        <template #header>
          <div class="dashboard-card-header">
            <h3 class="dashboard-card-title">多周期收益曲线</h3>
          </div>
        </template>
        <div ref="lineChartRef" class="chart-box"></div>
      </el-card>
    </section>

    <el-card class="dashboard-card" shadow="never">
      <template #header>
        <div class="dashboard-card-header">
          <h3 class="dashboard-card-title">指标对比</h3>
          <span class="source-label">{{ updatedAt ? `更新 ${updatedAt}` : '' }}</span>
        </div>
      </template>

      <el-table :data="indicatorRows" v-loading="loading" empty-text="请先选择至少两只股票并点击对比" stripe>
        <el-table-column prop="symbol" label="股票" min-width="140">
          <template #default="{ row }">
            <router-link class="stock-link" :to="`/stocks/${row.symbol}`">{{ stockLabel(row.symbol) }}</router-link>
          </template>
        </el-table-column>
        <el-table-column prop="latest_price" label="最新价" min-width="100" align="right">
          <template #default="{ row }">{{ formatNumber(row.latest_price) }}</template>
        </el-table-column>
        <el-table-column prop="status" label="数据状态" min-width="120">
          <template #default="{ row }">
            <el-tag
              size="small"
              :type="row.status.includes('不足') || row.status.includes('失败') ? 'warning' : 'info'"
              effect="light"
            >
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="ma5" label="MA5" min-width="100" align="right">
          <template #default="{ row }">{{ formatNumber(row.ma5) }}</template>
        </el-table-column>
        <el-table-column prop="ma20" label="MA20" min-width="100" align="right">
          <template #default="{ row }">{{ formatNumber(row.ma20) }}</template>
        </el-table-column>
        <el-table-column prop="rsi" label="RSI" min-width="100" align="right">
          <template #default="{ row }">{{ formatNumber(row.rsi) }}</template>
        </el-table-column>
        <el-table-column prop="perf5d" label="5日" min-width="100" align="right">
          <template #default="{ row }">
            <span :class="changeClass(row.perf5d)">{{ formatPctValue(row.perf5d) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="perf20d" label="20日" min-width="100" align="right">
          <template #default="{ row }">
            <span :class="changeClass(row.perf20d)">{{ formatPctValue(row.perf20d) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="perf60d" label="60日" min-width="100" align="right">
          <template #default="{ row }">
            <span :class="changeClass(row.perf60d)">{{ formatPctValue(row.perf60d) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import type { ECharts } from 'echarts/core'
import { analysisApi, stockApi } from '@/api'
import { loadKLineECharts } from '@/components/charts/echartsLoader'
import { readableApiError } from '@/utils/dataQuality'
import { normalizeStockSymbol } from '@/utils/symbols'

interface SearchResult {
  symbol: string
  name: string
}

interface SearchResponse {
  results?: SearchResult[]
}

interface CompareItem {
  latest_indicators?: Record<string, number | null>
  performance?: Record<string, number | null>
  latest_price?: number | null
  data_points?: number
  error?: string
}

interface CompareResponse {
  compare?: Record<string, CompareItem>
  updated_at?: string
}

interface PerformanceResponse {
  periods?: string[]
  data?: Record<string, Record<string, number | null>>
}

interface IndicatorRow {
  symbol: string
  status: string
  latest_price?: number | null
  ma5?: number | null
  ma20?: number | null
  rsi?: number | null
  perf5d?: number | null
  perf20d?: number | null
  perf60d?: number | null
}

const defaultSymbols = ['600519.SH', '000858.SZ', '601318.SH']
const selectedSymbols = ref<string[]>([...defaultSymbols])
const selectedSymbol = ref('')
const searchResults = ref<SearchResult[]>([])
const symbolNames = ref<Record<string, string>>({})
const searchLoading = ref(false)
const loading = ref(false)
const error = ref('')
const updatedAt = ref('')
const compareData = ref<Record<string, CompareItem>>({})
const performanceData = ref<Record<string, Record<string, number | null>>>({})
const periods = ref<string[]>(['1d', '5d', '20d', '60d'])
const barChartRef = ref<HTMLDivElement | null>(null)
const lineChartRef = ref<HTMLDivElement | null>(null)
let barChart: ECharts | null = null
let lineChart: ECharts | null = null

const indicatorRows = computed<IndicatorRow[]>(() => selectedSymbols.value.map((symbol) => {
  const item = compareData.value[symbol] || {}
  const indicators = item.latest_indicators || {}
  const performance = item.performance || {}
  return {
    symbol,
    status: item.error || (item.data_points ? `${item.data_points} 条K线` : '待加载'),
    latest_price: item.latest_price,
    ma5: indicators.ma5,
    ma20: indicators.ma20,
    rsi: indicators.rsi,
    perf5d: performance['5d'],
    perf20d: performance['20d'],
    perf60d: performance['60d'],
  }
}))

function normalizeSymbol(raw: string) {
  return raw.trim() ? normalizeStockSymbol(raw) : ''
}

function stockLabel(symbol: string) {
  const name = symbolNames.value[symbol]
  return name ? `${name} ${symbol}` : symbol
}

function formatNumber(value: unknown) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '--'
  return number.toFixed(2)
}

function formatPctValue(value: unknown) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '--'
  return `${number > 0 ? '+' : ''}${number.toFixed(2)}%`
}

function changeClass(value: unknown) {
  const number = Number(value)
  if (!Number.isFinite(number)) return ''
  return number > 0 ? 'up' : number < 0 ? 'down' : ''
}

async function searchStocks(query: string) {
  if (!query.trim()) {
    searchResults.value = []
    return
  }
  searchLoading.value = true
  try {
    const response = await stockApi.searchStocks<SearchResponse>(query, undefined, 10)
    searchResults.value = response.results || []
    for (const item of searchResults.value) {
      symbolNames.value[item.symbol] = item.name
    }
  } catch (e) {
    error.value = readableApiError(e, '搜索服务暂不可用，请稍后重试')
    searchResults.value = []
  } finally {
    searchLoading.value = false
  }
}

function addSelectedStock() {
  const symbol = normalizeSymbol(selectedSymbol.value)
  if (!symbol || selectedSymbols.value.includes(symbol) || selectedSymbols.value.length >= 5) return
  selectedSymbols.value.push(symbol)
  selectedSymbol.value = ''
}

function removeSymbol(symbol: string) {
  selectedSymbols.value = selectedSymbols.value.filter((item) => item !== symbol)
  void loadCompare()
}

function initCharts() {
  const echarts = loadKLineECharts()
  if (barChartRef.value && !barChart) barChart = echarts.init(barChartRef.value)
  if (lineChartRef.value && !lineChart) lineChart = echarts.init(lineChartRef.value)
}

function renderCharts() {
  initCharts()
  const symbols = selectedSymbols.value
  const selectedPeriod = '20d'

  barChart?.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 46, right: 18, top: 28, bottom: 36 },
    xAxis: { type: 'category', data: symbols.map(stockLabel) },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    series: [{
      type: 'bar',
      data: symbols.map((symbol) => performanceData.value[symbol]?.[selectedPeriod] ?? compareData.value[symbol]?.performance?.[selectedPeriod] ?? null),
      itemStyle: {
        color: (params: { value: number }) => Number(params.value) >= 0 ? '#e23b3b' : '#16a36a',
      },
    }],
  })

  lineChart?.setOption({
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    grid: { left: 46, right: 18, top: 42, bottom: 36 },
    xAxis: { type: 'category', data: periods.value },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    series: symbols.map((symbol) => ({
      name: stockLabel(symbol),
      type: 'line',
      smooth: true,
      data: periods.value.map((period) => performanceData.value[symbol]?.[period] ?? null),
    })),
  })
}

async function loadCompare() {
  if (selectedSymbols.value.length < 2) {
    error.value = '请至少选择两只股票'
    compareData.value = {}
    performanceData.value = {}
    await nextTick()
    renderCharts()
    return
  }
  loading.value = true
  error.value = ''
  try {
    const symbolParam = selectedSymbols.value.join(',')
    const [compareResponse, performanceResponse] = await Promise.all([
      analysisApi.compare(symbolParam, 'ma5,ma20,rsi'),
      analysisApi.comparePerformance(symbolParam, '1d,5d,20d,60d'),
    ])
    compareData.value = (compareResponse as CompareResponse).compare || {}
    performanceData.value = (performanceResponse as PerformanceResponse).data || {}
    periods.value = (performanceResponse as PerformanceResponse).periods || ['1d', '5d', '20d', '60d']
    updatedAt.value = (compareResponse as CompareResponse).updated_at || ''
    await nextTick()
    renderCharts()
  } catch (e) {
    error.value = readableApiError(e, '多股对比数据暂不可用，请稍后重试')
  } finally {
    loading.value = false
  }
}

function handleResize() {
  barChart?.resize()
  lineChart?.resize()
}

onMounted(async () => {
  window.addEventListener('resize', handleResize)
  await nextTick()
  initCharts()
  await loadCompare()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  barChart?.dispose()
  lineChart?.dispose()
})
</script>

<style scoped>
.stock-compare-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.page-header {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: var(--space-5);
  padding: var(--space-6);
}

.eyebrow {
  color: var(--color-text-muted);
  font-size: 12px;
  font-weight: 800;
}

.page-header h1 {
  margin: var(--space-2) 0 0;
  color: var(--color-text);
  font-size: 30px;
  font-weight: 900;
}

.compare-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  justify-content: flex-end;
}

.search-select {
  width: min(360px, 52vw);
}

.selected-panel {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  min-height: 42px;
  align-items: center;
}

.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--space-5);
}

.chart-box {
  width: 100%;
  height: 320px;
}

.source-label {
  color: var(--color-text-muted);
  font-size: 12px;
}

.stock-link {
  color: var(--color-primary);
  font-weight: 800;
  text-decoration: none;
}

.up {
  color: var(--color-up);
  font-weight: 800;
}

.down {
  color: var(--color-down);
  font-weight: 800;
}

@media (max-width: 960px) {
  .page-header,
  .compare-actions {
    align-items: stretch;
    flex-direction: column;
  }

  .search-select,
  .compare-actions :deep(.el-button) {
    width: 100%;
  }

  .chart-grid {
    grid-template-columns: 1fr;
  }
}
</style>
