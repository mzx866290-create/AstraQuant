<template>
  <div v-if="isLoggedIn" class="signed-home">
    <section class="member-hero">
      <div>
        <span class="member-kicker">AstraQuant 工作台</span>
        <h1>每日观察池</h1>
        <p>登录成功后直接进入观察、复核、加入自选和设置预警的闭环流程。</p>
      </div>
      <div class="member-actions">
        <el-button type="primary" :icon="Search" @click="router.push('/stocks')">
          浏览股票
        </el-button>
        <el-button :icon="Star" @click="router.push('/watchlist')">
          我的自选
        </el-button>
      </div>
    </section>

    <Recommendations />
  </div>

  <div v-else class="landing-page">
    <section class="hero-section">
      <div class="market-backdrop" aria-hidden="true">
        <div class="grid-lines"></div>
        <div class="glow glow-red"></div>
        <div class="glow glow-green"></div>
        <div class="ticker-strip top">
          <span v-for="item in tickerItems" :key="`top-${item.symbol}`">
            {{ item.symbol }} {{ item.change }}
          </span>
        </div>
        <div class="ticker-strip bottom">
          <span v-for="item in tickerItems" :key="`bottom-${item.symbol}`">
            {{ item.name }} {{ item.signal }}
          </span>
        </div>
      </div>

      <div class="hero-copy">
        <div class="hero-kicker">
          <span class="live-dot"></span>
          <span>A 股观察与风险工作台</span>
        </div>
        <h1>AstraQuant</h1>
        <p class="hero-tagline">AI 驱动的 A 股观察平台</p>
        <p class="hero-lead">
          把行情、公告、新闻、财报和 AI 评分收敛成一套可解释、可追踪、可复核的观察流程。
        </p>

        <div class="hero-actions">
          <el-button type="primary" size="large" :icon="observationIcon" @click="openObservationPool">
            {{ observationButtonText }}
          </el-button>
          <el-button size="large" class="ghost-button" :icon="Search" @click="router.push('/stocks')">
            浏览股票数据
          </el-button>
        </div>

        <div class="access-note">
          <el-icon><Lock /></el-icon>
          <span>每日观察池、自选同步与预警管理需要登录后使用。</span>
        </div>
      </div>

      <div class="hero-terminal" aria-label="AstraQuant market intelligence preview">
        <div class="terminal-header">
          <span></span>
          <span></span>
          <span></span>
          <strong>Signal Desk</strong>
        </div>
        <div class="terminal-score">
          <span>Observation Score</span>
          <strong>82</strong>
          <small>数据质量 A / 风险中性</small>
        </div>
        <div class="terminal-chart">
          <i v-for="bar in chartBars" :key="bar" :style="{ height: `${bar}%` }"></i>
        </div>
        <div class="signal-list">
          <div v-for="item in signalItems" :key="item.title" class="signal-item">
            <span :class="['signal-icon', item.tone]"></span>
            <div>
              <strong>{{ item.title }}</strong>
              <small>{{ item.desc }}</small>
            </div>
          </div>
        </div>
      </div>
    </section>

    <section class="workflow-section">
      <div class="section-heading">
        <span>核心闭环</span>
        <h2>从发现到跟踪，不把用户丢在半路</h2>
      </div>

      <div class="workflow-grid">
        <article v-for="item in capabilityItems" :key="item.title" class="workflow-card">
          <div class="card-icon">
            <el-icon><component :is="item.icon" /></el-icon>
          </div>
          <h3>{{ item.title }}</h3>
          <p>{{ item.desc }}</p>
        </article>
      </div>
    </section>

    <section class="guard-section">
      <div class="guard-copy">
        <span class="guard-label">访问控制</span>
        <h2>观察池只给登录用户看</h2>
        <p>
          首页只展示产品能力，不暴露候选股票。真正的每日观察池、添加自选、设置预警和 AI 分析入口都会走登录校验。
        </p>
      </div>
      <div class="guard-actions">
        <el-button type="primary" :icon="observationIcon" @click="openObservationPool">
          {{ observationButtonText }}
        </el-button>
        <el-button :icon="Star" @click="router.push('/watchlist')">
          我的自选
        </el-button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowRight,
  Bell,
  DataAnalysis,
  DataLine,
  Lock,
  Search,
  Star,
  TrendCharts,
} from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import Recommendations from './Recommendations.vue'

