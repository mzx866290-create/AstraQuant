import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { watchlistApi } from '@/api'
import { useUserStore } from '@/stores/user'

type WatchlistStockRow = {
  symbol: string
  name?: string
  market?: string
  sector?: string
}

type WatchlistGroup = {
  id: number
  name?: string
}

type WatchlistResponse = {
  id?: number
  data?: {
    id?: number
  }
}

type ApiValidationError = {
  msg?: string
}

export function useWatchlistActions() {
  const router = useRouter()
  const userStore = useUserStore()
  const addingSymbol = ref('')

  async function addToWatchlist(row: WatchlistStockRow) {
    if (!userStore.isLoggedIn) {
      ElMessage.warning('请先登录后再添加自选股')
      router.push({ name: 'Login', query: { redirect: '/watchlist' } })
      return
    }

    addingSymbol.value = row.symbol
    try {
      const res = await watchlistApi.getWatchlists()
      const data = Array.isArray(res) ? res : ((res as { data?: WatchlistGroup[] }).data || res)
      let watchlistId = Array.isArray(data) && data.length ? data[0].id : null
      if (!watchlistId) {
        const created = await watchlistApi.createWatchlist<WatchlistResponse>('默认自选')
        watchlistId = created.id || created.data?.id
      }
      if (!watchlistId) {
        throw new Error('自选分组创建失败，请稍后重试')
      }
      await watchlistApi.addToWatchlist(watchlistId, {
        symbol: row.symbol,
        name: row.name,
        market: row.market,
        sector: row.sector,
      })
      ElMessage.success(`${row.name || row.symbol} 已加入自选股`)
    } catch (error) {
      if (error instanceof Error && error.message === '自选分组创建失败，请稍后重试') {
        ElMessage.error(error.message)
        return
      }
      const detail = (error as { response?: { data?: { detail?: string | ApiValidationError[] } } })?.response?.data?.detail
      const message = Array.isArray(detail) ? detail.map((item) => item.msg).filter(Boolean).join('; ') : detail
      ElMessage.error(message || '添加自选股失败')
    } finally {
      addingSymbol.value = ''
    }
  }

  return {
    addingSymbol,
    addToWatchlist,
  }
}
