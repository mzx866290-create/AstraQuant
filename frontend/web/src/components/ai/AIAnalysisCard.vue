<template>
  <div class="ai-analysis-card">
    <div class="card-header">
      <h3>AI 智能分析</h3>
      <span v-if="quota" class="quota-badge">今日剩余 {{ quota.daily_remaining }} / {{ quota.daily_limit }}</span>
    </div>

    <div v-if="readiness" class="readiness-panel" :class="readiness.ready ? 'ready' : 'blocked'">
      <div class="readiness-header">
        <span>分析准备度：{{ readiness.quality }}</span>
        <button class="btn-link" @click="loadReadiness">刷新状态</button>
      </div>
      <div class="readiness-items">
        <div
          v-for="item in readinessItems"
          :key="item.key"
          class="readiness-item"
          :class="item.ready ? 'ok' : 'missing'"
          :title="qualityTitle(item)"
        >
          <span class="status-dot"></span>
          <span>{{ item.label }}</span>
          <span v-if="item.count !== undefined" class="item-count">{{ item.count }}</span>
        </div>
      </div>
      <div v-if="readiness.missing_context?.length" class="readiness-hint">
        缺失项：{{ readiness.missing_context.join('、') }}。AI会按缺失数据处理，不会把空值当结论。
      </div>
      <div v-if="isLoggedIn && readiness.missing_context?.some(t => ['financial','news','announcements'].includes(t))" class="readiness-hint">
        <button class="btn-link" :disabled="crawling" @click="crawlMissing">
          {{ crawling ? '补全中...' : '一键补全数据' }}
        </button>
      </div>
    </div>

    <div v-if="readinessError && isLoggedIn" class="status-panel warn">
      <div>{{ readinessError }}</div>
      <button class="btn-link" @click="loadReadiness">重新检查准备度</button>
    </div>

    <div v-if="modelHealth.length" class="health-row">
      <span v-for="m in modelHealth" :key="m.id" class="health-chip" :class="m.status">
        {{ m.name }}：{{ healthLabel(m.status) }}
      </span>
      <button class="btn-link" @click="refreshModelHealth">检测模型</button>
    </div>

    <div v-if="modelHealthError && isLoggedIn" class="status-panel warn">
      <div>{{ modelHealthError }}</div>
      <button class="btn-link" @click="refreshModelHealth">重新检测模型</button>
    </div>

    <div v-if="!quotaAvailable && isLoggedIn" class="quota-exhausted">
      今日调用次数已用完，请明天再试。
    </div>

    <div v-if="!isLoggedIn" class="login-prompt">
      登录后可使用 AI 分析。
      <router-link :to="loginRoute" class="btn-link">去登录</router-link>
    </div>

    <div v-else-if="initLoading" class="loading-models">加载模型中...</div>

    <div v-else-if="initError" class="status-panel error">
      <div>{{ initError }}</div>
      <button class="btn-link" @click="loadData">重试</button>
    </div>

    <div class="analysis-form" v-show="isLoggedIn && models.length > 0">
      <div class="form-grid">
        <label>
          <span>模型</span>
          <select v-model="selectedModelId" class="model-select">
            <option v-for="m in models" :key="m.id" :value="m.id">
              {{ m.name }} ({{ m.provider }}) - {{ healthLabel(m.health_status) }}
            </option>
          </select>
        </label>

        <label>
          <span>报告类型</span>
          <select v-model="reportTemplate" class="model-select">
            <option value="quick">快速诊断</option>
            <option value="professional">专业深度</option>
            <option value="teaching">投资者教学</option>
          </select>
        </label>

        <label>
          <span>框架</span>
          <select v-model="analysisFramework" class="model-select">
            <option value="">全面分析</option>
            <option value="technical">技术面</option>
            <option value="fundamental">基本面</option>
            <option value="valuation">估值</option>
            <option value="event">事件驱动</option>
          </select>
        </label>

        <label>
          <span>提示词类型</span>
          <select v-model="promptStyle" class="model-select">
            <option value="default">默认（不追加）</option>
            <option value="plain">通俗易懂</option>
            <option value="beginner">小白教学</option>
            <option value="professional">专业投研</option>
            <option value="risk_control">风险排雷</option>
          </select>
        </label>
      </div>

      <label class="cache-toggle">
        <input v-model="forceRefresh" type="checkbox" />
        <span>跳过缓存，重新生成</span>
      </label>

      <input
        v-model="question"
        placeholder="可选：输入你想重点关注的问题"
        class="question-input"
      />

      <div v-if="analyzing || reportTemplate !== 'quick'" class="duration-hint">
        {{ analysisDurationHint }}
      </div>

      <button @click="startAnalysis" :disabled="analyzing || !quotaAvailable || !!readinessError" class="btn-analyze">
        {{ analyzing ? '分析中...' : '开始分析' }}
      </button>

      <div v-if="analyzing" class="analysis-loading-panel" role="status" aria-live="polite">
        <div class="loading-top">
          <span class="loading-spinner" aria-hidden="true"></span>
          <div class="loading-copy">
            <div class="loading-title">正在生成{{ templateLabel(reportTemplate) }}报告</div>
            <div class="loading-subtitle">{{ loadingStageText }}</div>
          </div>
          <span class="loading-time">{{ formattedElapsed }}</span>
        </div>
        <div class="loading-progress" aria-hidden="true">
          <span :style="{ width: loadingProgressWidth }"></span>
        </div>
        <div class="loading-meta">
          <span>{{ selectedModelName }}</span>
          <span>{{ analysisDurationHint }}</span>
        </div>
      </div>
    </div>

    <div v-if="result" class="analysis-result">
      <div class="result-header">
        <span>分析结果</span>
        <span class="result-meta">
          {{ result.model_name }} · {{ result.response_time_ms }}ms · {{ result.tokens_used }} tokens
        </span>
      </div>

      <div v-if="result.cache_hit" class="result-note">命中缓存：同一股票、模型和报告类型今天已分析过。</div>
      <div v-if="result.report_meta" class="result-note">
        报告类型：{{ templateLabel(result.report_meta.report_template) }} · 提示词：{{ promptStyleLabel(result.report_meta.prompt_style) }} · 篇幅：{{ modeLabel(result.report_meta.report_mode) }} · 长度：{{ result.report_meta.length || 0 }} 字
      </div>
      <div v-if="result.report_meta?.data_grade" class="result-note">
        数据等级：{{ result.report_meta.data_grade.grade }} · {{ result.report_meta.data_grade.label }}。{{ result.report_meta.data_grade.analysis_scope }}
      </div>
      <div v-if="result.report_meta?.trimmed" class="result-note warn">
        报告已按当前模式自动压缩，数据来源仍保留。
      </div>
      <div v-if="result.fallback_reason" class="result-note warn">{{ result.fallback_reason }}</div>
      <div v-if="modelSwitchWarning" class="result-note warn">
        {{ modelSwitchWarning }}
      </div>
      <div v-for="warning in dataQualityWarnings" :key="warning" class="result-note warn">{{ warning }}</div>

      <div v-if="riskLights.length" class="risk-lights">
        <span v-for="risk in riskLights" :key="risk.key" class="risk-chip" :class="risk.level">
          {{ risk.label }}：{{ risk.level }}
        </span>
      </div>

      <div v-if="trustBoundarySections.length" class="trust-boundary-panel">
        <div class="trust-boundary-header">
          <span>可信边界</span>
          <span class="trust-boundary-tag">事实 / 规则 / 推断</span>
        </div>
        <div class="trust-boundary-grid">
          <div v-for="section in trustBoundarySections" :key="section.key" class="trust-boundary-item">
            <div class="trust-boundary-label">{{ section.label }}</div>
            <ul>
              <li v-for="item in section.items" :key="item">{{ item }}</li>
            </ul>
          </div>
        </div>
      </div>

      <div class="result-content markdown-body" v-html="renderedMarkdown"></div>

      <div v-if="hasSourceCitations" class="source-citations">
        <div class="source-title">数据来源追踪</div>
        <div class="source-text" v-html="sourceSection"></div>
      </div>

      <div class="follow-up-panel">
        <div class="follow-up-header">
          <div>
            <div class="follow-up-title">继续追问</div>
            <div class="follow-up-subtitle">围绕本次报告解释术语、拆解结论或追问风险点。每次追问消耗 1 次 AI 配额。</div>
          </div>
          <span v-if="quota" class="quota-badge">剩余 {{ quota.daily_remaining }}</span>
        </div>

        <div v-if="followUpItems.length" class="follow-up-list">
          <div v-for="item in followUpItems" :key="item.id" class="follow-up-item">
            <div class="follow-up-question">问：{{ item.question }}</div>
            <div class="follow-up-answer markdown-body" v-html="renderedFollowUpAnswers[item.id] || ''"></div>
            <div class="follow-up-meta">
              {{ item.model_name }} · {{ item.response_time_ms }}ms
            </div>
            <div v-if="item.fallback_reason" class="result-note warn">{{ item.fallback_reason }}</div>
          </div>
        </div>

        <textarea
          v-model="followUpQuestion"
          class="follow-up-input"
          rows="3"
          maxlength="500"
          placeholder="例如：这段结论是什么意思？我应该重点看哪个风险？PE/PB 怎么理解？"
        ></textarea>
        <div class="follow-up-actions">
          <span class="follow-up-count">{{ followUpQuestion.length }}/500</span>
          <button
            type="button"
            class="btn-follow-up"
            :disabled="followUpLoading || !followUpQuestion.trim() || !quotaAvailable"
            @click="submitFollowUp"
          >
            {{ followUpLoading ? '解答中...' : '发送追问' }}
          </button>
        </div>
      </div>

      <div class="disclaimer">以上分析仅供参考，不构成投资建议。</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { analysisApi, crawlApi } from '@/api'
