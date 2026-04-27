<template>
  <div class="timeshare-chart">
    <div class="chart-header">
      <span class="title">分时图</span>
      <span v-if="quote.price" :class="priceClass" class="current-price">
        {{ quote.price.toFixed(2) }}
      </span>
      <span v-if="quote.change_pct" :class="priceClass" class="change-pct">
        {{ quote.change_pct > 0 ? '+' : '' }}{{ quote.change_pct.toFixed(2) }}%
      </span>
    </div>
    <div ref="chartRef" class="chart-area" />
    <div class="price-info" v-if="quote.price">
      <span>今开: {{ quote.open?.toFixed(2) }}</span>
      <span>最高: {{ quote.high?.toFixed(2) }}</span>
      <span>最低: {{ quote.low?.toFixed(2) }}</span>
      <span>昨收: {{ (quote.price! / (1 + quote.change_pct! / 100)).toFixed(2) }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, shallowRef } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, BarChart } from 'echarts/charts'
import {
  GridComponent, TooltipComponent, MarkLineComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, MarkLineComponent, CanvasRenderer])

const props = defineProps<{ symbol: string }>()

interface Quote {
  price?: number
  change_pct?: number
  open?: number
  high?: number
  low?: number
}

const quote = ref<Quote>({})
const chartRef = ref<HTMLElement>()
const chart = shallowRef<echarts.ECharts | null>(null)

const priceClass = computed(() => {
  const v = quote.value.change_pct || 0
  return v >= 0 ? 'price-up' : 'price-down'
})

function generateTimeLabels(): string[] {
  // A股交易时段: 9:30-11:30, 13:00-15:00
  const labels: string[] = []
  for (let h = 9; h <= 11; h++) {
    for (let m = 0; m < 60; m += 1) {
      if (h === 9 && m < 30) continue
      labels.push(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`)
    }
  }
  for (let h = 13; h <= 15; h++) {
    for (let m = 0; m < 60; m += 1) {
      if (h === 15 && m > 0) break
      labels.push(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`)
    }
  }
  return labels
}

function generateMockTimeShare() {
  const labels = generateTimeLabels()
  const basePrice = 1700
  const prevClose = 1690
  let price = basePrice
  const prices: number[] = []
  const volumes: number[] = []
  const avgLine: (number | null)[] = []
  let sum = 0

  for (let i = 0; i < labels.length; i++) {
    const volatility = (Math.random() - 0.48) * 3
    price = +(price + volatility).toFixed(2)
    prices.push(price)
    sum += price
    // 均价线每5分钟更新
    avgLine.push(i % 5 === 0 ? +(sum / (i + 1)).toFixed(2) : null)
    volumes.push(Math.floor(Math.random() * 500 + 50))
  }

  quote.value = {
    price: price,
    change_pct: +((price - prevClose) / prevClose * 100).toFixed(2),
    open: prices[0],
    high: Math.max(...prices),
    low: Math.min(...prices),
  }

  return { labels, prices, volumes, avgLine, prevClose }
}

function renderChart() {
  if (!chartRef.value) return
  chart.value = echarts.init(chartRef.value)

  const { labels, prices, volumes, avgLine, prevClose } = generateMockTimeShare()

  const option: echarts.EChartsOption = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
    },
    grid: [
      { left: '6%', right: '6%', top: '5%', height: '60%' },
      { left: '6%', right: '6%', top: '70%', height: '22%' },
    ],
    xAxis: [
      {
        type: 'category',
        data: labels,
        gridIndex: 0,
        axisLabel: {
          interval: 60,
          formatter: (v: string) => v,
        },
        splitLine: { show: true, lineStyle: { type: 'dashed', opacity: 0.3 } },
      },
      {
        type: 'category',
        data: labels,
        gridIndex: 1,
        axisLabel: { interval: 60 },
      },
    ],
    yAxis: [
      {
        type: 'value',
        gridIndex: 0,
        scale: true,
        splitNumber: 4,
        splitLine: { lineStyle: { type: 'dashed' } },
        axisLabel: {
          formatter: (v: number) => v.toFixed(0),
        },
      },
      {
        type: 'value',
        gridIndex: 1,
        splitNumber: 2,
        axisLabel: { show: false },
      },
    ],
    series: [
      {
        name: '价格',
        type: 'line',
        data: prices,
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'none',
        lineStyle: { color: '#ef5350', width: 1.5 },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(239,83,80,0.15)' },
            { offset: 1, color: 'rgba(239,83,80,0.01)' },
          ]),
        },
        markLine: {
          silent: true,
          label: { formatter: '昨收 {c}', position: 'start' },
          data: [{ yAxis: prevClose }],
          lineStyle: { color: '#999', type: 'dashed', width: 1 },
        },
      },
      {
        name: '均价',
        type: 'line',
        data: avgLine,
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'none',
        lineStyle: { color: '#ff9800', width: 1, type: 'dotted' },
        connectNulls: true,
      },
      {
        name: '成交量',
        type: 'bar',
        data: volumes,
        xAxisIndex: 1,
        yAxisIndex: 1,
        itemStyle: {
          color: (params: any) => {
            const p = prices[params.dataIndex]
            return p >= prevClose ? '#ef5350' : '#26a69a'
          },
        },
      },
    ],
  }
  chart.value.setOption(option)
}

const resizeObserver = new ResizeObserver(() => chart.value?.resize())

onMounted(() => {
  renderChart()
  if (chartRef.value) resizeObserver.observe(chartRef.value)
})

onUnmounted(() => {
  resizeObserver.disconnect()
  chart.value?.dispose()
})
</script>

<style scoped>
.timeshare-chart {
  background: #fff;
  border-radius: 4px;
}

.chart-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border-bottom: 1px solid #ebeef5;
}

.title {
  font-size: 14px;
  font-weight: 600;
}

.current-price {
  font-size: 20px;
  font-weight: bold;
}

.change-pct {
  font-size: 14px;
}

.price-up { color: #ef5350; }
.price-down { color: #26a69a; }

.chart-area {
  height: 320px;
}

.price-info {
  display: flex;
  justify-content: space-around;
  padding: 6px 12px;
  font-size: 12px;
  color: #909399;
  border-top: 1px solid #ebeef5;
}
</style>
