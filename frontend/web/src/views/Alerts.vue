<template>
  <div class="alerts-page">
    <div class="page-header">
      <h2>价格预警</h2>
      <el-button type="primary" @click="showCreateDialog = true">创建预警</el-button>
    </div>

    <el-empty v-if="!alerts.length && !loading" description="暂无预警规则" />

    <el-table v-else :data="alerts" v-loading="loading" stripe>
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
            placeholder="搜索股票"
            :filter-method="searchStocks"
            @focus="loadStocks"
            :loading="stockLoading"
          >
            <el-option
              v-for="s in stocks"
              :key="s.id"
              :label="`${s.symbol} - ${s.name}`"
              :value="s.id"
            />
          </el-select>
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
import { ref, reactive, onMounted } from 'vue'
import { alertApi, stockApi } from '@/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

const alerts = ref<any[]>([])
const loading = ref(false)
const showCreateDialog = ref(false)
const submitting = ref(false)
const stockLoading = ref(false)
const stocks = ref<any[]>([])
const formRef = ref<FormInstance>()

const form = reactive({
  stock_id: null as number | null,
  alert_type: 'price_above',
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
    alerts.value = await alertApi.getAlerts()
  } catch (e: any) {
    ElMessage.error('获取预警列表失败')
  } finally {
    loading.value = false
  }
}

async function loadStocks() {
  if (stocks.value.length) return
  stockLoading.value = true
  try {
    const data = await stockApi.getStocks()
    stocks.value = data.slice(0, 100)
  } catch {
    stocks.value = []
  } finally {
    stockLoading.value = false
  }
}

async function searchStocks(query: string) {
  if (!query) {
    loadStocks()
    return
  }
  stockLoading.value = true
  try {
    stocks.value = await stockApi.searchStocks(query)
  } catch {
    stocks.value = []
  } finally {
    stockLoading.value = false
  }
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
  } catch (e: any) {
    const msg = e?.response?.data?.detail || '创建失败'
    ElMessage.error(msg)
  } finally {
    submitting.value = false
  }
}

async function toggleAlert(alert: any) {
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
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

function formatTime(time: string) {
  if (!time) return '-'
  return new Date(time).toLocaleString('zh-CN')
}

onMounted(loadAlerts)
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
</style>