<template>
  <div class="timeshare-chart">
    <div class="chart-header">
      <span class="title">分时图</span>
      <span v-if="quote.price" :class="priceClass" class="current-price">
        {{ formatPrice(quote.price) }}
      </span>
      <span v-if="quote.change_pct" :class="priceClass" class="change-pct">
        {{ formatPct(quote.change_pct) }}
      </span>
    </div>
    <div class="empty">分时数据暂未接入</div>
    <div class="price-info" v-if="quote.price">
      <span>今开: {{ formatPrice(quote.open) }}</span>
      <span>最高: {{ formatPrice(quote.high) }}</span>
      <span>最低: {{ formatPrice(quote.low) }}</span>
      <span>数据源: {{ quote.source || '-' }}</span>
    </div>
    <DataQualityPanel :quality="quote.data_quality || null" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { stockApi } from '@/api'
import DataQualityPanel from '@/components/common/DataQualityPanel.vue'
import type { DataQualityItem } from '@/utils/dataQuality'
import { formatPct, formatPrice } from '@/utils/formatters'

const props = defineProps<{ symbol: string }>()

interface Quote {
  price?: number
  change_pct?: number
  open?: number
  high?: number
  low?: number
  source?: string
  data_quality?: DataQualityItem
}

const quote = ref<Quote>({})

const priceClass = computed(() => {
  const v = Number(quote.value.change_pct)
  if (!Number.isFinite(v)) return ''
  return v > 0 ? 'price-up' : v < 0 ? 'price-down' : ''
})

async function loadQuote() {
  try {
    quote.value = await stockApi.getQuote(props.symbol)
  } catch {
    quote.value = {}
  }
}

onMounted(loadQuote)
watch(() => props.symbol, loadQuote)
</script>

<style scoped>
.timeshare-chart {
  background: var(--color-surface);
}

.chart-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.title {
  color: var(--color-text);
  font-size: 16px;
  font-weight: 700;
}

.current-price {
  font-family: var(--font-number);
  font-size: 24px;
  font-weight: 800;
}

.change-pct {
  font-family: var(--font-number);
  font-size: 14px;
  font-weight: 700;
}

.empty {
  height: 320px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-muted);
  font-size: 13px;
  background: linear-gradient(180deg, #fff 0%, var(--color-surface-muted) 100%);
}

.price-info {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: var(--space-3);
  padding-top: var(--space-3);
  color: var(--color-text-muted);
  font-family: var(--font-number);
  font-size: 12px;
  border-top: 1px solid var(--color-border);
}
</style>
