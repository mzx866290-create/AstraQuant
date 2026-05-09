<template>
  <div class="about-page">
    <!-- Hero Section -->
    <div class="about-hero">
      <div class="hero-content">
        <div class="brand-mark">S</div>
        <h1 class="hero-title">股票数据分析平台</h1>
        <p class="hero-desc">
          基于 AI 驱动的智能股票分析工具，提供实时行情、多维数据分析和投资决策辅助
        </p>
        <div class="hero-tags">
          <el-tag size="small" effect="light" class="hero-tag">开源</el-tag>
          <el-tag size="small" effect="light" type="success" class="hero-tag">免费</el-tag>
          <el-tag size="small" effect="light" type="warning" class="hero-tag">AI 驱动</el-tag>
        </div>
      </div>
    </div>

    <!-- Tech Stack -->
    <div class="about-section">
      <h2 class="section-title">
        <el-icon :size="20" class="section-icon"><Cpu /></el-icon>
        技术架构
      </h2>
      <div class="tech-grid">
        <div class="tech-card">
          <div class="tech-icon backend">
            <el-icon :size="24"><Monitor /></el-icon>
          </div>
          <h3>后端服务</h3>
          <ul>
            <li><strong>Python 3.11</strong> + FastAPI</li>
            <li>SQLAlchemy ORM</li>
            <li>异步任务调度</li>
          </ul>
        </div>
        <div class="tech-card">
          <div class="tech-icon database">
            <el-icon :size="24"><DataLine /></el-icon>
          </div>
          <h3>数据存储</h3>
          <ul>
            <li><strong>PostgreSQL</strong> 关系数据</li>
            <li>ClickHouse 时序分析</li>
            <li>Redis 缓存加速</li>
          </ul>
        </div>
        <div class="tech-card">
          <div class="tech-icon frontend">
            <el-icon :size="24"><Monitor /></el-icon>
          </div>
          <h3>前端界面</h3>
          <ul>
            <li><strong>Vue 3</strong> + TypeScript</li>
            <li>Vite 构建工具</li>
            <li>Element Plus UI</li>
          </ul>
        </div>
        <div class="tech-card">
          <div class="tech-icon data">
            <el-icon :size="24"><TrendCharts /></el-icon>
          </div>
          <h3>数据来源</h3>
          <ul>
            <li>AkShare 财经数据</li>
            <li>Tushare 专业接口</li>
            <li>东方财富实时行情</li>
          </ul>
        </div>
      </div>
    </div>

    <!-- Features -->
    <div class="about-section">
      <h2 class="section-title">
        <el-icon :size="20" class="section-icon"><Star /></el-icon>
        核心功能
      </h2>
      <div class="features-grid">
        <div class="feature-item">
          <div class="feature-icon">
            <el-icon :size="24"><TrendCharts /></el-icon>
          </div>
          <h3>实时行情</h3>
          <p>沪深 A 股实时行情数据，K 线图、分时图多维展示</p>
        </div>
        <div class="feature-item">
          <div class="feature-icon">
            <el-icon :size="24"><Cpu /></el-icon>
          </div>
          <h3>AI 智能分析</h3>
          <p>基于大语言模型的股票分析报告，多维度风险评估</p>
        </div>
        <div class="feature-item">
          <div class="feature-icon">
            <el-icon :size="24"><Collection /></el-icon>
          </div>
          <h3>自选股管理</h3>
          <p>个性化股票池，AI 批量摘要，风险灯可视化</p>
        </div>
        <div class="feature-item">
          <div class="feature-icon">
            <el-icon :size="24"><Bell /></el-icon>
          </div>
          <h3>价格预警</h3>
          <p>自定义价格提醒，及时把握交易机会</p>
        </div>
        <div class="feature-item">
          <div class="feature-icon">
            <el-icon :size="24"><DataLine /></el-icon>
          </div>
          <h3>数据采集</h3>
          <p>自动化定时任务，持续更新财务与新闻数据</p>
        </div>
        <div class="feature-item">
          <div class="feature-icon">
            <el-icon :size="24"><FirstAidKit /></el-icon>
          </div>
          <h3>监控告警</h3>
          <p>Prometheus + Grafana 全链路监控，实时告警</p>
        </div>
      </div>
    </div>

    <!-- Disclaimer -->
    <div class="about-section">
      <div class="disclaimer-card">
        <div class="disclaimer-header">
          <el-icon :size="24" class="disclaimer-icon"><Warning /></el-icon>
          <h2>免责声明</h2>
        </div>
        <div class="disclaimer-body">
          <p>
            本平台仅供<strong>学习和研究</strong>之用，提供的所有信息和数据不构成任何投资建议或收益保证。
            股票市场存在风险，用户在使用本平台时应自行判断并承担相关风险。
          </p>
          <p>
            AI 分析结果基于历史数据和算法模型，可能存在偏差。开发者不对因使用本平台而产生的任何直接或间接损失负责。
            请理性投资，审慎决策。
          </p>
        </div>
      </div>
    </div>

    <!-- Contact -->
    <div class="about-section">
      <h2 class="section-title">
        <el-icon :size="20" class="section-icon"><Link /></el-icon>
        开源社区
      </h2>
      <div class="contact-grid">
        <a href="https://github.com" target="_blank" rel="noopener noreferrer" class="contact-card github">
          <el-icon :size="28"><Document /></el-icon>
          <span>GitHub 仓库</span>
          <el-icon :size="16"><ArrowRight /></el-icon>
        </a>
        <a href="#" class="contact-card docs">
          <el-icon :size="28"><Reading /></el-icon>
          <span>使用文档</span>
          <el-icon :size="16"><ArrowRight /></el-icon>
        </a>
      </div>
    </div>

    <div class="version-info">
      <span>前端版本 0.1.0</span>
      <span class="divider">·</span>
      <span>© {{ new Date().getFullYear() }} 股票数据分析平台</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import {
  Cpu,
  Monitor,
  DataLine,
  TrendCharts,
  Star,
  Collection,
  Bell,
  FirstAidKit,
  Warning,
  Link,
  Document,
  Reading,
  ArrowRight,
} from '@element-plus/icons-vue'
</script>

