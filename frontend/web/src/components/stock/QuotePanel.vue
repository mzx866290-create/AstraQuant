<template>
  <div class="quote-panel">
    <el-descriptions :column="4" border size="small">
      <el-descriptions-item label="最新价" label-class-name="label">
        <span :class="priceClass">{{ formatPrice(quote.price) }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="涨跌幅" label-class-name="label">
        <span :class="priceClass">{{ formatPct(quote.change_pct) }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="涨跌额" label-class-name="label">
        <span :class="priceClass">{{ formatPrice(quote.change) }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="换手率" label-class-name="label">
        {{ formatPct(quote.turnover_rate) }}
      </el-descriptions-item>
      <el-descriptions-item label="今开" label-class-name="label">
        {{ formatPrice(quote.open) }}
      </el-descriptions-item>
      <el-descriptions-item label="最高" label-class-name="label">
        <span class="price-up">{{ formatPrice(quote.high) }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="最低" label-class-name="label">
        <span class="price-down">{{ formatPrice(quote.low) }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="成交量" label-class-name="label">
        {{ formatVolume(quote.volume) }}
      </el-descriptions-item>
      <el-descriptions-item label="成交额" label-class-name="label">
        {{ formatVolume(quote.turnover) }}
      </el-descriptions-item>
      <el-descriptions-item label="市盈率(动)" label-class-name="label">
        {{ quote.pe_ttm ? quote.pe_ttm.toFixed(2) : '--' }}
      </el-descriptions-item>
      <el-descriptions-item label="总市值" label-class-name="label">
        {{ formatMV(quote.total_mv) }}
      </el-descriptions-item>
      <el-descriptions-item label="流通市值" label-class-name="label">
        {{ formatMV(quote.circ_mv) }}
      </el-descriptions-item>
      <el-descriptions-item label="涨停价" label-class-name="label">
        <span class="price-up">{{ formatPrice(quote.up_limit) }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="跌停价" label-class-name="label">
        <span class="price-down">{{ formatPrice(quote.down_limit) }}</span>
      </el-descriptions-item>
    </el-descriptions>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { QuoteData } from '@/composables/useStockData'

const props = withDefaults(defineProps<{
  quote: Partial<QuoteData>
}>(), {
  quote: () => ({
    price: 0, change: 0, change_pct: 0, high: 0, low: 0,
    open: 0, volume: 0, turnover: 0, turnover_rate: 0,
    pe_ttm: 0, total_mv: 0, circ_mv: 0, up_limit: 0, down_limit: 0,
  }),
})

const priceClass = computed(() => {
  const v = props.quote.change_pct || 0
  return v > 0 ? 'price-up' : v < 0 ? 'price-down' : ''
})

const formatPrice = (v?: number) => (v ?? 0).toFixed(2)
const formatPct = (v?: number) => (v ?? 0) > 0 ? `+${(v ?? 0).toFixed(2)}%` : `${(v ?? 0).toFixed(2)}%`
const formatVolume = (v?: number) => {
  if (!v) return '--'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(2) + '万'
  return v.toString()
}
const formatMV = (v?: number) => {
  if (!v) return '--'
  if (v >= 1e12) return (v / 1e12).toFixed(2) + '万亿'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  return (v / 1e4).toFixed(2) + '万'
}
</script>

<style scoped>
.quote-panel {
  margin: 8px 0;
}
:deep(.label) {
  font-weight: 600;
  width: 80px;
}
.price-up { color: #ef5350; font-weight: bold; }
.price-down { color: #26a69a; font-weight: bold; }
</style>
