<template>
  <div class="money-flow">
    <h4>资金流向</h4>
    <div ref="chartRef" style="height: 200px" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, shallowRef } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ symbol: string }>()
const chartRef = ref<HTMLElement>()
const chart = shallowRef<echarts.ECharts>()

onMounted(() => {
  if (!chartRef.value) return
  chart.value = echarts.init(chartRef.value)
  // 模拟数据 - 后续从API获取
  chart.value.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: '10%', right: '5%', top: 20, bottom: 20 },
    xAxis: { type: 'category', data: ['主力净流入', '超大单', '大单', '中单', '小单'] },
    yAxis: { type: 'value' },
    series: [{
      type: 'bar',
      data: [
        { value: 125000000, itemStyle: { color: '#ef5350' } },
        { value: 86000000, itemStyle: { color: '#ef5350' } },
        { value: 39000000, itemStyle: { color: '#ff7043' } },
        { value: -42000000, itemStyle: { color: '#26a69a' } },
        { value: -83000000, itemStyle: { color: '#26a69a' } },
      ],
      label: {
        show: true,
        position: 'top',
        formatter: (p: any) => (p.value / 100000000).toFixed(2) + '亿',
      },
    }],
    color: ['#ef5350', '#ff7043', '#26a69a'],
  })
})
</script>
