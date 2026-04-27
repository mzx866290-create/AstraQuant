<template>
  <div class="watchlist-page">
    <el-card shadow="never">
      <template #header>
        <div class="card-header">
          <span>我的自选股</span>
          <el-button type="primary" size="small" @click="openAddDialog">
            + 添加股票
          </el-button>
        </div>
      </template>

      <el-empty v-if="watchlistItems.length === 0" description="暂无自选股，点击上方按钮添加" />

      <el-table v-else :data="watchlistItems" stripe style="width: 100%">
        <el-table-column prop="symbol" label="代码" width="140" />
        <el-table-column prop="name" label="名称" width="200" />
        <el-table-column prop="market" label="市场" width="80" />
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button type="primary" link @click="goDetail(row)">查看</el-button>
            <el-button type="danger" link @click="removeStock(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="showAddDialog" title="添加自选股" width="400px">
      <el-input
        v-model="addSymbol"
        placeholder="输入6位股票代码，如 600519"
        maxlength="6"
        @input="onInput"
        @keyup.enter="confirmAdd"
      />
      <div style="color:#999;font-size:12px;margin-top:6px">
        输入代码后按回车或点击「添加」
      </div>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmAdd" :disabled="addSymbol.trim().length < 6">添加</el-button>
      </template>
    </el-dialog>

    <Disclaimer />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { watchlistApi } from '@/api'
import Disclaimer from '@/components/common/Disclaimer.vue'

const router = useRouter()

const watchlistItems = ref<any[]>([])
const watchlistId = ref<number | null>(null)
const showAddDialog = ref(false)
const addSymbol = ref('')

function onInput(val: string) {
  addSymbol.value = val.replace(/[^0-9]/g, '').slice(0, 6)
}

function openAddDialog() {
  addSymbol.value = ''
  showAddDialog.value = true
}

async function loadWatchlist() {
  try {
    const res: any = await watchlistApi.getWatchlists()
    const data = Array.isArray(res) ? res : (res.data || res)
    if (Array.isArray(data) && data.length > 0) {
      watchlistId.value = data[0].id
      watchlistItems.value = data[0].items || []
    }
  } catch (e) {
    console.error('加载自选股失败:', e)
  }
}

async function confirmAdd() {
  const code = addSymbol.value.trim()
  if (code.length < 6 || !watchlistId.value) return
  try {
    await watchlistApi.addToWatchlist(watchlistId.value, undefined, code)
    showAddDialog.value = false
    addSymbol.value = ''
    await loadWatchlist()
  } catch (e: any) {
    const msg = e?.response?.data?.detail || '添加失败'
    alert(msg)
  }
}

async function removeStock(row: any) {
  if (!watchlistId.value) return
  try {
    await watchlistApi.removeFromWatchlist(watchlistId.value, row.stock_id)
    await loadWatchlist()
  } catch (e: any) {
    alert('删除失败')
  }
}

function goDetail(row: any) {
  router.push(`/stocks/${row.symbol}`)
}

onMounted(() => { loadWatchlist() })
</script>

<style scoped>
.watchlist-page {
  max-width: 1000px;
  margin: 0 auto;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
