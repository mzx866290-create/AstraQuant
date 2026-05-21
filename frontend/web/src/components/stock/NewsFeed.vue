<template>
  <div class="news-feed">
    <div class="feed-header">
      <div>
        <div class="section-kicker">资讯监控</div>
        <h4>实时新闻</h4>
      </div>
      <div class="feed-actions">
        <el-select
          v-model="sentimentFilter"
          size="small"
          placeholder="情感筛选"
          clearable
          class="filter-select"
          @change="onFilterChange"
        >
          <el-option label="全部" value="" />
          <el-option label="正面" value="正面" />
          <el-option label="中性" value="中性" />
          <el-option label="负面" value="负面" />
        </el-select>
        <el-button size="small" :icon="Refresh" :loading="loading" @click="refreshNews">
          刷新缓存
        </el-button>
        <el-button size="small" type="primary" :icon="isLoggedIn ? Download : Lock" :loading="crawling" @click="crawlCurrentNews">
          {{ isLoggedIn ? '采集最新新闻' : '登录后采集' }}
        </el-button>
      </div>
    </div>

    <div class="cache-meta">
      <span>缓存新闻</span>
      <strong>{{ cacheUpdatedText }}</strong>
    </div>

    <div v-if="sentimentSummary" class="signal-strip">
      <div class="signal-card dominant">
        <span>主导情绪</span>
        <strong :class="dominantSentimentClass">{{ sentimentSummary.dominant || '--' }}</strong>
      </div>
      <div class="signal-card positive">
        <span>正面</span>
        <strong>{{ sentimentSummary.positive }}</strong>
      </div>
      <div class="signal-card neutral">
        <span>中性</span>
        <strong>{{ sentimentSummary.neutral }}</strong>
      </div>
      <div class="signal-card negative">
        <span>负面</span>
        <strong>{{ sentimentSummary.negative }}</strong>
      </div>
    </div>

    <div class="quality-region">
      <DataQualityPanel :quality="dataQuality" />

      <div v-if="crawlNotice || crawlStatus || crawlError" class="crawl-status-bar">
        <span v-if="crawlNotice" class="crawl-status" :class="crawlNoticeLevel">
          {{ crawlNotice }}
        </span>
        <span v-if="crawlStatus" class="crawl-status" :class="crawlStatusLevel(crawlStatus)">
          {{ formatCrawlStatus(crawlStatus) }}
        </span>
        <span v-if="crawlError" class="crawl-status error">
          {{ crawlError }}
        </span>
      </div>
    </div>

    <div v-if="loading" class="loading-state">
      <div class="loading-line wide"></div>
      <div class="loading-line"></div>
      <div class="loading-line short"></div>
    </div>

    <div v-else-if="newsList.length === 0" class="empty">
      <div class="empty-title">暂无相关新闻</div>
      <small v-if="emptyReason">{{ emptyReason }}</small>
      <el-button size="small" type="primary" :loading="crawling" @click="crawlCurrentNews">
        {{ isLoggedIn ? '采集最新新闻' : '登录后采集新闻' }}
      </el-button>
    </div>

    <div v-else class="news-list">
      <article
        v-for="item in newsList"
        :key="item.id"
        class="news-item"
        :class="[impactClass(item.impact_level), sentimentItemClass(item.sentiment)]"
      >
        <div class="item-rail">
          <span class="rail-dot"></span>
        </div>

        <div class="item-body">
          <div class="item-topline">
            <div class="item-badges">
              <span class="sentiment-pill" :class="sentimentClass(item.sentiment)">
                {{ item.sentiment || '中性' }}
              </span>
              <span
                v-if="item.impact_level && item.impact_level !== '低'"
                class="impact-badge"
                :class="impactClass(item.impact_level)"
              >
                {{ item.impact_level }}影响
              </span>
              <span v-if="item.event_category" class="event-category">
                {{ item.event_category }}
              </span>
            </div>
            <span v-if="item.publish_time" class="time">{{ formatTime(item.publish_time) }}</span>
          </div>

          <button class="news-title" type="button" :disabled="!item.url" @click="openUrl(item.url)">
            {{ item.title }}
          </button>

          <p v-if="item.summary" class="news-summary">
            {{ item.summary }}
          </p>

          <div class="item-footer">
            <div class="source-line">
              <span v-if="item.source" class="source-tag">{{ item.source }}</span>
              <span v-if="item.source_authority" class="auth-tag">{{ item.source_authority }}</span>
            </div>
            <div v-if="displayedKeywords(item.keywords).length" class="news-keywords">
              <span v-for="kw in displayedKeywords(item.keywords)" :key="kw" class="keyword-tag">
                {{ kw }}
              </span>
            </div>
          </div>
        </div>
      </article>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { Download, Lock, Refresh } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { safeOpen } from '@/utils/safeOpen'
