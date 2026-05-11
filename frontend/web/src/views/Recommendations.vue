<template>
  <div class="recommendations-page">
    <section class="toolbar">
      <div>
        <h2>每日观察池</h2>
        <p>{{ toolbarDescription }}</p>
      </div>
      <div class="actions">
        <el-segmented v-model="market" :options="marketOptions" @change="loadRecommendations(false)" />
        <el-segmented v-model="strategy" :options="strategyOptions" @change="loadRecommendations(false)" />
        <el-button :icon="Refresh" :loading="loading" @click="loadRecommendations(true)">刷新</el-button>
      </div>
    </section>

    <section v-if="meta?.market_regime || meta?.active_strategy" class="research-strip">
      <div class="research-card">
        <span class="research-label">市场环境</span>
        <div class="research-value">
          <el-tag size="small" :type="regimeTagType(meta?.market_regime?.regime)">
            {{ regimeLabel(meta?.market_regime?.regime) }}
          </el-tag>
          <span>{{ confidenceLabel(meta?.market_regime?.confidence) }}</span>
        </div>
        <small>{{ regimeSignalSummary }}</small>
      </div>
      <div class="research-card">
        <span class="research-label">当前策略</span>
        <div class="research-value">
          <strong>{{ strategyLabel(meta?.active_strategy?.id || strategy) }}</strong>
          <el-tag size="small" effect="plain">{{ meta?.active_strategy?.selection_mode === 'auto' ? '自动' : '手动' }}</el-tag>
        </div>
        <small>{{ strategySummary }}</small>
      </div>
    </section>

    <el-alert
      class="risk-alert"
      type="warning"
      show-icon
      :closable="false"
      :title="meta?.disclaimer || '不是买入建议。观察池偏向小而美和散户友好价格，仍需结合估值、仓位、风险承受能力和完整公告独立判断。'"
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
        <span>正在拉取候选池、评分明细和数据可信度，请稍等。</span>
        <small>首次会先展示一批观察股，通常需要 10-30 秒；随后后台扩展到 50 只，可能还需要 1-3 分钟，请不要重复刷新页面。</small>
      </div>
      <div class="loading-bars" aria-hidden="true">
        <i v-for="bar in loadingBars" :key="bar" :style="{ width: `${bar}%` }"></i>
      </div>
    </section>

    <el-table
      v-else
      v-loading="loading"
      :data="items"
      stripe
      class="recommendation-table"
      @row-click="goDetail"
    >
      <template #empty>
        <div class="empty-state">
          <strong>暂无每日观察池数据</strong>
          <span>{{ emptyReason }}</span>
        </div>
      </template>
      <el-table-column type="expand" width="42">
        <template #default="{ row }">
          <div class="breakdown-panel">
            <strong>入选/扣分明细</strong>
            <div class="breakdown-grid">
              <div
                v-for="item in row.score_breakdown || []"
                :key="item.key"
                class="breakdown-item"
                :class="item.status"
              >
                <span>{{ item.label }}</span>
                <strong>{{ formatDelta(item.delta) }}</strong>
                <small>{{ item.message }}</small>
              </div>
            </div>
            <div v-if="row.strategy_weighted_factors?.length" class="strategy-score-panel">
              <div class="strategy-score-head">
                <strong>策略权重调整</strong>
                <small>
                  原始 {{ row.base_score ?? row.score }} / 策略 {{ row.strategy_score ?? row.score }} /
                  {{ formatDelta(row.strategy_score_delta || 0) }}
                </small>
              </div>
              <div v-if="row.strategy_score_blending" class="strategy-blending">
                <span>基准分占比 {{ formatPercent(row.strategy_score_blending.base_weight) }}</span>
                <span>策略加权占比 {{ formatPercent(row.strategy_score_blending.weighted_weight) }}</span>
                <span>
                  因子倍率 {{ formatNumber(row.strategy_score_blending.multiplier_min) }}-{{
                    formatNumber(row.strategy_score_blending.multiplier_max)
                  }}
                </span>
                <span>锚点 {{ formatNullableNumber(row.strategy_score_blending.anchor) }}</span>
              </div>
              <div class="strategy-factor-grid">
                <div
                  v-for="factor in row.strategy_weighted_factors.slice(0, 6)"
                  :key="`${row.symbol}-${factor.factor}-${factor.dimension}`"
                  class="strategy-factor-item"
                >
                  <span>{{ factor.label || factor.factor }}</span>
                  <strong>{{ formatDelta(factor.weighted_delta || 0) }}</strong>
                  <small>
                    {{ factor.dimension || 'unmapped' }} / 权重 {{ formatPercent(factor.weight) }} /
                    倍率 {{ factor.multiplier ?? 1 }}
                  </small>
                </div>
              </div>
            </div>
            <div v-if="vetoDetailItems(row.veto_result).length" class="risk-veto-panel">
              <div class="risk-veto-head">
                <strong>风险裁决详情</strong>
                <el-tag size="small" :type="vetoTagType(row.veto_result)" effect="light">
                  {{ vetoLabel(row.veto_result) }}
                </el-tag>
              </div>
              <div class="risk-veto-grid">
                <div
                  v-for="item in vetoDetailItems(row.veto_result)"
                  :key="`${row.symbol}-${item.key || item.type}-${item.severity}-${item.detail}`"
                  class="risk-veto-item"
                  :class="item.severity"
                >
                  <div class="risk-veto-item-head">
                    <strong>{{ item.key || item.type || 'risk' }}</strong>
                    <el-tag size="small" :type="item.severity === 'hard' ? 'danger' : 'warning'" effect="plain">
                      {{ item.severity === 'hard' ? '硬否决' : '软警告' }}
                    </el-tag>
                  </div>
                  <small>{{ item.detail }}</small>
                  <div class="risk-veto-meta">
                    <span v-if="item.score_delta != null">策略扣分 {{ formatDelta(item.score_delta) }}</span>
                    <span v-if="item.handling">处理方式：{{ item.handling }}</span>
                  </div>
                </div>
              </div>
            </div>
            <div class="review-panel">
              <div class="review-head">
                <strong>历史入池复盘</strong>
                <small v-if="row.review_summary">
                  {{ row.review_summary.latest_snapshot_date || '-' }} / {{ strategyLabel(row.review_summary.strategy_id) }}
                </small>
                <small v-else>{{ row.review_unavailable ? '复盘暂不可用' : '暂无历史复盘' }}</small>
              </div>
              <div v-if="row.review_summary" class="review-grid">
                <div v-for="offset in reviewOffsets" :key="`${row.symbol}-${offset}`" class="review-item">
                  <span>{{ offset }}</span>
                  <strong :class="reviewReturnClass(row.review_summary.reviews?.[offset]?.return_pct)">
                    {{ formatReviewReturn(row.review_summary.reviews?.[offset]?.return_pct) }}
                  </strong>
                  <small>{{ reviewMetaText(row.review_summary.reviews?.[offset]) }}</small>
                </div>
              </div>
            </div>
            <div v-if="row.evidence_chain?.length" class="evidence-panel">
              <strong>证据链</strong>
              <div class="evidence-grid">
                <div
                  v-for="item in evidenceTopItems(row)"
                  :key="`${row.symbol}-${item.factor}`"
                  class="evidence-item"
                >
                  <div class="evidence-head">
                    <span>{{ item.label || item.factor }}</span>
                    <el-tag size="small" :type="evidenceType(item)" effect="light">
                      {{ formatDelta(item.impact || 0) }}
                    </el-tag>
                  </div>
                  <small>{{ item.explanation }}</small>
                  <div class="evidence-meta">
                    <span>值：{{ evidenceValueText(item.value) }}</span>
                    <span v-if="item.threshold">阈值：{{ item.threshold }}</span>
                    <span v-if="item.source">来源：{{ item.source }}</span>
                    <span v-if="item.confidence">置信度：{{ item.confidence }}</span>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="row.theme_validation" class="theme-validation-panel">
              <div class="theme-validation-head">
                <strong>主题/产业链真实性验证</strong>
                <el-tag size="small" :type="themeRiskTag(row.theme_validation.concept_risk?.level)" effect="light">
                  蹭概念风险：{{ themeRiskLabel(row.theme_validation.concept_risk?.level) }}
                </el-tag>
              </div>
              <div class="theme-validation-grid">
                <div class="theme-validation-item">
                  <span>主题热度</span>
                  <strong>{{ themeHeatLabel(row.theme_validation.theme_heat?.level) }}</strong>
                  <small>{{ (row.theme_validation.theme_heat?.themes || []).join(' / ') || '-' }}</small>
                </div>
                <div class="theme-validation-item">
                  <span>产业链位置</span>
                  <strong>{{ chainStageLabel(row.theme_validation.chain_position?.stage) }}</strong>
                  <small>{{ row.theme_validation.chain_position?.sector || row.sector || '-' }}</small>
                </div>
                <div class="theme-validation-item">
                  <span>业务相关性</span>
                  <strong>{{ businessRelevanceLabel(row.theme_validation.business_relevance?.level) }}</strong>
                  <small>{{ row.theme_validation.business_relevance?.reason || '-' }}</small>
                </div>
                <div class="theme-validation-item">
                  <span>收入/订单验证</span>
                  <strong>{{ verificationLabel(row.theme_validation.verification?.level) }}</strong>
                  <small>{{ (row.theme_validation.verification?.signals || []).slice(0, 3).join(' / ') || '暂无公告/财务验证' }}</small>
                </div>
              </div>
              <div v-if="row.theme_validation.concept_risk?.warnings?.length" class="theme-warnings">
                <el-tag
                  v-for="warning in row.theme_validation.concept_risk.warnings"
                  :key="warning"
                  size="small"
                  type="warning"
                  effect="plain"
                >
                  {{ warning }}
                </el-tag>
              </div>
            </div>
            <div v-if="row.bull_case?.length || row.bear_case?.length || row.falsification?.length" class="debate-panel">
              <div v-if="row.bull_case?.length" class="debate-column">
                <strong>看多逻辑</strong>
                <ul>
                  <li v-for="item in row.bull_case" :key="`${row.symbol}-bull-${item.factor}-${item.argument}`">
                    {{ item.argument }}
                  </li>
                </ul>
              </div>
              <div v-if="row.bear_case?.length" class="debate-column">
                <strong>看空逻辑</strong>
                <ul>
                  <li v-for="item in row.bear_case" :key="`${row.symbol}-bear-${item.factor}-${item.argument}`">
                    {{ item.argument }}
                  </li>
                </ul>
              </div>
              <div v-if="row.falsification?.length" class="debate-column">
                <strong>证伪条件</strong>
                <ul>
                  <li v-for="item in row.falsification" :key="`${row.symbol}-falsify-${item.condition}`">
                    {{ item.condition }}
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column type="index" label="#" width="52" />
      <el-table-column label="股票" min-width="150">
        <template #default="{ row }">
          <div class="stock-cell">
            <strong>{{ row.name }}</strong>
            <span>{{ row.symbol }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="sector" label="行业" width="110" />
      <el-table-column label="评分" width="110">
        <template #default="{ row }">
          <div class="score-cell">
            <strong>{{ row.score }}</strong>
            <el-tag size="small" :type="ratingTag(row.rating?.level)">{{ row.rating?.text }}</el-tag>
            <small v-if="row.base_score != null && row.strategy_score != null" class="strategy-score-meta">
              原始 {{ row.base_score }} / 策略 {{ row.strategy_score }}
              <span :class="scoreDeltaClass(row.strategy_score_delta)">
                {{ formatDelta(row.strategy_score_delta || 0) }}
              </span>
            </small>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="数据" width="125">
        <template #default="{ row }">
          <el-tag
            size="small"
            :type="dataGradeTag(row.data_grade?.grade)"
            effect="light"
            :title="row.data_grade?.analysis_scope || ''"
          >
            {{ row.data_grade?.grade || 'D' }} {{ row.data_grade?.label || '数据不足' }}
          </el-tag>
          <el-tag
            v-if="row.candidate_source || meta?.candidate_source"
            size="small"
            :type="isFallbackCandidate(row, meta?.candidate_source) ? 'danger' : 'info'"
            effect="plain"
          >
            {{ candidateSourceLabel(row.candidate_source || meta?.candidate_source) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="行情" width="130">
        <template #default="{ row }">
          <div>{{ formatPrice(row.price) }}</div>
          <span :class="changeClass(row.change_pct)">{{ formatPct(row.change_pct) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="单手成本" width="105">
        <template #default="{ row }">
          {{ formatMoney(row.lot_cost) }}
        </template>
      </el-table-column>
      <el-table-column label="为什么值得看" min-width="280">
        <template #default="{ row }">
          <div class="chips">
            <el-tag v-for="reason in row.reasons || []" :key="reason" size="small" effect="plain">
              {{ reason }}
            </el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="主要加减分" min-width="230">
        <template #default="{ row }">
          <div class="chips">
            <el-tag
              v-for="item in topBreakdown(row)"
              :key="item.key"
              size="small"
              :type="breakdownType(item)"
              effect="light"
            >
              {{ item.label }} {{ formatDelta(item.delta) }}
            </el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="风险" min-width="220">
        <template #default="{ row }">
          <div class="chips risk">
            <el-tag
              v-if="row.veto_result"
              size="small"
              :type="vetoTagType(row.veto_result)"
              effect="light"
            >
              {{ vetoLabel(row.veto_result) }}
            </el-tag>
            <el-tag v-for="risk in row.risk_flags || []" :key="risk" size="small" type="warning" effect="plain">
              {{ risk }}
            </el-tag>
            <el-tag
              v-for="warning in recommendationRowWarnings(row, meta?.candidate_source).slice(0, 4)"
              :key="warning"
              size="small"
              type="danger"
              effect="plain"
            >
              {{ warning }}
            </el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button type="primary" link @click.stop="goDetail(row)">详情</el-button>
            <el-button
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
        </template>
      </el-table-column>
    </el-table>

    <div class="meta" v-if="meta">
      <span>候选来源 {{ candidateSourceText }}</span>
      <span>股票池 {{ meta.candidate_universe_count || meta.selection?.universe_count || meta.candidate_count || 0 }} 只</span>
      <span>本次评估 {{ meta.selection?.evaluated_count || meta.candidate_count || 0 }} 只</span>
      <span>有效评分 {{ meta.scored_count || 0 }} 只</span>
      <span>接口返回 {{ meta.count ?? items.length }} 只</span>
      <span>当前展示 {{ items.length }} 只</span>
      <span v-if="meta.initial_full_scan?.used">首次全量筛选</span>
      <span>{{ meta.cache_hit ? '缓存命中' : '重新计算' }}</span>
      <span>{{ meta.updated_at }}</span>
      <span>规则筛选，不是模型直接喊单</span>
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
import { formatDelta, formatMoney, formatPct, formatPrice } from '@/utils/formatters'
import {
  breakdownType,
  candidateSourceLabel,
  dataGradeTag,
  evidenceTopItems,
  evidenceType,
  evidenceValueText,
  isFallbackCandidate,
  regimeLabel,
  regimeTagType,
  ratingTag,
  recommendationActionBlockedReason,
  recommendationEmptyReason,
  recommendationRowWarnings,
  recommendationTrustState,
  resolveRecentReviewStrategy,
  strategyLabel,
  topBreakdown,
  vetoDetailItems,
  vetoLabel,
  vetoTagType,
  type RecentReviewsResponse,
  type RecommendationItem,
  type ReviewOffset,
  type ReviewResultItem,
  type RecommendationsResponse,
} from '@/utils/recommendations'

const router = useRouter()
const QUICK_LIMIT = 10
const QUICK_CANDIDATES = 50
const FULL_LIMIT = 50
const FULL_CANDIDATES = 200

const loading = ref(false)
const expanding = ref(false)
const market = ref('ALL')
const strategy = ref('auto')
const items = ref<RecommendationItem[]>([])
const meta = ref<RecommendationsResponse | null>(null)
const loadError = ref('')
const expansionMessage = ref('')
const { addingSymbol, addToWatchlist } = useWatchlistActions()
const loadingBars = [92, 74, 86, 58]
const reviewOffsets: ReviewOffset[] = ['T+1', 'T+5', 'T+20']
let requestSeq = 0

const marketOptions = [
  { label: '沪深', value: 'ALL' },
  { label: '沪市', value: 'SH' },
  { label: '深市', value: 'SZ' },
]

const strategyOptions = [
  { label: '自动', value: 'auto' },
  { label: '小而美', value: 'retail_small' },
  { label: '价值质量', value: 'value_quality' },
  { label: '成长动量', value: 'growth_momentum' },
  { label: '反转观察', value: 'reversal_watch' },
  { label: '事件驱动', value: 'event_driven' },
  { label: '红利防御', value: 'dividend_defensive' },
]

const toolbarDescription = computed(() => {
  const currentStrategy = meta.value?.active_strategy?.id || strategy.value
  if (currentStrategy === 'auto') return '系统会先判断市场环境，再自动选择更匹配的观察策略。'
  return `当前按“${strategyLabel(currentStrategy)}”筛选值得继续研究的候选股。`
})

const candidateSourceText = computed(() => {
  return candidateSourceLabel(meta.value?.candidate_source)
})

const regimeSignalSummary = computed(() => {
  const signals = meta.value?.market_regime?.signals || []
  if (!signals.length) return '暂无可展示的市场信号。'
  return signals.slice(0, 2).map((item) => item.detail || item.indicator || '').filter(Boolean).join('；')
})

const strategySummary = computed(() => {
  const active = meta.value?.active_strategy
  if (!active) return '尚未选择策略。'
  if (active.selection_mode === 'auto') {
    return `依据市场环境自动切换，底层评分内核：${strategyLabel(active.engine_strategy)}。`
  }
  return `手动指定策略，底层评分内核：${strategyLabel(active.engine_strategy)}。`
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
const recentReviewStrategy = computed(() => {
  return resolveRecentReviewStrategy(strategy.value, meta.value?.active_strategy?.id)
})

function confidenceLabel(value?: string) {
  if (value === 'high') return '高置信度'
  if (value === 'medium') return '中等置信度'
  if (value === 'low') return '低置信度'
  return '置信度未知'
}

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
      QUICK_LIMIT,
      forceRefresh,
      strategy.value,
      QUICK_CANDIDATES,
      true,
      true,
      false,
    )
    if (requestId !== requestSeq || currentMarket !== market.value) return
    items.value = res.recommendations || []
    meta.value = res
    void loadRecentReviews(requestId)
    void expandRecommendations(requestId, currentMarket)
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

async function expandRecommendations(requestId = requestSeq, requestMarket = market.value) {
  if (expanding.value) return
  expanding.value = true
  expansionMessage.value = '已先展示一批观察股，系统正在后台扩展到 50 只，通常还需要 1-3 分钟。'
  try {
    const res = await analysisApi.getRecommendations(
      requestMarket,
      FULL_LIMIT,
      false,
      strategy.value,
      FULL_CANDIDATES,
      true,
      true,
      false,
    )
    if (requestId !== requestSeq || requestMarket !== market.value) return
    items.value = res.recommendations || []
    meta.value = res
    void loadRecentReviews(requestId)
    expansionMessage.value = ''
  } catch {
    if (requestId !== requestSeq) return
    expansionMessage.value = '已展示首批观察股；扩展到 50 只暂时较慢，可稍后点击刷新重试。'
  } finally {
    if (requestId === requestSeq) {
      expanding.value = false
    }
  }
}

async function loadRecentReviews(requestId = requestSeq) {
  const symbols = items.value.map((item) => item.symbol).filter(Boolean)
  if (!symbols.length) return
  try {
    const response = await analysisApi.getRecentReviews<RecentReviewsResponse>(symbols, recentReviewStrategy.value)
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

function formatReviewReturn(value?: number | null) {
  if (value === null || value === undefined) return '-'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

function reviewReturnClass(value?: number | null) {
  if (value === null || value === undefined) return ''
  if (value > 0) return 'up'
  if (value < 0) return 'down'
  return ''
}

function scoreDeltaClass(value?: number | null) {
  if (value === null || value === undefined) return ''
  if (value > 0) return 'up'
  if (value < 0) return 'down'
  return ''
}

function formatPercent(value?: number | null) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-'
  return `${(Number(value) * 100).toFixed(1)}%`
}

function formatNumber(value?: number | null) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '-'
  return Number(value).toFixed(2)
}

function formatNullableNumber(value?: number | null) {
  return value === null || value === undefined ? '跟随基础分' : formatNumber(value)
}

function reviewMetaText(item?: ReviewResultItem | null) {
  if (!item) return '未到复盘时间'
  const flags = []
  if (item.falsification_triggered) flags.push('证伪')
  if (item.risk_signal_valid) flags.push('风险命中')
  return [item.review_date || '-', ...flags].join(' / ')
}

function themeHeatLabel(value?: string) {
  if (value === 'high') return '高热度'
  if (value === 'medium') return '中等热度'
  if (value === 'low') return '低热度'
  return '无主题'
}

function chainStageLabel(value?: string) {
  if (value === 'upstream') return '上游'
  if (value === 'midstream') return '中游'
  if (value === 'downstream') return '下游'
  return '未知'
}

function businessRelevanceLabel(value?: string) {
  if (value === 'direct') return '直接相关'
  if (value === 'indirect') return '间接相关'
  if (value === 'weak') return '弱相关'
  return '未知'
}

function verificationLabel(value?: string) {
  if (value === 'verified') return '已找到验证'
  if (value === 'unverified') return '未验证'
  if (value === 'missing') return '缺少主题'
  return '未知'
}

function themeRiskLabel(value?: string) {
  if (value === 'low') return '低'
  if (value === 'medium') return '中'
  if (value === 'high') return '高'
  return '未知'
}

function themeRiskTag(value?: string) {
  if (value === 'low') return 'success'
  if (value === 'medium') return 'warning'
  if (value === 'high') return 'danger'
  return 'info'
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

.research-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}

.research-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  background: #fff;
}

.research-label {
  color: #909399;
  font-size: 12px;
}

.research-value {
  display: flex;
  gap: 8px;
  align-items: center;
  color: #303133;
}

.research-card small {
  color: #606266;
  line-height: 1.5;
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

.recommendation-table {
  width: 100%;
}

.stock-cell,
.score-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stock-cell span {
  color: #909399;
  font-family: monospace;
}

.strategy-score-meta {
  color: #909399;
  font-size: 11px;
  line-height: 1.35;
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 18px 0;
  color: #909399;
}

.breakdown-panel {
  padding: 12px 18px 16px;
  background: #fafafa;
}

.breakdown-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.breakdown-item {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 4px 8px;
  padding: 8px 10px;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  background: #fff;
}

.breakdown-item small {
  grid-column: 1 / -1;
  color: #606266;
}

.breakdown-item.positive {
  border-color: #b7eb8f;
}

.breakdown-item.negative,
.breakdown-item.warning {
  border-color: #ffe58f;
}

.review-panel,
.strategy-score-panel,
.risk-veto-panel,
.evidence-panel,
.theme-validation-panel,
.debate-panel {
  margin-top: 14px;
}

.review-panel,
.strategy-score-panel,
.risk-veto-panel {
  padding: 10px 12px;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  background: #fff;
}

.review-head,
.strategy-score-head,
.risk-veto-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.review-head small,
.strategy-score-head small,
.review-item small {
  color: #606266;
}

.strategy-blending,
.risk-veto-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  margin-top: 8px;
  color: #606266;
  font-size: 12px;
}

.review-grid,
.strategy-factor-grid,
.risk-veto-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.review-item,
.strategy-factor-item,
.risk-veto-item {
  display: grid;
  gap: 4px;
  padding: 8px 10px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  background: #fafafa;
}

.review-item span {
  color: #909399;
  font-size: 12px;
}

.strategy-factor-item span,
.strategy-factor-item small {
  color: #909399;
  font-size: 12px;
}

.risk-veto-item.hard {
  border-color: #ffa39e;
  background: #fff7f6;
}

.risk-veto-item.soft {
  border-color: #ffe58f;
  background: #fffbe6;
}

.risk-veto-item-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
}

.risk-veto-item small {
  color: #606266;
  line-height: 1.5;
}

.evidence-grid,
.debate-panel {
  display: grid;
  gap: 10px;
  margin-top: 10px;
}

.evidence-grid {
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
}

.evidence-item,
.debate-column {
  padding: 10px 12px;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  background: #fff;
}

.evidence-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  align-items: center;
  margin-bottom: 6px;
}

.evidence-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 8px;
  color: #606266;
  font-size: 12px;
}

.theme-validation-panel {
  padding: 10px 12px;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  background: #fbfdff;
}

.theme-validation-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}

.theme-validation-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 8px;
  margin-top: 10px;
}

.theme-validation-item {
  display: grid;
  gap: 4px;
  padding: 8px 10px;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  background: #fff;
}

.theme-validation-item span {
  color: #909399;
  font-size: 12px;
}

.theme-validation-item small {
  color: #606266;
  line-height: 1.5;
}

.theme-warnings {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}

.debate-panel {
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.debate-column ul {
  margin: 8px 0 0;
  padding-left: 18px;
  color: #606266;
}

.debate-column li + li {
  margin-top: 6px;
}

.up {
  color: #d93026;
}

.down {
  color: #07883d;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 12px;
  color: #909399;
  font-size: 13px;
}

:deep(.el-table__row) {
  cursor: pointer;
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
}
</style>
