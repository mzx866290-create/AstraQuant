<template>
  <div class="recommendations-page">
    <section class="toolbar">
      <div>
        <h2>每日观察池</h2>
        <p>{{ toolbarDescription }}</p>
      </div>
      <div class="actions">
        <el-segmented v-model="market" :options="marketOptions" @change="loadRecommendations()" />
        <el-button :icon="Refresh" :loading="loading" @click="loadRecommendations()">重新加载</el-button>
      </div>
    </section>

    <section v-if="meta && !showInitialLoading" class="core-summary" :class="trustState.level">
      <div class="core-summary-main">
        <span class="core-eyebrow">{{ dataDateText || pipelineStatusText }}</span>
        <h3>{{ coreSummaryTitle }}</h3>
        <p>{{ coreSummaryMessage }}</p>
      </div>
      <div class="core-stat-grid">
        <span>
          <small>入池</small>
          <strong>{{ items.length }}</strong>
        </span>
        <span>
          <small>A档</small>
          <strong>{{ coreStats.tierA }}</strong>
        </span>
        <span>
          <small>可关注</small>
          <strong>{{ coreStats.actionable }}</strong>
        </span>
        <span>
          <small>等回踩</small>
          <strong>{{ coreStats.waiting }}</strong>
        </span>
      </div>
    </section>

    <el-alert
      class="screening-explainer"
      type="info"
      show-icon
      :closable="false"
      title="流程说明：先全量采集全市场快照，再按趋势、量价和风险规则筛选，最后只展示通过终筛的少数标的。"
      description="不是把全市场每只股票都直接列出来，而是先采集、再初筛、再风险否决，当前页面展示的是最终候选。"
    />

    <el-alert
      v-if="recommendationWarning"
      class="risk-alert"
      type="warning"
      show-icon
      :closable="false"
      :title="recommendationWarning"
    />

    <el-alert
      v-if="loadError"
      class="risk-alert"
      type="error"
      show-icon
      :closable="false"
      :title="loadError"
    />

    <el-alert
      v-if="expansionMessage"
      class="risk-alert"
      :type="expanding ? 'info' : 'warning'"
      show-icon
      :closable="false"
      :title="expansionMessage"
    />

    <el-alert
      v-if="isStaleData"
      class="risk-alert"
      type="warning"
      show-icon
      :closable="false"
      title="服务暂时不可用，显示的是本地缓存数据，可能不是最新结果。"
    />

    <section class="trust-strip" :class="trustState.level">
      <strong>可信状态：{{ trustState.label }}</strong>
      <span>{{ trustState.message }}</span>
      <span v-for="reason in trustState.reasons" :key="reason">{{ reason }}</span>
    </section>

    <section v-if="optimizerStatusItems.length" class="optimizer-strip">
      <span v-for="item in optimizerStatusItems" :key="item.label" class="optimizer-status-item">
        <small>{{ item.label }}</small>
        <strong>{{ item.value }}</strong>
      </span>
    </section>

    <section v-if="intradaySummaryItems.length" class="intraday-strip">
      <div class="intraday-strip-head">
        <strong>盘中确认</strong>
        <span>{{ intradayStatusText }}</span>
      </div>
      <span v-for="item in intradaySummaryItems" :key="item.label" class="intraday-status-item" :class="item.level">
        <small>{{ item.label }}</small>
        <strong>{{ item.value }}</strong>
      </span>
    </section>

    <!-- 盘前摘要 Banner -->
    <section v-if="poolSummary?.pool_style" class="pool-summary-banner">
      <div class="pool-summary-header">
        <span class="pool-style">{{ poolSummary.pool_style }}</span>
        <div class="tier-badges">
          <el-tag size="small" type="success">A档 {{ poolSummary.tier_counts?.A ?? 0 }}只</el-tag>
          <el-tag size="small" type="primary">B档 {{ poolSummary.tier_counts?.B ?? 0 }}只</el-tag>
          <el-tag size="small" type="info">C档 {{ poolSummary.tier_counts?.C ?? 0 }}只</el-tag>
        </div>
      </div>
      <div class="pool-summary-body">
        <div class="summary-row">
          <span class="summary-label">策略建议</span>
          <span>{{ poolSummary.recommended_strategy }}</span>
        </div>
        <div class="summary-row risk-row">
          <span class="summary-label">风险提示</span>
          <span>{{ poolSummary.biggest_risk }}</span>
        </div>
      </div>
    </section>

    <!-- 分层 Tab 筛选 -->
    <div v-if="items.length > 0" class="tier-filter">
      <el-radio-group v-model="selectedTier" size="small" @change="onTierChange">
        <el-radio-button value="">全部 ({{ items.length }})</el-radio-button>
        <el-radio-button value="A">
          A档 优先 ({{ tierCount('A') }})
        </el-radio-button>
        <el-radio-button value="B">
          B档 条件 ({{ tierCount('B') }})
        </el-radio-button>
        <el-radio-button value="C">
          C档 低优先 ({{ tierCount('C') }})
        </el-radio-button>
      </el-radio-group>
    </div>

    <div v-if="items.length > 0" class="readiness-filter">
      <button
        v-for="option in readinessOptions"
        :key="option.value || 'all'"
        type="button"
        class="readiness-option"
        :class="{ active: selectedReadiness === option.value }"
        :aria-pressed="selectedReadiness === option.value"
        @click="selectedReadiness = option.value"
      >
        <span>{{ option.label }}</span>
        <strong>{{ option.count }}</strong>
      </button>
    </div>

    <section v-if="!showInitialLoading && filteredItems.length > 0" class="bucket-overview">
      <div class="bucket-overview-head">
        <strong>已按观察池拆分</strong>
        <span>上面是筛选，下面按回调承接、趋势强势、超跌反弹三组分别展示。</span>
      </div>
      <div class="bucket-overview-grid">
        <button
          v-for="section in bucketSections"
          :key="section.key"
          type="button"
          class="bucket-overview-item"
          :class="[
            `bucket-overview-${section.key}`,
            { selected: selectedBucket === section.key, empty: section.count === 0 },
          ]"
          :aria-pressed="selectedBucket === section.key"
          @click="setBucketFilter(section.key)"
        >
          <span class="bucket-overview-copy">
            <strong>{{ section.label }}</strong>
            <small>{{ section.description }}</small>
          </span>
          <span class="bucket-overview-count">{{ section.count }} 只</span>
        </button>
      </div>
    </section>

    <section
      v-if="showInitialLoading"
      class="loading-panel"
      data-testid="recommendations-loading"
      aria-live="polite"
      aria-busy="true"
    >
      <div class="loading-orbit" aria-hidden="true">
        <span></span>
        <span></span>
      </div>
      <div class="loading-copy">
        <strong>正在加载每日观察池</strong>
        <span>首次会先展示一批观察股，通常需要 10-30 秒；随后后台扩展到 50 只，可能还需要 1-3 分钟，请不要重复刷新页面。</span>
      </div>
      <div class="loading-bars" aria-hidden="true">
        <i v-for="bar in loadingBars" :key="bar" :style="{ width: `${bar}%` }"></i>
      </div>
    </section>

    <section v-if="!showInitialLoading && items.length === 0 && !loading" class="empty-state">
      <strong>暂无每日观察池数据</strong>
      <span>{{ emptyReason }}</span>
    </section>

    <section v-if="!showInitialLoading && filteredItems.length === 0 && items.length > 0" class="empty-state">
      <strong>当前筛选暂无标的</strong>
      <span>{{ emptyFilterText }}</span>
    </section>

    <div v-if="!showInitialLoading && filteredItems.length > 0" ref="bucketStackRef" v-loading="loading" class="bucket-stack">
      <div class="bucket-active-filter">
        <span>{{ selectedBucketLabel }}</span>
        <strong>{{ displayItems.length }} 只</strong>
        <el-button v-if="selectedBucket" size="small" link type="primary" @click="clearBucketFilter">查看全部分类</el-button>
      </div>
      <section
        v-for="section in visibleBucketSections"
        :key="section.key"
        class="bucket-section"
        :class="{ active: selectedBucket === section.key }"
      >
        <div class="bucket-section-header">
          <div class="bucket-section-title">
            <strong>{{ section.label }}</strong>
            <span>{{ section.description }}</span>
          </div>
          <el-tag size="small" :type="bucketTagType(section.key)" effect="light">
            {{ section.count }} 只
          </el-tag>
        </div>
        <div v-if="section.items.length > 0" class="card-grid">
          <ObservationCard
            v-for="row in section.items"
            :key="row.symbol"
            :row="row"
            :display-index="getDisplayIndex(row)"
            :bucket-label="section.label"
            :meta="meta"
            :adding-symbol="addingSymbol"
            @view-detail="goDetail"
            @add-watchlist="handleAddToWatchlist"
          />
        </div>
        <div v-else class="bucket-empty">
          <el-empty description="今日未筛出该池标的" />
        </div>
      </section>
    </div>

    <details class="meta-panel" v-if="meta">
      <summary>数据与规则</summary>
      <div class="meta">
        <span>筛选结果 {{ meta.count ?? items.length }} 只</span>
        <span>当前展示 {{ displayItems.length }} 只</span>
        <span>状态 {{ pipelineStatusText }}</span>
        <span v-if="dataDateText">{{ dataDateText }}</span>
        <span v-if="targetDateText">{{ targetDateText }}</span>
        <span v-if="meta.news_enriched_count !== undefined">资讯增强 {{ meta.news_enriched_count }} 只</span>
        <span v-if="candidatePoolText">{{ candidatePoolText }}</span>
        <span v-if="meta.cache_hit !== undefined">{{ meta.cache_hit ? '缓存命中' : '重新计算' }}</span>
        <span>{{ meta.updated_at }}</span>
        <span>流程：全市场快照 -> 趋势/量价初筛 -> 风险否决 -> 观察池</span>
      </div>
    </details>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { analysisApi } from '@/api'
