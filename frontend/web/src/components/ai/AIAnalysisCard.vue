<template>
  <div class="ai-analysis-card">
    <div class="card-header">
      <h3>🤖 AI 智能分析</h3>
      <span v-if="quota" class="quota-badge">
        剩余: {{ quota.daily_remaining }} / {{ quota.daily_limit }} 今日
      </span>
    </div>

    <div v-if="!quotaAvailable && isLoggedIn" class="quota-exhausted">
      <p>今日调用次数已用完</p>
      <p class="hint">配额用完，请明天再来或联系管理员</p>
    </div>

    <div v-if="models.length === 0" class="loading-models">
      加载模型中...
    </div>

    <div class="analysis-form" v-show="models.length > 0">
      <div class="form-row">
        <label>选择模型:</label>
        <select v-model="selectedModelId" class="model-select">
          <option v-for="m in models" :key="m.id" :value="m.id">
            {{ m.name }} ({{ m.provider }})
          </option>
        </select>
      </div>

      <div class="form-row">
        <label>分析框架:</label>
        <select v-model="analysisFramework" class="model-select">
          <option value="">全面分析 (默认)</option>
          <option value="technical">技术面分析</option>
          <option value="fundamental">基本面分析</option>
          <option value="valuation">估值分析</option>
          <option value="event">事件驱动分析</option>
        </select>
      </div>

      <div class="form-row">
        <label>分析问题:</label>
        <input
          v-model="question"
          placeholder="请分析该股票近期走势和买卖点..."
          class="question-input"
        />
      </div>

      <button @click="startAnalysis" :disabled="analyzing" class="btn-analyze">
        {{ analyzing ? '分析中...' : '开始分析' }}
      </button>
    </div>

    <div v-if="result" class="analysis-result">
      <div class="result-header">
        <span>分析结果</span>
        <span class="result-meta">
          {{ result.model_name }} · {{ result.response_time_ms }}ms · {{ result.tokens_used }} tokens
        </span>
      </div>
      <div class="result-content markdown-body" v-html="renderedMarkdown"></div>

      <!-- 来源追溯 -->
      <div v-if="hasSourceCitations" class="source-citations">
        <div class="source-title">📊 数据来源追溯</div>
        <div class="source-text" v-html="sourceSection"></div>
      </div>
      <div class="disclaimer">⚠️ 以上分析仅供参考，不构成投资建议</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { analysisApi } from '@/api'
import { useUserStore } from '@/stores/user'
import markdownIt from 'markdown-it'

const props = defineProps<{
  symbol: string
}>()

const userStore = useUserStore()
const md = markdownIt()

const models = ref<any[]>([])
const quota = ref<any>(null)
const selectedModelId = ref<number | null>(null)
const question = ref('')
const analysisFramework = ref('')
const analyzing = ref(false)
const result = ref<any>(null)

const isLoggedIn = computed(() => userStore.isLoggedIn)
const quotaAvailable = computed(() => {
  if (!quota.value) return true
  return quota.value.daily_remaining > 0 && quota.value.monthly_remaining > 0
})

const renderedMarkdown = computed(() => {
  if (!result.value?.analysis) return ''
  // Split out the source citation section from the main analysis
  const parts = result.value.analysis.split(/\n## 数据来源\n/)
  return md.render(parts[0])
})

const hasSourceCitations = computed(() => {
  if (!result.value?.analysis) return false
  return result.value.analysis.includes('## 数据来源')
})

const sourceSection = computed(() => {
  if (!result.value?.analysis) return ''
  const parts = result.value.analysis.split(/\n## 数据来源\n/)
  if (parts.length > 1) {
    return md.render('## 数据来源\n' + parts[1])
  }
  return ''
})

async function loadData() {
  try {
    models.value = await analysisApi.getAIModels()
    if (models.value.length) {
      selectedModelId.value = models.value[0].id
    }
    quota.value = await analysisApi.getAIQuota()
  } catch (e) {
    console.error('加载数据失败:', e)
  }
}

async function startAnalysis() {
  if (!selectedModelId.value) {
    alert('请先选择一个模型')
    return
  }
  try {
    analyzing.value = true
    result.value = await analysisApi.analyzeStock(
      selectedModelId.value,
      props.symbol,
      question.value || undefined,
      analysisFramework.value || undefined
    )
    // 刷新配额
    quota.value = await analysisApi.getAIQuota()
  } catch (e: any) {
    alert(e.response?.data?.detail || '分析失败')
  } finally {
    analyzing.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.ai-analysis-card {
  background: #fff;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 15px;
}

.card-header h3 {
  margin: 0;
  color: #333;
}

.quota-badge {
  background: #f3f4f6;
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  color: #666;
}

.login-prompt,
.quota-exhausted {
  text-align: center;
  padding: 30px;
  color: #666;
}

.hint {
  font-size: 12px;
  color: #999;
}

.loading-models {
  text-align: center;
  padding: 20px;
  color: #999;
}

.analysis-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.form-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.form-row label {
  width: 80px;
  font-weight: 500;
}

.model-select,
.question-input {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
}

.btn-analyze {
  padding: 10px 20px;
  background: #7c3aed;
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  align-self: flex-end;
}

.btn-analyze:disabled {
  background: #ccc;
  cursor: not-allowed;
}

.btn-primary {
  display: inline-block;
  padding: 8px 16px;
  background: #7c3aed;
  color: #fff;
  text-decoration: none;
  border-radius: 4px;
}

.analysis-result {
  margin-top: 20px;
  border-top: 1px solid #eee;
  padding-top: 15px;
}

.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  font-weight: 500;
}

.result-meta {
  font-size: 12px;
  color: #999;
  font-weight: normal;
}

.result-content {
  background: #f9f9f9;
  padding: 15px;
  border-radius: 4px;
  line-height: 1.6;
}

.source-citations {
  margin-top: 15px;
  padding: 12px;
  background: #f8f9fa;
  border-radius: 6px;
  border-left: 3px solid #3182ce;
}
.source-title { font-size: 13px; font-weight: 600; color: #4a5568; margin-bottom: 6px; }
.source-text { font-size: 11px; color: #718096; line-height: 1.6; }

.disclaimer {
  margin-top: 10px;
  font-size: 12px;
  color: #999;
  text-align: center;
}
</style>