import { useUserStore } from '@/stores/user'
import { formatDuration } from '@/utils/formatters'
import { formatConfidenceLabel, formatQualitySource, formatQualityWarning } from '@/utils/dataQuality'

const props = defineProps<{
  symbol: string
  refreshKey?: number
}>()

interface AIModel {
  id: number
  name: string
  provider?: string
  health_status?: string
}

interface ModelHealthItem {
  id: number
  name: string
  status?: string
}

interface AIQuota {
  daily_remaining: number
  daily_limit: number
  monthly_remaining: number
  monthly_limit: number
}

interface ReadinessItem {
  label: string
  ready: boolean
  count?: number
  message?: string
  quality?: {
    source?: string
    confidence?: string
    warnings?: string[]
  }
}

interface AIReadiness {
  ready: boolean
  quality: string
  items?: Record<string, ReadinessItem>
  missing_context?: string[]
  blocking?: string[]
}

interface DataQualityEntry {
  warnings?: string[]
  is_fallback?: boolean
  source?: string
  confidence?: string | number
  unavailable?: boolean
  available?: boolean
  status?: string
}

type RiskLevel = 'green' | 'yellow' | 'red'

interface RiskLightInput {
  key?: string
  label?: string
  level?: RiskLevel | string
  message?: string
  warnings?: string[]
}

type TrustBoundaryValue = unknown

interface TrustBoundaryInput {
  facts?: TrustBoundaryValue
  data_facts?: TrustBoundaryValue
  rule_checks?: TrustBoundaryValue
  rules?: TrustBoundaryValue
  rule_judgement?: TrustBoundaryValue
  rule_judgment?: TrustBoundaryValue
  model_inference?: TrustBoundaryValue
  inference?: TrustBoundaryValue
  risk_limits?: TrustBoundaryValue
  risk_limitations?: TrustBoundaryValue
  limitations?: TrustBoundaryValue
  non_investment_advice?: TrustBoundaryValue
  disclaimer?: TrustBoundaryValue
}

interface TrustBoundarySection {
  key: string
  label: string
  items: string[]
}

