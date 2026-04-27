<template>
  <div class="news-feed">
    <div class="feed-header">
      <h4>实时新闻</h4>
      <div class="feed-filters">
        <el-select v-model="sentimentFilter" size="small" placeholder="情感筛选" clearable
                   style="width: 100px" @change="onFilterChange">
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

    <div v-if="loading" class="loading">加载中...</div>

    <div v-else-if="newsList.length === 0" class="empty">
      暂无相关新闻
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
import { ref, onMounted } from 'vue'

const props = defineProps<{ symbol: string }>()

const newsList = ref<any[]>([])
const sentimentSummary = ref<any>(null)
const sentimentFilter = ref('')
const loading = ref(false)

async function fetchNews() {
  loading.value = true
  try {
    const { default: api } = await import('@/api')
    const params: any = {}
    if (sentimentFilter.value) params.sentiment = sentimentFilter.value
    const resp = await api.get(`/api/v1/news/${props.symbol}`, { params })
    newsList.value = resp.data.news || []
    sentimentSummary.value = resp.data.sentiment_summary
  } catch (e) {
    console.error('获取新闻失败:', e)
    newsList.value = []
  } finally {
    loading.value = false
  }
}

function sentimentClass(sentiment: string) {
  return sentiment === '正面' ? 'positive' : sentiment === '负面' ? 'negative' : 'neutral'
}

function formatTime(time: string) {
  if (!time) return ''
  const d = new Date(time)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 3600000) return Math.floor(diff / 60000) + '分钟前'
  if (diff < 86400000) return Math.floor(diff / 3600000) + '小时前'
  return time.slice(0, 16)
}

function openUrl(url: string) {
  if (url) window.open(url, '_blank')
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
.loading, .empty { text-align: center; color: #999; padding: 30px; font-size: 13px; }
.time { margin-left: auto; }
</style>
