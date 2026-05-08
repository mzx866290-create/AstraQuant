<template>
  <div class="source-attribution" v-if="hasData">
    <div class="source-header">
      <span class="source-icon">📊</span>
      <span>数据来源</span>
      <span class="freshness" :class="freshnessClass">{{ freshnessText }}</span>
    </div>
    <div class="source-items">
      <div v-if="sources.kline" class="source-item">
        <span class="si-dot fresh"></span>
        <span>K线数据: {{ sources.kline }}</span>
      </div>
      <div v-if="sources.financial" class="source-item">
        <span class="si-dot" :class="sources.financialFreshness"></span>
        <span>财务数据: {{ sources.financial }}</span>
      </div>
      <div v-if="sources.news" class="source-item">
        <span class="si-dot fresh"></span>
        <span>新闻数据: {{ sources.news }}</span>
      </div>
      <div v-if="sources.announcements" class="source-item">
        <span class="si-dot fresh"></span>
        <span>公告数据: {{ sources.announcements }}</span>
      </div>
    </div>
    <div class="disclaimer">所有数据均来自公开信息源，分析结果仅供参考，不构成投资建议。</div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  sources: {
    kline?: string
    financial?: string
    financialFreshness?: string
    news?: string
    announcements?: string
  }
}>()

const hasData = computed(() => Object.keys(props.sources).length > 0)
const freshnessText = computed(() => {
  if (!props.sources.financialFreshness || props.sources.financialFreshness === 'today') {
    return '数据新鲜'
  }
  if (props.sources.financialFreshness === 'unavailable') {
    return '部分数据暂不可用'
  }
  return '财报数据来自上期报告'
})
const freshnessClass = computed(() => props.sources.financialFreshness || 'fresh')
</script>

<style scoped>
.source-attribution { background: #f8f9fa; border-radius: 8px; padding: 12px 16px; margin-top: 16px; }
.source-header { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; color: #4a5568; margin-bottom: 8px; }
.source-icon { font-size: 14px; }
.freshness { margin-left: auto; font-size: 11px; color: #38a169; font-weight: normal; }
.freshness.unavailable { color: #e53e3e; }
.freshness.stale { color: #d69e2e; }
.source-items { display: flex; flex-wrap: wrap; gap: 12px; }
.source-item { display: flex; align-items: center; gap: 4px; font-size: 11px; color: #718096; }
.si-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.si-dot.fresh { background: #38a169; }
.si-dot.stale { background: #d69e2e; }
.si-dot.unavailable { background: #e53e3e; }
.disclaimer { margin-top: 8px; font-size: 10px; color: #a0aec0; text-align: center; }
</style>