interface AIAnalysisResult {
  model_name: string
  response_time_ms: number
  tokens_used: number
  cache_hit?: boolean
  report_meta?: {
    report_template?: 'quick' | 'professional' | 'teaching'
    prompt_style?: 'default' | 'plain' | 'beginner' | 'professional' | 'risk_control'
    report_mode?: 'summary' | 'detailed'
    length?: number
    data_grade?: {
      grade?: string
      label?: string
      analysis_scope?: string
    }
    trimmed?: boolean
    audience?: 'normal' | 'beginner'
  }
  fallback_reason?: string
  actual_model?: string
  requested_model?: string
  analysis: string
  data_quality?: Record<string, DataQualityEntry>
  risk_lights?: RiskLightInput[] | Record<string, RiskLightInput>
  trust_boundary?: TrustBoundaryInput
}

interface FollowUpResponse {
  answer: string
  model_name: string
  response_time_ms: number
  fallback_reason?: string
}

type FollowUpItem = { id: string; question: string } & FollowUpResponse

interface ApiErrorLike {
  code?: string
  message?: string
  response?: {
    data?: {
      detail?: string
    }
  }
}

interface ReadinessDisplayItem {
  key: string
  label: string
  ready: boolean
  count?: number
  message?: string
  quality?: {
    source?: string
    confidence?: string
    warnings?: string[]
  }
}

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
interface MarkdownRenderer {
  render(src: string, env?: unknown): string
}

let markdownRenderer: MarkdownRenderer | null = null
let markdownRendererLoad: Promise<MarkdownRenderer> | null = null
let markdownRenderToken = 0

async function getMarkdownRenderer() {
  if (!markdownRendererLoad) {
    markdownRendererLoad = import('markdown-it')
      .then(({ default: markdownIt }) => {
        const renderer = markdownIt({ html: false, linkify: true, breaks: true })
        markdownRenderer = renderer
        return renderer
      })
      .catch((error) => {
        markdownRendererLoad = null
        throw error
      })
  }
  markdownRenderer = await markdownRendererLoad
  return markdownRenderer
}

const models = ref<AIModel[]>([])
const modelHealth = ref<ModelHealthItem[]>([])
const quota = ref<AIQuota | null>(null)
const readiness = ref<AIReadiness | null>(null)
const selectedModelId = ref<number | null>(null)
const question = ref('')
const analysisFramework = ref('')
const reportTemplate = ref<'quick' | 'professional' | 'teaching'>('quick')
const reportMode = computed<'summary' | 'detailed'>(() => reportTemplate.value === 'quick' ? 'summary' : 'detailed')
const promptStyle = ref<'default' | 'plain' | 'beginner' | 'professional' | 'risk_control'>('default')
const audience = computed<'normal' | 'beginner'>(() => promptStyle.value === 'plain' || promptStyle.value === 'beginner' ? 'beginner' : 'normal')
const forceRefresh = ref(false)
const analyzing = ref(false)
const crawling = ref(false)
const result = ref<AIAnalysisResult | null>(null)
const followUpQuestion = ref('')
const followUpLoading = ref(false)
const followUpItems = ref<FollowUpItem[]>([])
const analysisElapsedSeconds = ref(0)
const analysisStartedAt = ref<number | null>(null)
const initLoading = ref(false)
const initError = ref('')
const readinessError = ref('')
const modelHealthError = ref('')
const renderedMarkdown = ref('')
const sourceSection = ref('')
const renderedFollowUpAnswers = ref<Record<string, string>>({})
let analysisTimer: number | null = null

const isLoggedIn = computed(() => userStore.isLoggedIn)
const loginRoute = computed(() => ({ path: '/login', query: { redirect: route.fullPath } }))
const quotaAvailable = computed(() => {
  if (!quota.value) return true
  return quota.value.daily_remaining > 0 && quota.value.monthly_remaining > 0
})

const analysisDurationHint = computed(() => {
  if (reportTemplate.value === 'quick') {
    return '快速诊断一般需要 30-90 秒，模型拥堵时会更久。'
  }
  return '深度报告通常需要 1-4 分钟，页面会等待生成完成。'
})

const selectedModelName = computed(() => {
  return models.value.find((model) => model.id === selectedModelId.value)?.name || '当前模型'
})

const modelSwitchWarning = computed(() => {
  if (!result.value?.actual_model) return ''
  const requested = result.value.requested_model || selectedModelName.value
  if (result.value.actual_model === requested) return ''
  return `模型已降级或切换：请求 ${requested}，实际使用 ${result.value.actual_model}。`
})

const formattedElapsed = computed(() => formatDuration(analysisElapsedSeconds.value))

const loadingStageText = computed(() => {
  const seconds = analysisElapsedSeconds.value
  if (seconds < 8) return '正在整理行情、财务和新闻上下文...'
  if (seconds < 25) return '正在校验数据缺口，避免把空数据写成结论...'
  if (seconds < 60) return '正在调用模型生成报告，请保持页面打开。'
  if (seconds < 120) return '模型还在生成，深度报告会比普通接口更慢。'
  if (seconds < 240) return '仍在等待模型返回，当前请求没有中断。'
  return '等待时间较长，可能是模型或上游网关拥堵。'
})

const loadingProgressWidth = computed(() => {
  const expectedSeconds = reportTemplate.value === 'quick' ? 90 : 240
  const width = 8 + (analysisElapsedSeconds.value / expectedSeconds) * 82
  return `${Math.min(95, Math.max(8, Math.round(width)))}%`
})

const readinessItems = computed<ReadinessDisplayItem[]>(() => {
  if (!readiness.value?.items) return []
  return Object.entries(readiness.value.items).map(([key, value]) => ({
    key,
    ...value,
  }))
})

const hasSourceCitations = computed(() => result.value?.analysis?.includes('## 数据来源'))

