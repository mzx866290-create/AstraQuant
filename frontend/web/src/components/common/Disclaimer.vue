<template>
  <div class="disclaimer-bar">
    <el-alert
      :title="text"
      type="warning"
      :closable="false"
      show-icon
    />
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  text?: string
}>(), {
  text: '本平台提供的股票数据和分析仅供参考，不构成任何投资建议。投资有风险，入市需谨慎。',
})
</script>

<style scoped>
.disclaimer-bar {
  margin: 8px 0;
}
.disclaimer-bar :deep(.el-alert) {
  font-size: 12px;
}
</style>
