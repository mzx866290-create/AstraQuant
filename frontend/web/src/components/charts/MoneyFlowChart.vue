<template>
  <div class="money-flow">
    <div class="money-flow-header">
      <h4>资金流向</h4>
      <button class="refresh-btn" type="button" @click="loadData">刷新</button>
    </div>
    <div v-if="error" class="empty">{{ error }}</div>
    <div v-else ref="chartRef" class="flow-chart" />
    <div v-if="latestDate && !error" class="meta">数据日期：{{ latestDate }}</div>
    <DataQualityPanel :quality="flowQuality" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, shallowRef, watch, nextTick } from 'vue'
import type { ECharts } from 'echarts/core'
import { stockApi } from '@/api'
import { CHART_COLORS, axisTooltip, createResizeObserver } from '@/utils/charts'
import DataQualityPanel from '@/components/common/DataQualityPanel.vue'
import type { DataQualityItem } from '@/utils/dataQuality'

interface MoneyFlowItem {
  date?: string
  main_inflow?: number | null
  super_inflow?: number | null
  big_inflow?: number | null
  mid_inflow?: number | null
  small_inflow?: number | null
}

interface MoneyFlowResponse {
  data?: MoneyFlowItem[]
  data_quality?: DataQualityItem
}

interface BarLabelParams {
  value: number | null
}

async function loadECharts() {
  const { loadMoneyFlowECharts } = await import('./echartsLoader')
  return loadMoneyFlowECharts()
}

const props = defineProps<{ symbol: string }>()
const chartRef = ref<HTMLElement>()
const chart = shallowRef<ECharts>()
const error = ref('')
const latestDate = ref('')
const flowQuality = ref<DataQualityItem | null>(null)
const resizeObserver = createResizeObserver(() => chart.value)

function latestFlow(data: MoneyFlowItem[]) {
  return [...data].reverse().find(item => item && (
    item.main_inflow != null ||
    item.super_inflow != null ||
    item.big_inflow != null ||
    item.mid_inflow != null ||
    item.small_inflow != null
  ))
}

function moneyFlowEmptyMessage(quality: DataQualityItem | null) {
  if (!quality) return '暂无资金流向数据'
  const warnings = [
    quality.warning,
    ...(Array.isArray(quality.warnings) ? quality.warnings : []),
  ]
  if (quality.status === 'unavailable' && quality.freshness !== 'empty' && !warnings.includes('money_flow_empty')) {
    return '资金流数据源暂不可用'
  }
  return '暂无资金流向数据'
}

async function loadData() {
  error.value = ''
  latestDate.value = ''
  flowQuality.value = null
  try {
    const resp = await stockApi.getMoneyFlow<MoneyFlowResponse>(props.symbol)
    flowQuality.value = resp.data_quality || null
    const item = latestFlow(resp.data || [])
    if (!item) {
      error.value = moneyFlowEmptyMessage(flowQuality.value)
      chart.value?.dispose()
      chart.value = undefined
      return
    }
    latestDate.value = item.date || ''
    await nextTick()
    await renderChart(item)
  } catch {
    error.value = '资金流向数据暂不可用'
    chart.value?.dispose()
    chart.value = undefined
  }
}

async function renderChart(item: MoneyFlowItem) {
  if (!chartRef.value) return
  if (!chart.value) {
    const echarts = await loadECharts()
    if (!chartRef.value) return
    const nextChart = echarts.init(chartRef.value)
    chart.value = nextChart
    resizeObserver.observe(chartRef.value)
  }
  const currentChart = chart.value
  if (!currentChart) return
  currentChart.setOption({
    tooltip: axisTooltip,
    grid: { left: '10%', right: '5%', top: 28, bottom: 28 },
    xAxis: { type: 'category', data: ['主力净流入', '超大单', '大单', '中单', '小单'], axisLabel: { color: '#5f6b7a' } },
    yAxis: { type: 'value', axisLabel: { color: '#8a96a8' }, splitLine: { lineStyle: { color: '#e5eaf3' } } },
    series: [{
      type: 'bar',
      data: [
        item.main_inflow,
        item.super_inflow,
        item.big_inflow,
        item.mid_inflow,
        item.small_inflow,
      ].map(value => ({
        value: value == null ? null : value,
        itemStyle: { color: value == null ? '#cbd5e1' : value >= 0 ? CHART_COLORS.up : CHART_COLORS.down },
      })),
      label: {
        show: true,
        position: 'top',
        formatter: (p: BarLabelParams) => p.value == null ? '暂无' : (p.value / 100000000).toFixed(2) + '亿',
      },
    }],
    color: [CHART_COLORS.up, CHART_COLORS.down],
  })
}

onMounted(loadData)
onUnmounted(() => {
  resizeObserver.disconnect()
  chart.value?.dispose()
  chart.value = undefined
})
watch(() => props.symbol, loadData)
</script>

<style scoped>
.empty {
  height: 240px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-muted);
  font-size: 13px;
  background: var(--color-surface-muted);
  border-radius: var(--radius-sm);
}

.flow-chart {
  height: 260px;
}

.money-flow-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--space-4);
}

.money-flow-header h4 {
  margin: 0;
  color: var(--color-text);
  font-size: 16px;
  font-weight: 700;
}

.refresh-btn {
  border: 1px solid var(--color-border-strong);
  background: var(--color-surface);
  color: var(--color-text-secondary);
  border-radius: 999px;
  padding: 5px 12px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
}

.refresh-btn:hover {
  color: var(--color-primary);
  border-color: var(--color-primary);
  background: var(--color-primary-soft);
}

.meta {
  margin-top: var(--space-2);
  color: var(--color-text-muted);
  font-size: 12px;
  text-align: right;
}
</style>