async function renderMarkdownContent() {
  const token = ++markdownRenderToken
  const analysis = result.value?.analysis || ''
  const followUps = analysis ? followUpItems.value.map((item) => ({ id: item.id, answer: item.answer })) : []

  if (!analysis && !followUps.length) {
    renderedMarkdown.value = ''
    sourceSection.value = ''
    renderedFollowUpAnswers.value = {}
    return
  }

  let md: MarkdownRenderer
  try {
    md = await getMarkdownRenderer()
  } catch (error) {
    if (token === markdownRenderToken) {
      renderedMarkdown.value = ''
      sourceSection.value = ''
      renderedFollowUpAnswers.value = {}
    }
    console.error('加载 Markdown 渲染器失败', error)
    return
  }
  if (token !== markdownRenderToken) return

  if (analysis) {
    const parts = analysis.split(/\n## 数据来源\n/)
    renderedMarkdown.value = md.render(parts[0])
    sourceSection.value = parts.length > 1 ? md.render('## 数据来源\n' + parts[1]) : ''
  } else {
    renderedMarkdown.value = ''
    sourceSection.value = ''
  }

  renderedFollowUpAnswers.value = Object.fromEntries(
    followUps.map((item) => [item.id, md.render(item.answer)]),
  )
}

const riskLights = computed(() => {
  const incoming = result.value?.risk_lights
  if (Array.isArray(incoming) && incoming.length) {
    return incoming.map((risk, index) => ({
      key: risk.key || `${index}`,
      label: risk.label || '风险提示',
      level: normalizeRiskLevel(risk.level),
    }))
  }
  if (incoming && !Array.isArray(incoming)) {
    return Object.entries(incoming).map(([key, risk]) => ({
      key: risk.key || key,
      label: risk.label || '风险提示',
      level: normalizeRiskLevel(risk.level),
    }))
  }
  const quality = result.value?.data_quality || {}
  const risks: { key: string; label: string; level: RiskLevel }[] = []
  const pushRisk = (key: string, label: string, warnings: string[]) => {
    risks.push({ key, label, level: warnings.length ? 'yellow' : 'green' })
  }
  pushRisk('data', '数据风险', Object.values(quality).flatMap((item) => item?.warnings || []))
  pushRisk('valuation', '估值风险', quality.valuation?.warnings || [])
  pushRisk('technical', '技术风险', quality.kline?.warnings || [])
  pushRisk('news', '消息风险', quality.news?.warnings || [])
  dataQualityWarnings.value.forEach((warning, index) => {
    risks.push({ key: `data-quality-${index}`, label: warning, level: 'yellow' })
  })
  return risks
})

const dataQualityWarnings = computed(() => {
  const quality = result.value?.data_quality || {}
  const warnings: string[] = []

  Object.entries(quality).forEach(([key, item]) => {
    const source = String(item.source || '').toLowerCase()
    const confidence = item.confidence
    const confidenceText = confidence === undefined ? '' : String(confidence).toLowerCase()
    const numericConfidence = typeof confidence === 'number' ? confidence : Number.NaN
    const lowConfidence = confidenceText === 'low' || (!Number.isNaN(numericConfidence) && numericConfidence < 0.5)
    const unavailable = item.unavailable || item.available === false || item.status === 'unavailable'
    const fallbackSource = source === 'local-fallback' || source === 'fallback'

    if (item.is_fallback || fallbackSource) warnings.push(`${key} 使用本地兜底数据，结论可信度需下调。`)
    if (unavailable) warnings.push(`${key} 数据不可用，相关结论可能缺失或降级。`)
    if (lowConfidence) warnings.push(`${key} 数据置信度较低，请结合原始来源复核。`)
    ;(item.warnings || []).forEach((warning) => warnings.push(`${key}：${formatQualityWarning(warning)}`))
  })

  return Array.from(new Set(warnings))
})

const trustBoundarySections = computed<TrustBoundarySection[]>(() => {
  const boundary = result.value?.trust_boundary
  const readinessValue = readiness.value
  const reportMeta = result.value?.report_meta
  const quality = result.value?.data_quality || {}
  const riskSummary = riskLights.value

  const sections: TrustBoundarySection[] = [
    {
      key: 'facts',
      label: '事实数据',
      items: normalizeTrustBoundaryList(
        boundary?.facts || boundary?.data_facts || buildFactBoundaryFallback(quality, reportMeta, readinessValue),
      ),
    },
    {
      key: 'rules',
      label: '规则判断',
      items: normalizeTrustBoundaryList(
        boundary?.rule_checks ||
          boundary?.rules ||
          boundary?.rule_judgement ||
          boundary?.rule_judgment ||
          buildRuleBoundaryFallback(readinessValue, reportMeta, riskSummary),
      ),
    },
    {
      key: 'inference',
      label: '模型推断',
      items: normalizeTrustBoundaryList(
        boundary?.model_inference ||
          boundary?.inference ||
          buildInferenceBoundaryFallback(reportMeta, result.value?.analysis),
      ),
    },
    {
      key: 'risk',
      label: '风险限制',
      items: normalizeTrustBoundaryList(
        boundary?.risk_limits ||
          boundary?.risk_limitations ||
          boundary?.limitations ||
          buildRiskBoundaryFallback(result.value?.fallback_reason, riskSummary, readinessValue, reportMeta),
      ),
    },
    {
      key: 'advice',
      label: '非投资建议',
      items: normalizeTrustBoundaryList(
        boundary?.non_investment_advice ||
          boundary?.disclaimer ||
          '本结果仅用于研究和信息参考，不构成任何投资建议或收益保证。',
      ),
    },
  ]

  return sections.filter((section) => section.items.length > 0)
})

function normalizeRiskLevel(level?: string): RiskLevel {
  if (level === 'red' || level === 'yellow' || level === 'green') return level
  if (level === 'high' || level === 'danger') return 'red'
  if (level === 'medium' || level === 'warning') return 'yellow'
  return 'green'
}

function normalizeTrustBoundaryList(value: TrustBoundaryValue): string[] {
  if (!value) return []
  const items = Array.isArray(value)
    ? value
    : typeof value === 'object'
      ? Object.values(value as Record<string, unknown>)
      : [value]
  return items.map(formatTrustBoundaryItem).filter(Boolean).slice(0, 3)
}

function formatTrustBoundaryItem(item: unknown): string {
  if (typeof item === 'string') return item.trim()
  if (typeof item === 'number' || typeof item === 'boolean') return String(item)
  if (!item || typeof item !== 'object') return ''

  const record = item as Record<string, unknown>
  const label = typeof record.label === 'string' ? record.label : ''
  const level = typeof record.level === 'string' ? record.level : ''
  const message = typeof record.message === 'string' ? record.message : ''
  if (label || level || message) {
    const prefix = label || '规则判断'
    const levelText = level ? `（${level}）` : ''
    return `${prefix}${levelText}${message ? `：${message}` : ''}`
  }

  return Object.values(record)
    .filter((value) => typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean')
    .map(String)
    .join('，')
    .trim()
}

function buildFactBoundaryFallback(
  quality: Record<string, DataQualityEntry>,
  reportMeta?: AIAnalysisResult['report_meta'],
  readinessValue?: AIReadiness | null,
) {
  const items: string[] = []
  if (reportMeta?.data_grade?.label) {
    items.push(`数据等级：${reportMeta.data_grade.grade || '-'}，${reportMeta.data_grade.label}`)
  }
  if (readinessValue?.quality) {
    items.push(`分析准备度：${readinessValue.quality}`)
  }
  const qualityKeys = Object.keys(quality)
  if (qualityKeys.length) {
    items.push(`已纳入 ${qualityKeys.length} 类数据质量检查`)
  }
  return items.length ? items : ['基于当前可用行情、财务、新闻及页面上下文生成。']
}

function buildRuleBoundaryFallback(
  readinessValue: AIReadiness | null | undefined,
  reportMeta: AIAnalysisResult['report_meta'] | undefined,
  riskSummary: { label: string; level: RiskLevel }[],
) {
  const blockedItems = readinessValue?.items
    ? Object.values(readinessValue.items).filter((item) => !item.ready).map((item) => item.label)
    : []
  const items: string[] = []
  if (blockedItems.length) items.push(`未就绪项：${blockedItems.join('、')}`)
  if (reportMeta?.trimmed) items.push('报告已按当前模式压缩，结论需结合保留的数据来源阅读')
  if (riskSummary.length) items.push(`风险灯：${riskSummary.map((risk) => `${risk.label}${risk.level}`).join('、')}`)
  return items.length ? items : ['按数据完整性、风险灯和报告模式规则进行边界标记。']
}

function buildInferenceBoundaryFallback(
  reportMeta: AIAnalysisResult['report_meta'] | undefined,
  analysis?: string,
) {
  const items = ['模型推断来自对事实数据与规则结果的归纳，不等同于可验证事实。']
  if (reportMeta?.report_template) {
    items.push(`当前报告类型：${templateLabel(reportMeta.report_template)}。`)
  }
  if (analysis) {
    items.push('正文观点需结合上方事实数据和风险限制一起阅读。')
  }
  return items
}

function buildRiskBoundaryFallback(
  fallbackReason: string | undefined,
  riskSummary: { label: string; level: RiskLevel }[],
  readinessValue: AIReadiness | null | undefined,
  reportMeta: AIAnalysisResult['report_meta'] | undefined,
) {
  const items: string[] = []
  if (fallbackReason) items.push(fallbackReason)
  const warningRisks = riskSummary.filter((risk) => risk.level !== 'green')
  if (warningRisks.length) items.push(`需关注：${warningRisks.map((risk) => risk.label).join('、')}`)
  if (readinessValue?.missing_context?.length) items.push(`缺失上下文：${readinessValue.missing_context.join('、')}`)
  if (reportMeta?.data_grade?.analysis_scope) items.push(reportMeta.data_grade.analysis_scope)
  return items.length ? items : ['受数据时效、覆盖范围和模型稳定性限制，不能替代独立核验。']
}

function healthLabel(status?: string) {
  if (status === 'healthy') return '可用'
  if (status === 'unhealthy') return '异常'
  return '未检测'
}

function modeLabel(mode?: string) {
  return mode === 'detailed' ? '深度' : '速览'
}

function templateLabel(template?: string) {
  if (template === 'professional') return '专业深度'
  if (template === 'teaching') return '投资者教学'
  return '快速诊断'
}

function promptStyleLabel(value?: string) {
  if (value === 'plain') return '通俗易懂'
  if (value === 'beginner') return '小白教学'
  if (value === 'professional') return '专业投研'
  if (value === 'risk_control') return '风险排雷'
  return '默认'
}

function qualityTitle(item: ReadinessDisplayItem) {
  const q = item.quality || {}
  const warnings = q.warnings?.length ? `；提示：${q.warnings.map(formatQualityWarning).join('、')}` : ''
  return `${formatReadinessMessage(item.message)}；来源：${formatQualitySource(q.source) || '未知'}；置信度：${formatConfidenceLabel(q.confidence) || '未知'}${warnings}`
}

function formatReadinessMessage(message?: string) {
  if (!message) return ''
  const mapping: Record<string, string> = {
    'quote available': '行情数据可用',
    'kline available': 'K 线数据可用',
    'money flow available': '资金流数据可用',
    'financial reports available': '财报数据可用',
    'news available': '新闻数据可用',
    'announcements available': '公告数据可用',
    'PE/PB available': '估值指标可用',
    'price unavailable': '价格暂不可用',
    'PE/PB missing': '估值指标暂缺',
  }
  return mapping[message] || formatQualityWarning(message)
}

function getErrorMessage(error: unknown, fallback: string) {
  const e = error as ApiErrorLike
  return e.response?.data?.detail || e.message || fallback
}

function isTimeoutError(error: unknown, message: string) {
  const e = error as ApiErrorLike
  return e.code === 'ECONNABORTED' || /timeout|超时/i.test(message)
}

function startLoadingTimer() {
  stopLoadingTimer()
  analysisStartedAt.value = Date.now()
  analysisElapsedSeconds.value = 0
  analysisTimer = window.setInterval(() => {
    if (!analysisStartedAt.value) return
    analysisElapsedSeconds.value = Math.floor((Date.now() - analysisStartedAt.value) / 1000)
  }, 1000)
}

function stopLoadingTimer() {
  if (analysisTimer !== null) {
    window.clearInterval(analysisTimer)
    analysisTimer = null
  }
  analysisStartedAt.value = null
}

function goLogin() {
  router.push(loginRoute.value)
}

async function loadReadiness() {
  if (!isLoggedIn.value) return
  readinessError.value = ''
  try {
    readiness.value = await analysisApi.getAIReadiness<AIReadiness>(props.symbol)
  } catch (e) {
    console.error('加载分析准备度失败', e)
    readiness.value = null
    readinessError.value = getErrorMessage(e, '分析准备度加载失败，请重试；在准备度确认前已阻止 AI 分析，避免用不完整状态生成结论。')
  }
}

async function crawlMissing() {
  if (!readiness.value?.missing_context?.length) return
  const types = readiness.value.missing_context.filter(t => ['financial', 'news', 'announcements'].includes(t))
  if (!types.length) return
  crawling.value = true
  try {
    type CrawlResult = { fetched?: number; saved?: number }
    const calls = types.map(t => {
      if (t === 'financial') return crawlApi.crawlFinancials<CrawlResult>(props.symbol)
      if (t === 'news') return crawlApi.crawlNews<CrawlResult>(props.symbol)
      return crawlApi.crawlAnnouncements<CrawlResult>(props.symbol)
    })
    const results = await Promise.allSettled(calls)
    const total = results.reduce((sum, r) => {
      if (r.status === 'fulfilled') {
        return sum + (r.value?.saved ?? r.value?.fetched ?? 1)
      }
      return sum
    }, 0)
    ElMessage.success(`已补全数据，共获取 ${total} 条记录`)
    await loadReadiness()
  } catch (e) {
    ElMessage.warning('部分数据源暂不可用，已跳过')
  } finally {
    crawling.value = false
  }
}

async function recoverMissingData() {
  if (!isLoggedIn.value) {
    ElMessage.warning('请先登录后补全数据')
    goLogin()
    return
  }
  await loadReadiness()
  const types = readiness.value?.missing_context?.filter(t => ['financial', 'news', 'announcements'].includes(t)) || []
  if (!types.length) {
    ElMessage.info('暂无可自动补全的数据缺口')
    return
  }
  await crawlMissing()
}

async function loadModelHealth(refresh = false) {
  if (!isLoggedIn.value) return
  modelHealthError.value = ''
  try {
    const resp = await analysisApi.getAIModelHealth<{ models?: ModelHealthItem[] }>(refresh, refresh)
    modelHealth.value = resp.models || []
  } catch (e) {
    console.error('加载模型健康状态失败', e)
    modelHealthError.value = getErrorMessage(e, '模型健康状态加载失败，可重试检测或稍后再分析。')
  }
}

async function refreshModelHealth() {
  try {
    modelHealthError.value = ''
    await loadModelHealth(true)
    const modelResp = await analysisApi.getAIModels<AIModel[]>()
    models.value = modelResp
  } catch (e) {
    modelHealthError.value = getErrorMessage(e, '模型列表刷新失败，请稍后重试。')
  }
}

async function loadData() {
  if (!isLoggedIn.value) {
    models.value = []
    modelHealth.value = []
    quota.value = null
    readiness.value = null
    initError.value = ''
    readinessError.value = ''
    modelHealthError.value = ''
    return
  }
  initLoading.value = true
  initError.value = ''
  try {
    const [modelResp, quotaResp] = await Promise.all([
      analysisApi.getAIModels<AIModel[]>(),
      analysisApi.getAIQuota<AIQuota>(),
      loadReadiness(),
      loadModelHealth(false),
    ])
    models.value = modelResp
    if (models.value.length) selectedModelId.value = models.value[0].id
    quota.value = quotaResp
  } catch (e) {
    console.error('加载AI分析数据失败', e)
    initError.value = getErrorMessage(e, 'AI 模型或配额加载失败，请重试。')
    models.value = []
  } finally {
    initLoading.value = false
  }
}

async function startAnalysis() {
  if (!isLoggedIn.value) {
    ElMessage.warning('请先登录后再使用 AI 分析')
    goLogin()
    return
  }
  if (!selectedModelId.value) {
    ElMessage.warning('请先选择一个模型')
    return
  }
  if (readinessError.value) {
    ElMessage.warning('分析准备度未确认，请先重新检查准备度')
    return
  }
  if (readiness.value && !readiness.value.ready) {
    const blocking = readiness.value.blocking?.join('、') || '前置条件'
    ElMessage.warning(`暂不能分析：${blocking} 未就绪`)
    return
  }
  try {
    analyzing.value = true
    result.value = null
    followUpItems.value = []
    followUpQuestion.value = ''
    startLoadingTimer()
    result.value = await analysisApi.analyzeStock<AIAnalysisResult>(
      selectedModelId.value,
      props.symbol,
      question.value || undefined,
      analysisFramework.value || undefined,
      reportTemplate.value,
      reportMode.value,
      audience.value,
      promptStyle.value,
      forceRefresh.value,
    )
    const [quotaResp] = await Promise.all([analysisApi.getAIQuota<AIQuota>(), loadReadiness(), loadModelHealth(false)])
    quota.value = quotaResp
  } catch (error) {
    const message = getErrorMessage(error, '分析失败')
    ElMessage.error(isTimeoutError(error, message) ? 'AI 分析等待超时。可以稍后重试、切换快速诊断，或在管理员里换一个响应更稳定的模型。' : message)
  } finally {
    stopLoadingTimer()
    analyzing.value = false
  }
}

async function submitFollowUp() {
  const text = followUpQuestion.value.trim()
  if (!result.value?.analysis || !selectedModelId.value || !text) return
  if (!quotaAvailable.value) {
    ElMessage.warning('今日调用次数已用完，请明天再试。')
    return
  }
  try {
    followUpLoading.value = true
    const resp = await analysisApi.followUpAnalysis<FollowUpResponse>(
      selectedModelId.value,
      props.symbol,
      text,
      result.value.analysis,
      result.value.report_meta,
      result.value.report_meta?.prompt_style || promptStyle.value,
      result.value.report_meta?.audience || audience.value,
    )
    followUpItems.value.push({
      id: `${Date.now()}-${followUpItems.value.length}`,
      question: text,
      ...resp,
    })
    followUpQuestion.value = ''
    quota.value = await analysisApi.getAIQuota<AIQuota>()
  } catch (error) {
    const message = getErrorMessage(error, '追问失败')
    ElMessage.error(isTimeoutError(error, message) ? 'AI 追问等待超时。可以稍后重试，或把问题问得更短更具体。' : message)
  } finally {
    followUpLoading.value = false
  }
}

onMounted(loadData)
onBeforeUnmount(stopLoadingTimer)
onBeforeUnmount(() => {
  markdownRenderToken++
})
defineExpose({ loadReadiness, recoverMissingData })
watch(isLoggedIn, () => loadData())
watch(() => props.refreshKey, () => loadReadiness())
watch(() => props.symbol, () => {
  result.value = null
  followUpItems.value = []
  followUpQuestion.value = ''
  loadData()
})
watch(
  () => ({
    analysis: result.value?.analysis || '',
    followUps: result.value?.analysis
      ? followUpItems.value.map((item) => ({ id: item.id, answer: item.answer }))
      : [],
  }),
  () => {
    void renderMarkdownContent()
  },
)
</script>

<style scoped>
.ai-analysis-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  box-shadow: var(--shadow-card);
}

.card-header,
.readiness-header,
.result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
}