import { useWatchlistActions } from '@/composables/useWatchlistActions'
import ObservationCard from '@/components/recommendations/ObservationCard.vue'
import {
  recommendationEmptyReason,
  recommendationTrustState,
  type IntradayConfirmationResponse,
  type RecentReviewsResponse,
  type RecommendationItem,
  type RecommendationsResponse,
} from '@/utils/recommendations'

const router = useRouter()
const FULL_LIMIT = 50

const loading = ref(false)
const expanding = ref(false)
const market = ref('ALL')
const items = ref<RecommendationItem[]>([])
const meta = ref<RecommendationsResponse | null>(null)
const intradayMeta = ref<IntradayConfirmationResponse | null>(null)
const loadError = ref('')
const expansionMessage = ref('')
const selectedTier = ref('')
const selectedBucket = ref('')
const selectedReadiness = ref('')
const bucketStackRef = ref<HTMLElement | null>(null)
const { addingSymbol, addToWatchlist } = useWatchlistActions()
const loadingBars = [92, 74, 86, 58]
let requestSeq = 0

const poolSummary = computed(() => meta.value?.pool_summary)
const isStaleData = computed(() => (meta.value as any)?.source === 'local_cache' || (meta.value as any)?.stale === true)
const optimizerSummary = computed(() => poolSummary.value?.optimizer)

