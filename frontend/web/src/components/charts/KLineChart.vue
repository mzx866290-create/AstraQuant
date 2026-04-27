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

    <!-- 图表容器 -->
    <div ref="chartRef" class="chart-area" />

    <!-- 数据来源 -->
    <div class="chart-footer">
      <span class="data-source">数据来源: {{ dataSource || '等待加载...' }}</span>
      <span class="disclaimer">仅供参考，不构成投资建议</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, shallowRef } from 'vue'
import * as echarts from 'echarts/core'
import {
  CandlestickChart, BarChart, LineChart
} from 'echarts/charts'
import {
  GridComponent, TooltipComponent, DataZoomComponent,
  LegendComponent, MarkLineComponent
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useStockData, type KLineItem } from '@/composables/useStockData'

// 按需注册ECharts组件（减小bundle体积）
echarts.use([
  CandlestickChart, BarChart, LineChart, CanvasRenderer,
  GridComponent, TooltipComponent, DataZoomComponent,
  LegendComponent, MarkLineComponent,
])

const props = defineProps<{ symbol: string }>()

const chartRef = ref<HTMLElement>()
const chart = shallowRef<echarts.ECharts | null>(null)
const currentPeriod = ref('1d')
const adjustFlag = ref('1')
const activeIndicators = ref<string[]>(['ma5', 'ma20'])
const dataSource = ref('')

const { fetchKLine } = useStockData()

async function loadData() {
  if (!chart.value) return
  const res = await fetchKLine(props.symbol, currentPeriod.value, activeIndicators.value)
  dataSource.value = res.source
  renderChart(res.data, res.indicators)
}

function renderChart(data: KLineItem[], indicators: Record<string, number[]>) {
  if (!chart.value || data.length === 0) return

  const dates = data.map(d => d.date)
  const ohlc = data.map(d => [d.open, d.close, d.low, d.high])
  const volumes = data.map(d => d.volume)
  const upLimit = data.map(d => d.close * 1.1)      // 模拟涨停价
  const downLimit = data.map(d => d.close * 0.9)     // 模拟跌停价

  // 计算均线数据
  const calcMA = (period: number) => {
    return data.map((_, i) => {
      if (i < period - 1) return '-'
      let sum = 0
      for (let j = 0; j < period; j++) sum += data[i - j].close
      return +(sum / period).toFixed(2)
    })
  }

  // 生成系列
  const series: any[] = [
    {
      name: 'K线',
      type: 'candlestick',
      data: ohlc,
      xAxisIndex: 0,
      yAxisIndex: 0,
      itemStyle: {
        color: '#ef5350',        // 阳线(涨)颜色
        color0: '#26a69a',       // 阴线(跌)颜色
        borderColor: '#ef5350',
        borderColor0: '#26a69a',
      },
    },
    {
      name: '成交量',
      type: 'bar',
      data: volumes,
      xAxisIndex: 1,
      yAxisIndex: 1,
      itemStyle: {
        color: (params: any) => {
          const d = data[params.dataIndex]
          return d && d.close >= d.open ? '#ef5350' : '#26a69a'
        },
      },
    },
    {
      name: '涨停价',
      type: 'line',
      data: upLimit,
      xAxisIndex: 0,
      yAxisIndex: 0,
      symbol: 'none',
      lineStyle: { type: 'dashed', color: '#ff7043', width: 1 },
      z: 1,
    },
    {
      name: '跌停价',
      type: 'line',
      data: downLimit,
      xAxisIndex: 0,
      yAxisIndex: 0,
      symbol: 'none',
      lineStyle: { type: 'dashed', color: '#66bb6a', width: 1 },
      z: 1,
    },
  ]

  // 添加均线指标
  const colors = ['#ff7043', '#ab47bc', '#42a5f5', '#66bb6a']
  activeIndicators.value.forEach((ind, idx) => {
    const period = parseInt(ind.replace('ma', ''))
    if (!isNaN(period)) {
      series.push({
        name: `MA${period}`,
        type: 'line',
        data: calcMA(period),
        xAxisIndex: 0,
        yAxisIndex: 0,
        symbol: 'none',
        lineStyle: { width: 1, color: colors[idx % colors.length] },
      })
    }
  })

  const option: echarts.EChartsOption = {
    animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      borderWidth: 1,
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

function onPeriodChange(val: string) {
  currentPeriod.value = val
  loadData()
}

function onIndicatorsChange() {
  loadData()
}

function onAdjustChange(val: string) {
  adjustFlag.value = val
  loadData()
}

// 响应式Resize
const resizeObserver = new ResizeObserver(() => chart.value?.resize())

onMounted(() => {
  if (chartRef.value) {
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
  height: 100%;
  background: #fff;
  border-radius: 4px;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border-bottom: 1px solid #ebeef5;
}

.toolbar :deep(.el-radio-button__inner) {
  padding: 4px 10px;
  font-size: 12px;
}

.toolbar :deep(.el-checkbox-button__inner) {
  padding: 4px 10px;
  font-size: 12px;
}

.chart-area {
  flex: 1;
  min-height: 450px;
}

.chart-footer {
  display: flex;
  justify-content: space-between;
  padding: 4px 12px;
  font-size: 12px;
  color: #999;
  border-top: 1px solid #ebeef5;
}

.data-source {
  color: #909399;
}

.disclaimer {
  color: #f56c6c;
}
</style>