import DataQualityPanel from '@/components/common/DataQualityPanel.vue'
import { crawlStatusLevel, crawlStatusReason, formatCrawlError, formatCrawlStatus, formatQualityTime, pickDataQuality, type CrawlStatus, type DataQualityItem } from '@/utils/dataQuality'
import { useUserStore } from '@/stores/user'

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
  message?: string
  skipped?: boolean
}

type NewsParams = {
  sentiment?: string
  live_fallback?: boolean
}

const props = defineProps<{ symbol: string }>()
const emit = defineEmits<{
  crawlComplete: []
  dataQualityChange: [quality: DataQualityItem | null, source: string]
}>()
const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const newsList = ref<NewsItem[]>([])
const sentimentSummary = ref<SentimentSummary | null>(null)
const sentimentFilter = ref('')
const loading = ref(false)
const crawling = ref(false)
const crawlStatus = ref<CrawlStatus | null>(null)
const crawlError = ref('')
const crawlNotice = ref('')
const crawlNoticeLevel = ref('info')
const dataQuality = ref<DataQualityItem | null>(null)
const emptyReason = computed(() => crawlStatusReason(crawlStatus.value))
const isLoggedIn = computed(() => userStore.isLoggedIn)
const dominantSentimentClass = computed(() => sentimentClass(sentimentSummary.value?.dominant))
const cacheUpdatedText = computed(() => {
  const time = dataQuality.value?.updated_at || crawlStatus.value?.finished_at
  return time ? formatQualityTime(time) : '暂无更新时间'
})

async function fetchNews(options: { preserveNotice?: boolean } = {}) {
  loading.value = true
  if (!options.preserveNotice) {
    crawlNotice.value = ''
  }
  try {
    const { default: api } = await import('@/api')
    const params: NewsParams = { live_fallback: false }
    if (sentimentFilter.value) params.sentiment = sentimentFilter.value
    const resp = await api.get<NewsResponse>(`/api/v1/news/${props.symbol}`, { params })
    newsList.value = resp.news || []
    sentimentSummary.value = resp.sentiment_summary || null
    dataQuality.value = pickDataQuality(resp.data_quality, 'news')
    emit('dataQualityChange', dataQuality.value, dataQuality.value?.source || '')
    await loadCrawlStatus()
  } catch (e) {
    console.error('获取新闻失败:', e)
    newsList.value = []
    dataQuality.value = null
    emit('dataQualityChange', null, '')
    await loadCrawlStatus()
  } finally {
    loading.value = false
  }
}

function sentimentClass(sentiment?: string) {
  return sentiment === '正面' ? 'positive' : sentiment === '负面' ? 'negative' : 'neutral'
}

function sentimentItemClass(sentiment?: string) {
  return `sentiment-${sentimentClass(sentiment)}`
}

function impactClass(level?: string) {
  if (level === '高') return 'impact-high'
  if (level === '中') return 'impact-medium'
  return 'impact-low'
}

function displayedKeywords(keywords?: string[]) {
  return (keywords || []).filter(Boolean).slice(0, 4)
}

