<template>
  <div class="kline-chart">
    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="period-group">
        <el-radio-group v-model="currentPeriod" size="small" @change="onPeriodChange">
          <el-radio-button value="1m">1分</el-radio-button>
          <el-radio-button value="5m">5分</el-radio-button>
          <el-radio-button value="15m">15分</el-radio-button>
          <el-radio-button value="30m">30分</el-radio-button>
          <el-radio-button value="60m">60分</el-radio-button>
          <el-radio-button value="1d">日K</el-radio-button>
          <el-radio-button value="1w">周K</el-radio-button>
          <el-radio-button value="1M">月K</el-radio-button>
        </el-radio-group>
      </div>
      <div class="indicator-group">
        <el-checkbox-group v-model="activeIndicators" size="small" @change="onIndicatorsChange">
          <el-checkbox-button value="ma5" label="MA5" />
          <el-checkbox-button value="ma10" label="MA10" />
          <el-checkbox-button value="ma20" label="MA20" />
          <el-checkbox-button value="ma60" label="MA60" />
          <el-checkbox-button value="macd" label="MACD" />
          <el-checkbox-button value="boll" label="BOLL" />
        </el-checkbox-group>
      </div>
      <div class="adjust-group">
        <el-radio-group v-model="adjustFlag" size="small" @change="onAdjustChange">
          <el-radio-button value="0">不复权</el-radio-button>
          <el-radio-button value="1">前复权</el-radio-button>
          <el-radio-button value="2">后复权</el-radio-button>
        </el-radio-group>
      </div>
    </div>

    <DataQualityPanel :quality="dataQuality" />
    <el-alert
      v-if="chartMessage"
      class="chart-warning"
      type="warning"
      show-icon
      :closable="false"
      :title="chartMessage"
    />

    <!-- 图表容器 -->
    <div ref="chartRef" class="chart-area" />
    <div v-if="!hasChartData" class="empty-chart">暂无可展示的真实K线数据</div>

    <!-- 数据来源 -->
    <div class="chart-footer">
      <span class="data-source">数据来源: {{ dataSource || '等待加载...' }}</span>
      <span class="disclaimer">仅供参考，不构成投资建议</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, shallowRef } from 'vue'
import type { SeriesOption } from 'echarts'
import type { ECharts, EChartsCoreOption } from 'echarts/core'
import { useStockData, type KLineItem } from '@/composables/useStockData'
import { CHART_COLORS, axisTooltip, calculateMovingAverage, createLimitLine, createResizeObserver } from '@/utils/charts'
import DataQualityPanel from '@/components/common/DataQualityPanel.vue'
import type { DataQualityItem } from '@/utils/dataQuality'

async function loadECharts() {
  const { loadKLineECharts } = await import('./echartsLoader')
  return loadKLineECharts()
}

interface VolumeParams {
  dataIndex: number
}

type RadioValue = string | number | boolean | undefined

const props = defineProps<{ symbol: string }>()

const chartRef = ref<HTMLElement>()
const chart = shallowRef<ECharts | null>(null)
const currentPeriod = ref('1d')
const adjustFlag = ref('1')
const activeIndicators = ref<string[]>(['ma5', 'ma20'])
const dataSource = ref('')
const dataQuality = ref<DataQualityItem | null>(null)
const chartMessage = ref('')
const hasChartData = ref(false)

const { fetchKLine } = useStockData()

async function loadData() {
  if (!chart.value) return
  const res = await fetchKLine(props.symbol, currentPeriod.value, activeIndicators.value)
  dataSource.value = res.source
  dataQuality.value = res.data_quality
  chartMessage.value = res.data_quality?.is_fallback
    ? '当前K线为降级或模拟数据，请不要作为真实市场走势使用'
    : ''
  renderChart(res.data, res.indicators)
}

