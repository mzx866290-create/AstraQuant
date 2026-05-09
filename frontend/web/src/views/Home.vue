<template>
  <div class="home-page">
    <section class="topbar">
      <div>
        <h2>今日观察</h2>
        <p>偏向单手成本友好、市值不过分庞大、数据风险较低的小中盘候选股。</p>
      </div>
      <div class="topbar-actions">
        <el-segmented v-model="market" :options="marketOptions" @change="loadRecommendations(false)" />
        <el-button :icon="Refresh" :loading="loading" @click="loadRecommendations(true)">刷新</el-button>
      </div>
    </section>

    <el-alert
      class="disclaimer"
      type="warning"
      show-icon
      :closable="false"
      title="今日观察不是买入建议。这里偏向小而美和散户友好价格，但仍需结合详情页、公告、估值和自身风险承受能力判断。"
    />

    <el-alert
      v-if="recommendationWarning"
      class="disclaimer"
      type="warning"
      show-icon
      :closable="false"
      :title="recommendationWarning"
    />

    <section class="trust-strip" :class="trustState.level">
      <strong>可信状态：{{ trustState.label }}</strong>
      <span>{{ trustState.message }}</span>
      <span v-for="reason in trustState.reasons" :key="reason">{{ reason }}</span>
    </section>

    <section class="health-strip" :class="systemHealth?.status || 'unknown'">
      <span>服务状态：{{ healthText }}</span>
      <span v-for="svc in systemHealth?.services || []" :key="svc.service">
        {{ serviceName(svc.service) }} {{ svc.status === 'ok' ? '正常' : '异常' }}
      </span>
      <span v-if="systemHealth?.status !== 'ok'" class="health-hint">
        本地异常时运行：python scripts/start_local.py
      </span>
    </section>

    <!-- 骨架屏 -->
    <div v-if="loading" class="skeleton-grid">
      <div v-for="i in 6" :key="i" class="skeleton-card">
        <div class="skeleton-header">
          <div class="skeleton-title"></div>
          <div class="skeleton-circle"></div>
        </div>
        <div class="skeleton-body">
          <div class="skeleton-line skeleton-line-lg"></div>
          <div class="skeleton-line"></div>
          <div class="skeleton-tags">
            <div class="skeleton-tag"></div>
            <div class="skeleton-tag"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- 卡片网格 -->
    <div v-else-if="recommendations.length > 0" class="recommendation-grid">
      <div
        v-for="(row, index) in recommendations"
        :key="row.symbol"
        class="stock-card"
        :style="{ animationDelay: `${index * 0.05}s` }"
        @click="goDetail(row)"
      >
        <div class="card-header">
          <div class="stock-info">
            <strong class="stock-name">{{ row.name }}</strong>
            <div class="stock-meta">
              <span class="stock-symbol">{{ row.symbol }}</span>
              <el-tag v-if="row.sector" size="small" effect="plain" class="sector-tag">{{ row.sector }}</el-tag>
            </div>
          </div>
          <div class="score-ring" :class="scoreClass(row.score)">
            <span class="score-value">{{ row.score }}</span>
            <span class="score-label">{{ row.rating?.text }}</span>
          </div>
        </div>

        <div class="card-metrics">
          <div class="metric">
            <span class="metric-label">最新价</span>
            <strong class="metric-value">{{ formatPrice(row.price) }}</strong>
          </div>
          <div class="metric">
            <span class="metric-label">涨跌幅</span>
            <strong class="metric-value" :class="changeClass(row.change_pct)">
              {{ formatPct(row.change_pct) }}
            </strong>
          </div>
          <div class="metric">
            <span class="metric-label">单手成本</span>
            <strong class="metric-value">{{ formatMoney(row.lot_cost) }}</strong>
          </div>
        </div>

        <div class="card-data-grade">
          <el-tag
            size="small"
            :type="dataGradeTag(row.data_grade?.grade)"
            effect="light"
            class="grade-tag"
          >
            {{ row.data_grade?.grade || 'D' }}
          </el-tag>
          <span class="grade-label">{{ row.data_grade?.label || '数据不足' }}</span>
          <el-tag
            v-if="row.candidate_source || meta?.candidate_source"
            size="small"
            :type="isFallbackCandidate(row, meta?.candidate_source) ? 'danger' : 'info'"
            effect="plain"
            class="source-tag"
          >
            {{ candidateSourceLabel(row.candidate_source || meta?.candidate_source) }}
          </el-tag>
        </div>

        <div v-if="row.reasons?.length" class="card-section">
          <span class="section-label">观察理由</span>
          <div class="chips">
            <el-tag
              v-for="reason in row.reasons.slice(0, 3)"
              :key="reason"
              size="small"
              effect="plain"
              class="reason-tag"
            >
              {{ reason }}
            </el-tag>
          </div>
        </div>

        <div v-if="topBreakdown(row).length" class="card-section">
          <span class="section-label">评分明细</span>
          <div class="chips">
            <el-tag
              v-for="item in topBreakdown(row).slice(0, 4)"
              :key="item.key"
              size="small"
              :type="breakdownType(item)"
              effect="light"
              class="breakdown-tag"
            >
              {{ item.label }} {{ formatDelta(item.delta) }}
            </el-tag>
          </div>
        </div>

        <div v-if="(row.risk_flags || []).length || recommendationRowWarnings(row, meta?.candidate_source).length" class="card-section">
          <span class="section-label">风险</span>
          <div class="chips">
            <el-tag
              v-for="risk in (row.risk_flags || []).slice(0, 2)"
              :key="risk"
              size="small"
              type="warning"
              effect="plain"
              class="risk-tag"
            >
              {{ risk }}
            </el-tag>
            <el-tag
              v-for="warning in recommendationRowWarnings(row, meta?.candidate_source).slice(0, 2)"
              :key="warning"
              size="small"
              type="danger"
              effect="plain"
              class="risk-tag"
            >
              {{ warning }}
            </el-tag>
          </div>
        </div>

        <div class="card-actions" @click.stop>
          <el-button type="primary" link @click="goDetail(row)">详情</el-button>
          <el-button
            type="success"
            link
            :loading="addingSymbol === row.symbol"
            :disabled="Boolean(actionBlockedReason(row))"
            :title="actionBlockedReason(row)"
            @click="handleAddToWatchlist(row)"
          >
            加自选
          </el-button>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-else class="empty-state-card">
      <div class="empty-content">
        <el-icon :size="56" class="empty-icon"><TrendCharts /></el-icon>
        <strong>暂无今日观察数据</strong>
        <span>{{ emptyReason }}</span>
      </div>
    </div>

    <section class="home-actions">
      <router-link to="/recommendations" class="action-link">
        <el-icon><TrendCharts /></el-icon>
        <span>完整观察池</span>
      </router-link>
      <router-link to="/stocks" class="action-link">
        <el-icon><Search /></el-icon>
        <span>搜索股票</span>
      </router-link>
      <router-link to="/watchlist" class="action-link">
        <el-icon><Star /></el-icon>
        <span>我的自选</span>
      </router-link>
    </section>

    <div class="meta" v-if="meta">
      <span>候选来源 {{ candidateSourceText }}</span>
      <span>候选 {{ meta.candidate_count || 0 }} 只</span>
      <span>有效评分 {{ meta.scored_count || 0 }} 只</span>
      <span>{{ meta.cache_hit ? '缓存命中' : '重新计算' }}</span>
      <span>{{ meta.updated_at }}</span>
      <span>本页为观察池，不是买入建议</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh, Search, Star, TrendCharts } from '@element-plus/icons-vue'
