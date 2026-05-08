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

    <el-table
      v-loading="loading"
      :data="recommendations"
      stripe
      class="observe-table"
      @row-click="goDetail"
    >
      <template #empty>
        <div class="empty-state">
          <strong>暂无今日观察数据</strong>
          <span>{{ emptyReason }}</span>
        </div>
      </template>
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
      <el-table-column label="评分" width="105">
        <template #default="{ row }">
          <div class="score-cell">
            <strong>{{ row.score }}</strong>
            <el-tag size="small" :type="ratingTag(row.rating?.level)">{{ row.rating?.text }}</el-tag>
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
      <el-table-column label="行情" width="120">
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
      <el-table-column label="观察理由" min-width="280">
        <template #default="{ row }">
          <div class="chips">
            <el-tag v-for="reason in (row.reasons || []).slice(0, 3)" :key="reason" size="small" effect="plain">
              {{ reason }}
            </el-tag>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="评分明细" min-width="230">
        <template #default="{ row }">
          <div class="breakdown-list">
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
          <div class="chips">
            <el-tag v-for="risk in (row.risk_flags || []).slice(0, 2)" :key="risk" size="small" type="warning" effect="plain">
              {{ risk }}
            </el-tag>
            <el-tag
              v-for="warning in recommendationRowWarnings(row, meta?.candidate_source).slice(0, 3)"
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
  ratingTag,
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
  if (meta.value?.candidate_source === 'fallback') return '开发兜底'
  if (meta.value?.candidate_source === 'db') return '数据库'
  return '未知'
})

const recommendationWarning = computed(() => {
  if (!meta.value) return ''
  if (meta.value.status === 'unavailable') return '今日观察池不可用：数据库候选池为空，系统没有生成候选结果。'
  const warnings = meta.value.warnings || []
  if (meta.value.candidate_source === 'fallback') {
    return '当前观察池使用开发兜底候选池，仅用于调试展示，不代表真实市场筛选结果。'
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

.observe-table {
  width: 100%;
  border: 1px solid var(--color-border);
  box-shadow: var(--shadow-card);
}

.stock-cell,
.score-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stock-cell span,
.score-cell strong {
  font-family: var(--font-number);
  font-variant-numeric: tabular-nums;
}

.stock-cell span {
  color: var(--color-text-muted);
}

.chips,
.breakdown-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
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
}
</style>