.card-header {
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.card-header h3 {
  margin: 0;
  color: var(--color-text);
  font-size: 18px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.quota-badge,
.health-chip,
.risk-chip {
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 700;
  background: var(--color-surface-muted);
  color: var(--color-text-secondary);
}

.readiness-panel {
  border: 1px solid rgba(22, 163, 106, 0.24);
  border-radius: var(--radius-md);
  padding: var(--space-3) var(--space-4);
  margin: var(--space-4) 0;
  background: #f2fbf6;
}

.readiness-panel.blocked {
  border-color: #f2d48b;
  background: var(--color-warning-soft);
}

.btn-link {
  border: none;
  background: transparent;
  color: var(--color-primary);
  cursor: pointer;
  font-size: 12px;
  font-weight: 700;
}

.readiness-items,
.health-row,
.risk-lights {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.readiness-item {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 9px;
  border-radius: 999px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  font-size: 12px;
  color: var(--color-text-secondary);
}

.readiness-item.ok .status-dot {
  background: var(--color-down);
}

.readiness-item.missing .status-dot {
  background: var(--color-warning);
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}

.item-count,
.readiness-hint {
  color: var(--color-text-muted);
  font-size: 12px;
}

.health-chip.healthy,
.risk-chip.green {
  background: #ecfdf5;
  color: #047857;
}

.health-chip.unhealthy,
.risk-chip.red {
  background: var(--color-danger-soft);
  color: #b91c1c;
}

.risk-chip.yellow {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.trust-boundary-panel {
  margin-top: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
}

.trust-boundary-header {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
  align-items: center;
  color: var(--color-text);
  font-size: 13px;
  font-weight: 800;
}

.trust-boundary-tag {
  color: var(--color-text-muted);
  font-size: 12px;
  font-weight: 700;
}

.trust-boundary-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.trust-boundary-item {
  min-width: 0;
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
}

.trust-boundary-label {
  color: var(--color-text-secondary);
  font-size: 12px;
  font-weight: 800;
}

.trust-boundary-item ul {
  display: grid;
  gap: 4px;
  margin: 6px 0 0;
  padding-left: 16px;
  color: var(--color-text-muted);
  font-size: 12px;
  line-height: 1.45;
}

.login-prompt,
.quota-exhausted,
.loading-models {
  text-align: center;
  padding: var(--space-6);
  color: var(--color-text-muted);
}

.status-panel {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-3);
  margin: var(--space-4) 0;
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-text-secondary);
  background: var(--color-surface-muted);
  font-size: 13px;
}

.status-panel.warn {
  border-color: #f2d48b;
  color: var(--color-warning);
  background: var(--color-warning-soft);
}

.status-panel.error {
  border-color: rgba(185, 28, 28, 0.22);
  color: #b91c1c;
  background: var(--color-danger-soft);
}

.analysis-form {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: var(--space-3);
  align-items: end;
  padding: var(--space-4);
  background: var(--color-surface-muted);
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
}

.form-grid {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--space-3);
}

.form-grid label {
  display: flex;
  flex-direction: column;
  gap: 5px;
  color: var(--color-text-secondary);
  font-size: 13px;
  font-weight: 600;
}

.model-select,
.question-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  color: var(--color-text);
  background: var(--color-surface);
  font-size: 14px;
  transition: border-color var(--transition-fast), box-shadow var(--transition-fast);
}

