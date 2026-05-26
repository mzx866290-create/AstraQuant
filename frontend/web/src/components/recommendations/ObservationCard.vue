<template>
  <article
    class="stock-card"
    :class="{ 'tier-a': row.tier === 'A', 'tier-b': row.tier === 'B', 'tier-c': row.tier === 'C' }"
    role="button"
    tabindex="0"
    @click="$emit('view-detail', row)"
    @keyup.enter="$emit('view-detail', row)"
    @keyup.space.prevent="$emit('view-detail', row)"
  >
    <div class="card-header">
      <div class="card-rank">#{{ displayIndex + 1 }}</div>
      <div class="card-stock-info">
        <strong>{{ row.name }}</strong>
        <span class="card-symbol">{{ row.symbol }}</span>
        <small v-if="rowDataDate" class="card-data-date">{{ rowDataDate }}</small>
      </div>
      <div class="card-score">
        <el-tag v-if="row.tier" size="small" :type="tierTagType(row.tier)" class="tier-tag">
          {{ row.tier }}档
        </el-tag>
        <span class="score-number">{{ row.score }}</span>
        <el-tag size="small" :type="ratingTagType">
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
        {{ row.observation_bucket_label || bucketLabel }}
      </el-tag>
      <el-tag
        v-if="row.intraday_confirmation"
        size="small"
        :type="intradayTagType(row.intraday_confirmation.status)"
        effect="dark"
        class="intraday-tag"
      >
        {{ row.intraday_confirmation.label || '盘中确认' }}
      </el-tag>
      <span v-if="row.sector" class="card-sector">{{ row.sector }}</span>
    </div>

    <div class="observation-plan">
      <div class="plan-primary">
        <span>下一步</span>
        <strong>{{ observationNextAction }}</strong>
      </div>
      <div class="plan-grid">
        <span>
          <small>触发</small>
          <strong>{{ observationTrigger }}</strong>
        </span>
        <span>
          <small>失效</small>
          <strong>{{ observationInvalidation }}</strong>
        </span>
        <span>
          <small>风险</small>
          <strong>{{ observationRisk }}</strong>
        </span>
      </div>
    </div>

    <div class="retail-summary">
      <div v-if="row.intraday_confirmation" class="summary-line intraday-line" :class="row.intraday_confirmation.status">
        <span class="summary-label intraday-label">盘中</span>
        <span>{{ intradayLineText }}</span>
      </div>
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
      <div v-if="optimizerAdjustmentText" class="summary-line optimizer-line">
        <span class="summary-label optimizer-label">优化</span>
        <span>{{ optimizerAdjustmentText }}</span>
      </div>
      <template v-if="!row.trigger_condition && !row.risk_warning">
        <div class="summary-line risk-line" :class="recommendationRiskHint(row).level">
          <span class="summary-label">风险提示</span>
          <span>{{ recommendationRiskHint(row).message }}</span>
        </div>
      </template>
      <div v-if="capitalFlowUnavailable" class="summary-line source-line">
        <span class="summary-label">资金流</span>
        <span>暂未覆盖，不作为买入或放弃的单独依据。</span>
      </div>
    </div>

    <div class="card-footer">
      <div class="card-warnings">
        <el-tag
          v-for="warning in warnings"
          :key="warning"
          size="small"
          type="danger"
          effect="plain"
        >
          {{ warning }}
        </el-tag>
      </div>
      <div class="card-actions">
        <el-button size="small" type="primary" link @click.stop="$emit('view-detail', row)">详情</el-button>
        <el-button
          size="small"
          type="success"
          link
          :loading="addingSymbol === row.symbol"
          :disabled="Boolean(blockedReason)"
          :title="blockedReason"
          @click.stop="$emit('add-watchlist', row)"
        >
          加入观察
        </el-button>
      </div>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { formatPct, formatPrice } from '@/utils/formatters'
import {
  ratingTag,
  recommendationActionBlockedReason,
  recommendationPlainReason,
  recommendationRiskHint,
  recommendationRowWarnings,
  riskHintTagType,
  scoreReferenceText,
  scoreTagType,
  type RecommendationItem,
  type RecommendationsResponse,
} from '@/utils/recommendations'

const props = defineProps<{
  row: RecommendationItem
  displayIndex: number
  bucketLabel: string
  meta: RecommendationsResponse | null
  addingSymbol: string | null
}>()

defineEmits<{
  'view-detail': [row: RecommendationItem]
  'add-watchlist': [row: RecommendationItem]
}>()

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

function intradayTagType(status?: string | null): 'success' | 'primary' | 'warning' | 'info' | 'danger' | undefined {
  if (status === 'actionable') return 'success'
  if (status === 'wait_pullback') return 'warning'
  if (status === 'invalidated' || status === 'quote_error') return 'danger'
  if (status === 'quote_degraded') return 'info'
  return 'info'
}

function changeClass(value?: number | string) {
  const number = Number(value)
  if (!Number.isFinite(number)) return ''
  return number >= 0 ? 'up' : 'down'
}

const ratingTagType = computed(() => {
  const type = ratingTag(props.row.rating?.level)
  return type === 'info' && !props.row.rating?.level ? scoreTagType(props.row.score) : type
})

const rowDataDate = computed(() => {
  if (!props.row.snapshot_date) return ''
  return `基于 ${props.row.snapshot_date} 收盘`
})

