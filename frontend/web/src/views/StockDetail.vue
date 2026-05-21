<template>
  <div class="stock-detail" v-loading="loading">
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      closable
      class="error-alert"
    />
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
    >
      <template #default>
        <div class="data-alert-actions">
          <el-button size="small" type="warning" plain :loading="dataRecoveryLoading" @click="recoverMissingDataFromTop">
            {{ userStore.isLoggedIn ? '一键补全上下文数据' : '登录后补全上下文数据' }}
          </el-button>
        </div>
      </template>
    </el-alert>

    <div v-if="observationSummary" class="ai-summary-card">
      <div class="ai-summary-header">
        <el-icon class="ai-summary-icon"><DataAnalysis /></el-icon>
        <span class="ai-summary-title">AI 投资解读</span>
        <span class="ai-summary-date">{{ observationSummaryDate }}</span>
      </div>
      <p class="ai-summary-body">{{ observationSummary }}</p>
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
      <KLineChart v-if="chartMode === 'kline'" :symbol="symbol" @data-quality-change="onKlineQualityChange" />
      <TimeShareChart v-else :symbol="symbol" />
    </el-card>

    <div class="content-grid news-grid">
      <NewsFeed :symbol="rawSymbol" @crawl-complete="refreshReadiness" @data-quality-change="onNewsQualityChange" />
      <AnnouncementTimeline :symbol="rawSymbol" @crawl-complete="refreshReadiness" @data-quality-change="onAnnouncementQualityChange" />
    </div>

    <AIAnalysisCard id="ai-analysis-section" ref="aiAnalysisCardRef" :symbol="symbol" :refresh-key="refreshKey" />

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
          <el-descriptions-item label="资料来源">{{ formatQualitySource(stockInfo.source || stockInfo.dataQuality?.source) || '--' }}</el-descriptions-item>
          <el-descriptions-item label="资料更新">{{ formatQualityTime(stockInfo.updatedAt || stockInfo.dataQuality?.updated_at) || '--' }}</el-descriptions-item>
          <el-descriptions-item label="数据质量">
            {{ profileQualityText }}
          </el-descriptions-item>
        </el-descriptions>
        <div v-if="profileWarnings.length" class="profile-quality-warnings">
          <el-tag v-for="warning in profileWarnings" :key="warning" size="small" type="warning" effect="light">
            {{ formatQualityWarning(warning) }}
          </el-tag>
        </div>
      </el-card>
    </div>

    <FinancialReportTable :symbol="rawSymbol" @crawl-complete="refreshReadiness" @data-quality-change="onFinancialQualityChange" />

    <!-- Analysis panels -->
    <el-collapse v-model="activeAnalysisSections" class="analysis-collapse">
      <!-- Section 1: Technical Score -->
      <el-collapse-item name="technical" title="技术评分">
        <div v-loading="techLoading || technicalLoading || patternLoading" class="analysis-panel-body">
          <template v-if="techData && !techError">
            <el-descriptions :column="1" border size="small" class="analysis-desc">
              <el-descriptions-item label="综合评分">
                <strong>{{ techData.total_score != null ? techData.total_score : '--' }}</strong> / 10
              </el-descriptions-item>
              <el-descriptions-item label="评级">{{ techData.rating || '--' }}</el-descriptions-item>
            </el-descriptions>
            <table v-if="techData.dimensions && techData.dimensions.length" class="analysis-table">
              <thead>
                <tr>
                  <th>维度</th>
                  <th>得分</th>
                  <th>权重</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="dim in techData.dimensions" :key="dim.name">
                  <td>{{ dim.label || dim.name }}</td>
                  <td>{{ dim.score != null ? dim.score : '--' }}</td>
                  <td>{{ dim.weight != null ? dim.weight : '--' }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="techData.warnings && techData.warnings.length" class="analysis-warnings">
              <span v-for="(w, i) in techData.warnings" :key="i" class="analysis-warning-item">
                <el-icon><WarningFilled /></el-icon>
                {{ w }}
              </span>
            </div>
          </template>
          <span v-else-if="techError" class="analysis-unavailable">技术评分暂不可用</span>

          <template v-if="technicalData && !technicalError">
            <div class="analysis-sub-title">均线 (MA)</div>
            <el-descriptions :column="2" border size="small" class="analysis-desc">
              <el-descriptions-item label="MA5">{{ fmtVal(lastVal(technicalData.ma5)) }}</el-descriptions-item>
              <el-descriptions-item label="MA20">{{ fmtVal(lastVal(technicalData.ma20)) }}</el-descriptions-item>
            </el-descriptions>

            <div class="analysis-sub-title">MACD</div>
            <el-descriptions :column="3" border size="small" class="analysis-desc">
              <el-descriptions-item label="DIF">{{ fmtVal(lastVal(technicalData.macd?.dif)) }}</el-descriptions-item>
              <el-descriptions-item label="DEA">{{ fmtVal(lastVal(technicalData.macd?.dea)) }}</el-descriptions-item>
              <el-descriptions-item label="柱状">{{ fmtVal(lastVal(technicalData.macd?.histogram)) }}</el-descriptions-item>
            </el-descriptions>

            <div class="analysis-sub-title">BOLL 布林带</div>
            <el-descriptions :column="3" border size="small" class="analysis-desc">
              <el-descriptions-item label="上轨">{{ fmtVal(lastVal(technicalData.boll?.upper)) }}</el-descriptions-item>
              <el-descriptions-item label="中轨">{{ fmtVal(lastVal(technicalData.boll?.middle)) }}</el-descriptions-item>
              <el-descriptions-item label="下轨">{{ fmtVal(lastVal(technicalData.boll?.lower)) }}</el-descriptions-item>
            </el-descriptions>

            <div class="analysis-sub-title">KDJ</div>
            <el-descriptions :column="3" border size="small" class="analysis-desc">
              <el-descriptions-item label="K">{{ fmtVal(lastVal(technicalData.kdj?.k)) }}</el-descriptions-item>
              <el-descriptions-item label="D">{{ fmtVal(lastVal(technicalData.kdj?.d)) }}</el-descriptions-item>
              <el-descriptions-item label="J">{{ fmtVal(lastVal(technicalData.kdj?.j)) }}</el-descriptions-item>
            </el-descriptions>

            <div class="analysis-sub-title">RSI</div>
            <el-descriptions :column="1" border size="small" class="analysis-desc">
              <el-descriptions-item label="RSI">{{ fmtVal(lastVal(technicalData.rsi)) }}</el-descriptions-item>
            </el-descriptions>
          </template>
          <span v-else-if="technicalError" class="analysis-unavailable">技术指标暂不可用</span>

          <template v-if="patternData.length">
            <div class="analysis-sub-title">近期K线形态</div>
            <div class="pattern-tags">
              <el-tooltip
                v-for="p in patternData"
                :key="p.name + p.date"
                :content="p.description || ''"
                placement="top"
                :disabled="!p.description"
              >
                <el-tag :type="patternTagType(p.signal)" size="small">
                  {{ PATTERN_NAMES[p.name] || p.name }} · {{ p.signal }}
                  <span v-if="p.date">({{ p.date }}, {{ p.confidence || '--' }})</span>
                </el-tag>
              </el-tooltip>
            </div>
          </template>
        </div>
      </el-collapse-item>

      <!-- Section 2: Financial Analysis -->
      <el-collapse-item name="financial" title="财务分析">
        <div v-loading="financialLoading" class="analysis-panel-body">
          <span v-if="financialError && fscoreError && dupointError" class="analysis-unavailable">数据暂不可用</span>
          <template v-else>
            <template v-if="financialData && !financialError">
              <div class="analysis-sub-title">核心指标</div>
              <el-descriptions :column="1" border size="small" class="analysis-desc">
                <el-descriptions-item label="营收同比">{{ fmtPctVal(financialData.revenue_yoy) }}</el-descriptions-item>
                <el-descriptions-item label="净利润同比">{{ fmtPctVal(financialData.net_profit_yoy) }}</el-descriptions-item>
                <el-descriptions-item label="ROE">{{ fmtPctVal(financialData.roe) }}</el-descriptions-item>
                <el-descriptions-item label="毛利率">{{ fmtPctVal(financialData.gross_margin) }}</el-descriptions-item>
                <el-descriptions-item label="经营现金流">{{ financialData.operating_cf != null ? financialData.operating_cf : '--' }}</el-descriptions-item>
              </el-descriptions>
            </template>
            <span v-else-if="financialError" class="analysis-unavailable">核心指标暂不可用</span>

            <template v-if="fscoreData && !fscoreError">
              <div class="analysis-sub-title">F-Score</div>
              <el-descriptions :column="1" border size="small" class="analysis-desc">
                <el-descriptions-item label="F-Score 总分">{{ fscoreData.total_score != null ? fscoreData.total_score : '--' }}</el-descriptions-item>
                <el-descriptions-item v-if="fscoreData.summary" label="摘要">{{ fscoreData.summary }}</el-descriptions-item>
              </el-descriptions>
            </template>
            <span v-else-if="fscoreError" class="analysis-unavailable">F-Score 暂不可用</span>

            <template v-if="dupontData && !dupointError">
              <div class="analysis-sub-title">杜邦分析</div>
              <el-descriptions :column="1" border size="small" class="analysis-desc">
                <el-descriptions-item label="净利润率">{{ fmtPctVal(dupontData.net_margin) }}</el-descriptions-item>
                <el-descriptions-item label="资产周转率">{{ dupontData.asset_turnover != null ? Number(dupontData.asset_turnover).toFixed(3) : '--' }}</el-descriptions-item>
                <el-descriptions-item label="财务杠杆">{{ dupontData.leverage != null ? Number(dupontData.leverage).toFixed(3) : '--' }}</el-descriptions-item>
                <el-descriptions-item label="ROE(杜邦)">{{ fmtPctVal(dupontData.roe) }}</el-descriptions-item>
              </el-descriptions>
            </template>
            <span v-else-if="dupointError" class="analysis-unavailable">杜邦分析暂不可用</span>
          </template>
        </div>
      </el-collapse-item>

      <!-- Section 3: Valuation -->
      <el-collapse-item name="valuation" title="估值分析">
        <div v-loading="valuationLoading" class="analysis-panel-body">
          <span v-if="valuationError" class="analysis-unavailable">数据暂不可用</span>
          <template v-else-if="valuationData">
            <el-descriptions :column="1" border size="small" class="analysis-desc">
              <el-descriptions-item v-if="valuationData.pe_ttm != null" label="PE(TTM)">{{ Number(valuationData.pe_ttm).toFixed(2) }}</el-descriptions-item>
              <el-descriptions-item v-if="valuationData.pb != null" label="PB">{{ Number(valuationData.pb).toFixed(2) }}</el-descriptions-item>
              <el-descriptions-item v-if="valuationData.ps != null" label="PS">{{ Number(valuationData.ps).toFixed(2) }}</el-descriptions-item>
              <el-descriptions-item v-if="valuationData.ev_ebitda != null" label="EV/EBITDA">{{ Number(valuationData.ev_ebitda).toFixed(2) }}</el-descriptions-item>
              <el-descriptions-item v-if="valuationData.dcf_value != null" label="DCF估值">{{ valuationData.dcf_value }}</el-descriptions-item>
              <el-descriptions-item v-if="valuationData.verdict" label="综合判断">{{ valuationData.verdict }}</el-descriptions-item>
            </el-descriptions>
          </template>
        </div>
      </el-collapse-item>

      <!-- Section 4: Research Debate -->
      <el-collapse-item name="debate" title="研究辩论">
        <div v-loading="debateLoading" class="analysis-panel-body">
          <span v-if="debateError" class="analysis-unavailable">研究辩论暂不可用</span>
          <template v-else-if="debateData">
            <div class="debate-summary">
              <div>
                <span>观察评分</span>
                <strong>{{ debateData.score ?? '--' }}</strong>
                <small v-if="debateData.rating?.text">{{ debateData.rating.text }}</small>
              </div>
              <div>
                <span>策略</span>
                <strong>{{ debateData.active_strategy?.name || strategyName(debateData.active_strategy?.id) }}</strong>
                <small>{{ strategyName(debateData.active_strategy?.engine_strategy) }}</small>
              </div>
              <div>
                <span>风险裁决</span>
                <el-tag size="small" :type="vetoTagType(debateData.veto_result)" effect="light">
                  {{ vetoLabel(debateData.veto_result) }}
                </el-tag>
                <small>{{ debateData.data_grade?.grade || 'D' }} {{ debateData.data_grade?.label || '数据待核验' }}</small>
              </div>
            </div>

            <div v-if="debateData.key_disagreement?.length" class="analysis-sub-title">关键分歧</div>
            <div v-if="debateData.key_disagreement?.length" class="disagreement-list">
              <div v-for="item in debateData.key_disagreement" :key="`${item.topic}-${item.bull_view}-${item.bear_view}`" class="disagreement-item">
                <strong>{{ item.topic || '当前策略判断' }}</strong>
                <span>看多：{{ item.bull_view || '--' }}</span>
                <span>看空：{{ item.bear_view || '--' }}</span>
              </div>
            </div>

            <div class="analysis-sub-title">多空观点</div>
            <div class="debate-grid">
              <div class="debate-column">
                <strong>看多逻辑</strong>
                <ul v-if="debateData.bull_case?.length">
                  <li v-for="item in debateData.bull_case" :key="`bull-${item.factor}-${item.argument}`">
                    {{ item.argument }}
                  </li>
                </ul>
                <span v-else class="analysis-unavailable">暂无明确看多证据</span>
              </div>
              <div class="debate-column">
                <strong>看空逻辑</strong>
                <ul v-if="debateData.bear_case?.length">
                  <li v-for="item in debateData.bear_case" :key="`bear-${item.factor}-${item.argument}`">
                    {{ item.argument }}
                  </li>
                </ul>
                <span v-else class="analysis-unavailable">暂无明确看空证据</span>
              </div>
              <div class="debate-column">
                <strong>证伪条件</strong>
                <ul v-if="debateData.falsification?.length">
                  <li v-for="item in debateData.falsification" :key="`falsification-${item.condition}`">
                    {{ item.condition }}
                  </li>
                </ul>
                <span v-else class="analysis-unavailable">暂无可展示条件</span>
              </div>
            </div>

            <template v-if="debateEvidence.length">
              <div class="analysis-sub-title">核心证据</div>
              <div class="evidence-grid">
                <div v-for="item in debateEvidence" :key="`${item.factor}-${item.explanation}`" class="evidence-item">
                  <div class="evidence-head">
                    <span>{{ item.label || item.factor }}</span>
                    <el-tag size="small" :type="evidenceTagType(item)" effect="light">
                      {{ formatEvidenceImpact(item.impact) }}
                    </el-tag>
                  </div>
                  <small>{{ item.explanation || '--' }}</small>
                  <div class="evidence-meta">
                    <span>值：{{ evidenceValueText(item.value) }}</span>
                    <span v-if="item.threshold">阈值：{{ item.threshold }}</span>
                    <span v-if="item.source">来源：{{ item.source }}</span>
                  </div>
                </div>
              </div>
            </template>
          </template>
        </div>
      </el-collapse-item>
    </el-collapse>

    <SourceAttributionBanner :sources="dataSources" />
    <Disclaimer />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, defineAsyncComponent, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { DataAnalysis, WarningFilled } from '@element-plus/icons-vue'
import QuotePanel from '@/components/stock/QuotePanel.vue'
import Disclaimer from '@/components/common/Disclaimer.vue'
import SourceAttributionBanner from '@/components/common/SourceAttributionBanner.vue'
import { useStockData, type QuoteData } from '@/composables/useStockData'
import { stockApi } from '@/api'
import { analysisApi } from '@/api/analysis'
import { useUserStore } from '@/stores/user'
import { formatDelta, formatMarketValue, formatPct, formatPrice, formatShares, formatSigned } from '@/utils/formatters'
import { formatConfidenceLabel, formatQualitySource, formatQualityStatus, formatQualityTime, formatQualityWarning, qualityWarnings } from '@/utils/dataQuality'
import type { DataQualityItem } from '@/utils/dataQuality'
import { marketLabels, normalizeStockSymbol, parseStockSymbol, stockCode, type MarketCode } from '@/utils/symbols'

const KLineChart = defineAsyncComponent(() => import('@/components/charts/KLineChart.vue'))
const TimeShareChart = defineAsyncComponent(() => import('@/components/charts/TimeShareChart.vue'))
const MoneyFlowChart = defineAsyncComponent(() => import('@/components/charts/MoneyFlowChart.vue'))
const AIAnalysisCard = defineAsyncComponent(() => import('@/components/ai/AIAnalysisCard.vue'))
const NewsFeed = defineAsyncComponent(() => import('@/components/stock/NewsFeed.vue'))
const AnnouncementTimeline = defineAsyncComponent(() => import('@/components/stock/AnnouncementTimeline.vue'))
const FinancialReportTable = defineAsyncComponent(() => import('@/components/stock/FinancialReportTable.vue'))

interface AIAnalysisCardExpose {
  recoverMissingData: () => Promise<void>
}

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const symbol = ref((route.params.symbol as string) || '600519.SH')
const stockName = ref('')
const loading = ref(false)
const error = ref<string | null>(null)
const quoteError = ref<string | null>(null)
const detailError = ref<string | null>(null)
const chartMode = ref('kline')
const quote = reactive<Partial<QuoteData>>({})
const klineQuality = ref<DataQualityItem | null>(null)
const klineSource = ref('')
const financialQuality = ref<DataQualityItem | null>(null)
const financialSource = ref('')
const newsQuality = ref<DataQualityItem | null>(null)
const newsSource = ref('')
const announcementQuality = ref<DataQualityItem | null>(null)
const announcementSource = ref('')
const refreshKey = ref(0)
const aiAnalysisCardRef = ref<AIAnalysisCardExpose | null>(null)
const dataRecoveryLoading = ref(false)
const observationSummary = ref<string | null>(null)
const observationSummaryDate = ref<string | null>(null)
const stockInfo = reactive({
  name: '',
  sector: '',
  listDate: '',
  latestPrice: 0,
  totalMv: 0,
  circMv: 0,
  totalShares: 0,
  floatShares: 0,
  source: '',
  updatedAt: '',
  dataQuality: null as DataQualityItem | null,
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
  source?: string
  updated_at?: string
  data_quality?: DataQualityItem
}

interface QuotePayload {
  name?: string
  price?: number
  total_mv?: number
  circ_mv?: number
}

const { fetchQuote } = useStockData()

const rawSymbol = computed(() => stockCode(symbol.value))
const dataSources = computed(() => ({
  kline: klineQuality.value?.source || klineSource.value || quote.data_quality?.source || quote.source || '东方财富/AKShare',
  klineFreshness: klineQuality.value?.freshness,
  financial: financialQuality.value?.source || financialSource.value || '暂不可用',
  financialFreshness: financialQuality.value?.freshness || 'unavailable',
  news: newsQuality.value?.source || newsSource.value || '暂不可用',
  newsFreshness: newsQuality.value?.freshness || 'unavailable',
  announcements: announcementQuality.value?.source || announcementSource.value || '暂不可用',
  announcementsFreshness: announcementQuality.value?.freshness || 'unavailable',
}))
const dataAvailabilityMessage = computed(() => {
  if (quoteError.value && detailError.value) return '行情和个股基础信息暂不可用，页面数值可能为空，请稍后重试。'
  if (quoteError.value) return '实时行情暂不可用，价格、涨跌幅和估值数据不可作为当前行情参考。'
  if (detailError.value) return '个股基础信息暂不可用，行业、上市日期等资料可能缺失。'
  return ''
})

const marketCode = ref<MarketCode>('SH')
const marketText = computed(() => marketLabels[marketCode.value])
const marketClass = computed(() => `tag-${marketCode.value.toLowerCase()}`)
const priceClass = computed(() => {
  const value = Number(quote.change_pct)
  if (!Number.isFinite(value)) return ''
  return value > 0 ? 'price-up' : value < 0 ? 'price-down' : ''
})
const profileWarnings = computed(() => qualityWarnings(stockInfo.dataQuality))
const profileQualityText = computed(() => {
  const quality = stockInfo.dataQuality
  if (!quality) return '暂无质量信息'
  const confidence = formatConfidenceLabel(quality.confidence)
  const status = formatQualityStatus(quality.status || (quality.is_fallback ? 'fallback' : 'ok'))
  const source = (quality.source || '').toLowerCase()
  const isPublicSource = ['akshare', 'eastmoney', 'tencent', 'sina-tencent'].some((value) => source.includes(value))
  const fallback = quality.is_fallback ? ` · ${isPublicSource ? '公开源补充' : '降级数据'}` : ''
  return `${status}${confidence ? ` · 置信度 ${confidence}` : ''}${fallback}`
})

function refreshReadiness() {
  refreshKey.value += 1
}

function onKlineQualityChange(quality: DataQualityItem | null, source: string) {
  klineQuality.value = quality
  klineSource.value = source
}

function onFinancialQualityChange(quality: DataQualityItem | null, source: string) {
  financialQuality.value = quality
  financialSource.value = source
}

function onNewsQualityChange(quality: DataQualityItem | null, source: string) {
  newsQuality.value = quality
  newsSource.value = source
}

function onAnnouncementQualityChange(quality: DataQualityItem | null, source: string) {
  announcementQuality.value = quality
  announcementSource.value = source
}

async function recoverMissingDataFromTop() {
  if (!userStore.isLoggedIn) {
    router.push({ path: '/login', query: { redirect: route.fullPath } })
    return
  }
  dataRecoveryLoading.value = true
  refreshReadiness()
  await nextTick()
  document.getElementById('ai-analysis-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  try {
    await aiAnalysisCardRef.value?.recoverMissingData()
  } finally {
    dataRecoveryLoading.value = false
  }
}

function normalizeSymbol(rawValue: string) {
  return normalizeStockSymbol(rawValue)
}

function updateMarketText(value: string) {
  marketCode.value = parseStockSymbol(value).market
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
  stockInfo.source = ''
  stockInfo.updatedAt = ''
  stockInfo.dataQuality = null
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
  stockInfo.source = info?.source || info?.data_quality?.source || ''
  stockInfo.updatedAt = info?.updated_at || info?.data_quality?.updated_at || ''
  stockInfo.dataQuality = info?.data_quality || null
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
  observationSummary.value = null
  observationSummaryDate.value = null
  klineQuality.value = null
  klineSource.value = ''
  financialQuality.value = null
  financialSource.value = ''
  newsQuality.value = null
  newsSource.value = ''
  announcementQuality.value = null
  announcementSource.value = ''
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

  // 非阻塞加载 AI 摘要
  analysisApi.getObservationSummary(nextSymbol)
    .then((res: any) => {
      if (res?.summary_text) {
        observationSummary.value = res.summary_text
        observationSummaryDate.value = res.snapshot_date || null
      }
    })
    .catch(() => {})
}

// ---- Analysis panels state ----
const activeAnalysisSections = ref<string[]>([])

interface TechDimension {
  name: string
  label?: string
  score?: number | null
  weight?: number | null
}

interface TechScoreData {
  total_score?: number | null
  rating?: string
  dimensions?: TechDimension[]
  warnings?: string[]
}

interface TechnicalIndicators {
  ma5?: Array<number | null>
  ma20?: Array<number | null>
  macd?: {
    dif?: Array<number | null>
    dea?: Array<number | null>
    histogram?: Array<number | null>
  }
  boll?: {
    upper?: Array<number | null>
    middle?: Array<number | null>
    lower?: Array<number | null>
  }
  kdj?: {
    k?: Array<number | null>
    d?: Array<number | null>
    j?: Array<number | null>
  }
  rsi?: Array<number | null>
}

interface TechnicalResponse {
  indicators?: TechnicalIndicators
}

interface PatternItem {
  name: string
  signal: string
  confidence?: string
  description?: string
  date?: string
  price?: number | null
}

interface PatternResponse {
  patterns?: PatternItem[]
}

interface FinancialData {
  revenue_yoy?: number | null
  net_profit_yoy?: number | null
  roe?: number | null
  gross_margin?: number | null
  operating_cf?: number | string | null
}

interface FScoreData {
  total_score?: number | null
  summary?: string
}

interface DupontData {
  net_margin?: number | null
  asset_turnover?: number | null
  leverage?: number | null
  roe?: number | null
}

interface ValuationData {
  pe_ttm?: number | null
  pb?: number | null
  ps?: number | null
  ev_ebitda?: number | null
  dcf_value?: number | string | null
  verdict?: string
}

interface DebateRiskItem {
  type?: string
  severity?: string
  detail?: string
}

interface DebateData {
  score?: number | null
  base_score?: number | null
  strategy_score?: number | null
  strategy_score_delta?: number | null
  rating?: {
    level?: string
    text?: string
  }
  active_strategy?: {
    id?: string
    name?: string
    engine_strategy?: string
    selection_mode?: string
  }
  data_grade?: {
    grade?: string
    label?: string
    analysis_scope?: string
  }
  veto_result?: {
    passed?: boolean
    level?: string
    veto_reason?: string | null
    vetoes?: DebateRiskItem[]
    warnings?: DebateRiskItem[]
  }
  evidence_chain?: EvidenceItem[]
  bull_case?: DebateCaseItem[]
  bear_case?: DebateCaseItem[]
  key_disagreement?: Array<{
    topic?: string
    bull_view?: string
    bear_view?: string
  }>
  falsification?: Array<{
    condition?: string
  }>
}

interface DebateCaseItem {
  factor?: string
  argument?: string
  strength?: string
}

interface EvidenceItem {
  factor?: string
  label?: string
  value?: unknown
  threshold?: string
  source?: string
  impact?: number
  explanation?: string
}

// Technical score
const techLoading = ref(false)
const techError = ref(false)
const techData = ref<TechScoreData | null>(null)
const technicalLoading = ref(false)
const technicalError = ref(false)
const technicalData = ref<TechnicalIndicators | null>(null)
const patternLoading = ref(false)
const patternData = ref<PatternItem[]>([])

const PATTERN_NAMES: Record<string, string> = {
  doji: '十字星',
  hammer: '锤子线',
  shooting_star: '射击之星',
  engulfing_bull: '看涨吞没',
  engulfing_bear: '看跌吞没',
  three_white_soldiers: '三白兵',
  three_black_crows: '三只乌鸦',
  morning_star: '早晨之星',
  evening_star: '黄昏之星',
}

// Financial analysis
const financialLoading = ref(false)
const financialError = ref(false)
const fscoreError = ref(false)
const dupointError = ref(false)
const financialData = ref<FinancialData | null>(null)
const fscoreData = ref<FScoreData | null>(null)
const dupontData = ref<DupontData | null>(null)

// Valuation
const valuationLoading = ref(false)
const valuationError = ref(false)
const valuationData = ref<ValuationData | null>(null)
const debateLoading = ref(false)
const debateError = ref(false)
const debateData = ref<DebateData | null>(null)

const debateEvidence = computed(() => {
  const items = debateData.value?.evidence_chain || []
  return items
    .filter((item) => item.factor !== 'base')
    .sort((a, b) => Math.abs(Number(b.impact || 0)) - Math.abs(Number(a.impact || 0)))
    .slice(0, 4)
})

function fmtPctVal(v: unknown): string {
  const n = Number(v)
  if (v == null || !Number.isFinite(n)) return '--'
  return (n * 100).toFixed(2) + '%'
}

function fmtVal(v: unknown): string {
  const n = Number(v)
  if (v == null || !Number.isFinite(n)) return '--'
  return n.toFixed(2)
}

function lastVal(arr: unknown): number | null {
  if (!Array.isArray(arr)) return null
  for (let i = arr.length - 1; i >= 0; i -= 1) {
    const value = arr[i]
    if (value != null && Number.isFinite(Number(value))) return Number(value)
  }
  return null
}

function patternTagType(signal: string): 'success' | 'danger' | 'warning' {
  if (signal.includes('看涨')) return 'success'
  if (signal.includes('看跌')) return 'danger'
  return 'warning'
}

function strategyName(id?: string): string {
  const mapping: Record<string, string> = {
    auto: '自动策略',
    retail_small: '小而美观察',
    value_quality: '价值质量',
    growth_momentum: '成长动量',
    reversal_watch: '反转观察',
    event_driven: '事件驱动',
    dividend_defensive: '红利防御',
    quality: '质量优先',
  }
  return mapping[id || ''] || id || '未选择'
}

function vetoTagType(veto?: DebateData['veto_result']): 'success' | 'warning' | 'danger' | 'info' {
  if (!veto) return 'info'
  if (veto.passed === false || veto.level === 'hard') return 'danger'
  if ((veto.warnings || []).length || veto.level === 'soft') return 'warning'
  return 'success'
}

function vetoLabel(veto?: DebateData['veto_result']): string {
  if (!veto) return '未校验'
  if (veto.passed === false || veto.level === 'hard') return '已否决'
  if ((veto.warnings || []).length || veto.level === 'soft') return '软警告'
  return '已通过'
}

function evidenceTagType(item: EvidenceItem): 'success' | 'warning' | 'info' {
  const impact = Number(item.impact)
  if (impact > 0) return 'success'
  if (impact < 0) return 'warning'
  return 'info'
}

function formatEvidenceImpact(value?: number | null): string {
  const text = formatDelta(value)
  return text || '0'
}

function evidenceValueText(value: unknown): string {
  if (value == null) return 'N/A'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' ? value as Record<string, unknown> : null
}

function unwrapApiPayload<T>(value: unknown): T | null {
  const record = asRecord(value)
  if (record && 'data' in record) return (record.data as T) ?? null
  return (value as T) ?? null
}

function normalizeTechScore(value: unknown): TechScoreData | null {
  const payload = unwrapApiPayload<Record<string, unknown>>(value)
  if (!payload) return null
  const dimensionsPayload = payload.dimensions
  const dimensions = Array.isArray(dimensionsPayload)
    ? dimensionsPayload as TechDimension[]
    : Object.entries(asRecord(dimensionsPayload) || {}).map(([name, rawDimension]) => {
        const dimension = asRecord(rawDimension) || {}
        return {
          name,
          label: typeof dimension.label === 'string' ? dimension.label : undefined,
          score: dimension.score as number | null | undefined,
          weight: dimension.weight as number | null | undefined,
        }
      })
  const ratingPayload = payload.rating
  const ratingRecord = asRecord(ratingPayload)
  return {
    total_score: payload.total_score as number | null | undefined,
    rating: typeof ratingPayload === 'string'
      ? ratingPayload
      : String(ratingRecord?.text || ratingRecord?.level || ''),
    dimensions,
    warnings: Array.isArray(payload.warnings) ? payload.warnings as string[] : [],
  }
}

function normalizeFinancialData(value: unknown): FinancialData | null {
  const payload = unwrapApiPayload<Record<string, unknown>>(value)
  if (!payload) return null
  const summary = asRecord(payload.summary) || payload
  return {
    revenue_yoy: summary.revenue_yoy as number | null | undefined,
    net_profit_yoy: summary.net_profit_yoy as number | null | undefined,
    roe: summary.roe as number | null | undefined,
    gross_margin: summary.gross_margin as number | null | undefined,
    operating_cf: summary.operating_cf as number | string | null | undefined,
  }
}

function normalizeFScore(value: unknown): FScoreData | null {
  const payload = unwrapApiPayload<Record<string, unknown>>(value)
  const fScore = asRecord(payload?.f_score) || payload
  if (!fScore) return null
  return {
    total_score: (fScore.score ?? fScore.total_score) as number | null | undefined,
    summary: String(fScore.explanation || fScore.rating || fScore.summary || ''),
  }
}

function normalizeDupont(value: unknown): DupontData | null {
  const payload = unwrapApiPayload<Record<string, unknown>>(value)
  const dupont = asRecord(payload?.dupont) || payload
  if (!dupont) return null
  return {
    net_margin: dupont.net_margin as number | null | undefined,
    asset_turnover: dupont.asset_turnover as number | null | undefined,
    leverage: (dupont.leverage ?? dupont.equity_multiplier) as number | null | undefined,
    roe: dupont.roe as number | null | undefined,
  }
}

function normalizeValuation(value: unknown): ValuationData | null {
  const payload = unwrapApiPayload<Record<string, unknown>>(value)
  if (!payload) return null
  const zScore = asRecord(payload.z_score)
  return {
    pe_ttm: (payload.pe_ttm ?? payload.current_pe) as number | null | undefined,
    pb: (payload.pb ?? payload.current_pb) as number | null | undefined,
    ps: payload.ps as number | null | undefined,
    ev_ebitda: payload.ev_ebitda as number | null | undefined,
    dcf_value: payload.dcf_value as number | string | null | undefined,
    verdict: String(payload.verdict || zScore?.rating || ''),
  }
}

async function loadAnalysis(sym: string) {
  // Reset state
  techError.value = false
  techData.value = null
  technicalError.value = false
  technicalData.value = null
  patternData.value = []
  financialError.value = false
  fscoreError.value = false
  dupointError.value = false
  financialData.value = null
  fscoreData.value = null
  dupontData.value = null
  valuationError.value = false
  valuationData.value = null
  debateError.value = false
  debateData.value = null

  techLoading.value = true
  technicalLoading.value = true
  patternLoading.value = true
  financialLoading.value = true
  valuationLoading.value = true
  debateLoading.value = true

  const [techResult, technicalResult, patternResult, financialResult, fscoreResult, dupontResult, valuationResult, debateResult] = await Promise.allSettled([
    analysisApi.getScore(sym),
    analysisApi.getTechnical(sym),
    analysisApi.detectPatterns(sym),
    analysisApi.getFinancialAnalysis(sym),
    analysisApi.getFScore(sym),
    analysisApi.getDuPont(sym),
    analysisApi.getValuation(sym),
    analysisApi.getStockDebate<DebateData>(sym),
  ])

  // Technical
  techLoading.value = false
  if (techResult.status === 'fulfilled') {
    techData.value = normalizeTechScore(techResult.value)
  } else {
    techError.value = true
  }

  technicalLoading.value = false
  if (technicalResult.status === 'fulfilled') {
    technicalData.value = ((technicalResult.value as TechnicalResponse)?.indicators) ?? null
  } else {
    technicalError.value = true
  }

  patternLoading.value = false
  if (patternResult.status === 'fulfilled') {
    patternData.value = ((patternResult.value as PatternResponse)?.patterns) ?? []
  } else {
    patternData.value = []
  }

  // Financial
  if (financialResult.status === 'fulfilled') {
    financialData.value = normalizeFinancialData(financialResult.value)
  } else {
    financialError.value = true
  }

  if (fscoreResult.status === 'fulfilled') {
    fscoreData.value = normalizeFScore(fscoreResult.value)
  } else {
    fscoreError.value = true
  }

  if (dupontResult.status === 'fulfilled') {
    dupontData.value = normalizeDupont(dupontResult.value)
  } else {
    dupointError.value = true
  }
  financialLoading.value = false

  // Valuation
  valuationLoading.value = false
  if (valuationResult.status === 'fulfilled') {
    valuationData.value = normalizeValuation(valuationResult.value)
  } else {
    valuationError.value = true
  }

  debateLoading.value = false
  if (debateResult.status === 'fulfilled') {
    debateData.value = (debateResult.value as DebateData) ?? null
  } else {
    debateError.value = true
  }
}

const analysisLoaded = ref(false)

watch(activeAnalysisSections, (sections) => {
  if (sections.length > 0 && !analysisLoaded.value) {
    analysisLoaded.value = true
    loadAnalysis(normalizeSymbol(symbol.value))
  }
})

watch(
  () => route.params.symbol as string,
  (value) => {
    loadStockDetail(value || '600519.SH')
    analysisLoaded.value = false
    if (activeAnalysisSections.value.length > 0) {
      analysisLoaded.value = true
      loadAnalysis(normalizeSymbol(value || '600519.SH'))
    }
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

.tag-bj {
  background: #fff7e6;
  color: #ad6800;
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

.ai-summary-card {
  background: linear-gradient(135deg, #f0f7ff 0%, #e8f4fd 100%);
  border: 1px solid #b3d8f5;
  border-left: 4px solid #409eff;
  border-radius: var(--radius-md);
  padding: var(--space-4) var(--space-5);
  margin-bottom: var(--space-4);
}

.ai-summary-header {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.ai-summary-icon {
  color: #1a73e8;
  font-size: 18px;
}

.ai-summary-title {
  font-weight: 600;
  font-size: 14px;
  color: #1a73e8;
}

.ai-summary-date {
  font-size: 12px;
  color: var(--color-text-muted);
  margin-left: auto;
}

.ai-summary-body {
  margin: 0;
  font-size: 14px;
  line-height: 1.7;
  color: var(--color-text-primary);
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

.profile-quality-warnings {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-3);
}

.analysis-collapse {
  border-radius: var(--radius-md);
  overflow: hidden;
}

.analysis-panel-body {
  min-height: 40px;
  padding: var(--space-3) 0;
}

.analysis-unavailable {
  color: var(--color-text-muted);
  font-size: 13px;
}

.analysis-desc {
  margin-bottom: var(--space-4);
}

.analysis-sub-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--color-text-secondary);
  margin: var(--space-4) 0 var(--space-2);
}

.analysis-sub-title:first-child {
  margin-top: 0;
}

.analysis-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  margin-bottom: var(--space-4);
}

.analysis-table th,
.analysis-table td {
  border: 1px solid var(--color-border);
  padding: 6px 10px;
  text-align: left;
}

.analysis-table th {
  background: var(--color-surface-secondary, #f5f7fa);
  font-weight: 600;
  color: var(--color-text-secondary);
}

.analysis-warnings {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  margin-top: var(--space-2);
}

.analysis-warning-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--color-warning, #b45309);
}

.pattern-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.debate-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.debate-summary > div,
.disagreement-item,
.debate-column,
.evidence-item {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
}

.debate-summary > div {
  display: grid;
  gap: 4px;
  padding: var(--space-3);
}

.debate-summary span,
.debate-summary small,
.evidence-meta {
  color: var(--color-text-muted);
  font-size: 12px;
}

.debate-summary strong {
  color: var(--color-text);
  font-size: 16px;
}

.disagreement-list,
.debate-grid,
.evidence-grid {
  display: grid;
  gap: var(--space-3);
}

.disagreement-item {
  display: grid;
  gap: 6px;
  padding: var(--space-3);
  color: var(--color-text-secondary);
  font-size: 13px;
}

.disagreement-item strong {
  color: var(--color-text);
}

.debate-grid {
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.debate-column,
.evidence-item {
  padding: var(--space-3);
}

.debate-column ul {
  margin: var(--space-2) 0 0;
  padding-left: 18px;
  color: var(--color-text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.debate-column li + li {
  margin-top: 6px;
}

.evidence-grid {
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}

.evidence-head {
  display: flex;
  justify-content: space-between;
  gap: var(--space-2);
  align-items: center;
  margin-bottom: var(--space-2);
}

.evidence-item small {
  color: var(--color-text-secondary);
  line-height: 1.5;
}

.evidence-meta {
  display: grid;
  gap: 4px;
  margin-top: var(--space-2);
}

@media (max-width: 640px) {
  .analysis-table {
    font-size: 12px;
  }

  .analysis-table th,
  .analysis-table td {
    padding: 4px 6px;
  }
}

@media (max-width: 1024px) {
  .two-column {
    grid-template-columns: 1fr;
  }

  .news-grid {
    grid-template-columns: 1fr;
  }
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

  .beginner-guide {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .stock-hero {
    padding: var(--space-4);
  }

  .stock-identity h2 {
    font-size: 24px;
  }

  .hero-price strong {
    font-size: 32px;
  }
}
</style>
