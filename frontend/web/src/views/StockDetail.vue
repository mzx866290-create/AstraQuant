<template>
  <div class="stock-detail" v-loading="loading">
    <section class="stock-hero dashboard-card">
      <div class="stock-identity">
        <div>
          <div class="eyebrow">股票详情</div>
          <h2>{{ stockName || symbol }}</h2>
        </div>
        <div class="identity-tags">
          <span class="stock-code">{{ symbol }}</span>
          <span class="stock-tag" :class="marketClass">{{ marketText }}</span>
        </div>
      </div>
      <div class="hero-price">
        <span class="price-label">最新价</span>
        <strong :class="priceClass">{{ formatPrice(quote.price) }}</strong>
        <span :class="priceClass" class="price-change">
          {{ formatSigned(quote.change) }} / {{ formatPct(quote.change_pct) }}
        </span>
      </div>
    </section>

    <QuotePanel :quote="quote" />

    <el-alert
      v-if="dataAvailabilityMessage"
      :title="dataAvailabilityMessage"
      type="warning"
      show-icon
      :closable="false"
      class="data-alert"
    />

    <div class="beginner-guide">
      <div v-for="item in beginnerChecks" :key="item.key" class="guide-item" :class="item.level">
        <span class="guide-label">{{ item.label }}</span>
        <span class="guide-text">{{ item.text }}</span>
      </div>
    </div>

    <el-card class="chart-card dashboard-card" shadow="never">
      <template #header>
        <div class="dashboard-card-header">
          <h3 class="dashboard-card-title">行情图表</h3>
          <el-radio-group v-model="chartMode" size="small">
            <el-radio-button value="kline">K线图</el-radio-button>
            <el-radio-button value="timeshare">分时图</el-radio-button>
          </el-radio-group>
        </div>
      </template>
      <KLineChart v-if="chartMode === 'kline'" :symbol="symbol" />
      <TimeShareChart v-else :symbol="symbol" />
    </el-card>

    <div class="content-grid two-column">
      <el-card class="dashboard-card" shadow="never">
        <MoneyFlowChart :symbol="symbol" />
      </el-card>
      <el-card class="dashboard-card" shadow="never">
        <template #header>
          <div class="dashboard-card-header">
            <h3 class="dashboard-card-title">个股信息</h3>
          </div>
        </template>
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="股票名称">{{ stockInfo.name || '--' }}</el-descriptions-item>
          <el-descriptions-item label="所属行业">{{ stockInfo.sector || '--' }}</el-descriptions-item>
          <el-descriptions-item label="上市日期">{{ stockInfo.listDate || '--' }}</el-descriptions-item>
          <el-descriptions-item label="总市值">{{ formatMarketValue(quote.total_mv) }}</el-descriptions-item>
          <el-descriptions-item label="流通市值">{{ formatMarketValue(quote.circ_mv || stockInfo.circMv) }}</el-descriptions-item>
          <el-descriptions-item label="总股本">{{ formatShares(stockInfo.totalShares) }}</el-descriptions-item>
          <el-descriptions-item label="市盈率(动)">{{ quote.pe_ttm ? quote.pe_ttm.toFixed(2) : '--' }}</el-descriptions-item>
        </el-descriptions>
      </el-card>
    </div>

    <AIAnalysisCard :symbol="symbol" :refresh-key="refreshKey" />

    <div class="content-grid news-grid">
      <NewsFeed :symbol="rawSymbol" @crawl-complete="refreshReadiness" />
      <AnnouncementTimeline :symbol="rawSymbol" @crawl-complete="refreshReadiness" />
    </div>

    <FinancialReportTable :symbol="rawSymbol" @crawl-complete="refreshReadiness" />

    <SourceAttributionBanner :sources="dataSources" />
    <Disclaimer />

    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      closable
      class="error-alert"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, defineAsyncComponent } from 'vue'
import { useRoute } from 'vue-router'
import QuotePanel from '@/components/stock/QuotePanel.vue'
import Disclaimer from '@/components/common/Disclaimer.vue'
import SourceAttributionBanner from '@/components/common/SourceAttributionBanner.vue'
import { useStockData, type QuoteData } from '@/composables/useStockData'
import { stockApi } from '@/api'
import { formatMarketValue, formatPct, formatPrice, formatShares, formatSigned } from '@/utils/formatters'
import type { DataQualityItem } from '@/utils/dataQuality'

const KLineChart = defineAsyncComponent(() => import('@/components/charts/KLineChart.vue'))
const TimeShareChart = defineAsyncComponent(() => import('@/components/charts/TimeShareChart.vue'))
const MoneyFlowChart = defineAsyncComponent(() => import('@/components/charts/MoneyFlowChart.vue'))
const AIAnalysisCard = defineAsyncComponent(() => import('@/components/ai/AIAnalysisCard.vue'))
const NewsFeed = defineAsyncComponent(() => import('@/components/stock/NewsFeed.vue'))
const AnnouncementTimeline = defineAsyncComponent(() => import('@/components/stock/AnnouncementTimeline.vue'))
const FinancialReportTable = defineAsyncComponent(() => import('@/components/stock/FinancialReportTable.vue'))