const coreStats = computed(() => {
  const counts = intradayMeta.value?.summary?.counts || {}
  return {
    tierA: items.value.filter((item) => item.tier === 'A').length,
    actionable: Number(counts.actionable ?? readinessCount('actionable')),
    waiting: Number(counts.wait_pullback ?? readinessCount('wait_pullback')),
    invalidated: Number(counts.invalidated ?? readinessCount('invalidated')),
  }
})

const coreSummaryTitle = computed(() => {
  if (trustState.value.level === 'blocked') return '今天不适合直接使用观察池'
  if (!items.value.length) return '今天还没有可用观察标的'
  if (coreStats.value.actionable > 0) return `今天先看 ${coreStats.value.actionable} 只可关注标的`
  if (coreStats.value.waiting > 0) return `今天先等 ${coreStats.value.waiting} 只标的回踩确认`
  return `今天有 ${items.value.length} 只观察线索`
})

const coreSummaryMessage = computed(() => {
  if (poolSummary.value?.recommended_strategy || poolSummary.value?.biggest_risk) {
    return [poolSummary.value.recommended_strategy, poolSummary.value.biggest_risk].filter(Boolean).join('；')
  }
  if (trustState.value.level === 'blocked') return trustState.value.message
  if (coreStats.value.invalidated > 0) {
    return `${coreStats.value.invalidated} 只盘中已触发失效或报价异常，优先看仍处于可关注/等回踩状态的标的。`
  }
  return '把它当作研究和盯盘清单：先看触发条件，再看失效条件，最后决定是否加入观察。'
})

const intradaySummaryItems = computed(() => {
  const counts = intradayMeta.value?.summary?.counts
  if (!counts) return []
  return [
    { label: '可关注', value: `${counts.actionable || 0} 只`, level: 'good' },
    { label: '等回踩', value: `${counts.wait_pullback || 0} 只`, level: 'wait' },
    { label: '仅观察', value: `${counts.watch_only || 0} 只`, level: 'watch' },
    { label: '已失效', value: `${counts.invalidated || 0} 只`, level: 'bad' },
  ]
})

