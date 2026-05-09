<template>
  <div class="quote-panel dashboard-card">
    <DataQualityPanel :quality="quoteQuality" />
    <el-alert
      v-if="quoteQuality?.is_fallback"
      class="quote-warning"
      type="warning"
      show-icon
      :closable="false"
      title="当前行情为降级数据，可能来自K线或本地兜底，不等同于实时行情。"
    />
    <div class="quote-grid">
      <div class="quote-item primary">
        <span class="quote-label">最新价</span>
        <strong :class="priceClass" class="quote-value">{{ formatPrice(quote.price) }}</strong>
      </div>
      <div class="quote-item">
        <span class="quote-label">涨跌幅</span>
        <strong :class="priceClass" class="quote-value">{{ formatPct(quote.change_pct) }}</strong>
      </div>
      <div class="quote-item">
        <span class="quote-label">涨跌额</span>
        <strong :class="priceClass" class="quote-value">{{ formatPrice(quote.change) }}</strong>
      </div>
      <div class="quote-item">
        <span class="quote-label">换手率</span>
        <strong class="quote-value">{{ formatPct(quote.turnover_rate) }}</strong>
      </div>
      <div class="quote-item">
        <span class="quote-label">今开</span>
        <strong class="quote-value">{{ formatPrice(quote.open) }}</strong>
      </div>
      <div class="quote-item">
        <span class="quote-label">最高</span>
        <strong class="quote-value price-up">{{ formatPrice(quote.high) }}</strong>
      </div>
      <div class="quote-item">
        <span class="quote-label">最低</span>
        <strong class="quote-value price-down">{{ formatPrice(quote.low) }}</strong>
      </div>
      <div class="quote-item">
        <span class="quote-label">成交量</span>
        <strong class="quote-value">{{ formatVolume(quote.volume) }}</strong>
      </div>
      <div class="quote-item">
        <span class="quote-label">成交额</span>
        <strong class="quote-value">{{ formatVolume(quote.turnover) }}</strong>
      </div>
      <div class="quote-item">
        <span class="quote-label">市盈率(动)</span>
        <strong class="quote-value">{{ quote.pe_ttm ? quote.pe_ttm.toFixed(2) : '--' }}</strong>
      </div>
      <div class="quote-item">
        <span class="quote-label">总市值</span>
        <strong class="quote-value">{{ formatMarketValue(quote.total_mv) }}</strong>
      </div>
      <div class="quote-item">
        <span class="quote-label">流通市值</span>
        <strong class="quote-value">{{ formatMarketValue(quote.circ_mv) }}</strong>
      </div>
      <div v-if="quote.up_limit" class="quote-item limit">
        <span class="quote-label">涨停价</span>
        <strong class="quote-value price-up">{{ formatPrice(quote.up_limit) }}</strong>
      </div>
      <div v-if="quote.down_limit" class="quote-item limit">
        <span class="quote-label">跌停价</span>
        <strong class="quote-value price-down">{{ formatPrice(quote.down_limit) }}</strong>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { QuoteData } from '@/composables/useStockData'
import DataQualityPanel from '@/components/common/DataQualityPanel.vue'
import { formatMarketValue, formatPct, formatPrice, formatVolume } from '@/utils/formatters'

const props = withDefaults(defineProps<{
  quote?: Partial<QuoteData>
}>(), {
  quote: () => ({}),
})

const priceClass = computed(() => {
  const v = Number(props.quote?.change_pct)
  if (!Number.isFinite(v)) return ''
  return v > 0 ? 'price-up' : v < 0 ? 'price-down' : ''
})

const quoteQuality = computed(() => props.quote?.data_quality || null)
</script>

<style scoped>
.quote-panel {
  padding: var(--space-4);
}

.quote-warning {
  margin-bottom: var(--space-3);
}

.quote-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: var(--space-3);
}

/* Primary metric spans 2 columns on desktop */
.quote-item.primary {
  grid-column: span 2;
  grid-row: span 2;
  background: linear-gradient(135deg, #fff7f7 0%, #f8fbff 100%);
  border-color: var(--color-border);
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
}

.quote-item.primary .quote-label {
  font-size: 14px;
  margin-bottom: var(--space-3);
}

.quote-item.primary .quote-value {
  font-size: 36px;
}

@media (max-width: 1180px) {
  .quote-grid {
    grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  }

  .quote-item.primary {
    grid-column: span 2;
    grid-row: span 1;
  }

  .quote-item.primary .quote-value {
    font-size: 28px;
  }
}

@media (max-width: 720px) {
  .quote-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .quote-item.primary {
    grid-column: span 2;
    grid-row: span 1;
  }

  .quote-item.limit {
    grid-column: span 2;
  }
}

.quote-item {
  min-width: 0;
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
  border: 1px solid transparent;
}

.quote-item.primary {
  grid-column: span 2;
  background: linear-gradient(135deg, #fff7f7 0%, #f8fbff 100%);
  border-color: var(--color-border);
}

.quote-item.limit {
  background: #fff;
  border-color: var(--color-border);
}

.quote-label {
  display: block;
  margin-bottom: var(--space-2);
  color: var(--color-text-muted);
  font-size: 12px;
}

.quote-value {
  display: block;
  color: var(--color-text);
  font-family: var(--font-number);
  font-size: 15px;
  font-variant-numeric: tabular-nums;
  line-height: 1.1;
}

.quote-item.primary .quote-value {
  font-size: 28px;
  letter-spacing: -0.04em;
}

@media (max-width: 1180px) {
  .quote-grid {
    grid-template-columns: repeat(4, minmax(112px, 1fr));
  }
}

@media (max-width: 720px) {
  .quote-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .quote-item.primary {
    grid-column: span 2;
  }
}
</style>
