<template>
  <div v-if="quality" class="data-quality-panel">
    <span
      v-for="risk in riskTags"
      :key="risk"
      class="quality-risk"
    >
      {{ risk }}
    </span>
    <span v-if="quality.source" class="quality-item">来源: {{ formatQualitySource(quality.source) }}</span>
    <span v-if="quality.updated_at" class="quality-item">更新时间: {{ formatQualityTime(quality.updated_at) }}</span>
    <span v-if="quality.freshness" class="quality-item">新鲜度: {{ formatFreshness(quality.freshness) }}</span>
    <span v-if="quality.confidence !== undefined && quality.confidence !== null && quality.confidence !== ''" class="quality-item">置信度: {{ formatConfidenceLabel(quality.confidence) }}</span>
    <span v-for="warning in qualityWarnings(quality)" :key="warning" class="quality-warning">
      {{ formatQualityWarning(warning) }}
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  formatConfidenceLabel,
  formatFreshness,
  formatQualitySource,
  formatQualityTime,
  formatQualityWarning,
  qualityRiskTags,
  qualityWarnings,
  type DataQualityItem,
} from '@/utils/dataQuality'

const props = defineProps<{
  quality: DataQualityItem | null
}>()

const riskTags = computed(() => {
  return qualityRiskTags(props.quality)
})
</script>

<style scoped>
.data-quality-panel {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-4);
  color: var(--color-text-secondary);
  font-size: 12px;
}

.quality-item,
.quality-warning,
.quality-risk {
  padding: 4px 8px;
  border-radius: 999px;
}

.quality-item {
  background: var(--color-surface-muted);
  border: 1px solid var(--color-border);
}

.quality-warning {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.quality-risk {
  background: #fff1f0;
  border: 1px solid #ffa39e;
  color: #c53030;
  font-weight: 700;
}
</style>