const intradayStatusText = computed(() => {
  if (!intradayMeta.value) return '等待盘中确认'
  const window = intradayMeta.value.window || '--'
  return `${window} 复核：${intradayMeta.value.summary?.message || '已完成'}`
})

const optimizerStatusItems = computed(() => {
  const optimizer = optimizerSummary.value
  if (!optimizer || optimizer.status === 'not_applied') return []
  const news = optimizer.news_quality || {}
  const diversification = optimizer.diversification || {}
  return [
    { label: '市场模式', value: regimePlainLabel(optimizer.regime) },
    { label: '二次校准', value: `${optimizer.adjusted ?? 0}/${optimizer.processed ?? items.value.length} 只` },
    { label: '资讯时效', value: `${news.fresh ?? 0} 新 / ${news.stale ?? 0} 旧` },
    { label: '分散度', value: `${diversification.penalties_applied ?? 0} 只降权` },
  ].filter((item) => item.value)
})

const filteredItems = computed(() => {
  let rows = items.value
  if (selectedTier.value) {
    rows = rows.filter(r => r.tier === selectedTier.value)
  }
  if (selectedReadiness.value) {
    rows = rows.filter((row) => readinessKey(row) === selectedReadiness.value)
  }
  return rows
})

const readinessOptions = computed(() => [
  { label: '全部状态', value: '', count: items.value.length },
  { label: '可关注', value: 'actionable', count: readinessCount('actionable') },
  { label: '等回踩', value: 'wait_pullback', count: readinessCount('wait_pullback') },
  { label: '仅观察', value: 'watch_only', count: readinessCount('watch_only') },
  { label: '已失效', value: 'invalidated', count: readinessCount('invalidated') },
])

const emptyFilterText = computed(() => {
  if (selectedTier.value || selectedReadiness.value) return '当前筛选组合没有标的，可以切回全部档位或全部状态。'
  return '可以切回全部档位，或查看另外两个观察池分类。'
})

const bucketOrder = ['pullback_support', 'trend_strength', 'oversold_reversal'] as const

const bucketMetaMap: Record<string, { label: string; description: string }> = {
  pullback_support: {
    label: '回调承接池',
    description: '趋势未坏，回踩后等确认，偏稳健。',
  },
  trend_strength: {
    label: '趋势强势池',
    description: '强势延续型候选，适合盯住放量和强势封板。',
  },
  oversold_reversal: {
    label: '超跌反弹池',
    description: '超跌修复型候选，波动更大，先看反弹确认。',
  },
}

const bucketSections = computed(() => bucketOrder.map((key) => {
  const itemsInBucket = filteredItems.value.filter((row) => (row.observation_bucket || 'trend_strength') === key)
  const meta = bucketMetaMap[key]
  return {
    key,
    label: meta.label,
    description: meta.description,
    count: itemsInBucket.length,
    items: itemsInBucket,
  }
}))

const visibleBucketSections = computed(() => {
  if (!selectedBucket.value) return bucketSections.value
  return bucketSections.value.filter((section) => section.key === selectedBucket.value)
})

const displayItems = computed(() => visibleBucketSections.value.flatMap((section) => section.items))

const selectedBucketLabel = computed(() => {
  if (!selectedBucket.value) return '全部观察池分类'
  const section = bucketSections.value.find((item) => item.key === selectedBucket.value)
  return section ? `当前查看：${section.label}` : '当前分类'
})

function tierCount(tier: string): number {
  return items.value.filter(r => r.tier === tier).length
}

function readinessCount(value: string) {
  return items.value.filter((row) => readinessKey(row) === value).length
}

function readinessKey(row: RecommendationItem) {
  const status = row.intraday_confirmation?.status
  if (status === 'actionable') return 'actionable'
  if (status === 'wait_pullback') return 'wait_pullback'
  if (status === 'invalidated' || status === 'quote_error') return 'invalidated'
  if (status === 'watch_only' || status === 'quote_degraded') return 'watch_only'
  if (row.observation_action === '只看不追') return 'watch_only'
  if (row.observation_action === '回踩承接' || row.observation_action === '缩量企稳') return 'wait_pullback'
  return row.tier === 'A' ? 'actionable' : 'watch_only'
}