const observationNextAction = computed(() => {
  const confirmation = props.row.intraday_confirmation
  if (confirmation?.next_action) return confirmation.next_action
  if (confirmation?.label) return confirmation.label
  if (props.row.observation_action) return props.row.observation_action
  if (props.row.tier === 'A') return '优先观察'
  if (props.row.tier === 'B') return '等条件触发'
  return '只看不追'
})

const observationTrigger = computed(() => {
  return props.row.trigger_condition || props.row.intraday_confirmation?.reasons?.[0] || '等待量价确认'
})

const observationInvalidation = computed(() => {
  return props.row.invalidation_condition || firstFalsification() || '跌破关键支撑或信号转弱'
})

const observationRisk = computed(() => {
  return props.row.risk_warning || recommendationRiskHint(props.row).message
})

const blockedReason = computed(() => {
  return recommendationActionBlockedReason(props.row, props.meta)
})

const optimizerAdjustmentText = computed(() => {
  const reasons = props.row.optimizer_adjustments || props.row.pool_optimizer?.adjustments || []
  return reasons.slice(0, 2).join('；')
})

const capitalFlowUnavailable = computed(() => {
  const signal = props.row.capital_flow_status || props.row.capital_flow_features?.signal || props.row.capital_flow_features?.status
  return signal === 'unavailable'
})

const warnings = computed(() => {
  return recommendationRowWarnings(props.row, props.meta?.candidate_source).slice(0, 2)
})

const intradayLineText = computed(() => {
  const confirmation = props.row.intraday_confirmation
  if (!confirmation) return ''
  const quote = confirmation.quote || {}
  const price = quote.price != null ? `现价 ${formatPrice(quote.price)}` : ''
  const change = quote.change_pct != null ? `涨跌 ${formatPct(quote.change_pct)}` : ''
  const action = confirmation.next_action || ''
  return [price, change, action].filter(Boolean).join('，')
})

function firstFalsification() {
  return props.row.falsification?.find((item) => item.condition)?.condition || ''
}
</script>

<style scoped>
.stock-card {
  padding: 16px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  transition: box-shadow 0.2s, border-color 0.2s;
}

.stock-card:hover {
  border-color: #c6e2ff;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}

.stock-card:focus-visible {
  border-color: var(--el-color-primary);
  outline: 2px solid var(--el-color-primary-light-5);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.card-rank {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
}

.card-stock-info {
  flex: 1;
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 8px;
  min-width: 0;
}

.card-stock-info strong {
  font-size: 16px;
  white-space: nowrap;
}

.card-symbol {
  color: #909399;
  font-size: 13px;
  font-family: var(--font-number);
}

.card-data-date {
  color: #909399;
  font-size: 12px;
}

.card-score {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 3px;
  flex-shrink: 0;
}

.card-score small {
  display: block;
  color: #909399;
  font-size: 11px;
}

.score-number {
  font-family: var(--font-number);
  font-size: 20px;
  font-weight: 700;
  color: #303133;
}

.card-price-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.card-price {
  font-family: var(--font-number);
  font-weight: 600;
}

.card-change {
  font-family: var(--font-number);
}

.card-sector {
  margin-left: auto;
  color: #909399;
  font-size: 12px;
}

.observation-plan {
  margin: 0 0 10px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #f8fafc;
  border: 1px solid #e5e7eb;
}

.plan-primary {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 6px;
}

.plan-primary span,
.plan-grid small {
  color: #606266;
  font-size: 12px;
  white-space: nowrap;
}

.plan-primary strong {
  font-size: 14px;
  color: var(--el-color-primary);
}

.plan-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}

.plan-grid span {
  display: flex;
  flex-direction: column;
}

.plan-grid small {
  margin-bottom: 2px;
}

.plan-grid strong {
  font-size: 13px;
  font-weight: 500;
  color: #303133;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.retail-summary {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 10px;
  padding: 8px 10px;
  border-radius: 6px;
  background: #f5f5f5;
  font-size: 13px;
  line-height: 1.6;
}

.summary-line {
  display: flex;
  gap: 8px;
  align-items: baseline;
}

.summary-label {
  flex-shrink: 0;
  color: #606266;
  font-size: 12px;
  font-weight: 700;
}

.summary-label::after {
  content: '：';
}

.ai-label {
  color: #7c3aed;
}

.ai-summary-line {
  background: linear-gradient(135deg, #f5f3ff 0%, #ede9fe 100%);
  padding: 6px 8px;
  border-radius: 4px;
  margin: -2px -2px 0;
}

.intraday-line {
  background: #f0fdf4;
  padding: 4px 6px;
  border-radius: 4px;
}

.intraday-line.actionable {
  background: #f0fdf4;
  color: #15803d;
}

.intraday-line.invalidated,
.intraday-line.quote_error {
  background: #fff2f0;
  color: #cf1322;
}

.intraday-label {
  color: #0369a1;
}

.source-line {
  color: #909399;
  font-size: 12px;
}

.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.card-warnings {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.card-actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
}

.bucket-tag {
  border-color: #e5e7eb;
  color: #606266;
  font-size: 11px;
}

.up { color: #f56c6c; }
.down { color: #67c23a; }

.stock-card.tier-a {
  border-left: 3px solid #67c23a;
}

.stock-card.tier-b {
  border-left: 3px solid #409eff;
}

.stock-card.tier-c {
  border-left: 3px solid #909399;
}

.tier-tag {
  margin-right: 4px;
}

.action-tag {
  font-weight: 600;
}

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

@media (max-width: 760px) {
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
</style>
