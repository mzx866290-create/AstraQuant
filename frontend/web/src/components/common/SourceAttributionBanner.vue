<template>
  <div class="source-attribution" v-if="hasData">
    <div class="source-header">
      <el-icon class="source-icon"><DataLine /></el-icon>
      <span>数据来源</span>
      <span class="freshness" :class="freshnessClass">{{ freshnessText }}</span>
    </div>
    <div class="source-items">
      <div v-if="sources.kline" class="source-item">
        <span class="si-dot" :class="sources.klineFreshness || 'fresh'"></span>
        <span>K线数据: {{ displaySource(sources.kline) }}</span>
      </div>
      <div v-if="sources.financial" class="source-item">
        <span class="si-dot" :class="sources.financialFreshness || 'fresh'"></span>
        <span>财务数据: {{ displaySource(sources.financial) }}</span>
      </div>
      <div v-if="sources.news" class="source-item">
        <span class="si-dot" :class="sources.newsFreshness || 'fresh'"></span>
        <span>新闻数据: {{ displaySource(sources.news) }}</span>
      </div>
      <div v-if="sources.announcements" class="source-item">
        <span class="si-dot" :class="sources.announcementsFreshness || 'fresh'"></span>
        <span>公告数据: {{ displaySource(sources.announcements) }}</span>
      </div>
    </div>
    <div class="disclaimer">所有数据均来自公开信息源，分析结果仅供参考，不构成投资建议。</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { DataLine } from '@element-plus/icons-vue'
import { formatQualitySource } from '@/utils/dataQuality'

const props = defineProps<{
  sources: {
    kline?: string
    klineFreshness?: string
    financial?: string
    financialFreshness?: string
    news?: string
    newsFreshness?: string
    announcements?: string
    announcementsFreshness?: string
  }
}>()

const hasData = computed(() => Object.keys(props.sources).length > 0)
const displaySource = (source?: string) => formatQualitySource(source) || '暂不可用'
const freshnessValues = computed(() => [
  props.sources.klineFreshness,
  props.sources.financialFreshness,
  props.sources.newsFreshness,
  props.sources.announcementsFreshness,
].filter(Boolean))
const freshnessText = computed(() => {
  const values = freshnessValues.value
  if (values.includes('stale')) return '部分数据过旧'
  if (values.includes('unavailable')) return '部分数据暂不可用'
  if (values.includes('empty')) return '部分数据暂无'
  if (!values.length || values.every((value) => value === 'today' || value === 'realtime' || value === 'recent' || value === 'published')) {
    return '数据新鲜'
  }
  return '部分数据来自历史报告'
})
const freshnessClass = computed(() => {
  const values = freshnessValues.value
  if (values.includes('stale')) return 'stale'
  if (values.includes('unavailable')) return 'unavailable'
  if (values.includes('empty')) return 'empty'
  return 'fresh'
})
</script>

<style scoped>
.source-attribution { background: #f8f9fa; border-radius: 8px; padding: 12px 16px; margin-top: 16px; }
.source-header { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; color: #4a5568; margin-bottom: 8px; }
.source-icon { color: #4a5568; font-size: 14px; }
.freshness { margin-left: auto; font-size: 11px; color: #38a169; font-weight: normal; }
.freshness.unavailable { color: #e53e3e; }
.freshness.stale { color: #d69e2e; }
.freshness.empty { color: #718096; }
.source-items { display: flex; flex-wrap: wrap; gap: 12px; }
.source-item { display: flex; align-items: center; gap: 4px; font-size: 11px; color: #718096; }
.si-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.si-dot.fresh { background: #38a169; }
.si-dot.stale { background: #d69e2e; }
.si-dot.unavailable { background: #e53e3e; }
.si-dot.empty { background: #a0aec0; }
.disclaimer { margin-top: 8px; font-size: 10px; color: #a0aec0; text-align: center; }
</style>