async function setBucketFilter(bucket: string) {
  selectedBucket.value = selectedBucket.value === bucket ? '' : bucket
  await nextTick()
  bucketStackRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function clearBucketFilter() {
  selectedBucket.value = ''
}

function bucketTagType(bucket: string): 'success' | 'primary' | 'warning' | 'info' | 'danger' | undefined {
  if (bucket === 'trend_strength') return 'success'
  if (bucket === 'pullback_support') return 'primary'
  if (bucket === 'oversold_reversal') return 'warning'
  return 'info'
}

function getDisplayIndex(row: RecommendationItem): number {
  return filteredItems.value.indexOf(row)
}

function onTierChange() {
  // 筛选无需重新加载
}

function regimePlainLabel(regime?: string) {
  if (regime === 'strong_trend') return '强趋势'
  if (regime === 'weak_market') return '弱市'
  if (regime === 'range_bound') return '震荡'
  return regime || '未知'
}

const marketOptions = [
  { label: '沪深', value: 'ALL' },
  { label: '沪市', value: 'SH' },
  { label: '深市', value: 'SZ' },
]

const toolbarDescription = computed(() => {
  return '基于收盘行情、资金流和风险规则生成，每日 15:45 盘后更新，用于下一交易日观察。'
})

const recommendationWarning = computed(() => {
  if (!meta.value) return ''
  if (meta.value.status === 'unavailable') return '每日观察池不可用：数据库候选池为空，系统没有生成候选结果。'
  const warnings = meta.value.warnings || []
  if (meta.value.candidate_source === 'fallback') {
    return '当前观察池使用开发兜底候选池，仅用于调试展示，不代表真实市场筛选结果。'
  }
  if (meta.value.candidate_source === 'mixed') {
    return '数据库候选池偏小，已用开发兜底候选补足；每只标的会单独标明来源。'
  }
  return warnings[0] || ''
})

const trustState = computed(() => recommendationTrustState(meta.value))
const emptyReason = computed(() => loadError.value || recommendationEmptyReason(meta.value))
const showInitialLoading = computed(() => loading.value && !meta.value && items.value.length === 0)
const pipelineStatusText = computed(() => {
  if (meta.value?.pool_phase_label) return meta.value.pool_phase_label
  if (meta.value?.pipeline_status === 'stale') return '展示最近一次结果'
  if (meta.value?.pipeline_status === 'empty') return '暂无结果'
  return '已完成终筛'
})
const dataDateText = computed(() => {
  const date = meta.value?.data_date || items.value.find((item) => item.snapshot_date)?.snapshot_date
  if (!date) return ''
  return `基于 ${date} 收盘数据`
})
const targetDateText = computed(() => {
  const date = meta.value?.target_date
  if (!date) return ''
  return `用于 ${date} 观察`
})
const candidatePoolText = computed(() => {
  const universe = meta.value?.candidate_universe_count || meta.value?.selection?.universe_count
  const evaluated = meta.value?.selection?.evaluated_count || meta.value?.candidate_count
  const scored = meta.value?.scored_count
  if (!universe && !evaluated && !scored) return ''
  return `候选统计：股票池 ${universe || '-'} 只 / 评估 ${evaluated || '-'} 只 / 有效评分 ${scored || '-'} 只`
})

function readableApiError(error: unknown) {
  const detail = (error as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (typeof item === 'object' && item && 'msg' in item ? String(item.msg) : ''))
      .filter(Boolean)
      .join('；')
  }
  if (typeof detail === 'string') return detail
  return '每日观察池加载失败，请稍后重试或检查分析服务状态。'
}

async function loadRecommendations() {
  const requestId = ++requestSeq
  loading.value = true
  expanding.value = false
  loadError.value = ''
  expansionMessage.value = ''
  try {
    const currentMarket = market.value
    const res = await analysisApi.getRecommendations(
      currentMarket,
      FULL_LIMIT,
      false,
    )
    if (requestId !== requestSeq || currentMarket !== market.value) return
    items.value = res.recommendations || []
    meta.value = res
    void loadIntradayConfirmation(requestId, currentMarket)
    if (res.pool_phase_message) {
      expansionMessage.value = res.pool_phase_message
    } else if (res.pipeline_status === 'stale') {
      const date = res.data_date || items.value.find((item) => item.snapshot_date)?.snapshot_date
      const targetDate = res.target_date
      expansionMessage.value = date
        ? `当前沿用基于 ${date} 收盘数据生成的观察池${targetDate ? `，原用于 ${targetDate} 观察` : ''}；等待今日盘后更新。`
        : '当前展示的是最近一次观察池结果（非今日），今日数据尚未生成。'
    } else if (res.pipeline_status === 'empty') {
      expansionMessage.value = '今日筛选完成，暂无符合条件的观察标的。'
    }
    void loadRecentReviews(requestId)
  } catch (error) {
    if (requestId !== requestSeq) return
    loadError.value = readableApiError(error)
    ElMessage.error(loadError.value)
    items.value = []
    meta.value = null
    intradayMeta.value = null
  } finally {
    loading.value = false
  }
}