const router = useRouter()
const userStore = useUserStore()

const isLoggedIn = computed(() => userStore.isLoggedIn)
const observationButtonText = computed(() => (isLoggedIn.value ? '进入每日观察池' : '登录查看观察池'))
const observationIcon = computed(() => (isLoggedIn.value ? ArrowRight : Lock))

const tickerItems = [
  { symbol: 'SH000001', name: '上证指数', change: '+0.82%', signal: '趋势观察' },
  { symbol: 'SZ399001', name: '深证成指', change: '-0.18%', signal: '波动收敛' },
  { symbol: 'CY399006', name: '创业板指', change: '+1.24%', signal: '量能回暖' },
  { symbol: 'BK-AI', name: '科技成长', change: '+2.06%', signal: '情绪偏强' },
]

const chartBars = [34, 56, 48, 68, 62, 76, 58, 82, 74, 88, 66, 72]

const signalItems = [
  { title: '数据可信度', desc: '标记缓存、降级与更新时间', tone: 'green' },
  { title: '风险解释', desc: '区分事实数据、规则评分和模型推断', tone: 'red' },
  { title: '观察闭环', desc: '从观察池进入自选、预警和详情复核', tone: 'blue' },
]

const capabilityItems = [
  {
    title: '每日观察池',
    desc: '登录后查看筛选结果，保留评分来源、候选池规模和更新时间。',
    icon: TrendCharts,
  },
  {
    title: '数据可信度',
    desc: '把实时数据、缓存数据和兜底数据分层展示，降低误判风险。',
    icon: DataLine,
  },
  {
    title: '自选与预警',
    desc: '围绕关注股票建立持续跟踪，不让一次性分析停在页面上。',
    icon: Bell,
  },
  {
    title: 'AI 风控分析',
    desc: '强调证据来源和限制说明，避免把模型输出包装成买入建议。',
    icon: DataAnalysis,
  },
]

function openObservationPool() {
  if (isLoggedIn.value) {
    router.push('/recommendations')
    return
  }

  router.push({ path: '/login', query: { redirect: '/recommendations' } })
}
</script>

<style scoped>
.landing-page {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
}

.signed-home {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}

.member-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-5);
  overflow: hidden;
  padding: var(--space-6);
  border-radius: var(--radius-lg);
  background:
    radial-gradient(circle at 12% 20%, rgba(226, 59, 59, 0.22), transparent 28%),
    radial-gradient(circle at 88% 18%, rgba(22, 163, 106, 0.18), transparent 30%),
    linear-gradient(135deg, #05070d 0%, #111827 58%, #060b13 100%);
  color: #f8fafc;
  box-shadow: 0 18px 60px rgba(15, 23, 42, 0.18);
}

.member-kicker {
  color: rgba(248, 250, 252, 0.68);
  font-size: 13px;
  font-weight: 800;
}

.member-hero h1 {
  margin: var(--space-2) 0;
  color: #fff;
  font-size: clamp(32px, 5vw, 54px);
  line-height: 1.05;
  font-weight: 900;
}

.member-hero p {
  max-width: 640px;
  margin: 0;
  color: rgba(248, 250, 252, 0.78);
  line-height: 1.7;
}

.member-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  justify-content: flex-end;
  flex-shrink: 0;
}