const route = useRoute()
const symbol = ref((route.params.symbol as string) || '600519.SH')
const stockName = ref('')
const loading = ref(false)
const error = ref<string | null>(null)
const quoteError = ref<string | null>(null)
const detailError = ref<string | null>(null)
const chartMode = ref('kline')
const quote = reactive<Partial<QuoteData>>({})
const refreshKey = ref(0)
const stockInfo = reactive({
  name: '',
  sector: '',
  listDate: '',
  latestPrice: 0,
  totalMv: 0,
  circMv: 0,
  totalShares: 0,
  floatShares: 0,
})
interface StockInfoPayload {
  name?: string
  sector?: string
  list_date?: string
  latest_price?: number
  total_mv?: number
  circ_mv?: number
  total_shares?: number
  float_shares?: number
}

interface QuotePayload {
  name?: string
  price?: number
  total_mv?: number
  circ_mv?: number
}

const { fetchQuote } = useStockData()

const rawSymbol = computed(() => symbol.value.replace(/\.(SH|SZ|SS)$/, ''))
const hasDetailData = computed(() => Boolean(stockInfo.name || stockInfo.sector || stockInfo.listDate))
const dataSources = computed(() => ({
  kline: '东方财富/AKShare',
  financial: hasDetailData.value ? 'AKShare' : '暂不可用',
  news: '东方财富/新浪/AKShare',
  announcements: 'AKShare/东方财富',
  financialFreshness: hasDetailData.value ? 'today' : 'unavailable',
}))
const dataAvailabilityMessage = computed(() => {
  if (quoteError.value && detailError.value) return '行情和个股基础信息暂不可用，页面数值可能为空，请稍后重试。'
  if (quoteError.value) return '实时行情暂不可用，价格、涨跌幅和估值数据不可作为当前行情参考。'
  if (detailError.value) return '个股基础信息暂不可用，行业、上市日期等资料可能缺失。'
  return ''
})

const marketText = ref('沪市')
const marketClass = computed(() => marketText.value === '沪市' ? 'tag-sh' : 'tag-sz')
const priceClass = computed(() => {
  const value = Number(quote.change_pct)
  if (!Number.isFinite(value)) return ''
  return value > 0 ? 'price-up' : value < 0 ? 'price-down' : ''
})
const beginnerChecks = computed(() => [
  {
    key: 'price',
    label: '价格有效性',
    level: quote.price && quote.price > 0 ? 'ok' : 'warn',
    text: quote.price && quote.price > 0
      ? `当前行情来自 ${quote.source || quote.data_quality?.source || '行情源'}${quote.data_quality?.is_fallback ? '，但属于降级数据' : ''}`
      : quoteError.value || '价格为空或为0，不能作为交易价格依据',
  },
  {
    key: 'valuation',
    label: '估值可判断性',
    level: quote.pe_ttm && quote.pe_ttm > 0 ? 'ok' : 'warn',
    text: quote.pe_ttm && quote.pe_ttm > 0 ? `PE(TTM) ${Number(quote.pe_ttm).toFixed(2)}，可作为估值参考` : 'PE/PB不完整，暂时无法判断贵不贵',
  },
  {
    key: 'company',
    label: '个股信息',
    level: stockInfo.name ? 'ok' : 'warn',
    text: stockInfo.name ? `${stockInfo.name}，行业：${stockInfo.sector || '未披露'}` : '个股基础信息未加载完整',
  },
])

function refreshReadiness() {
  refreshKey.value += 1
}

function normalizeSymbol(rawValue: string) {
  const raw = rawValue || '600519.SH'
  if (raw.includes('.')) return raw
  return raw.startsWith('6') ? `${raw}.SH` : `${raw}.SZ`
}

function updateMarketText(value: string) {
  if (value.endsWith('.SH') || value.startsWith('6')) marketText.value = '沪市'
  else marketText.value = '深市'
}

function resetStockInfo() {
  stockName.value = ''
  stockInfo.name = ''
  stockInfo.sector = ''
  stockInfo.listDate = ''
  stockInfo.latestPrice = 0
  stockInfo.totalMv = 0
  stockInfo.circMv = 0
  stockInfo.totalShares = 0
  stockInfo.floatShares = 0
}

function resetQuote() {
  for (const key of Object.keys(quote)) {
    delete (quote as Record<string, unknown>)[key]
  }
}

function errorMessage(err: unknown, fallback: string) {
  return (err as { message?: string })?.message || fallback
}

function unavailableQuality(message: string): DataQualityItem {
  return {
    source: 'unavailable',
    status: 'unavailable',
    freshness: 'error',
    confidence: 'low',
    is_fallback: true,
    warnings: [message],
  }
}