async function loadIntradayConfirmation(requestId = requestSeq, currentMarket = market.value) {
  if (!items.value.length) return
  try {
    const response = await analysisApi.getIntradayConfirmation(currentMarket, Math.min(FULL_LIMIT, 20))
    if (requestId !== requestSeq || currentMarket !== market.value) return
    intradayMeta.value = response
    const confirmations = new Map((response.items || []).map((item) => [item.symbol, item]))
    items.value = items.value.map((item) => ({
      ...item,
      intraday_confirmation: confirmations.get(item.symbol) || item.intraday_confirmation,
    }))
  } catch (error) {
    if (requestId !== requestSeq) return
    console.warn('盘中确认加载失败:', error)
  }
}

async function loadRecentReviews(requestId = requestSeq) {
  const symbols = items.value.map((item) => item.symbol).filter(Boolean)
  if (!symbols.length) return
  try {
    const response = await analysisApi.getRecentReviews<RecentReviewsResponse>(symbols)
    if (requestId !== requestSeq) return
    const reviewItems = response.items || {}
    items.value = items.value.map((item) => ({
      ...item,
      review_summary: reviewItems[item.symbol],
      review_unavailable: response.status !== 'ok' || !reviewItems[item.symbol],
    }))
  } catch (error) {
    if (requestId !== requestSeq) return
    items.value = items.value.map((item) => ({ ...item, review_unavailable: true }))
    console.warn('复盘摘要加载失败:', error)
  }
}

function goDetail(row: RecommendationItem) {
  router.push(`/stocks/${row.symbol}`)
}

function handleAddToWatchlist(row: RecommendationItem) {
  addToWatchlist(row)
}

onMounted(() => loadRecommendations())
</script>

<style scoped>
.recommendations-page {
  max-width: 1180px;
  margin: 0 auto;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  margin-bottom: 12px;
}

.toolbar h2 {
  margin: 0 0 4px;
  font-size: 22px;
}

.toolbar p {
  margin: 0;
  color: #606266;
}

.actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.screening-explainer {
  margin-bottom: 12px;
}

.risk-alert {
  margin-bottom: 12px;
}

.core-summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(360px, 0.65fr);
  gap: 14px;
  margin-bottom: 12px;
  padding: 16px;
  border: 1px solid #dcdfe6;
  border-radius: 10px;
  background: #fff;
  box-shadow: var(--shadow-card);
}

.core-summary.stable {
  border-color: #b7eb8f;
  background: linear-gradient(135deg, #ffffff 0%, #f2fbf6 100%);
}

.core-summary.warning {
  border-color: #faad14;
  background: linear-gradient(135deg, #ffffff 0%, #fffbe6 100%);
}

.core-summary.blocked {
  border-color: #ff4d4f;
  background: linear-gradient(135deg, #ffffff 0%, #fff2f0 100%);
}

.core-summary-main {
  min-width: 0;
}

.core-eyebrow {
  display: inline-flex;
  margin-bottom: 6px;
  color: #606266;
  font-size: 12px;
  font-weight: 700;
}

.core-summary h3 {
  margin: 0 0 6px;
  color: #303133;
  font-size: 20px;
  line-height: 1.25;
}

.core-summary p {
  margin: 0;
  color: #606266;
  font-size: 13px;
  line-height: 1.6;
}

.core-stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.core-stat-grid span {
  min-width: 0;
  padding: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.78);
}

.core-stat-grid small {
  display: block;
  color: #606266;
  font-size: 12px;
}

.core-stat-grid strong {
  display: block;
  margin-top: 4px;
  color: #303133;
  font-size: 22px;
  line-height: 1;
}

.trust-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  color: #606266;
  background: #fff;
  font-size: 13px;
  transition: all 0.3s;
}

.trust-strip strong {
  color: #303133;
}

.trust-strip.stable {
  border-color: #b7eb8f;
  background: #f2fbf6;
}

.trust-strip.warning {
  border-color: #faad14;
  background: #fffbe6;
  padding: 14px 16px;
  font-size: 14px;
  border-width: 2px;
  animation: trust-pulse 2s ease-in-out 3;
}

.trust-strip.warning strong {
  color: #d48806;
}

.trust-strip.blocked {
  border-color: #ff4d4f;
  background: #fff2f0;
  padding: 14px 16px;
  font-size: 14px;
  font-weight: 500;
  border-width: 2px;
  animation: trust-pulse 2s ease-in-out 3;
}

.trust-strip.blocked strong {
  color: #cf1322;
}

@keyframes trust-pulse {
  0%, 100% { box-shadow: none; }
  50% { box-shadow: 0 0 12px rgba(255, 77, 79, 0.25); }
}

.optimizer-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.optimizer-status-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 42px;
  padding: 9px 10px;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  background: #fff;
}