<style scoped>
.about-page {
  max-width: 1000px;
  margin: 0 auto;
}

/* Hero Section */
.about-hero {
  text-align: center;
  padding: var(--space-12) var(--space-6);
  margin-bottom: var(--space-8);
  background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #1d4ed8 100%);
  border-radius: var(--radius-lg);
  position: relative;
  overflow: hidden;
}

.about-hero::before {
  content: '';
  position: absolute;
  top: -50%;
  right: -50%;
  width: 100%;
  height: 100%;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.3) 0%, transparent 70%);
}

.about-hero::after {
  content: '';
  position: absolute;
  bottom: -30%;
  left: -30%;
  width: 80%;
  height: 80%;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.2) 0%, transparent 70%);
}

.hero-content {
  position: relative;
  z-index: 1;
}

.brand-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 80px;
  height: 80px;
  background: rgba(255, 255, 255, 0.1);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 20px;
  font-size: 36px;
  font-weight: 800;
  color: #fff;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  margin-bottom: var(--space-6);
}

.hero-title {
  font-size: 32px;
  font-weight: 800;
  color: #fff;
  margin: 0 0 var(--space-4);
  letter-spacing: -0.02em;
}

.hero-desc {
  font-size: 16px;
  color: rgba(255, 255, 255, 0.8);
  max-width: 560px;
  margin: 0 auto var(--space-6);
  line-height: 1.6;
}

.hero-tags {
  display: flex;
  justify-content: center;
  gap: var(--space-3);
}

.hero-tag {
  background: rgba(255, 255, 255, 0.15) !important;
  border-color: rgba(255, 255, 255, 0.2) !important;
  color: #fff !important;
  font-weight: 700;
  backdrop-filter: blur(10px);
}