function applyStockInfo(info?: StockInfoPayload | null, q?: QuotePayload | null) {
  stockName.value = info?.name || q?.name || symbol.value
  stockInfo.name = info?.name || q?.name || ''
  stockInfo.sector = info?.sector || ''
  stockInfo.listDate = info?.list_date ? String(info.list_date).slice(0, 10) : ''
  stockInfo.latestPrice = Number(info?.latest_price || q?.price || 0)
  stockInfo.totalMv = Number(info?.total_mv || q?.total_mv || 0)
  stockInfo.circMv = Number(info?.circ_mv || q?.circ_mv || 0)
  stockInfo.totalShares = Number(info?.total_shares || 0)
  stockInfo.floatShares = Number(info?.float_shares || 0)
  if (!quote.total_mv && stockInfo.totalMv) quote.total_mv = stockInfo.totalMv
  if (!quote.circ_mv && stockInfo.circMv) quote.circ_mv = stockInfo.circMv
}

async function loadStockDetail(rawValue: string) {
  const nextSymbol = normalizeSymbol(rawValue)
  symbol.value = nextSymbol
  updateMarketText(nextSymbol)
  resetStockInfo()
  resetQuote()
  loading.value = true
  error.value = null
  quoteError.value = null
  detailError.value = null
  try {
    const [q, info] = await Promise.all([
      fetchQuote(nextSymbol).catch((err) => {
        quoteError.value = `行情请求失败：${errorMessage(err, '数据暂不可用')}`
        quote.data_quality = unavailableQuality(quoteError.value)
        return null
      }),
      stockApi.getStockDetail<StockInfoPayload>(nextSymbol).catch((err) => {
        detailError.value = `个股信息请求失败：${errorMessage(err, '数据暂不可用')}`
        return null
      }),
    ])
    if (q) Object.assign(quote, q)
    applyStockInfo(info, q)
    if (quoteError.value && detailError.value) {
      stockName.value = symbol.value
    }
  } catch (err) {
    error.value = '数据加载失败: ' + ((err as { message?: string }).message || '')
  } finally {
    loading.value = false
  }
}

watch(
  () => route.params.symbol as string,
  (value) => {
    loadStockDetail(value || '600519.SH')
  },
  { immediate: true }
)
</script>

<style scoped>
.stock-detail {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.stock-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: end;
  gap: var(--space-6);
  padding: var(--space-6);
}

.stock-identity {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--space-4);
}

.eyebrow {
  margin-bottom: var(--space-2);
  color: var(--color-text-muted);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
  text-transform: uppercase;
}

.stock-identity h2 {
  margin: 0;
  color: var(--color-text);
  font-size: 30px;
  font-weight: 800;
  letter-spacing: 0;
}

.identity-tags {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.stock-code {
  color: var(--color-text-secondary);
  font-family: var(--font-number);
  font-size: 14px;
}

.stock-tag {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 999px;
  font-weight: 700;
}

.tag-sh {
  background: #e8f3ff;
  color: #1264c8;
}

.tag-sz {
  background: #eaf8f0;
  color: #128052;
}

.hero-price {
  min-width: 220px;
  text-align: right;
}

.price-label {
  display: block;
  margin-bottom: var(--space-2);
  color: var(--color-text-muted);
  font-size: 12px;
}

.hero-price strong {
  display: block;
  font-family: var(--font-number);
  font-size: 38px;
  line-height: 1;
  letter-spacing: 0;
}

.price-change {
  display: block;
  margin-top: var(--space-2);
  font-family: var(--font-number);
  font-size: 14px;
}

.beginner-guide {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
}

.guide-item {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  background: var(--color-surface);
}

.guide-item.ok {
  border-color: rgba(22, 163, 106, 0.24);
  background: #f2fbf6;
}

.guide-item.warn {
  border-color: #f2d48b;
  background: var(--color-warning-soft);
}

.guide-label {
  display: block;
  font-size: 12px;
  color: var(--color-text-muted);
  margin-bottom: var(--space-1);
}

.guide-text {
  color: var(--color-text-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.content-grid {
  display: grid;
  gap: var(--space-5);
}

.two-column {
  grid-template-columns: minmax(0, 1.1fr) minmax(320px, 0.9fr);
}

.news-grid {
  grid-template-columns: minmax(0, 1.4fr) minmax(320px, 1fr);
}

.error-alert {
  margin-top: var(--space-2);
}

.data-alert {
  margin-top: calc(var(--space-5) * -0.5);
}

@media (max-width: 960px) {
  .stock-hero,
  .stock-identity {
    align-items: flex-start;
    grid-template-columns: 1fr;
    flex-direction: column;
  }

  .hero-price {
    text-align: left;
  }

  .beginner-guide,
  .two-column,
  .news-grid {
    grid-template-columns: 1fr;
  }
}
</style>