.optimizer-status-item small {
  color: #606266;
  font-size: 12px;
}

.optimizer-status-item strong {
  color: #303133;
  font-size: 13px;
  text-align: right;
}

.intraday-strip {
  display: grid;
  grid-template-columns: 1.6fr repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.intraday-strip-head,
.intraday-status-item {
  min-height: 44px;
  padding: 9px 10px;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  background: #fff;
}

.intraday-strip-head {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.intraday-strip-head strong {
  color: #303133;
  font-size: 13px;
}

.intraday-strip-head span {
  color: #606266;
  font-size: 12px;
  line-height: 1.35;
}

.intraday-status-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.intraday-status-item small {
  color: #606266;
  font-size: 12px;
}

.intraday-status-item strong {
  font-size: 13px;
}

.intraday-status-item.good {
  border-color: #b7eb8f;
  background: #f2fbf6;
}

.intraday-status-item.wait {
  border-color: #f2d48b;
  background: #fff8e6;
}

.intraday-status-item.bad {
  border-color: #ffa39e;
  background: #fff1f0;
}

.bucket-overview {
  display: grid;
  gap: 10px;
  margin-bottom: 12px;
  padding: 12px;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  background: #fff;
}

.bucket-overview-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
}

.bucket-overview-head strong {
  color: #303133;
  font-size: 14px;
}

.bucket-overview-head span {
  color: #606266;
  font-size: 13px;
}

.bucket-overview-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.bucket-overview-item {
  appearance: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 42px;
  gap: 8px;
  padding: 9px 10px;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  background: #f8fafc;
  color: #303133;
  cursor: pointer;
  transition: border-color 0.2s, background-color 0.2s, box-shadow 0.2s, opacity 0.2s;
  font: inherit;
  text-align: left;
}

.bucket-overview-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.bucket-overview-copy strong {
  font-size: 13px;
  white-space: nowrap;
}

.bucket-overview-copy small {
  color: #606266;
  font-size: 12px;
  line-height: 1.35;
}

.bucket-overview-count {
  flex-shrink: 0;
  font-size: 16px;
  font-weight: 700;
}

.bucket-overview-item:hover,
.bucket-overview-item:focus-visible {
  border-color: var(--el-color-primary);
  box-shadow: 0 2px 10px rgba(64, 158, 255, 0.12);
  outline: none;
}

.bucket-overview-item.selected {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 1px rgba(64, 158, 255, 0.2) inset;
}

.bucket-overview-item.empty {
  opacity: 0.72;
}

.bucket-overview-pullback_support {
  border-color: #b9dcff;
  background: #f0f7ff;
}

.bucket-overview-trend_strength {
  border-color: #b7eb8f;
  background: #f2fbf6;
}

.bucket-overview-oversold_reversal {
  border-color: #f2d48b;
  background: #fff8e6;
}

.loading-panel {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 16px;
  align-items: center;
  min-height: 220px;
  margin-bottom: 12px;
  padding: 24px;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  background: #fff;
  box-shadow: var(--shadow-card);
}

.loading-orbit {
  position: relative;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: #f5f7fa;
}

.loading-orbit::before {
  content: '';
  position: absolute;
  inset: 6px;
  border: 3px solid #dbeafe;
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: loading-spin 0.9s linear infinite;
}

.loading-orbit span {
  position: absolute;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-down);
}

.loading-orbit span:first-child {
  top: 8px;
  right: 10px;
}