.hero-section {
  position: relative;
  min-height: min(720px, calc(100vh - 150px));
  overflow: hidden;
  border-radius: var(--radius-lg);
  background:
    radial-gradient(circle at 24% 18%, rgba(226, 59, 59, 0.22), transparent 28%),
    radial-gradient(circle at 78% 18%, rgba(22, 163, 106, 0.2), transparent 30%),
    linear-gradient(135deg, #05070d 0%, #111827 52%, #060b13 100%);
  color: #f8fafc;
  padding: clamp(32px, 6vw, 82px);
  box-shadow: 0 28px 90px rgba(15, 23, 42, 0.28);
}

.market-backdrop {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.grid-lines {
  position: absolute;
  inset: 0;
  opacity: 0.22;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.08) 1px, transparent 1px);
  background-size: 54px 54px;
}

.glow {
  position: absolute;
  width: 420px;
  height: 420px;
  border-radius: 50%;
  filter: blur(20px);
  opacity: 0.42;
}

.glow-red {
  left: -120px;
  bottom: 8%;
  background: rgba(226, 59, 59, 0.22);
}

.glow-green {
  right: -100px;
  top: 14%;
  background: rgba(22, 163, 106, 0.2);
}

.ticker-strip {
  position: absolute;
  left: -4%;
  right: -4%;
  display: flex;
  gap: 28px;
  color: rgba(248, 250, 252, 0.24);
  font-family: var(--font-number);
  font-size: 13px;
  white-space: nowrap;
}

.ticker-strip.top {
  top: 24px;
}

.ticker-strip.bottom {
  bottom: 24px;
  justify-content: flex-end;
}

.hero-copy {
  position: relative;
  z-index: 1;
  max-width: 760px;
  padding-top: clamp(10px, 5vh, 44px);
}

.hero-kicker,
.access-note {
  display: inline-flex;
  align-items: center;
  gap: var(--space-2);
  color: rgba(248, 250, 252, 0.78);
}

.hero-kicker {
  padding: 8px 12px;
  border: 1px solid rgba(248, 250, 252, 0.14);
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.5);
  font-size: 13px;
  font-weight: 700;
}

.live-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #16a36a;
  box-shadow: 0 0 0 6px rgba(22, 163, 106, 0.16);
}

.hero-copy h1 {
  margin: var(--space-5) 0 var(--space-3);
  color: #fff;
  font-size: clamp(56px, 9vw, 118px);
  line-height: 0.95;
  font-weight: 900;
}

.hero-tagline {
  margin: 0 0 var(--space-3);
  color: #f97316;
  font-size: clamp(22px, 3vw, 34px);
  line-height: 1.2;
  font-weight: 900;
}

.hero-lead {
  max-width: 680px;
  margin: 0;
  color: rgba(248, 250, 252, 0.82);
  font-size: clamp(18px, 2.2vw, 26px);
  line-height: 1.55;
  font-weight: 600;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin-top: var(--space-6);
}

.hero-actions :deep(.el-button) {
  min-height: 48px;
  border-radius: var(--radius-sm);
  padding: 0 22px;
  font-weight: 800;
}

.ghost-button {
  border-color: rgba(248, 250, 252, 0.22);
  background: rgba(248, 250, 252, 0.08);
  color: #fff;
}

.ghost-button:hover {
  border-color: rgba(248, 250, 252, 0.38);
  background: rgba(248, 250, 252, 0.14);
  color: #fff;
}

.access-note {
  margin-top: var(--space-4);
  font-size: 13px;
}

.hero-terminal {
  position: relative;
  z-index: 1;
  width: min(460px, 100%);
  margin: clamp(36px, 7vh, 74px) 0 0 auto;
  border: 1px solid rgba(248, 250, 252, 0.14);
  border-radius: var(--radius-md);
  background: rgba(7, 12, 22, 0.78);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.34);
  backdrop-filter: blur(16px);
}

.terminal-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: var(--space-4);
  border-bottom: 1px solid rgba(248, 250, 252, 0.1);
  color: rgba(248, 250, 252, 0.58);
  font-size: 12px;
}

.terminal-header span {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: rgba(248, 250, 252, 0.24);
}

.terminal-header strong {
  margin-left: auto;
  font-family: var(--font-number);
  font-weight: 600;
}

.terminal-score {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: var(--space-1) var(--space-3);
  padding: var(--space-5);
}