import { analysisApi } from '@/api'
import { useWatchlistActions } from '@/composables/useWatchlistActions'
import { formatDelta, formatMoney, formatPct, formatPrice } from '@/utils/formatters'
import {
  breakdownType,
  candidateSourceLabel,
  dataGradeTag,
  isFallbackCandidate,
  recommendationActionBlockedReason,
  recommendationEmptyReason,
  recommendationRowWarnings,
  recommendationTrustState,
  topBreakdown,
  type RecommendationItem,
  type RecommendationsResponse,
} from '@/utils/recommendations'

interface SystemHealth {
  status?: string
  services?: {
    service: string
    status: string
  }[]
}

interface ApiErrorLike {
  response?: {
    data?: {
      detail?: string
    }
  }
}

const router = useRouter()
const loading = ref(false)
const market = ref('ALL')
const recommendations = ref<RecommendationItem[]>([])
const meta = ref<RecommendationsResponse | null>(null)
const systemHealth = ref<SystemHealth | null>(null)
const { addingSymbol, addToWatchlist } = useWatchlistActions()

const marketOptions = [
  { label: '沪深', value: 'ALL' },
  { label: '沪市', value: 'SH' },
  { label: '深市', value: 'SZ' },
]

async function loadRecommendations(forceRefresh = false) {
  loading.value = true
  try {
    const res = await analysisApi.getRecommendations(market.value, 10, forceRefresh, 'retail_small')
    recommendations.value = res.recommendations || []
    meta.value = res
  } catch (error) {
    ElMessage.error((error as ApiErrorLike)?.response?.data?.detail || '今日观察加载失败')
    recommendations.value = []
    meta.value = null
  } finally {
    loading.value = false
  }
}

