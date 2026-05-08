<template>
  <div class="news-feed">
    <div class="feed-header">
      <h4>实时新闻</h4>
      <div class="feed-filters">
        <el-select v-model="sentimentFilter" size="small" placeholder="情感筛选" clearable class="filter-select" @change="onFilterChange">
          <el-option label="全部" value="" />
          <el-option label="正面" value="正面" />
          <el-option label="中性" value="中性" />
          <el-option label="负面" value="负面" />
        </el-select>
        <el-button size="small" @click="refreshNews" :loading="loading">刷新</el-button>
      </div>
    </div>

    <div v-if="sentimentSummary" class="sentiment-bar">
      <span class="sent-tag positive">正面 {{ sentimentSummary.positive }}条</span>
      <span class="sent-tag neutral">中性 {{ sentimentSummary.neutral }}条</span>
      <span class="sent-tag negative">负面 {{ sentimentSummary.negative }}条</span>
      <span class="sent-tag dominant">主导: {{ sentimentSummary.dominant }}</span>
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

    <div v-else-if="newsList.length === 0" class="empty">
      <div>暂无相关新闻</div>
      <small v-if="emptyReason">{{ emptyReason }}</small>
      <el-button size="small" type="primary" :loading="crawling" @click="crawlCurrentNews">
        立即采集 {{ props.symbol }} 新闻
      </el-button>
    </div>

    <div v-else class="news-list">
      <div v-for="item in newsList" :key="item.id"
           class="news-item"
           :class="'impact-' + item.impact_level">
        <div class="news-meta">
          <span class="sentiment-dot" :class="sentimentClass(item.sentiment)"></span>
          <span class="sentiment-label" :class="sentimentClass(item.sentiment)">
            {{ item.sentiment }}
          </span>
          <span v-if="item.impact_level && item.impact_level !== '低'"
                class="impact-badge" :class="'impact-' + item.impact_level">
            {{ item.impact_level }}影响
          </span>
          <span v-if="item.event_category" class="event-category">
            {{ item.event_category }}
          </span>
          <span class="source-tag">{{ item.source }}</span>
          <span class="auth-tag">{{ item.source_authority }}</span>
          <span class="time">{{ formatTime(item.publish_time) }}</span>
        </div>
        <div class="news-title" @click="openUrl(item.url)">
          {{ item.title }}
        </div>
        <div v-if="item.summary" class="news-summary">
          {{ item.summary }}
        </div>
        <div v-if="item.keywords && item.keywords.length" class="news-keywords">
          <el-tag v-for="kw in item.keywords" :key="kw" size="small" type="info">{{ kw }}</el-tag>
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

type Sentiment = '正面' | '中性' | '负面'

interface NewsItem {
  id: number | string
  title: string
  url?: string
  summary?: string
  sentiment?: Sentiment | string
  impact_level?: string
  event_category?: string
  source?: string
  source_authority?: string
  publish_time?: string
  keywords?: string[]
}

interface SentimentSummary {
  positive: number
  neutral: number
  negative: number
  dominant: string
}

interface NewsResponse {
  news?: NewsItem[]
  sentiment_summary?: SentimentSummary
  data_quality?: Record<string, DataQualityItem> | DataQualityItem
}

interface CrawlStatusResponse {
  statuses?: {
    news?: CrawlStatus
  }
}

interface CrawlNewsResponse {
  crawl_status?: CrawlStatus
}

type NewsParams = {
  sentiment?: string
}

const props = defineProps<{ symbol: string }>()
const emit = defineEmits<{ crawlComplete: [] }>()

const newsList = ref<NewsItem[]>([])
const sentimentSummary = ref<SentimentSummary | null>(null)
const sentimentFilter = ref('')
const loading = ref(false)
const crawling = ref(false)
const crawlStatus = ref<CrawlStatus | null>(null)
const crawlError = ref('')
const dataQuality = ref<DataQualityItem | null>(null)
const emptyReason = computed(() => crawlStatusReason(crawlStatus.value))

async function fetchNews() {
  loading.value = true
  try {
    const { default: api } = await import('@/api')
    const params: NewsParams = {}
    if (sentimentFilter.value) params.sentiment = sentimentFilter.value
    const resp = await api.get<NewsResponse>(`/api/v1/news/${props.symbol}`, { params })
    newsList.value = resp.news || []
    sentimentSummary.value = resp.sentiment_summary || null
    dataQuality.value = pickDataQuality(resp.data_quality, 'news')
    await loadCrawlStatus()
  } catch (e) {
    console.error('获取新闻失败:', e)
    newsList.value = []
    dataQuality.value = null
    await loadCrawlStatus()
  } finally {
    loading.value = false
  }
}

