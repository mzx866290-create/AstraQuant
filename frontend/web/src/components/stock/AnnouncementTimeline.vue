<template>
  <div class="announcement-timeline">
    <div class="timeline-header">
      <h4>公司公告</h4>
      <el-select v-model="categoryFilter" size="small" placeholder="类型筛选" clearable
                 style="width: 120px" @change="fetchAnnouncements">
        <el-option label="全部" value="" />
        <el-option label="定期报告" value="定期报告" />
        <el-option label="业绩预告" value="业绩预告" />
        <el-option label="分红送转" value="分红送转" />
        <el-option label="股东变动" value="股东变动" />
        <el-option label="重大事项" value="重大事项" />
        <el-option label="临时公告" value="临时公告" />
      </el-select>
    </div>

    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="items.length === 0" class="empty">暂无公告</div>

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
import { ref, onMounted } from 'vue'

const props = defineProps<{ symbol: string }>()

const items = ref<any[]>([])
const categoryFilter = ref('')
const loading = ref(false)

async function fetchAnnouncements() {
  loading.value = true
  try {
    const { default: api } = await import('@/api')
    const params: any = {}
    if (categoryFilter.value) params.category = categoryFilter.value
    const resp = await api.get(`/api/v1/announcements/${props.symbol}`, { params })
    items.value = resp.data.announcements || []
  } catch (e) {
    console.error('获取公告失败:', e)
    items.value = []
  } finally {
    loading.value = false
  }
}

function categoryClass(cat: string) {
  const map: Record<string, string> = {
    '定期报告': 'cat-report', '业绩预告': 'cat-estimate', '分红送转': 'cat-div',
    '股东变动': 'cat-shareholder', '重大事项': 'cat-important', '临时公告': 'cat-temp',
  }
  return map[cat] || 'cat-temp'
}

function openUrl(url: string) {
  if (url) window.open(url, '_blank')
}

onMounted(fetchAnnouncements)
</script>

<style scoped>
.announcement-timeline { background: #fff; border-radius: 8px; padding: 16px; }
.timeline-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.timeline-header h4 { margin: 0; font-size: 15px; }
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
.loading, .empty { text-align: center; color: #999; padding: 30px; font-size: 13px; }
</style>