async function loadSystemHealth() {
  try {
    systemHealth.value = await analysisApi.getPublicSystemHealth<SystemHealth>()
  } catch {
    systemHealth.value = { status: 'degraded', services: [] }
  }
}

const healthText = computed(() => {
  if (!systemHealth.value) return '检查中'
  return systemHealth.value.status === 'ok' ? '全部正常' : '部分异常'
})

const candidateSourceText = computed(() => {
  return candidateSourceLabel(meta.value?.candidate_source)
})

const recommendationWarning = computed(() => {
  if (!meta.value) return ''
  if (meta.value.status === 'unavailable') return '今日观察池不可用：数据库候选池为空，系统没有生成候选结果。'
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
const emptyReason = computed(() => recommendationEmptyReason(meta.value))

function serviceName(name: string) {
  if (name === 'market-service') return '行情'
  if (name === 'user-service') return '用户'
  if (name === 'analysis-service') return '分析'
  return name
}

function changeClass(value?: number | string) {
  const number = Number(value)
  if (!Number.isFinite(number)) return ''
  return number >= 0 ? 'up' : 'down'
}

function scoreClass(score?: number) {
  if (!score || !Number.isFinite(score)) return ''
  if (score >= 70) return 'high'
  if (score >= 40) return 'medium'
  return 'low'
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

onMounted(() => {
  loadSystemHealth()
  loadRecommendations(false)
})
</script>

<style scoped>
.home-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.topbar {
  display: flex;
  justify-content: space-between;
  gap: var(--space-4);
  align-items: center;
  padding: var(--space-5);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
}

.topbar h2 {
  margin: 0 0 var(--space-1);
  color: var(--color-text);
  font-size: 26px;
  font-weight: 800;
  letter-spacing: -0.03em;
}

.topbar p {
  margin: 0;
  color: var(--color-text-secondary);
}

.topbar-actions {
  display: flex;
  gap: var(--space-3);
  align-items: center;
}

.disclaimer {
  border-radius: var(--radius-md);
}

.health-strip {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  background: var(--color-surface);
  font-size: 13px;
  box-shadow: var(--shadow-card);
}

.health-strip.ok {
  border-color: rgba(22, 163, 106, 0.24);
  background: #f2fbf6;
}

.health-strip.degraded,
.health-strip.unknown {
  border-color: #f2d48b;
  background: var(--color-warning-soft);
}

.health-hint {
  font-family: var(--font-number);
  color: var(--color-warning);
}

.trust-strip {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text-secondary);
  background: var(--color-surface);
  font-size: 13px;
  box-shadow: var(--shadow-card);
}

.trust-strip strong {
  color: var(--color-text);
}

.trust-strip.stable {
  border-color: rgba(22, 163, 106, 0.24);
  background: #f2fbf6;
}

.trust-strip.warning {
  border-color: #f2d48b;
  background: var(--color-warning-soft);
}

.trust-strip.blocked {
  border-color: #ffa39e;
  background: #fff1f0;
}

.empty-state {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--space-6) 0;
  color: var(--color-text-muted);
}

/* Skeleton loading */
.skeleton-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: var(--space-4);
}

.skeleton-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  overflow: hidden;
}

.skeleton-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-4);
}

.skeleton-title {
  height: 20px;
  width: 120px;
  border-radius: var(--radius-sm);
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
}

.skeleton-circle {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
}

.skeleton-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.skeleton-line {
  height: 16px;
  width: 60%;
  border-radius: var(--radius-sm);
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
}

.skeleton-line-lg {
  width: 40%;
  height: 28px;
}

