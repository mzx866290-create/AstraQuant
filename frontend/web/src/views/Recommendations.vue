<template>
  <div class="recommendations-page">
    <section class="toolbar">
      <div>
        <h2>每日观察池</h2>
        <p>{{ toolbarDescription }}</p>
      </div>
      <div class="actions">
        <el-segmented v-model="market" :options="marketOptions" @change="loadRecommendations()" />
        <el-button :icon="Refresh" :loading="loading" @click="loadRecommendations()">刷新</el-button>
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

    <section class="trust-strip" :class="trustState.level">
      <strong>可信状态：{{ trustState.label }}</strong>
      <span>{{ trustState.message }}</span>
      <span v-for="reason in trustState.reasons" :key="reason">{{ reason }}</span>
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
      <span>可以切回全部档位，或查看另外两个观察池分类。</span>
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
          <article
            v-for="row in section.items"
            :key="row.symbol"
            class="stock-card"
            :class="{ 'tier-a': row.tier === 'A', 'tier-b': row.tier === 'B', 'tier-c': row.tier === 'C' }"
            role="button"
            tabindex="0"
            @click="goDetail(row)"
            @keyup.enter="goDetail(row)"
            @keyup.space.prevent="goDetail(row)"
          >
            <div class="card-header">
              <div class="card-rank">#{{ getDisplayIndex(row) + 1 }}</div>
              <div class="card-stock-info">
                <strong>{{ row.name }}</strong>
                <span class="card-symbol">{{ row.symbol }}</span>
                <small v-if="rowDataDate(row)" class="card-data-date">{{ rowDataDate(row) }}</small>
              </div>
              <div class="card-score">
                <el-tag v-if="row.tier" size="small" :type="tierTagType(row.tier)" class="tier-tag">
                  {{ row.tier }}档
                </el-tag>
                <span class="score-number">{{ row.score }}</span>
                <el-tag size="small" :type="recommendationRatingTag(row)">
                  {{ row.rating?.text || scoreReferenceText(row.score) }}
                </el-tag>
              </div>
            </div>

            <div class="card-price-row">
              <span class="card-price">{{ formatPrice(row.price) }}</span>
              <span class="card-change" :class="changeClass(row.change_pct)">{{ formatPct(row.change_pct) }}</span>
              <el-tag v-if="row.observation_action" size="small" :type="actionTagType(row.observation_action)" effect="light" class="action-tag">
                {{ row.observation_action }}
              </el-tag>
              <el-tag v-else size="small" :type="riskHintTagType(recommendationRiskHint(row))" effect="light">
                {{ recommendationRiskHint(row).label }}
              </el-tag>
              <el-tag size="small" effect="plain" class="bucket-tag">
                {{ row.observation_bucket_label || section.label }}
              </el-tag>
              <span v-if="row.sector" class="card-sector">{{ row.sector }}</span>
            </div>

            <div class="retail-summary">
              <div v-if="row.summary_text" class="summary-line ai-summary-line">
                <span class="summary-label ai-label">AI解读</span>
                <span>{{ row.summary_text }}</span>
              </div>
              <template v-else>
                <div class="summary-line reason-line">
                  <span class="summary-label">入选理由</span>
                  <span>{{ recommendationPlainReason(row) }}</span>
                </div>
              </template>
              <div v-if="row.trigger_condition" class="summary-line trigger-line">
                <span class="summary-label trigger-label">触发</span>
                <span>{{ row.trigger_condition }}</span>
              </div>
              <div v-if="row.invalidation_condition" class="summary-line invalidation-line">
                <span class="summary-label">失效</span>
                <span>{{ row.invalidation_condition }}</span>
              </div>
              <div v-if="row.risk_warning" class="summary-line risk-warning-line">
                <span class="summary-label risk-label">风险</span>
                <span>{{ row.risk_warning }}</span>
              </div>
              <template v-if="!row.trigger_condition">
                <div class="summary-line risk-line" :class="recommendationRiskHint(row).level">
                  <span class="summary-label">风险提示</span>
                  <span>{{ recommendationRiskHint(row).message }}</span>
                </div>
              </template>
              <div v-if="firstFalsification(row) && !row.invalidation_condition" class="summary-line invalidation-line">
                <span class="summary-label">失效条件</span>
                <span>{{ firstFalsification(row) }}</span>
              </div>
              <div v-if="capitalFlowUnavailable(row)" class="summary-line source-line">
                <span class="summary-label">资金流</span>
                <span>暂未覆盖，不作为买入或放弃的单独依据。</span>
              </div>
            </div>

            <div class="card-footer">
              <div class="card-warnings">
                <el-tag
                  v-for="warning in recommendationRowWarnings(row, meta?.candidate_source).slice(0, 2)"
                  :key="warning"
                  size="small"
                  type="danger"
                  effect="plain"
                >
                  {{ warning }}
                </el-tag>
              </div>
              <div class="card-actions">
                <el-button size="small" type="primary" link @click.stop="goDetail(row)">详情</el-button>
                <el-button
                  size="small"
                  type="success"
                  link
                  :loading="addingSymbol === row.symbol"
                  :disabled="Boolean(actionBlockedReason(row))"
                  :title="actionBlockedReason(row)"
                  @click.stop="handleAddToWatchlist(row)"
                >
                  加自选
                </el-button>
              </div>
            </div>
          </article>
        </div>
        <div v-else class="bucket-empty">
          <el-empty description="今日未筛出该池标的" />
        </div>
      </section>
    </div>

    <div class="meta" v-if="meta">
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
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { analysisApi } from '@/api'
import { useWatchlistActions } from '@/composables/useWatchlistActions'
import { formatPct, formatPrice } from '@/utils/formatters'
import {
  ratingTag,
  recommendationActionBlockedReason,
  recommendationEmptyReason,
  recommendationPlainReason,
  recommendationRiskHint,
  recommendationRowWarnings,
  recommendationTrustState,
  riskHintTagType,
  scoreReferenceText,
  scoreTagType,
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
const loadError = ref('')
const expansionMessage = ref('')
const selectedTier = ref('')
const selectedBucket = ref('')
const bucketStackRef = ref<HTMLElement | null>(null)
const { addingSymbol, addToWatchlist } = useWatchlistActions()
const loadingBars = [92, 74, 86, 58]
let requestSeq = 0

const poolSummary = computed(() => meta.value?.pool_summary)

const filteredItems = computed(() => {
  if (!selectedTier.value) return items.value
  return items.value.filter(r => r.tier === selectedTier.value)
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

function onTierChange() {
  // 筛选无需重新加载
}

function getDisplayIndex(row: RecommendationItem): number {
  return filteredItems.value.indexOf(row)
}

function tierTagType(tier?: string | null): 'success' | 'primary' | 'warning' | 'info' | 'danger' | undefined {
  if (tier === 'A') return 'success'
  if (tier === 'B') return 'primary'
  return 'info'
}

function actionTagType(action?: string | null): 'success' | 'primary' | 'warning' | 'info' | 'danger' | undefined {
  if (action === '回踩承接') return 'success'
  if (action === '放量突破') return 'warning'
  if (action === '缩量企稳') return 'primary'
  if (action === '只看不追') return 'info'
  if (action === '消息验证') return 'warning'
  return 'info'
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
    if (res.pool_phase_message) {
      expansionMessage.value = res.pool_phase_message
    } else if (res.pipeline_status === 'stale') {
      const date = res.data_date || items.value.find((item) => item.snapshot_date)?.snapshot_date
      const targetDate = res.target_date
      expansionMessage.value = date
        ? `当前沿用基于 ${date} 收盘数据生成的观察池${targetDate ? `，原用于 ${targetDate} 观察` : ''}；等待今日盘后更新。`
        : '当前展示的是最近一次观察池结果（非今日），今日数据尚未生成。'
    } else if (res.pipeline_status === 'empty') {
      expansionMessage.value = '观察池暂无数据，请先运行一次采集（点击刷新按钮）。'
    }
    void loadRecentReviews(requestId)
  } catch (error) {
    if (requestId !== requestSeq) return
    loadError.value = readableApiError(error)
    ElMessage.error(loadError.value)
    items.value = []
    meta.value = null
  } finally {
    loading.value = false
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
  const reason = actionBlockedReason(row)
  if (reason) {
    ElMessage.warning(reason)
    return
  }
  addToWatchlist(row)
}

function actionBlockedReason(row: RecommendationItem) {
  return recommendationActionBlockedReason(row, meta.value)
}

function changeClass(value?: number | string) {
  const number = Number(value)
  if (!Number.isFinite(number)) return ''
  return number >= 0 ? 'up' : 'down'
}

function recommendationRatingTag(row: RecommendationItem) {
  const type = ratingTag(row.rating?.level)
  return type === 'info' && !row.rating?.level ? scoreTagType(row.score) : type
}

function rowDataDate(row: RecommendationItem) {
  if (!row.snapshot_date) return ''
  return `基于 ${row.snapshot_date} 收盘`
}

function firstFalsification(row: RecommendationItem) {
  return row.falsification?.find((item) => item.condition)?.condition || ''
}

function capitalFlowUnavailable(row: RecommendationItem) {
  const signal = row.capital_flow_status || row.capital_flow_features?.signal || row.capital_flow_features?.status
  return signal === 'unavailable'
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
}

.trust-strip strong {
  color: #303133;
}

.trust-strip.stable {
  border-color: #b7eb8f;
  background: #f2fbf6;
}

.trust-strip.warning {
  border-color: #f2d48b;
  background: #fff8e6;
}

.trust-strip.blocked {
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

.bucket-tag {
  flex-shrink: 0;
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

.stock-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid #dcdfe6;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  transition: box-shadow 0.2s, border-color 0.2s;
}

.stock-card:hover {
  border-color: var(--el-color-primary-light-5, #a0cfff);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}

.stock-card:focus-visible {
  outline: 2px solid var(--el-color-primary, #409eff);
  outline-offset: 2px;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 10px;
}

.card-rank {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #f0f2f5;
  color: #606266;
  font-size: 12px;
  font-weight: 600;
  flex-shrink: 0;
}

.card-stock-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.card-stock-info strong {
  font-size: 15px;
  color: #303133;
}

.card-symbol {
  color: #909399;
  font-family: monospace;
  font-size: 12px;
}

.card-data-date {
  color: #909399;
  font-size: 12px;
}

.card-score {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  max-width: 128px;
  text-align: right;
}

.card-score small {
  color: #909399;
  font-size: 11px;
  line-height: 1.35;
}

.score-number {
  font-size: 20px;
  font-weight: 700;
  color: #303133;
}

.card-price-row {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
}

.card-price {
  font-weight: 500;
  color: #303133;
}

.card-change {
  font-weight: 500;
}

.card-sector {
  margin-left: auto;
  color: #909399;
  font-size: 12px;
}

.retail-summary {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #f8fafc;
  font-size: 13px;
  line-height: 1.55;
}

.summary-line {
  display: flex;
  gap: 8px;
  color: #303133;
}

.summary-label {
  flex-shrink: 0;
  color: #606266;
  font-weight: 700;
}

.summary-label::after {
  content: '->';
}

.ai-label {
  color: #1a73e8;
}

.ai-summary-line {
  background: #f0f7ff;
  border-radius: 6px;
  padding: 6px 10px;
  border-left: 3px solid #409eff;
}

.risk-line.medium {
  color: #b7791f;
}

.risk-line.high {
  color: #c53030;
}

.risk-line.low {
  color: #2f855a;
}

.invalidation-line {
  color: #7c2d12;
}

.source-line {
  color: #606266;
}

.card-breakdown {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.capital-flow-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px 8px;
  border-radius: 6px;
  background: #f5f7fa;
  color: #606266;
  font-size: 12px;
}

.capital-flow-main {
  display: flex;
  align-items: center;
  gap: 8px;
}

.capital-flow-row small {
  color: #909399;
  padding-left: 2px;
}

.card-debate {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 6px;
  background: #f9fafb;
  font-size: 13px;
}

.debate-side {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  line-height: 1.5;
  color: #606266;
}

.debate-side span:last-child {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.debate-label {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}

.debate-side.bull .debate-label {
  background: #f0fdf4;
  color: #16a34a;
}

.debate-side.bear .debate-label {
  background: #fef2f2;
  color: #dc2626;
}

.card-evidence {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.evidence-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #606266;
}

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-top: auto;
  padding-top: 6px;
  border-top: 1px solid #f0f2f5;
}

.card-warnings {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  flex: 1;
  min-width: 0;
}

.card-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 40px 0;
  color: #909399;
}

.up {
  color: #d93026;
}

.down {
  color: #07883d;
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 12px;
  color: #909399;
  font-size: 13px;
}

@media (max-width: 760px) {
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

  .card-grid {
    grid-template-columns: 1fr;
  }

  .stock-card {
    padding: 14px;
  }

  .card-header,
  .card-price-row,
  .card-footer {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .card-score {
    align-items: flex-start;
    max-width: 100%;
    text-align: left;
  }

  .card-sector {
    margin-left: 0;
  }

  .summary-line {
    flex-direction: column;
    gap: 4px;
  }

  .card-actions {
    width: 100%;
    justify-content: flex-end;
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

/* 卡片分层边框 */
.stock-card.tier-a {
  border-left: 3px solid #67c23a;
}

.stock-card.tier-b {
  border-left: 3px solid #409eff;
}

.stock-card.tier-c {
  border-left: 3px solid #909399;
}

/* 分层标签 */
.tier-tag {
  margin-right: 4px;
}

/* 观察动作标签 */
.action-tag {
  font-weight: 600;
}

/* 触发/失效/风险条件 */
.trigger-line {
  color: #166534;
}

.trigger-label {
  color: #166534 !important;
  font-weight: 600 !important;
}

.risk-warning-line {
  color: #b45309;
}

.risk-label {
  color: #b45309 !important;
  font-weight: 600 !important;
}
</style>
