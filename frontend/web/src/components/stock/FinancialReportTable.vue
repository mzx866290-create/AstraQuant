<template>
  <div class="financial-table">
    <div class="table-header">
      <h4>财务数据</h4>
    </div>

    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="!reports.length" class="empty">暂无财报数据，请先运行数据采集</div>

    <div v-else class="table-wrapper">
      <el-table :data="reports" size="small" stripe>
        <el-table-column prop="report_date" label="报告期" width="110">
          <template #default="{ row }">
            {{ row.report_date?.slice(0, 10) }}
          </template>
        </el-table-column>
        <el-table-column prop="report_type" label="类型" width="70" />
        <el-table-column label="营收(亿)" width="100" align="right">
          <template #default="{ row }">
            {{ fmtValue(row.revenue, 1e8) }}
          </template>
        </el-table-column>
        <el-table-column label="营收同比" width="85" align="right">
          <template #default="{ row }">
            <span :class="changeClass(row.revenue_yoy)">
              {{ fmtPct(row.revenue_yoy) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="净利润(亿)" width="100" align="right">
          <template #default="{ row }">
            {{ fmtValue(row.net_profit, 1e8) }}
          </template>
        </el-table-column>
        <el-table-column label="净利同比" width="85" align="right">
          <template #default="{ row }">
            <span :class="changeClass(row.net_profit_yoy)">
              {{ fmtPct(row.net_profit_yoy) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="毛利率" width="80" align="right">
          <template #default="{ row }">
            {{ fmtPct(row.gross_margin) }}
          </template>
        </el-table-column>
        <el-table-column label="净利率" width="80" align="right">
          <template #default="{ row }">
            {{ fmtPct(row.net_margin) }}
          </template>
        </el-table-column>
        <el-table-column label="ROE" width="80" align="right">
          <template #default="{ row }">
            {{ fmtPct(row.roe) }}
          </template>
        </el-table-column>
        <el-table-column label="EPS" width="70" align="right">
          <template #default="{ row }">
            {{ row.eps?.toFixed(2) || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="PE" width="65" align="right">
          <template #default="{ row }">
            {{ row.pe_ttm?.toFixed(1) || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="PB" width="65" align="right">
          <template #default="{ row }">
            {{ row.pb?.toFixed(2) || '-' }}
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'

const props = defineProps<{ symbol: string }>()

const reports = ref<any[]>([])
const loading = ref(false)

async function fetchFinancials() {
  loading.value = true
  try {
    const { default: api } = await import('@/api')
    const resp = await api.get(`/api/v1/financials/${props.symbol}`)
    reports.value = (resp.data.reports || []).slice(0, 8)
  } catch (e) {
    console.error('获取财报失败:', e)
    reports.value = []
  } finally {
    loading.value = false
  }
}

function fmtValue(val: number | null, divisor: number = 1): string {
  if (val == null) return '-'
  return (val / divisor).toFixed(2)
}

function fmtPct(val: number | null): string {
  if (val == null) return '-'
  return (val > 0 ? '+' : '') + val.toFixed(2) + '%'
}

function changeClass(val: number | null): string {
  if (val == null) return ''
  return val >= 0 ? 'positive' : 'negative'
}

onMounted(fetchFinancials)
</script>

<style scoped>
.financial-table { background: #fff; border-radius: 8px; padding: 16px; }
.table-header { margin-bottom: 12px; }
.table-header h4 { margin: 0; font-size: 15px; }
.table-wrapper { overflow-x: auto; }
.positive { color: #e53e3e; }
.negative { color: #38a169; }
.loading, .empty { text-align: center; color: #999; padding: 30px; font-size: 13px; }
</style>
