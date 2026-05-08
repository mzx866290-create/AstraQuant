import type { EChartsCoreOption } from 'echarts/core'
import type { KLineItem } from '@/composables/useStockData'

export const CHART_COLORS = {
  up: '#e23b3b',
  down: '#16a36a',
  ma: ['#ff7043', '#ab47bc', '#42a5f5', '#66bb6a'],
  palette: ['#f59e0b', '#7c3aed', '#2563eb', '#16a36a'],
}

export const axisTooltip = {
  trigger: 'axis',
  backgroundColor: 'rgba(15, 23, 42, 0.92)',
  borderWidth: 0,
  textStyle: { color: '#fff', fontFamily: 'monospace', fontSize: 12 },
} as const

export function calculateMovingAverage(data: KLineItem[], period: number) {
  return data.map((_, index) => {
    if (index < period - 1) return '-'
    let sum = 0
    for (let offset = 0; offset < period; offset += 1) sum += data[index - offset].close
    return Number((sum / period).toFixed(2))
  })
}

export function createResizeObserver(getChart: () => { resize: () => void } | null | undefined) {
  return new ResizeObserver(() => getChart()?.resize())
}

export function createLimitLine(name: string, data: number[], color: string): EChartsCoreOption {
  return {
    name,
    type: 'line',
    data,
    xAxisIndex: 0,
    yAxisIndex: 0,
    symbol: 'none',
    lineStyle: { type: 'dashed', color, width: 1 },
    z: 1,
  }
}