function sentimentClass(sentiment?: string) {
  return sentiment === '正面' ? 'positive' : sentiment === '负面' ? 'negative' : 'neutral'
}

function formatTime(time?: string) {
  if (!time) return ''
  const d = new Date(time)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 3600000) return Math.floor(diff / 60000) + '分钟前'
  if (diff < 86400000) return Math.floor(diff / 3600000) + '小时前'
  return time.slice(0, 16)
}

function openUrl(url?: string) {
  safeOpen(url)
}

async function loadCrawlStatus() {
  try {
    const { crawlApi } = await import('@/api')
    const resp = await crawlApi.getCrawlStatus<CrawlStatusResponse>(props.symbol)
    crawlStatus.value = resp.statuses?.news || null
  } catch (e) {
    crawlStatus.value = null
  }
}

async function crawlCurrentNews() {
  crawling.value = true
  crawlError.value = ''
  try {
    const { crawlApi } = await import('@/api')
    const resp = await crawlApi.crawlNews<CrawlNewsResponse>(props.symbol)
    crawlStatus.value = resp.crawl_status || null
    await fetchNews()
    emit('crawlComplete')
  } catch (error) {
    crawlError.value = formatCrawlError(error as { response?: { status?: number; data?: { detail?: string } }; message?: string }, '新闻')
  } finally {
    crawling.value = false
  }
}

function onFilterChange() { fetchNews() }
function refreshNews() { fetchNews() }

onMounted(fetchNews)
</script>

<style scoped>
.news-feed { background: #fff; border-radius: 8px; padding: 16px; }
.feed-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.feed-header h4 { margin: 0; font-size: 15px; }
.feed-filters { display: flex; gap: 8px; }
.filter-select { width: 100px; }
.sentiment-bar { display: flex; gap: 10px; margin-bottom: 12px; padding: 8px 12px; background: #f8f9fa; border-radius: 6px; font-size: 12px; }
.sent-tag.positive { color: #e53e3e; }
.sent-tag.negative { color: #38a169; }
.sent-tag.neutral { color: #718096; }
.news-list { max-height: 500px; overflow-y: auto; }
.news-item { padding: 10px 0; border-bottom: 1px solid #f0f0f0; }
.news-item.impact-高 { background: #fff5f5; padding: 10px 8px; border-radius: 4px; }
.news-meta { display: flex; align-items: center; gap: 8px; font-size: 11px; color: #999; margin-bottom: 4px; flex-wrap: wrap; }
.sentiment-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.sentiment-dot.positive { background: #e53e3e; }
.sentiment-dot.negative { background: #38a169; }
.sentiment-dot.neutral { background: #a0aec0; }
.sentiment-label.positive { color: #e53e3e; font-weight: 600; }
.sentiment-label.negative { color: #38a169; font-weight: 600; }
.impact-badge { padding: 1px 6px; border-radius: 3px; font-size: 10px; font-weight: 600; }
.impact-badge.impact-高 { background: #fed7d7; color: #c53030; }
.impact-badge.impact-中 { background: #feebc8; color: #c05621; }
.event-category { padding: 1px 6px; border-radius: 3px; background: #ebf8ff; color: #3182ce; font-size: 10px; }
.source-tag { color: #718096; }
.auth-tag { padding: 0px 4px; border-radius: 2px; background: #f0fff4; color: #276749; font-size: 10px; }
.news-title { font-size: 13px; line-height: 1.5; cursor: pointer; color: #2d3748; }
.news-title:hover { color: #3182ce; }
.news-summary { font-size: 12px; color: #718096; margin-top: 4px; line-height: 1.4; }
.news-keywords { margin-top: 4px; display: flex; gap: 4px; flex-wrap: wrap; }
.loading, .empty { text-align: center; color: #999; padding: 30px; font-size: 13px; display: flex; flex-direction: column; align-items: center; gap: 10px; }
.crawl-status-bar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.crawl-status { font-size: 12px; color: #718096; line-height: 1.4; max-width: 360px; }
.crawl-status.success { color: #047857; }
.crawl-status.warning { color: #b7791f; }
.crawl-status.error { color: #c53030; }
.crawl-status.info { color: #3182ce; }
.time { margin-left: auto; }
</style>