.model-select:focus,
.question-input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-soft);
}

.cache-toggle {
  grid-column: 1 / -1;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--color-text-secondary);
  font-size: 13px;
}

.duration-hint {
  grid-column: 1 / -1;
  color: var(--color-text-muted);
  font-size: 12px;
}

.question-input {
  min-height: 42px;
}

.btn-analyze {
  min-height: 42px;
  padding: 0 28px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--color-primary);
  color: #fff;
  cursor: pointer;
  font-weight: 800;
  font-size: 14px;
  letter-spacing: -0.01em;
  box-shadow: 0 4px 14px rgba(29, 78, 216, 0.3);
  transition: all var(--transition-fast);
  position: relative;
  overflow: hidden;
}

.btn-analyze:hover:not(:disabled) {
  background: #2563eb;
  box-shadow: 0 6px 20px rgba(29, 78, 216, 0.35);
  transform: translateY(-1px);
}

.btn-analyze:active:not(:disabled) {
  transform: translateY(0);
}

.btn-analyze:disabled {
  background: #cbd5e1;
  box-shadow: none;
  cursor: not-allowed;
}

/* Ripple effect */
.btn-analyze::after {
  content: '';
  position: absolute;
  top: 50%;
  left: 50%;
  width: 0;
  height: 0;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 50%;
  transform: translate(-50%, -50%);
  transition: width 0.6s, height 0.6s;
  pointer-events: none;
}