function renderChart(data: KLineItem[], _indicators: Record<string, number[]>) {
  if (!chart.value) return
  hasChartData.value = data.length > 0
  if (data.length === 0) {
    chart.value.clear()
    return
  }

  const dates = data.map(d => d.date)
  const ohlc = data.map(d => [d.open, d.close, d.low, d.high])
  const volumes = data.map(d => d.volume)
  const upLimit = data.map(d => d.close * 1.1)
  const downLimit = data.map(d => d.close * 0.9)

  // 生成系列
  const series: SeriesOption[] = [
    {
      name: 'K线',
      type: 'candlestick',
      data: ohlc,
      xAxisIndex: 0,
      yAxisIndex: 0,
      itemStyle: {
        color: CHART_COLORS.up,
        color0: CHART_COLORS.down,
        borderColor: CHART_COLORS.up,
        borderColor0: CHART_COLORS.down,
      },
    },
    {
      name: '成交量',
      type: 'bar',
      data: volumes,
      xAxisIndex: 1,
      yAxisIndex: 1,
      itemStyle: {
        color: (params: VolumeParams) => {
          const d = data[params.dataIndex]
          return d && d.close >= d.open ? CHART_COLORS.up : CHART_COLORS.down
        },
      },
    },
    createLimitLine('涨停价', upLimit, CHART_COLORS.up),
    createLimitLine('跌停价', downLimit, CHART_COLORS.down),
  ]

  activeIndicators.value.forEach((ind, idx) => {
    const period = parseInt(ind.replace('ma', ''))
    if (!isNaN(period)) {
      series.push({
        name: `MA${period}`,
        type: 'line',
        data: calculateMovingAverage(data, period),
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'none',
        lineStyle: { width: 1, color: CHART_COLORS.ma[idx % CHART_COLORS.ma.length] },
      })
    }
  })

  const option: EChartsCoreOption = {
    animation: false,
    color: CHART_COLORS.palette,
    tooltip: {
      ...axisTooltip,
      axisPointer: { type: 'cross' },
    },
    legend: {
      data: ['K线', '成交量', ...activeIndicators.value.map(i => i.toUpperCase())],
      top: 0,
    },
    grid: [
      { left: '6%', right: '3%', top: '12%', height: '55%' },
      { left: '6%', right: '3%', top: '72%', height: '20%' },
    ],
    xAxis: [
      {
        type: 'category',
        data: dates,
        gridIndex: 0,
        axisLine: { onZero: false },
        axisLabel: { show: true },
      },
      {
        type: 'category',
        data: dates,
        gridIndex: 1,
        axisLabel: { show: true },
      },
    ],
    yAxis: [
      { scale: true, gridIndex: 0, splitArea: { show: true } },
      { scale: true, gridIndex: 1, splitNumber: 2 },
    ],
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: [0, 1],
        start: 70,
        end: 100,
      },
      {
        type: 'slider',
        xAxisIndex: [0, 1],
        start: 70,
        end: 100,
        height: 20,
        bottom: 2,
      },
    ],
    series,
  }

  chart.value.setOption(option, true)
}

function onPeriodChange(val: RadioValue) {
  if (val === undefined) return
  currentPeriod.value = String(val)
  loadData()
}

function onIndicatorsChange() {
  loadData()
}

function onAdjustChange(val: RadioValue) {
  if (val === undefined) return
  adjustFlag.value = String(val)
  loadData()
}

const resizeObserver = createResizeObserver(() => chart.value)

onMounted(async () => {
  if (chartRef.value) {
    const echarts = await loadECharts()
    if (!chartRef.value) return
    chart.value = echarts.init(chartRef.value, undefined, { renderer: 'canvas' })
    resizeObserver.observe(chartRef.value)
    loadData()
  }
})

onUnmounted(() => {
  resizeObserver.disconnect()
  chart.value?.dispose()
})

watch(() => props.symbol, () => loadData())
</script>

<style scoped>
.kline-chart {
  display: flex;
  flex-direction: column;
  min-height: 500px;
  background: var(--color-surface);
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-3) 0 var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.period-group,
.indicator-group,
.adjust-group {
  min-width: 0;
}

.toolbar :deep(.el-radio-button__inner),
.toolbar :deep(.el-checkbox-button__inner) {
  padding: 5px 10px;
  font-size: 12px;
}

.chart-area {
  flex: 1;
  min-height: 420px;
}

.chart-warning {
  margin: var(--space-3) 0 0;
}

.empty-chart {
  height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-muted);
  font-size: 13px;
  background: var(--color-surface-muted);
  border-radius: var(--radius-sm);
}

.chart-footer {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
  padding-top: var(--space-3);
  color: var(--color-text-muted);
  font-size: 12px;
  border-top: 1px solid var(--color-border);
}

.disclaimer {
  color: var(--color-warning);
}

@media (max-width: 768px) {
  .kline-chart {
    min-height: 420px;
  }

  .chart-area {
    min-height: 330px;
  }

  .chart-footer {
    flex-direction: column;
  }
}
</style>
