<template>
  <div class="recommendations-page">
    <section class="toolbar">
      <div>
        <h2>每日观察池</h2>
        <p>偏向单手成本友好、市值不过分庞大、数据风险较低的小中盘候选股。</p>
      </div>
      <div class="actions">
        <el-segmented v-model="market" :options="marketOptions" @change="loadRecommendations(false)" />
        <el-button :icon="Refresh" :loading="loading" @click="loadRecommendations(true)">刷新</el-button>
      </div>
    </section>

    <el-alert
      class="risk-alert"
      type="warning"
      show-icon
      :closable="false"
      title="不是买入建议。观察池偏向小而美和散户友好价格，仍需结合估值、仓位、风险承受能力和完整公告独立判断。"
    />

    <el-alert
      v-if="recommendationWarning"
      class="risk-alert"
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

    <el-table
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
      <span>候选 {{ meta.candidate_count || 0 }} 只</span>
      <span>有效评分 {{ meta.scored_count || 0 }} 只</span>
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

const router = useRouter()
const loading = ref(false)
const market = ref('ALL')
const items = ref<RecommendationItem[]>([])
const meta = ref<RecommendationsResponse | null>(null)
const { addingSymbol, addToWatchlist } = useWatchlistActions()

const marketOptions = [
  { label: '沪深', value: 'ALL' },
  { label: '沪市', value: 'SH' },
  { label: '深市', value: 'SZ' },
]

const candidateSourceText = computed(() => {
  if (meta.value?.candidate_source === 'fallback') return '开发兜底'
  if (meta.value?.candidate_source === 'db') return '数据库'
  return '未知'
})

const recommendationWarning = computed(() => {
  if (!meta.value) return ''
  if (meta.value.status === 'unavailable') return '每日观察池不可用：数据库候选池为空，系统没有生成候选结果。'
  const warnings = meta.value.warnings || []
  if (meta.value.candidate_source === 'fallback') {
    return '当前观察池使用开发兜底候选池，仅用于调试展示，不代表真实市场筛选结果。'
  }
  return warnings[0] || ''
})

const trustState = computed(() => recommendationTrustState(meta.value))
const emptyReason = computed(() => recommendationEmptyReason(meta.value))

async function loadRecommendations(forceRefresh = false) {
  loading.value = true
  try {
    const res = await analysisApi.getRecommendations(market.value, 10, forceRefresh, 'retail_small')
    items.value = res.recommendations || []
    meta.value = res
  } catch (error) {
    ElMessage.error((error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '每日观察池加载失败')
    items.value = []
    meta.value = null
  } finally {
    loading.value = false
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
  }
}
</style>