.btn-analyze:active::after {
  width: 300px;
  height: 300px;
}

.form-grid {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-3);
}

.form-grid label {
  display: flex;
  flex-direction: column;
  gap: 5px;
  color: var(--color-text-secondary);
  font-size: 13px;
  font-weight: 600;
}

.cache-toggle {
  grid-column: 1 / -1;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--color-text-secondary);
  font-size: 13px;
}

.duration-hint {
  grid-column: 1 / -1;
  color: var(--color-text-muted);
  font-size: 12px;
}

.model-select,
.question-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  color: var(--color-text);
  background: var(--color-surface);
  font-size: 14px;
}

.segmented-control {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 4px;
  min-height: 42px;
  padding: 4px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
}

.segmented-control button {
  min-width: 0;
  border: none;
  border-radius: calc(var(--radius-sm) - 2px);
  background: transparent;
  color: var(--color-text-secondary);
  cursor: pointer;
  font-size: 14px;
  font-weight: 700;
}

.segmented-control button.active {
  background: var(--color-surface);
  color: var(--color-primary);
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.12);
}

.segmented-control button:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 1px;
}

.question-input {
  min-height: 42px;
}

.btn-analyze {
  min-height: 42px;
  padding: 0 22px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--color-primary);
  color: #fff;
  cursor: pointer;
  font-weight: 800;
  box-shadow: 0 8px 18px rgba(29, 78, 216, 0.22);
}