.skeleton-tags {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.skeleton-tag {
  width: 60px;
  height: 24px;
  border-radius: 999px;
  background: linear-gradient(90deg, var(--color-border) 25%, var(--color-surface-muted) 50%, var(--color-border) 75%);
  background-size: 200% 100%;
  animation: skeleton-loading 1.5s ease-in-out infinite;
}

@keyframes skeleton-loading {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Card grid */
.recommendation-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: var(--space-4);
}

.stock-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  cursor: pointer;
  transition: all var(--transition-base);
  animation: card-enter 0.4s ease-out backwards;
}

.stock-card:hover {
  border-color: var(--color-primary);
  box-shadow: 0 8px 24px rgba(29, 78, 216, 0.08);
  transform: translateY(-2px);
}

@keyframes card-enter {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.stock-info {
  min-width: 0;
  flex: 1;
}

.stock-name {
  display: block;
  font-size: 16px;
  font-weight: 800;
  color: var(--color-text);
  margin-bottom: var(--space-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stock-meta {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.stock-symbol {
  font-family: var(--font-number);
  font-size: 13px;
  color: var(--color-text-muted);
}

.sector-tag {
  font-size: 11px;
}

.score-ring {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  border: 3px solid var(--color-border);
  flex-shrink: 0;
  transition: all var(--transition-fast);
}

.score-ring:hover {
  transform: scale(1.05);
}

.score-ring.high {
  border-color: var(--color-down);
  background: var(--color-success-bg);
}

.score-ring.medium {
  border-color: var(--color-warning);
  background: var(--color-warning-soft);
}

.score-ring.low {
  border-color: var(--color-up);
  background: var(--color-danger-soft);
}

.score-value {
  font-size: 18px;
  font-weight: 800;
  font-family: var(--font-number);
  line-height: 1;
}

.score-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--color-text-muted);
  margin-top: 2px;
}

.card-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--space-3);
  padding: var(--space-3);
  background: var(--color-surface-muted);
  border-radius: var(--radius-sm);
  margin-bottom: var(--space-3);
}

.metric {
  text-align: center;
}

.metric-label {
  display: block;
  font-size: 11px;
  color: var(--color-text-muted);
  margin-bottom: var(--space-1);
}

.metric-value {
  display: block;
  font-family: var(--font-number);
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
}

.card-data-grade {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--color-border);
}

.grade-label {
  font-size: 13px;
  color: var(--color-text-secondary);
}

.grade-tag {
  font-weight: 700;
}

.card-section {
  margin-bottom: var(--space-3);
}

.section-label {
  display: block;
  font-size: 11px;
  font-weight: 700;
  color: var(--color-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-bottom: var(--space-2);
}

.chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
}

.reason-tag,
.breakdown-tag,
.risk-tag {
  font-size: 11px;
}

.card-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: var(--space-3);
  border-top: 1px solid var(--color-border);
  margin-top: var(--space-2);
}

.empty-state-card {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 320px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-8);
}

.empty-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
  color: var(--color-text-muted);
  text-align: center;
}

.empty-content strong {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
}

.empty-icon {
  color: var(--color-border-strong);
}

.up {
  color: var(--color-up);
  font-family: var(--font-number);
  font-weight: 700;
}

.down {
  color: var(--color-down);
  font-family: var(--font-number);
  font-weight: 700;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.home-actions {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--space-3);
}

.action-link {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-2);
  min-height: 48px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  color: var(--color-text);
  text-decoration: none;
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
  transition: border-color 0.2s ease, color 0.2s ease, transform 0.2s ease;
}

.action-link:hover {
  border-color: var(--color-primary);
  color: var(--color-primary);
  transform: translateY(-1px);
}

.meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  color: var(--color-text-muted);
  font-size: 13px;
}

:deep(.el-table__row) {
  cursor: pointer;
}

@media (max-width: 760px) {
  .topbar {
    align-items: stretch;
    flex-direction: column;
  }

  .topbar-actions {
    justify-content: space-between;
  }

  .home-actions {
    grid-template-columns: 1fr;
  }

  .recommendation-grid,
  .skeleton-grid {
    grid-template-columns: 1fr;
  }

  .stock-card {
    padding: var(--space-4);
  }

  .card-metrics {
    grid-template-columns: 1fr;
    gap: var(--space-2);
  }

  .metric {
    display: flex;
    justify-content: space-between;
    align-items: center;
    text-align: left;
  }

  .metric-label {
    margin-bottom: 0;
  }
}
</style>