/* Section */
.about-section {
  margin-bottom: var(--space-8);
}

.section-title {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  font-size: 20px;
  font-weight: 800;
  color: var(--color-text);
  margin: 0 0 var(--space-5);
  letter-spacing: -0.01em;
}

.section-icon {
  color: var(--color-primary);
}

/* Tech Grid */
.tech-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: var(--space-4);
}

.tech-card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  transition: all var(--transition-base);
}

.tech-card:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-2px);
}

.tech-icon {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--space-3);
}

.tech-icon.backend {
  background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%);
  color: #2563eb;
}

.tech-icon.database {
  background: linear-gradient(135deg, #f3e8ff 0%, #e9d5ff 100%);
  color: #9333ea;
}

.tech-icon.frontend {
  background: linear-gradient(135deg, #dcfce7 0%, #bbf7d0 100%);
  color: #16a34a;
}

.tech-icon.data {
  background: linear-gradient(135deg, #ffedd5 0%, #fed7aa 100%);
  color: #ea580c;
}

.tech-card h3 {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0 0 var(--space-3);
}

.tech-card ul {
  margin: 0;
  padding-left: var(--space-4);
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.8;
}

.tech-card li {
  margin-bottom: var(--space-1);
}

/* Features Grid */
.features-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-4);
}

.feature-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: var(--space-5);
  transition: all var(--transition-base);
}

.feature-item:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-2px);
}

.feature-icon {
  width: 48px;
  height: 48px;
  border-radius: var(--radius-md);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-bottom: var(--space-3);
  background: linear-gradient(135deg, #e8f0ff 0%, #f0f7ff 100%);
  color: var(--color-primary);
}

.feature-item h3 {
  font-size: 16px;
  font-weight: 700;
  color: var(--color-text);
  margin: 0 0 var(--space-2);
}

.feature-item p {
  font-size: 14px;
  color: var(--color-text-secondary);
  line-height: 1.6;
  margin: 0;
}

/* Disclaimer */
.disclaimer-card {
  background: linear-gradient(135deg, #fef2f2 0%, #fff1f2 100%);
  border: 1px solid #fecdd3;
  border-radius: var(--radius-md);
  padding: var(--space-6);
  overflow: hidden;
}

.disclaimer-header {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  margin-bottom: var(--space-4);
}

.disclaimer-icon {
  color: #e11d48;
}

.disclaimer-header h2 {
  font-size: 18px;
  font-weight: 800;
  color: #be123c;
  margin: 0;
}

.disclaimer-body p {
  font-size: 14px;
  line-height: 1.8;
  color: #9f1239;
  margin: 0 0 var(--space-3);
}

.disclaimer-body p:last-child {
  margin-bottom: 0;
}

.disclaimer-body strong {
  color: #be123c;
}

/* Contact */
.contact-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: var(--space-4);
}

.contact-card {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-4) var(--space-5);
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  text-decoration: none;
  color: var(--color-text);
  transition: all var(--transition-base);
  font-weight: 600;
  font-size: 14px;
}

.contact-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-card-hover);
  transform: translateY(-1px);
  color: var(--color-primary);
}

.contact-card :deep(svg) {
  flex-shrink: 0;
}

.contact-card span {
  flex: 1;
}

/* Version */
.version-info {
  text-align: center;
  padding: var(--space-6);
  color: var(--color-text-muted);
  font-size: 13px;
  font-weight: 600;
}

.version-info .divider {
  margin: 0 var(--space-3);
}

/* Responsive */
@media (max-width: 640px) {
  .about-hero {
    padding: var(--space-8) var(--space-4);
  }

  .hero-title {
    font-size: 24px;
  }

  .hero-desc {
    font-size: 14px;
  }

  .tech-grid,
  .features-grid {
    grid-template-columns: 1fr;
  }

  .contact-grid {
    grid-template-columns: 1fr;
  }
}
</style>
