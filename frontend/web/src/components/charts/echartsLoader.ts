import * as echarts from 'echarts/core'
import { BarChart, CandlestickChart, LineChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

let kLineRegistered = false
let moneyFlowRegistered = false

export function loadKLineECharts() {
  if (!kLineRegistered) {
    echarts.use([
      CandlestickChart,
      BarChart,
      LineChart,
      CanvasRenderer,
      GridComponent,
      TooltipComponent,
      DataZoomComponent,
      LegendComponent,
      MarkLineComponent,
    ])
    kLineRegistered = true
  }
  return echarts
}

export function loadMoneyFlowECharts() {
  if (!moneyFlowRegistered) {
    echarts.use([
      BarChart,
      GridComponent,
      TooltipComponent,
      CanvasRenderer,
    ])
    moneyFlowRegistered = true
  }
  return echarts
}
