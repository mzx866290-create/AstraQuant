<template>
  <div class="recommendations-page">
    <section class="toolbar">
      <div>
        <h2>每日观察池</h2>
        <p>{{ toolbarDescription }}</p>
      </div>
      <div class="actions">
        <el-segmented v-model="market" :options="marketOptions" @change="loadRecommendations(false)" />
        <el-button :icon="Refresh" :loading="loading" @click="loadRecommendations(true)">刷新</el-button>
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

    <div v-if="!showInitialLoading && items.length > 0" v-loading="loading" class="card-grid">
      <article
        v-for="(row, index) in items"
        :key="row.symbol"
        class="stock-card"
        @click="goDetail(row)"
      >
        <div class="card-header">
          <div class="card-rank">#{{ index + 1 }}</div>
          <div class="card-stock-info">
            <strong>{{ row.name }}</strong>
            <span class="card-symbol">{{ row.symbol }}</span>
          </div>
          <div class="card-score">
            <span class="score-number">{{ row.score }}</span>
            <el-tag size="small" :type="recommendationRatingTag(row)">
              {{ row.rating?.text || scoreReferenceText(row.score) }}
            </el-tag>
            <small>{{ scoreReferenceDetail(row.score) }}</small>
          </div>
        </div>

        <div class="card-price-row">
          <span class="card-price">{{ formatPrice(row.price) }}</span>
          <span class="card-change" :class="changeClass(row.change_pct)">{{ formatPct(row.change_pct) }}</span>
          <el-tag size="small" :type="riskHintTagType(recommendationRiskHint(row))" effect="light">
            {{ recommendationRiskHint(row).label }}
          </el-tag>
          <span v-if="row.sector" class="card-sector">{{ row.sector }}</span>
        </div>

        <div class="retail-summary">
          <div class="summary-line reason-line">
            <span class="summary-label">入选理由</span>
            <span>{{ recommendationPlainReason(row) }}</span>
          </div>
          <div class="summary-line risk-line" :class="recommendationRiskHint(row).level">
            <span class="summary-label">风险提示</span>
            <span>{{ recommendationRiskHint(row).message }}</span>
          </div>
        </div>

        <div v-if="row.capital_flow_features" class="capital-flow-row">
          <div class="capital-flow-main">
            <el-tag size="small" :type="capitalFlowTagType(row)" effect="light">
              {{ capitalFlowLabel(row) }}
            </el-tag>
            <span>{{ capitalFlowSummary(row) || 'AKShare资金流验证已接入' }}</span>
          </div>
          <small v-if="capitalFlowSourceText(row)">{{ capitalFlowSourceText(row) }}</small>
        </div>

        <div class="card-breakdown">
          <el-tag
            v-for="item in topBreakdown(row)"
            :key="item.key"
            size="small"
            :type="breakdownType(item)"
            effect="light"
          >
            {{ item.label }} {{ formatDelta(item.delta) }}
          </el-tag>
          <el-tag
            v-if="row.veto_result"
            size="small"
            :type="vetoTagType(row.veto_result)"
            effect="light"
          >
            {{ vetoLabel(row.veto_result) }}
          </el-tag>
        </div>

        <div v-if="row.bull_case?.length || row.bear_case?.length" class="card-debate">
          <div v-if="row.bull_case?.length" class="debate-side bull">
            <span class="debate-label">多</span>
            <span>{{ row.bull_case[0]?.argument }}</span>
          </div>
          <div v-if="row.bear_case?.length" class="debate-side bear">
            <span class="debate-label">空</span>
            <span>{{ row.bear_case[0]?.argument }}</span>
          </div>
        </div>

        <div v-if="evidenceTopItems(row, 2).length" class="card-evidence">
          <div v-for="item in evidenceTopItems(row, 2)" :key="`${row.symbol}-${item.factor}`" class="evidence-chip">
            <span>{{ item.label || item.factor }}</span>
            <el-tag size="small" :type="evidenceType(item)" effect="light">{{ formatDelta(item.impact || 0) }}</el-tag>
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

    <div class="meta" v-if="meta">
      <span>筛选结果 {{ meta.count ?? items.length }} 只</span>
      <span>当前展示 {{ items.length }} 只</span>
      <span>状态 {{ pipelineStatusText }}</span>
      <span v-if="candidatePoolText">{{ candidatePoolText }}</span>
      <span v-if="meta.cache_hit !== undefined">{{ meta.cache_hit ? '缓存命中' : '重新计算' }}</span>
      <span>{{ meta.updated_at }}</span>
      <span>流程：全市场快照 → 趋势/量价初筛 → 风险否决 → 观察池</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { analysisApi } from '@/api'
import { useWatchlistActions } from '@/composables/useWatchlistActions'
import { formatDelta, formatPct, formatPrice } from '@/utils/formatters'
import {
  breakdownType,
  capitalFlowLabel,
  capitalFlowSourceText,
  capitalFlowSummary,
  capitalFlowTagType,
  evidenceTopItems,
  evidenceType,
  ratingTag,
  recommendationActionBlockedReason,
  recommendationEmptyReason,
  recommendationPlainReason,
  recommendationRiskHint,
  recommendationRowWarnings,
  recommendationTrustState,
  riskHintTagType,
  scoreReferenceDetail,
  scoreReferenceText,
  scoreTagType,
  topBreakdown,
  vetoLabel,
  vetoTagType,
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
const { addingSymbol, addToWatchlist } = useWatchlistActions()
const loadingBars = [92, 74, 86, 58]
let requestSeq = 0

const marketOptions = [
  { label: '沪深', value: 'ALL' },
  { label: '沪市', value: 'SH' },
  { label: '深市', value: 'SZ' },
]

const toolbarDescription = computed(() => {
  return '基于均线趋势确认 + 安全边际筛选，每日 15:35 自动更新。'
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
  if (meta.value?.pipeline_status === 'stale') return '展示最近一次结果'
  if (meta.value?.pipeline_status === 'empty') return '暂无结果'
  return '已完成终筛'
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

async function loadRecommendations(forceRefresh = false) {
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
      forceRefresh,
    )
    if (requestId !== requestSeq || currentMarket !== market.value) return
    items.value = res.recommendations || []
    meta.value = res
    if (res.pipeline_status === 'stale') {
      expansionMessage.value = '当前展示的是最近一次观察池结果（非今日），今日数据尚未生成。'
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

onMounted(() => loadRecommendations(false))
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
  content: '：';
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

  .card-grid {
    grid-template-columns: 1fr;
  }
}
</style>