.btn-analyze:disabled {
  background: #9ca3af;
  box-shadow: none;
  cursor: not-allowed;
}

.analysis-loading-panel {
  grid-column: 1 / -1;
  display: grid;
  gap: var(--space-3);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
}

.loading-top {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: var(--space-3);
  align-items: center;
}

.loading-spinner {
  width: 20px;
  height: 20px;
  border: 2px solid rgba(29, 78, 216, 0.18);
  border-top-color: var(--color-primary);
  border-radius: 50%;
  animation: loading-spin 0.8s linear infinite;
}

.loading-copy {
  min-width: 0;
}

.loading-title {
  color: var(--color-text);
  font-size: 14px;
  font-weight: 800;
}

.loading-subtitle,
.loading-meta {
  color: var(--color-text-muted);
  font-size: 12px;
}

.loading-subtitle {
  margin-top: 3px;
}

.loading-time {
  color: var(--color-primary);
  font-variant-numeric: tabular-nums;
  font-size: 13px;
  font-weight: 800;
}

.loading-progress {
  height: 6px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(148, 163, 184, 0.28);
}

.loading-progress span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: var(--color-primary);
  transition: width 0.4s ease;
}

.loading-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2) var(--space-4);
}

@keyframes loading-spin {
  to {
    transform: rotate(360deg);
  }
}

.analysis-result {
  margin-top: var(--space-5);
  border-top: 1px solid var(--color-border);
  padding-top: var(--space-4);
}

.result-meta,
.result-note {
  color: var(--color-text-muted);
  font-size: 12px;
}

.result-note {
  margin-top: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
}

.result-note.warn {
  background: var(--color-warning-soft);
  color: var(--color-warning);
}

.result-content {
  margin-top: var(--space-4);
  color: var(--color-text);
  line-height: 1.75;
}

.result-content :deep(h1),
.result-content :deep(h2),
.result-content :deep(h3) {
  color: var(--color-text);
  letter-spacing: -0.02em;
}

.source-citations {
  margin-top: var(--space-4);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
  color: var(--color-text-secondary);
  font-size: 13px;
}

.source-title {
  font-weight: 700;
  margin-bottom: var(--space-2);
}

.follow-up-panel {
  display: grid;
  gap: var(--space-3);
  margin-top: var(--space-4);
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
}

.follow-up-header {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
  align-items: flex-start;
}

.follow-up-title {
  color: var(--color-text);
  font-size: 15px;
  font-weight: 800;
}

.follow-up-subtitle,
.follow-up-count,
.follow-up-meta {
  color: var(--color-text-muted);
  font-size: 12px;
}

.follow-up-list {
  display: grid;
  gap: var(--space-3);
}

.follow-up-item {
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface-muted);
}

.follow-up-question {
  color: var(--color-text);
  font-size: 13px;
  font-weight: 800;
}

.follow-up-answer {
  margin-top: var(--space-2);
  color: var(--color-text);
  line-height: 1.7;
}

.follow-up-meta {
  margin-top: var(--space-2);
}

.follow-up-input {
  width: 100%;
  resize: vertical;
  min-height: 84px;
  padding: 10px 12px;
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-sm);
  color: var(--color-text);
  background: var(--color-surface);
  font-size: 14px;
  line-height: 1.5;
}

.follow-up-actions {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
  align-items: center;
}

.btn-follow-up {
  min-height: 36px;
  padding: 0 16px;
  border: none;
  border-radius: var(--radius-sm);
  background: var(--color-primary);
  color: #fff;
  cursor: pointer;
  font-weight: 800;
}

.btn-follow-up:disabled {
  background: #9ca3af;
  cursor: not-allowed;
}

.disclaimer {
  margin-top: var(--space-3);
  color: var(--color-text-muted);
  font-size: 12px;
}

@media (max-width: 960px) {
  .analysis-form {
    grid-template-columns: 1fr;
  }

  .form-grid {
    grid-template-columns: 1fr;
  }

  .trust-boundary-grid {
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  }

  .card-header,
  .result-header,
  .trust-boundary-header,
  .follow-up-header,
  .follow-up-actions {
    align-items: flex-start;
    flex-direction: column;
  }

  .btn-analyze,
  .btn-follow-up {
    width: 100%;
  }
}

@media (max-width: 640px) {
  .trust-boundary-grid {
    grid-template-columns: 1fr;
  }

  .ai-analysis-card {
    padding: var(--space-4);
  }
}
</style>
