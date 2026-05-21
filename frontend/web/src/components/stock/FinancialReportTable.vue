<template>
  <div class="financial-table">
    <div class="table-header">
      <h4>财务数据</h4>
    </div>

    <DataQualityPanel :quality="dataQuality" />
    <div v-if="crawlStatus || crawlError" class="crawl-status-bar">
      <span v-if="crawlStatus" class="crawl-status" :class="crawlStatusLevel(crawlStatus)">
        {{ formatCrawlStatus(crawlStatus, '期') }}
      </span>
      <span v-if="crawlError" class="crawl-status error">
        {{ crawlError }}
      </span>
    </div>

    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="!reports.length" class="empty">
      <div>{{ isLoggedIn ? '暂无财报数据，请先运行数据采集' : '暂无财报数据，登录后可尝试采集补全' }}</div>
      <small v-if="emptyReason">{{ emptyReason }}</small>
      <el-button size="small" type="primary" :loading="crawling" @click="crawlCurrentFinancials">
        {{ isLoggedIn ? `立即采集 ${props.symbol} 财报` : '登录后采集财报' }}
      </el-button>
    </div>

    <div v-else class="table-wrapper">
      <el-table :data="reports" size="small" stripe empty-text="暂无财报数据">
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
import { computed, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import DataQualityPanel from '@/components/common/DataQualityPanel.vue'
import { crawlStatusLevel, crawlStatusReason, formatCrawlError, formatCrawlStatus, pickDataQuality, type CrawlStatus, type DataQualityItem } from '@/utils/dataQuality'
import { useUserStore } from '@/stores/user'

interface FinancialReport {
  report_date?: string
  report_type?: string
  revenue?: number | null
  revenue_yoy?: number | null
  net_profit?: number | null
  net_profit_yoy?: number | null
  gross_margin?: number | null
  net_margin?: number | null
  roe?: number | null
  eps?: number | null
  pe_ttm?: number | null
  pb?: number | null
}

interface FinancialsResponse {
  reports?: FinancialReport[]
  data_quality?: Record<string, DataQualityItem> | DataQualityItem
}

interface CrawlStatusResponse {
  statuses?: {
    financials?: CrawlStatus
  }
}

interface CrawlFinancialsResponse {
  crawl_status?: CrawlStatus
}


const props = defineProps<{ symbol: string }>()
const emit = defineEmits<{
  crawlComplete: []
  dataQualityChange: [quality: DataQualityItem | null, source: string]
}>()
const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const reports = ref<FinancialReport[]>([])
const loading = ref(false)
const crawling = ref(false)
const crawlStatus = ref<CrawlStatus | null>(null)
const crawlError = ref('')
const dataQuality = ref<DataQualityItem | null>(null)
const emptyReason = computed(() => crawlStatusReason(crawlStatus.value))
const isLoggedIn = computed(() => userStore.isLoggedIn)

async function fetchFinancials() {
  loading.value = true
  try {
    const { default: api } = await import('@/api')
    const resp = await api.get<FinancialsResponse>(`/api/v1/financials/${props.symbol}`)
    reports.value = (resp.reports || []).slice(0, 8)
    dataQuality.value = pickDataQuality(resp.data_quality, 'financial')
    emit('dataQualityChange', dataQuality.value, dataQuality.value?.source || '')
    await loadCrawlStatus()
  } catch (e) {
    console.error('获取财报失败:', e)
    reports.value = []
    dataQuality.value = null
    emit('dataQualityChange', null, '')
  } finally {
    loading.value = false
  }
}

async function loadCrawlStatus() {
  if (!isLoggedIn.value) {
    crawlStatus.value = null
    return
  }
  try {
    const { crawlApi } = await import('@/api')
    const resp = await crawlApi.getCrawlStatus<CrawlStatusResponse>(props.symbol)
    crawlStatus.value = resp.statuses?.financials || null
  } catch (e) {
    crawlStatus.value = null
  }
}

async function crawlCurrentFinancials() {
  if (!isLoggedIn.value) {
    crawlError.value = ''
    ElMessage.warning('请先登录后采集财报')
    router.push({ path: '/login', query: { redirect: route.fullPath } })
    return
  }
  crawling.value = true
  crawlError.value = ''
  try {
    const { crawlApi } = await import('@/api')
    const resp = await crawlApi.crawlFinancials<CrawlFinancialsResponse>(props.symbol)
    crawlStatus.value = resp.crawl_status || null
    await fetchFinancials()
    emit('crawlComplete')
  } catch (error) {
    crawlError.value = formatCrawlError(error as { response?: { status?: number; data?: { detail?: string } }; message?: string }, '财报')
  } finally {
    crawling.value = false
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
.financial-table {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  box-shadow: var(--shadow-card);
}

.table-header {
  margin-bottom: var(--space-3);
}

.table-header h4 {
  margin: 0;
  color: var(--color-text);
  font-size: 16px;
  font-weight: 800;
}

.table-wrapper {
  overflow-x: auto;
}

.table-wrapper :deep(.el-table__cell) {
  font-variant-numeric: tabular-nums;
}

.table-wrapper :deep(.el-table__cell.is-right .cell) {
  font-family: var(--font-number);
}

.loading,
.empty {
  min-height: 160px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  color: var(--color-text-muted);
  text-align: center;
  font-size: 13px;
  background: var(--color-surface-muted);
  border-radius: var(--radius-sm);
}

.crawl-status {
  max-width: 360px;
  color: var(--color-text-muted);
  font-size: 12px;
  line-height: 1.4;
}

.crawl-status-bar {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-3);
}

.crawl-status.success {
  color: #047857;
}

.crawl-status.warning {
  color: #b7791f;
}

.crawl-status.error {
  color: #c53030;
}

.crawl-status.info {
  color: #3182ce;
}
</style>
