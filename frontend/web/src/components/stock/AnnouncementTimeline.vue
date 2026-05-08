<template>
  <div class="announcement-timeline">
    <div class="timeline-header">
      <h4>公司公告</h4>
        <el-select v-model="categoryFilter" size="small" placeholder="类型筛选" clearable class="filter-select" @change="fetchAnnouncements">
        <el-option label="全部" value="" />
        <el-option label="定期报告" value="定期报告" />
        <el-option label="业绩预告" value="业绩预告" />
        <el-option label="分红送转" value="分红送转" />
        <el-option label="股东变动" value="股东变动" />
        <el-option label="重大事项" value="重大事项" />
        <el-option label="临时公告" value="临时公告" />
      </el-select>
    </div>

    <DataQualityPanel :quality="dataQuality" />
    <div v-if="crawlStatus || crawlError" class="crawl-status-bar">
      <span v-if="crawlStatus" class="crawl-status" :class="crawlStatusLevel(crawlStatus)">
        {{ formatCrawlStatus(crawlStatus) }}
      </span>
      <span v-if="crawlError" class="crawl-status error">
        {{ crawlError }}
      </span>
    </div>

    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="items.length === 0" class="empty">
      <div>暂无公告</div>
      <small v-if="emptyReason">{{ emptyReason }}</small>
      <el-button size="small" type="primary" :loading="crawling" @click="crawlCurrentAnnouncements">
        立即采集 {{ props.symbol }} 公告
      </el-button>
    </div>

    <div v-else class="timeline-list">
      <div v-for="item in items" :key="item.id" class="timeline-item"
           :class="'cat-' + (item.category || '临时公告')">
        <div class="tl-dot" :class="categoryClass(item.category)"></div>
        <div class="tl-content">
          <div class="tl-meta">
            <span class="tl-category" :class="categoryClass(item.category)">
              {{ item.category || '临时公告' }}
            </span>
            <span class="tl-date">{{ item.announce_date?.slice(0, 10) }}</span>
          </div>
          <div class="tl-title" @click="openUrl(item.content_url)">
            {{ item.title }}
          </div>
          <div v-if="item.summary" class="tl-summary">
            {{ item.summary?.slice(0, 200) }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { safeOpen } from '@/utils/safeOpen'
import DataQualityPanel from '@/components/common/DataQualityPanel.vue'
import { crawlStatusLevel, crawlStatusReason, formatCrawlError, formatCrawlStatus, pickDataQuality, type CrawlStatus, type DataQualityItem } from '@/utils/dataQuality'

interface AnnouncementItem {
  id: number | string
  title: string
  category?: string
  announce_date?: string
  content_url?: string
  summary?: string
}

interface AnnouncementsResponse {
  announcements?: AnnouncementItem[]
  data_quality?: Record<string, DataQualityItem> | DataQualityItem
}

interface CrawlStatusResponse {
  statuses?: {
    announcements?: CrawlStatus
  }
}

interface CrawlAnnouncementsResponse {
  crawl_status?: CrawlStatus
}

interface AnnouncementParams {
  category?: string
}

const props = defineProps<{ symbol: string }>()
const emit = defineEmits<{ crawlComplete: [] }>()

const items = ref<AnnouncementItem[]>([])
const categoryFilter = ref('')
const loading = ref(false)
const crawling = ref(false)
const crawlStatus = ref<CrawlStatus | null>(null)
const crawlError = ref('')
const dataQuality = ref<DataQualityItem | null>(null)
const emptyReason = computed(() => crawlStatusReason(crawlStatus.value))

async function fetchAnnouncements() {
  loading.value = true
  try {
    const { default: api } = await import('@/api')
    const params: AnnouncementParams = {}
    if (categoryFilter.value) params.category = categoryFilter.value
    const resp = await api.get<AnnouncementsResponse>(`/api/v1/announcements/${props.symbol}`, { params })
    items.value = resp.announcements || []
    dataQuality.value = pickDataQuality(resp.data_quality, 'announcements')
    await loadCrawlStatus()
  } catch (e) {
    console.error('获取公告失败:', e)
    items.value = []
    dataQuality.value = null
  } finally {
    loading.value = false
  }
}

async function loadCrawlStatus() {
  try {
    const { crawlApi } = await import('@/api')
    const resp = await crawlApi.getCrawlStatus<CrawlStatusResponse>(props.symbol)
    crawlStatus.value = resp.statuses?.announcements || null
  } catch (e) {
    crawlStatus.value = null
  }
}

async function crawlCurrentAnnouncements() {
  crawling.value = true
  crawlError.value = ''
  try {
    const { crawlApi } = await import('@/api')
    const resp = await crawlApi.crawlAnnouncements<CrawlAnnouncementsResponse>(props.symbol)
    crawlStatus.value = resp.crawl_status || null
    await fetchAnnouncements()
    emit('crawlComplete')
  } catch (error) {
    crawlError.value = formatCrawlError(error as { response?: { status?: number; data?: { detail?: string } }; message?: string }, '公告')
  } finally {
    crawling.value = false
  }
}

function categoryClass(cat?: string) {
  const map: Record<string, string> = {
    '定期报告': 'cat-report', '业绩预告': 'cat-estimate', '分红送转': 'cat-div',
    '股东变动': 'cat-shareholder', '重大事项': 'cat-important', '临时公告': 'cat-temp',
  }
  return map[cat || '临时公告'] || 'cat-temp'
}

function openUrl(url?: string) {
  safeOpen(url)
}

onMounted(fetchAnnouncements)
</script>

<style scoped>
.announcement-timeline { background: #fff; border-radius: 8px; padding: 16px; }
.timeline-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.timeline-header h4 { margin: 0; font-size: 15px; }
.filter-select { width: 120px; }
.timeline-list { max-height: 500px; overflow-y: auto; }
.timeline-item { display: flex; gap: 12px; padding: 10px 0; border-bottom: 1px solid #f5f5f5; }
.tl-dot { width: 10px; height: 10px; border-radius: 50%; margin-top: 4px; flex-shrink: 0; }
.tl-dot.cat-report { background: #3182ce; }
.tl-dot.cat-estimate { background: #e53e3e; }
.tl-dot.cat-div { background: #38a169; }
.tl-dot.cat-shareholder { background: #d69e2e; }
.tl-dot.cat-important { background: #805ad5; }
.tl-dot.cat-temp { background: #a0aec0; }
.tl-content { flex: 1; }
.tl-meta { display: flex; gap: 10px; align-items: center; margin-bottom: 4px; }
.tl-category { font-size: 11px; padding: 1px 6px; border-radius: 3px; color: #fff; }
.tl-category.cat-report { background: #3182ce; }
.tl-category.cat-estimate { background: #e53e3e; }
.tl-category.cat-div { background: #38a169; }
.tl-category.cat-shareholder { background: #d69e2e; }
.tl-category.cat-important { background: #805ad5; }
.tl-category.cat-temp { background: #a0aec0; }
.tl-date { font-size: 12px; color: #999; }
.tl-title { font-size: 13px; color: #2d3748; cursor: pointer; line-height: 1.5; }
.tl-title:hover { color: #3182ce; }
.tl-summary { font-size: 12px; color: #718096; margin-top: 4px; line-height: 1.4; }
.loading, .empty { text-align: center; color: #999; padding: 30px; font-size: 13px; display: flex; flex-direction: column; align-items: center; gap: 10px; }
.crawl-status-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.crawl-status { font-size: 12px; color: #718096; line-height: 1.4; max-width: 320px; }
.crawl-status.success { color: #047857; }
.crawl-status.warning { color: #b7791f; }
.crawl-status.error { color: #c53030; }
.crawl-status.info { color: #3182ce; }
</style>