.loading-orbit span:last-child {
  left: 10px;
  bottom: 8px;
  background: var(--color-up);
}

.loading-copy {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.loading-copy strong {
  color: var(--color-text);
  font-size: 16px;
}

.loading-copy span,
.loading-copy small {
  color: var(--color-text-secondary);
  font-size: 13px;
}

.loading-copy small {
  color: var(--color-warning);
  line-height: 1.6;
}

.loading-bars {
  grid-column: 1 / -1;
  display: grid;
  gap: 10px;
  margin-top: 4px;
}

.loading-bars i {
  display: block;
  height: 12px;
  border-radius: 999px;
  background: linear-gradient(90deg, #edf2f7 25%, #dbeafe 50%, #edf2f7 75%);
  background-size: 200% 100%;
  animation: loading-shimmer 1.2s ease-in-out infinite;
}

@keyframes loading-spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes loading-shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

.bucket-stack {
  display: grid;
  gap: 18px;
  margin-bottom: 12px;
  scroll-margin-top: 78px;
}

.bucket-active-filter {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  padding: 10px 12px;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  background: #fff;
  color: #606266;
  font-size: 13px;
}

.bucket-active-filter span {
  color: #303133;
  font-weight: 600;
}

.bucket-active-filter strong {
  color: var(--el-color-primary);
}

.bucket-section {
  display: grid;
  gap: 10px;
}

.bucket-section.active .bucket-section-header {
  border-color: var(--el-color-primary);
  background: #f0f7ff;
}

.bucket-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  background: #fff;
}

.bucket-section-title {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.bucket-section-title strong {
  color: #303133;
  font-size: 15px;
}

.bucket-section-title span {
  color: #606266;
  font-size: 12px;
  line-height: 1.45;
}

.bucket-empty {
  border: 1px dashed #dcdfe6;
  border-radius: 8px;
  background: #fff;
}

.bucket-empty :deep(.el-empty) {
  padding: 22px 0;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 14px;
  margin-bottom: 12px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 40px 0;
  color: #909399;
}

.meta-panel {
  margin-top: 12px;
  color: #606266;
  font-size: 13px;
}

.meta-panel summary {
  display: inline-flex;
  cursor: pointer;
  color: #606266;
  font-weight: 700;
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 8px;
  color: #909399;
  font-size: 13px;
}

@media (max-width: 760px) {
  .core-summary {
    grid-template-columns: 1fr;
  }

  .core-stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .actions {
    justify-content: space-between;
    flex-wrap: wrap;
  }

  .actions .el-segmented {
    flex: 1 1 100%;
  }

  .actions .el-button {
    flex: 1 1 120px;
  }

  .optimizer-strip,
  .intraday-strip,
  .bucket-overview-grid {
    grid-template-columns: 1fr;
  }

  .card-grid {
    grid-template-columns: 1fr;
  }
}

/* 盘前摘要 Banner */
.pool-summary-banner {
  margin: 0 0 16px;
  padding: 12px 16px;
  background: linear-gradient(135deg, #f0f9ff 0%, #e0f2fe 100%);
  border: 1px solid #bae6fd;
  border-radius: 10px;
}

.pool-summary-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.pool-style {
  font-size: 14px;
  font-weight: 600;
  color: #0369a1;
}

.tier-badges {
  display: flex;
  gap: 6px;
}

.pool-summary-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.summary-row {
  display: flex;
  gap: 8px;
  font-size: 13px;
}

.summary-row .summary-label {
  font-weight: 600;
  color: #64748b;
  white-space: nowrap;
  min-width: 56px;
}

.summary-row.risk-row {
  color: #b45309;
}

/* 分层 Tab 筛选 */
.tier-filter {
  margin: 0 0 16px;
}

.readiness-filter {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: -6px 0 14px;
}

.readiness-option {
  appearance: none;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 34px;
  padding: 6px 10px;
  border: 1px solid #dcdfe6;
  border-radius: 999px;
  background: #fff;
  color: #606266;
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  transition: border-color 0.2s, color 0.2s, background 0.2s;
}

.readiness-option strong {
  color: #303133;
  font-family: var(--font-number);
  font-size: 13px;
}

.readiness-option:hover,
.readiness-option:focus-visible,
.readiness-option.active {
  border-color: var(--el-color-primary);
  background: #f0f7ff;
  color: var(--el-color-primary);
  outline: none;
}

.readiness-option.active strong {
  color: var(--el-color-primary);
}

</style>