.terminal-score span,
.terminal-score small {
  color: rgba(248, 250, 252, 0.58);
}

.terminal-score strong {
  grid-row: span 2;
  align-self: center;
  color: #fff;
  font-family: var(--font-number);
  font-size: 52px;
}

.terminal-chart {
  display: flex;
  align-items: end;
  gap: 8px;
  height: 140px;
  padding: 0 var(--space-5) var(--space-5);
}

.terminal-chart i {
  flex: 1;
  min-width: 10px;
  border-radius: 6px 6px 0 0;
  background: linear-gradient(180deg, #f97316 0%, #e23b3b 55%, #16a36a 100%);
  opacity: 0.88;
}

.signal-list {
  display: grid;
  gap: var(--space-3);
  padding: 0 var(--space-5) var(--space-5);
}

.signal-item {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: var(--space-3);
  align-items: center;
  padding: var(--space-3);
  border: 1px solid rgba(248, 250, 252, 0.1);
  border-radius: var(--radius-sm);
  background: rgba(248, 250, 252, 0.06);
}

.signal-icon {
  width: 11px;
  height: 11px;
  border-radius: 50%;
}

.signal-icon.green {
  background: #16a36a;
}

.signal-icon.red {
  background: #e23b3b;
}

.signal-icon.blue {
  background: #60a5fa;
}

.signal-item strong,
.signal-item small {
  display: block;
}

.signal-item strong {
  color: #fff;
  font-size: 14px;
}

.signal-item small {
  margin-top: 2px;
  color: rgba(248, 250, 252, 0.58);
}

.workflow-section {
  display: grid;
  gap: var(--space-5);
}

.section-heading span,
.guard-label {
  color: var(--color-primary);
  font-size: 13px;
  font-weight: 800;
}

.section-heading h2,
.guard-copy h2 {
  margin: var(--space-2) 0 0;
  color: var(--color-text);
  font-size: clamp(26px, 4vw, 42px);
  line-height: 1.12;
  font-weight: 900;
}

.workflow-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-4);
}

.workflow-card {
  min-height: 214px;
  padding: var(--space-5);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-surface);
  box-shadow: var(--shadow-card);
}

.card-icon {
  width: 42px;
  height: 42px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-size: 22px;
}

.workflow-card h3 {
  margin: var(--space-4) 0 var(--space-2);
  color: var(--color-text);
  font-size: 18px;
}

.workflow-card p,
.guard-copy p {
  margin: 0;
  color: var(--color-text-secondary);
  line-height: 1.7;
}

.guard-section {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-5);
  padding: var(--space-6);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background:
    linear-gradient(135deg, rgba(29, 78, 216, 0.08), rgba(22, 163, 106, 0.08)),
    var(--color-surface);
  box-shadow: var(--shadow-card);
}

.guard-copy {
  max-width: 760px;
}

.guard-copy h2 {
  font-size: clamp(24px, 3vw, 34px);
}

.guard-copy p {
  margin-top: var(--space-3);
}

.guard-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  justify-content: flex-end;
}

@media (max-width: 1180px) {
  .workflow-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .member-hero {
    align-items: stretch;
    flex-direction: column;
    padding: var(--space-5);
  }

  .member-actions {
    justify-content: stretch;
  }

  .member-actions :deep(.el-button) {
    width: 100%;
  }

  .hero-section {
    min-height: auto;
    padding: var(--space-6) var(--space-4);
  }

  .hero-copy h1 {
    font-size: clamp(48px, 16vw, 76px);
  }

  .hero-actions :deep(.el-button) {
    width: 100%;
  }

  .hero-terminal {
    margin-top: var(--space-6);
  }

  .terminal-chart {
    height: 110px;
  }

  .workflow-grid {
    grid-template-columns: 1fr;
  }

  .guard-section {
    align-items: stretch;
    flex-direction: column;
    padding: var(--space-5);
  }

  .guard-actions {
    justify-content: stretch;
  }

  .guard-actions :deep(.el-button) {
    width: 100%;
  }
}
</style>