function formatTime(time?: string) {
  if (!time) return ''
  const timestamp = Date.parse(time)
  if (!Number.isFinite(timestamp)) return time.slice(0, 16)

  const diff = Date.now() - timestamp
  if (diff >= 0 && diff < 60000) return '刚刚'
  if (diff >= 0 && diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff >= 0 && diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  return time.slice(0, 16).replace('T', ' ')
}

function openUrl(url?: string) {
  safeOpen(url)
}

async function loadCrawlStatus() {
  if (!isLoggedIn.value) {
    crawlStatus.value = null
    return
  }
  try {
    const { crawlApi } = await import('@/api')
    const resp = await crawlApi.getCrawlStatus<CrawlStatusResponse>(props.symbol)
    crawlStatus.value = resp.statuses?.news || null
  } catch (e) {
    crawlStatus.value = null
  }
}

async function crawlCurrentNews() {
  if (!isLoggedIn.value) {
    crawlNotice.value = '登录后可采集最新新闻。'
    crawlNoticeLevel.value = 'info'
    crawlError.value = ''
    ElMessage.warning('请先登录后采集新闻')
    router.push({ path: '/login', query: { redirect: route.fullPath } })
    return
  }
  crawling.value = true
  crawlError.value = ''
  crawlNotice.value = ''
  try {
    const { crawlApi } = await import('@/api')
    const resp = await crawlApi.crawlNews<CrawlNewsResponse>(props.symbol)
    crawlStatus.value = resp.crawl_status || null
    crawlNotice.value = resp.message || (resp.skipped ? '近期已采集，无需重复采集' : '已采集最新新闻')
    crawlNoticeLevel.value = resp.skipped ? 'info' : 'success'
    await fetchNews({ preserveNotice: true })
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
.news-feed {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-card);
  display: flex;
  flex-direction: column;
  min-height: 100%;
  padding: var(--space-4);
}

.feed-header {
  align-items: flex-start;
  display: flex;
  gap: var(--space-4);
  justify-content: space-between;
  margin-bottom: var(--space-4);
}

.section-kicker {
  color: var(--color-text-muted);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
  margin-bottom: var(--space-1);
}

.feed-header h4 {
  color: var(--color-text);
  font-size: 17px;
  font-weight: 800;
  letter-spacing: 0;
  line-height: 1.2;
  margin: 0;
}

.feed-actions {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  justify-content: flex-end;
}

.filter-select {
  width: 120px;
}

.cache-meta {
  align-items: center;
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-text-muted);
  display: flex;
  font-size: 12px;
  gap: var(--space-2);
  justify-content: space-between;
  margin-bottom: var(--space-3);
  padding: var(--space-2) var(--space-3);
}

.cache-meta strong {
  color: var(--color-text-secondary);
  font-family: var(--font-number);
  font-size: 12px;
  font-weight: 700;
}

.signal-strip {
  display: grid;
  gap: var(--space-2);
  grid-template-columns: minmax(0, 1.4fr) repeat(3, minmax(72px, 0.8fr));
  margin-bottom: var(--space-4);
}

.signal-card {
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  min-width: 0;
  padding: var(--space-2) var(--space-3);
}

.signal-card span {
  color: var(--color-text-muted);
  display: block;
  font-size: 11px;
  line-height: 1.4;
}

.signal-card strong {
  color: var(--color-text);
  display: block;
  font-family: var(--font-number);
  font-size: 18px;
  line-height: 1.2;
  margin-top: 2px;
}

.signal-card.dominant strong {
  font-family: var(--font-sans);
  font-size: 15px;
}

.positive,
.signal-card.positive strong {
  color: var(--color-down);
}

.negative,
.signal-card.negative strong {
  color: var(--color-up);
}

.neutral,
.signal-card.neutral strong {
  color: var(--color-text-secondary);
}

.quality-region {
  border-bottom: 1px solid var(--color-border);
  margin-bottom: var(--space-1);
  padding-bottom: var(--space-3);
}

.quality-region :deep(.data-quality-panel) {
  margin-bottom: 0;
}

.crawl-status-bar {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.crawl-status {
  border-radius: 999px;
  font-size: 12px;
  line-height: 1.45;
  max-width: 100%;
  padding: 4px 8px;
}

.crawl-status.success {
  background: var(--color-success-bg);
  color: var(--color-success);
}

.crawl-status.warning {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.crawl-status.error {
  background: var(--color-danger-soft);
  color: var(--color-up);
}

.crawl-status.info {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.news-list {
  max-height: 520px;
  overflow-y: auto;
  padding-right: var(--space-1);
}

.news-item {
  display: grid;
  gap: var(--space-3);
  grid-template-columns: 14px minmax(0, 1fr);
  padding: var(--space-4) 0;
}

.news-item + .news-item {
  border-top: 1px solid var(--color-border);
}

.item-rail {
  display: flex;
  justify-content: center;
  padding-top: 8px;
  position: relative;
}

.item-rail::after {
  background: var(--color-border);
  bottom: calc(var(--space-4) * -1);
  content: "";
  position: absolute;
  top: 24px;
  width: 1px;
}

.news-item:last-child .item-rail::after {
  display: none;
}

.rail-dot {
  background: var(--color-text-muted);
  border: 3px solid var(--color-surface);
  border-radius: 50%;
  box-shadow: 0 0 0 1px var(--color-border);
  height: 10px;
  width: 10px;
  z-index: 1;
}

.sentiment-positive .rail-dot {
  background: var(--color-down);
}

.sentiment-negative .rail-dot,
.impact-high .rail-dot {
  background: var(--color-up);
}

.item-body {
  min-width: 0;
}

.item-topline {
  align-items: flex-start;
  display: flex;
  gap: var(--space-3);
  justify-content: space-between;
  margin-bottom: var(--space-2);
}

.item-badges,
.item-footer,
.source-line,
.news-keywords {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.sentiment-pill,
.impact-badge,
.event-category,
.source-tag,
.auth-tag,
.keyword-tag {
  align-items: center;
  border-radius: 999px;
  display: inline-flex;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.35;
  max-width: 100%;
  padding: 3px 8px;
}

.sentiment-pill.positive {
  background: var(--color-success-bg);
  color: var(--color-down);
}

.sentiment-pill.negative {
  background: var(--color-danger-soft);
  color: var(--color-up);
}

.sentiment-pill.neutral {
  background: var(--color-surface-muted);
  color: var(--color-text-secondary);
}

.impact-badge.impact-high {
  background: var(--color-danger-soft);
  border: 1px solid rgba(226, 59, 59, 0.18);
  color: var(--color-up);
}

.impact-badge.impact-medium {
  background: var(--color-warning-soft);
  border: 1px solid rgba(196, 122, 16, 0.2);
  color: var(--color-warning);
}

.event-category {
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.time {
  color: var(--color-text-muted);
  flex: 0 0 auto;
  font-family: var(--font-number);
  font-size: 11px;
  line-height: 1.5;
  padding-top: 2px;
}

.news-title {
  appearance: none;
  background: transparent;
  border: 0;
  color: var(--color-text);
  cursor: pointer;
  display: block;
  font: inherit;
  font-size: 15px;
  font-weight: 750;
  letter-spacing: 0;
  line-height: 1.55;
  padding: 0;
  text-align: left;
  transition: color var(--transition-fast);
  width: 100%;
}

.news-title:hover:not(:disabled) {
  color: var(--color-primary);
}

.news-title:disabled {
  cursor: default;
}

.news-summary {
  color: var(--color-text-secondary);
  display: -webkit-box;
  font-size: 13px;
  line-height: 1.65;
  margin: var(--space-2) 0 0;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}

.item-footer {
  justify-content: space-between;
  margin-top: var(--space-3);
}

.source-tag {
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  color: var(--color-text-secondary);
  font-weight: 600;
}

.auth-tag {
  background: var(--color-success-bg);
  color: var(--color-success);
}

.keyword-tag {
  background: transparent;
  border: 1px solid var(--color-border);
  color: var(--color-text-muted);
  font-weight: 600;
}

.loading-state,
.empty {
  align-items: center;
  color: var(--color-text-muted);
  display: flex;
  flex-direction: column;
  font-size: 14px;
  gap: var(--space-3);
  justify-content: center;
  min-height: 180px;
  padding: var(--space-8) var(--space-4);
  text-align: center;
}

.loading-line {
  animation: pulse 1.2s ease-in-out infinite;
  background: var(--color-surface-muted);
  border-radius: 999px;
  height: 12px;
  width: 72%;
}

.loading-line.wide {
  width: 86%;
}

.loading-line.short {
  width: 44%;
}

.empty-title {
  color: var(--color-text-secondary);
  font-weight: 700;
}

.news-list::-webkit-scrollbar {
  width: 6px;
}

.news-list::-webkit-scrollbar-track {
  background: transparent;
}

.news-list::-webkit-scrollbar-thumb {
  background: var(--color-border);
  border-radius: 3px;
}

.news-list::-webkit-scrollbar-thumb:hover {
  background: var(--color-border-strong);
}

@keyframes pulse {
  0%,
  100% {
    opacity: 0.55;
  }

  50% {
    opacity: 1;
  }
}

@media (max-width: 720px) {
  .feed-header,
  .item-topline,
  .item-footer {
    align-items: stretch;
    flex-direction: column;
  }

  .feed-actions {
    width: 100%;
  }

  .filter-select {
    flex: 1;
    width: auto;
  }

  .signal-strip {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .news-item {
    grid-template-columns: 10px minmax(0, 1fr);
  }
}
</style>
