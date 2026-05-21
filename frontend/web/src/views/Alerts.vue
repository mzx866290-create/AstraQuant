<template>
  <div class="alerts-page">
    <div class="page-header">
      <h2>价格预警</h2>
      <div class="header-actions">
        <el-button :loading="checking" @click="checkAlerts">立即检查</el-button>
        <el-button type="primary" @click="openCreateDialog()">创建预警</el-button>
      </div>
    </div>

    <el-alert
      v-if="lastCheck"
      class="check-summary"
      :type="lastCheck.triggered_count > 0 ? 'warning' : 'success'"
      show-icon
      :closable="false"
      :title="`已检查 ${lastCheck.checked_count} 条启用预警，触发 ${lastCheck.triggered_count} 条`"
    />

    <el-alert
      v-if="schedulerStatus"
      class="check-summary"
      type="info"
      show-icon
      :closable="false"
      :title="schedulerTitle"
    />

    <el-card class="watchlist-card" shadow="never">
      <template #header>
        <div class="section-header">
          <span>我的自选股</span>
          <el-button size="small" :loading="watchlistLoading" @click="loadWatchlist">刷新</el-button>
        </div>
      </template>

      <el-empty
        v-if="!watchlistLoading && !watchlistStocks.length"
        description="暂无自选股，请先添加自选股后设置预警"
      >
        <el-button type="primary" @click="$router.push('/watchlist')">去添加自选股</el-button>
      </el-empty>

      <el-table
        v-else
        :data="watchlistStocks"
        v-loading="watchlistLoading"
        empty-text="暂无自选股"
        stripe
        size="small"
        class="watchlist-table"
      >
        <el-table-column prop="symbol" label="代码" width="120" />
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column prop="market" label="市场" width="80" />
        <el-table-column prop="sector" label="行业" min-width="120">
          <template #default="{ row }">{{ row.sector || '-' }}</template>
        </el-table-column>
        <el-table-column label="预警" width="120" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small" @click="openCreateDialog(row)">设预警</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-divider />

    <el-empty v-if="!alerts.length && !loading" description="暂无预警规则" />

    <el-table v-else :data="alerts" v-loading="loading" empty-text="暂无预警规则" stripe>
      <el-table-column prop="stock_symbol" label="股票代码" width="100" />
      <el-table-column prop="stock_name" label="股票名称" width="120" />
      <el-table-column prop="alert_type" label="预警类型" width="120">
        <template #default="{ row }">
          <el-tag v-if="row.alert_type === 'price_above'" type="success">价格突破上限</el-tag>
          <el-tag v-else-if="row.alert_type === 'price_below'" type="danger">价格突破下限</el-tag>
          <el-tag v-else type="warning">涨跌幅</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="threshold" label="阈值" width="100">
        <template #default="{ row }">
          {{ row.alert_type === 'change_pct' ? `${row.threshold}%` : row.threshold }}
        </template>
      </el-table-column>
      <el-table-column label="检查结果" min-width="220">
        <template #default="{ row }">
          <div v-if="checkResult(row.id)" class="check-result" :class="checkResult(row.id)?.status">
            <strong>{{ checkResult(row.id)?.status === 'triggered' ? '已触发' : checkResult(row.id)?.status === 'error' ? '异常' : '观察中' }}</strong>
            <span>{{ checkResult(row.id)?.message }}</span>
          </div>
          <span v-else class="muted">尚未检查</span>
        </template>
      </el-table-column>
      <el-table-column prop="is_active" label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'">
            {{ row.is_active ? '启用' : '禁用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="triggered_at" label="触发时间" width="160">
        <template #default="{ row }">
          {{ row.triggered_at ? formatTime(row.triggered_at) : '-' }}
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" width="160">
        <template #default="{ row }">
          {{ formatTime(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150">
        <template #default="{ row }">
          <el-button size="small" @click="toggleAlert(row)" :disabled="!!row.triggered_at">
            {{ row.is_active ? '禁用' : '启用' }}
          </el-button>
          <el-button size="small" type="danger" @click="deleteAlert(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="showCreateDialog" title="创建价格预警" width="500px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="股票" prop="stock_id">
          <el-select
            v-model="form.stock_id"
            filterable
            placeholder="从我的自选股选择"
            :disabled="!watchlistStocks.length"
          >
            <el-option
              v-for="s in watchlistStocks"
              :key="s.stock_id"
              :label="`${s.symbol} - ${s.name}`"
              :value="s.stock_id"
            />
          </el-select>
          <div v-if="!watchlistStocks.length" class="form-tip">
            暂无自选股，请先添加自选股后创建预警。
          </div>
        </el-form-item>
        <el-form-item label="预警类型" prop="alert_type">
          <el-select v-model="form.alert_type" placeholder="选择预警类型">
            <el-option value="price_above" label="价格突破上限" />
            <el-option value="price_below" label="价格突破下限" />
            <el-option value="change_pct" label="涨跌幅超限" />
          </el-select>
        </el-form-item>
        <el-form-item label="阈值" prop="threshold">
          <el-input-number v-model="form.threshold" :precision="2" :step="0.01" />
          <span class="threshold-hint">
            {{ form.alert_type === 'change_pct' ? '% (涨跌幅)' : '元 (价格)' }}
          </span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="createAlert" :loading="submitting">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, computed } from 'vue'
import { alertApi, watchlistApi } from '@/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useUserStore } from '@/stores/user'

type AlertType = 'price_above' | 'price_below' | 'change_pct'

type AlertCheckStatus = 'triggered' | 'error' | 'ok' | string

interface PriceAlert {
  id: number
  stock_symbol?: string
  stock_name?: string
  alert_type: AlertType
  threshold: number
  is_active: boolean
  triggered_at?: string | null
  created_at: string
}

interface WatchlistStock {
  stock_id: number
  symbol: string
  name?: string
  market?: string
  sector?: string
}

interface WatchlistGroup {
  items?: WatchlistStock[]
}

interface CheckResult {
  alert_id: number
  status: AlertCheckStatus
  message?: string
}

interface AlertCheckSummary {
  checked_count: number
  triggered_count: number
  items?: CheckResult[]
}

interface SchedulerStatus {
  running?: boolean
  enabled?: boolean
  interval_seconds?: number
  last_result?: AlertCheckSummary
}

interface ApiErrorLike {
  response?: {
    data?: {
      detail?: string
    }
  }
}

const alerts = ref<PriceAlert[]>([])
const loading = ref(false)
const showCreateDialog = ref(false)
const submitting = ref(false)
const checking = ref(false)
const watchlistLoading = ref(false)
const watchlistStocks = ref<WatchlistStock[]>([])
const formRef = ref<FormInstance>()
const lastCheck = ref<AlertCheckSummary | null>(null)
const checkResultMap = ref<Record<number, CheckResult>>({})
const schedulerStatus = ref<SchedulerStatus | null>(null)
const userStore = useUserStore()
const canViewSchedulerStatus = computed(() => userStore.isAdmin)

const form = reactive({
  stock_id: null as number | null,
  alert_type: 'price_above' as AlertType,
  threshold: 0,
})

const rules: FormRules = {
  stock_id: [{ required: true, message: '请选择股票', trigger: 'change' }],
  alert_type: [{ required: true, message: '请选择预警类型', trigger: 'change' }],
  threshold: [{ required: true, message: '请输入阈值', trigger: 'blur' }],
}

async function loadAlerts() {
  loading.value = true
  try {
    alerts.value = await alertApi.getAlerts<PriceAlert[]>()
  } catch {
    ElMessage.error('获取预警列表失败')
  } finally {
    loading.value = false
  }
}

async function loadSchedulerStatus() {
  if (!canViewSchedulerStatus.value) {
    schedulerStatus.value = null
    return
  }
  try {
    schedulerStatus.value = await alertApi.getSchedulerStatus<SchedulerStatus>()
  } catch {
    schedulerStatus.value = null
  }
}

function checkResult(id: number) {
  return checkResultMap.value[id]
}

async function loadWatchlist() {
  watchlistLoading.value = true
  try {
    const res = await watchlistApi.getWatchlists<WatchlistGroup[] | { data?: WatchlistGroup[] }>()
    const groups = Array.isArray(res) ? res : (res.data || [])
    const seen = new Set<number>()
    const rows: WatchlistStock[] = []
    for (const group of groups) {
      for (const item of group.items || []) {
        if (!item.stock_id || seen.has(item.stock_id)) continue
        seen.add(item.stock_id)
        rows.push(item)
      }
    }
    watchlistStocks.value = rows
  } catch {
    watchlistStocks.value = []
    ElMessage.error('加载自选股失败')
  } finally {
    watchlistLoading.value = false
  }
}

function openCreateDialog(stock?: WatchlistStock) {
  if (!watchlistStocks.value.length) {
    ElMessage.warning('请先添加自选股后再创建预警')
  }
  form.stock_id = stock?.stock_id || null
  form.alert_type = 'price_above'
  form.threshold = 0
  showCreateDialog.value = true
}

async function createAlert() {
  if (!formRef.value) return
  await formRef.value.validate()
  submitting.value = true
  try {
    await alertApi.createAlert({
      stock_id: form.stock_id,
      alert_type: form.alert_type,
      threshold: form.threshold,
    })
    ElMessage.success('预警创建成功')
    showCreateDialog.value = false
    form.stock_id = null
    form.alert_type = 'price_above'
    form.threshold = 0
    await loadAlerts()
  } catch (e) {
    const msg = (e as ApiErrorLike)?.response?.data?.detail || '创建失败'
    ElMessage.error(msg)
  } finally {
    submitting.value = false
  }
}

async function checkAlerts() {
  checking.value = true
  try {
    const data = await alertApi.checkAlerts<AlertCheckSummary>()
    lastCheck.value = data
    checkResultMap.value = Object.fromEntries((data.items || []).map((item) => [item.alert_id, item]))
    if (data.triggered_count > 0) {
      ElMessage.warning(`触发 ${data.triggered_count} 条预警`)
    } else {
      ElMessage.success('暂无触发的预警')
    }
    await loadAlerts()
    await loadSchedulerStatus()
  } catch (e) {
    ElMessage.error((e as ApiErrorLike)?.response?.data?.detail || '检查预警失败')
  } finally {
    checking.value = false
  }
}

async function toggleAlert(alert: PriceAlert) {
  try {
    await alertApi.toggleAlert(alert.id)
    ElMessage.success(`预警已${alert.is_active ? '禁用' : '启用'}`)
    await loadAlerts()
  } catch {
    ElMessage.error('操作失败')
  }
}

async function deleteAlert(id: number) {
  try {
    await ElMessageBox.confirm('确定删除这条预警吗？', '提示', { type: 'warning' })
    await alertApi.deleteAlert(id)
    ElMessage.success('删除成功')
    await loadAlerts()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

function formatTime(time: string) {
  if (!time) return '-'
  return new Date(time).toLocaleString('zh-CN')
}

const schedulerTitle = computed(() => {
  if (!schedulerStatus.value) return ''
  const status = schedulerStatus.value
  const state = status.running ? '自动检查运行中' : status.enabled ? '自动检查未运行' : '自动检查已关闭'
  const interval = status.interval_seconds ? `，周期 ${status.interval_seconds} 秒` : ''
  const last = status.last_result
  const lastText = last ? `，上次检查 ${last.checked_count} 条，触发 ${last.triggered_count} 条` : ''
  return `${state}${interval}${lastText}`
})

onMounted(() => {
  loadWatchlist()
  loadAlerts()
  loadSchedulerStatus()
})
</script>

<style scoped>
.alerts-page {
  max-width: 1200px;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.page-header h2 {
  margin: 0;
}
.threshold-hint {
  margin-left: 8px;
  color: #909399;
}
.header-actions {
  display: flex;
  gap: 10px;
}
.watchlist-card {
  margin-bottom: 16px;
}
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.section-header span {
  font-weight: 700;
}
.watchlist-table {
  width: 100%;
}
.form-tip {
  margin-top: 6px;
  color: #909399;
  font-size: 12px;
  line-height: 1.5;
}
.check-summary {
  margin-bottom: 14px;
}
.check-result {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
}
.check-result strong {
  color: #606266;
}
.check-result.triggered strong {
  color: #d97706;
}
.check-result.error strong {
  color: #dc2626;
}
.muted {
  color: #909399;
}

@media (max-width: 760px) {
  .page-header,
  .section-header {
    align-items: stretch;
    flex-direction: column;
  }

  .header-actions {
    justify-content: space-between;
    flex-wrap: wrap;
  }

  .header-actions .el-button {
    flex: 1 1 140px;
    min-width: 0;
  }
}
</style>
